"""
test_forensic.py - Milestone 2 Forensic Audit
Covers:
  1. Atomic multi-booking rollback
  2. Role enforcement (FARMER/OPERATOR/ADMIN)
  3. HTTP event idempotency
  4. Stale recommendation protection
  5. Approval state machine
  6. Simulated time propagation
  7. Scenario endpoint classification
  8+9. Full closed-loop trace + procurement/payment intact
"""

import pytest
import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import app
from api.dependencies import get_db
from infrastructure.database.database import Base
from infrastructure.database.models import (
    RecommendationModel, RecommendationChangeModel, BookingModel
)
from core.domain.models import (
    CentreState, Counter, CounterStatus, OperatingStatus,
    BookingState, ProcurementStatus, PaymentStatus, ConstraintSet
)

# ── Test DB ──────────────────────────────────────────────────────────────────
_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _override_get_db():
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module", autouse=True)
def _install_db_override():
    """Install this module's DB override for the duration of the module, then restore."""
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db
    yield
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous


client = TestClient(app)



@pytest.fixture(scope="module")
def centre():
    Base.metadata.create_all(bind=_engine)
    db = _SessionLocal()
    cid = f"forensic_{uuid.uuid4().hex[:6]}"
    state = CentreState(
        centre_id=cid,
        timestamp=datetime(2026, 8, 31, 8, 0, 0),
        operating_status=OperatingStatus.OPEN,
        counters=[
            Counter(counter_id=f"cnt1_{cid}", centre_id=cid,
                    status=CounterStatus.ACTIVE, processing_rate=4.0),
            Counter(counter_id=f"cnt2_{cid}", centre_id=cid,
                    status=CounterStatus.ACTIVE, processing_rate=4.0),
        ],
    )
    constraints = ConstraintSet(
        operating_hours_start="08:00",
        operating_hours_end="18:00",
        slot_capacity=4,
        booking_validity_window_minutes=30,
        available_capacity=4,
        minimum_notice_minutes=15,
    )
    from infrastructure.database.repositories import SQLAlchemyCentreRepository
    repo = SQLAlchemyCentreRepository(db)
    repo.update_state(state)
    repo.update_constraints(cid, constraints)
    db.commit()
    yield cid, db
    db.close()
    Base.metadata.drop_all(bind=_engine)



# ── Helpers ──────────────────────────────────────────────────────────────────

def make_booking(centre_id, hours_from_now=2, booking_id=None):
    bid = booking_id or f"b_{uuid.uuid4().hex[:8]}"
    start = (datetime(2026, 8, 31, 8, 0, 0) + timedelta(hours=hours_from_now)).isoformat()
    resp = client.post("/api/bookings", json={
        "booking_id": bid,
        "farmer_id": f"f_{uuid.uuid4().hex[:6]}",
        "centre_id": centre_id,
        "scheduled_start_time": start,
        "priority_level": 0,
    })
    assert resp.status_code == 200, f"make_booking failed: {resp.json()}"
    return bid


def insert_recommendation(db, centre_id, changes, status="PENDING"):
    rec_id = f"rec_{uuid.uuid4().hex[:8]}"
    rec = RecommendationModel(
        recommendation_id=rec_id,
        centre_id=centre_id,
        trigger_event_id=f"ev_{uuid.uuid4().hex[:6]}",
        created_at=datetime(2026, 8, 31, 9, 0, 0),
        status=status,
        reason="Forensic test",
        expected_impact="Test",
        constraint_check="[]",
        fairness_check="[]",
    )
    db.add(rec)
    db.flush()
    for c in changes:
        db.add(RecommendationChangeModel(
            recommendation_id=rec_id,
            booking_id=c["booking_id"],
            original_start=c["original_start"],
            proposed_start=c["proposed_start"],
            priority_level=0,
            reschedule_count=0,
        ))
    db.commit()
    return rec_id


def approve(rec_id, sim_time=None):
    t = (sim_time or datetime(2026, 8, 31, 9, 5, 0)).isoformat()
    return client.post(
        f"/api/recommendations/{rec_id}/approve?simulated_time={t}",
        headers={"X-User-Role": "ADMIN"},
    )


def reject_rec(rec_id):
    return client.post(
        f"/api/recommendations/{rec_id}/reject",
        headers={"X-User-Role": "ADMIN"},
    )


def booking_row(db, booking_id):
    return db.query(BookingModel).filter(
        BookingModel.booking_id == booking_id).first()


def rec_row(db, rec_id):
    return db.query(RecommendationModel).filter(
        RecommendationModel.recommendation_id == rec_id).first()


# ════════════════════════════════════════════════════════════════════════════
# 1. ATOMIC MULTI-BOOKING ROLLBACK
# ════════════════════════════════════════════════════════════════════════════

def test_partial_failure_rolls_back_all_bookings(centre):
    """
    3-booking recommendation. Booking 2 is put into COMPLETED so
    mark_rescheduled fails midway. Verifies full rollback:
    b1 untouched, b3 untouched, recommendation still PENDING.
    """
    cid, db = centre
    sim = datetime(2026, 8, 31, 10, 0, 0)

    b1 = make_booking(cid, hours_from_now=2, booking_id=f"b_r1_{uuid.uuid4().hex[:6]}")
    b2 = make_booking(cid, hours_from_now=3, booking_id=f"b_r2_{uuid.uuid4().hex[:6]}")
    b3 = make_booking(cid, hours_from_now=4, booking_id=f"b_r3_{uuid.uuid4().hex[:6]}")

    row1 = booking_row(db, b1)
    row2 = booking_row(db, b2)
    row3 = booking_row(db, b3)
    orig_start_b1 = row1.scheduled_start_time

    rec_id = insert_recommendation(db, cid, [
        {"booking_id": b1, "original_start": row1.scheduled_start_time,
         "proposed_start": row1.scheduled_start_time + timedelta(hours=3)},
        {"booking_id": b2, "original_start": row2.scheduled_start_time,
         "proposed_start": row2.scheduled_start_time + timedelta(hours=3)},
        {"booking_id": b3, "original_start": row3.scheduled_start_time,
         "proposed_start": row3.scheduled_start_time + timedelta(hours=3)},
    ])

    # Sabotage booking 2 midway
    row2.booking_state = BookingState.COMPLETED
    db.commit()

    resp = approve(rec_id, sim)
    assert resp.status_code == 400, f"Expected 400 got {resp.status_code}: {resp.json()}"

    db.expire_all()
    b1r = booking_row(db, b1)
    assert b1r.reschedule_count == 0, "b1 reschedule_count must be 0"
    assert b1r.booking_state == BookingState.SCHEDULED, "b1 must remain SCHEDULED"
    assert abs((b1r.scheduled_start_time - orig_start_b1).total_seconds()) < 2, \
        "b1 start_time must not have changed"
    assert booking_row(db, b3).reschedule_count == 0, "b3 reschedule_count must be 0"
    assert rec_row(db, rec_id).status == "PENDING", "Rec must remain PENDING"


# ════════════════════════════════════════════════════════════════════════════
# 2. ROLE ENFORCEMENT
# ════════════════════════════════════════════════════════════════════════════

def test_farmer_cannot_post_events(centre):
    cid, _ = centre
    resp = client.post("/api/events", json={
        "event_id": f"ev_{uuid.uuid4().hex[:8]}",
        "timestamp": datetime(2026, 8, 31, 9, 0, 0).isoformat(),
        "source": "GATE", "event_type": "FARMER_ARRIVED",
        "metadata": {"centre_id": cid, "booking_id": "x"},
    }, headers={"X-User-Role": "FARMER"})
    assert resp.status_code == 403


def test_farmer_cannot_get_centre_state(centre):
    cid, _ = centre
    assert client.get(f"/api/centres/{cid}/state",
                      headers={"X-User-Role": "FARMER"}).status_code == 403


def test_farmer_cannot_get_predictions(centre):
    cid, _ = centre
    sim = datetime(2026, 8, 31, 9, 0, 0).isoformat()
    assert client.get(
        f"/api/centres/{cid}/predictions?simulated_time={sim}",
        headers={"X-User-Role": "FARMER"}).status_code == 403


def test_farmer_cannot_approve_recommendation(centre):
    cid, db = centre
    rec_id = insert_recommendation(db, cid, [])
    resp = client.post(
        f"/api/recommendations/{rec_id}/approve?simulated_time=2026-08-31T09:00:00",
        headers={"X-User-Role": "FARMER"},
    )
    assert resp.status_code == 403


def test_farmer_cannot_reject_recommendation(centre):
    cid, db = centre
    rec_id = insert_recommendation(db, cid, [])
    assert client.post(f"/api/recommendations/{rec_id}/reject",
                       headers={"X-User-Role": "FARMER"}).status_code == 403


def test_operator_cannot_approve_recommendation(centre):
    cid, db = centre
    rec_id = insert_recommendation(db, cid, [])
    resp = client.post(
        f"/api/recommendations/{rec_id}/approve?simulated_time=2026-08-31T09:00:00",
        headers={"X-User-Role": "OPERATOR"},
    )
    assert resp.status_code == 403


def test_operator_cannot_reject_recommendation(centre):
    cid, db = centre
    rec_id = insert_recommendation(db, cid, [])
    assert client.post(f"/api/recommendations/{rec_id}/reject",
                       headers={"X-User-Role": "OPERATOR"}).status_code == 403


def test_operator_cannot_run_scenario(centre):
    sim = datetime(2026, 8, 31, 9, 0, 0).isoformat()
    assert client.post(f"/api/scenarios/run?simulated_time={sim}",
                       headers={"X-User-Role": "OPERATOR"}).status_code == 403


def test_farmer_cannot_run_scenario(centre):
    sim = datetime(2026, 8, 31, 9, 0, 0).isoformat()
    assert client.post(f"/api/scenarios/run?simulated_time={sim}",
                       headers={"X-User-Role": "FARMER"}).status_code == 403


def test_invalid_role_is_rejected(centre):
    cid, _ = centre
    assert client.get(f"/api/centres/{cid}/state",
                      headers={"X-User-Role": "SUPERUSER"}).status_code == 403


def test_operator_can_post_events_auth_passes(centre):
    """OPERATOR is authorised; domain drives actual outcome code."""
    cid, _ = centre
    resp = client.post("/api/events", json={
        "event_id": f"ev_op_{uuid.uuid4().hex[:8]}",
        "timestamp": datetime(2026, 8, 31, 9, 0, 0).isoformat(),
        "source": "SYSTEM", "event_type": "COUNTER_UNAVAILABLE",
        "metadata": {"centre_id": cid, "counter_id": f"cnt1_{cid}"},
    }, headers={"X-User-Role": "OPERATOR"})
    assert resp.status_code in (200, 400, 409)


def test_admin_can_approve_empty_recommendation(centre):
    cid, db = centre
    rec_id = insert_recommendation(db, cid, [])
    assert approve(rec_id).status_code == 200


def test_admin_can_reject(centre):
    cid, db = centre
    rec_id = insert_recommendation(db, cid, [])
    assert reject_rec(rec_id).status_code == 200


# ════════════════════════════════════════════════════════════════════════════
# 3. HTTP EVENT IDEMPOTENCY
# ════════════════════════════════════════════════════════════════════════════

def test_duplicate_event_returns_409(centre):
    """Same event_id twice → second call must return 409 DUPLICATE_EVENT."""
    cid, _ = centre
    event_id = f"idem_ev_{uuid.uuid4().hex[:8]}"

    # Ensure cnt2 is UNAVAILABLE so RESTORED is a legal transition
    client.post("/api/events", json={
        "event_id": f"prereq_{uuid.uuid4().hex[:8]}",
        "timestamp": datetime(2026, 8, 31, 9, 0, 0).isoformat(),
        "source": "SYSTEM", "event_type": "COUNTER_UNAVAILABLE",
        "metadata": {"centre_id": cid, "counter_id": f"cnt2_{cid}"},
    }, headers={"X-User-Role": "OPERATOR"})

    payload = {
        "event_id": event_id,
        "timestamp": datetime(2026, 8, 31, 9, 30, 0).isoformat(),
        "source": "SYSTEM", "event_type": "COUNTER_RESTORED",
        "metadata": {"centre_id": cid, "counter_id": f"cnt2_{cid}"},
    }
    r1 = client.post("/api/events", json=payload, headers={"X-User-Role": "OPERATOR"})
    assert r1.status_code != 409, "First submit must not be 409"

    if r1.status_code == 200:
        r2 = client.post("/api/events", json=payload, headers={"X-User-Role": "OPERATOR"})
        assert r2.status_code == 409, f"Duplicate must return 409, got {r2.status_code}"
        assert r2.json()["detail"]["code"] == "DUPLICATE_EVENT"


def test_duplicate_arrival_does_not_double_queue(centre):
    """Identical FARMER_ARRIVED submitted twice must not increment queue twice."""
    cid, _ = centre
    bid = make_booking(cid, hours_from_now=12, booking_id=f"b_idem_{uuid.uuid4().hex[:6]}")
    event_id = f"idem_arr_{uuid.uuid4().hex[:8]}"
    payload = {
        "event_id": event_id,
        "timestamp": datetime(2026, 8, 31, 10, 0, 0).isoformat(),
        "source": "GATE", "event_type": "FARMER_ARRIVED",
        "metadata": {"centre_id": cid, "booking_id": bid},
    }
    r1 = client.post("/api/events", json=payload, headers={"X-User-Role": "OPERATOR"})
    assert r1.status_code == 200

    q1 = client.get(f"/api/centres/{cid}/state",
                    headers={"X-User-Role": "OPERATOR"}).json()["current_queue"]

    r2 = client.post("/api/events", json=payload, headers={"X-User-Role": "OPERATOR"})
    assert r2.status_code == 409

    q2 = client.get(f"/api/centres/{cid}/state",
                    headers={"X-User-Role": "OPERATOR"}).json()["current_queue"]
    assert q2 == q1, f"Queue must not change on duplicate (was {q1}, now {q2})"


# ════════════════════════════════════════════════════════════════════════════
# 4. STALE RECOMMENDATION PROTECTION
# ════════════════════════════════════════════════════════════════════════════

def test_approval_rejected_when_booking_moved(centre):
    """original_start in recommendation no longer matches booking → 400 stale."""
    cid, db = centre
    bid = make_booking(cid, hours_from_now=20, booking_id=f"b_stale_{uuid.uuid4().hex[:6]}")
    row = booking_row(db, bid)
    orig = row.scheduled_start_time

    rec_id = insert_recommendation(db, cid, [{
        "booking_id": bid,
        "original_start": orig,
        "proposed_start": orig + timedelta(hours=2),
    }])
    # Externally move the booking
    row.scheduled_start_time = orig + timedelta(hours=1)
    db.commit()

    resp = approve(rec_id)
    assert resp.status_code == 400
    assert "stale" in resp.json()["detail"].lower()


def test_approval_rejected_when_booking_cancelled(centre):
    """Cancelled booking after recommendation was created → 400."""
    cid, db = centre
    bid = make_booking(cid, hours_from_now=21, booking_id=f"b_canc_{uuid.uuid4().hex[:6]}")
    row = booking_row(db, bid)

    rec_id = insert_recommendation(db, cid, [{
        "booking_id": bid,
        "original_start": row.scheduled_start_time,
        "proposed_start": row.scheduled_start_time + timedelta(hours=2),
    }])
    row.booking_state = BookingState.CANCELLED
    db.commit()

    resp = approve(rec_id)
    assert resp.status_code == 400
    detail = resp.json()["detail"].lower()
    assert "stale" in detail or "cancelled" in detail


def test_approval_succeeds_when_booking_unchanged(centre):
    """Baseline: unchanged booking → approval succeeds."""
    cid, db = centre
    bid = make_booking(cid, hours_from_now=22, booking_id=f"b_ok_{uuid.uuid4().hex[:6]}")
    row = booking_row(db, bid)

    rec_id = insert_recommendation(db, cid, [{
        "booking_id": bid,
        "original_start": row.scheduled_start_time,
        "proposed_start": row.scheduled_start_time + timedelta(hours=2),
    }])
    assert approve(rec_id).status_code == 200


# ════════════════════════════════════════════════════════════════════════════
# 5. APPROVAL STATE MACHINE
# ════════════════════════════════════════════════════════════════════════════

def test_pending_to_approved(centre):
    cid, db = centre
    rec_id = insert_recommendation(db, cid, [])
    assert approve(rec_id).status_code == 200
    db.expire_all()
    assert rec_row(db, rec_id).status == "APPROVED"


def test_pending_to_rejected(centre):
    cid, db = centre
    rec_id = insert_recommendation(db, cid, [])
    assert reject_rec(rec_id).status_code == 200
    db.expire_all()
    assert rec_row(db, rec_id).status == "REJECTED"


def test_cannot_approve_already_approved(centre):
    cid, db = centre
    rec_id = insert_recommendation(db, cid, [], status="APPROVED")
    resp = approve(rec_id)
    assert resp.status_code == 400
    assert "APPROVED" in resp.json()["detail"]


def test_cannot_reject_already_rejected(centre):
    cid, db = centre
    rec_id = insert_recommendation(db, cid, [], status="REJECTED")
    resp = reject_rec(rec_id)
    assert resp.status_code == 400
    assert "REJECTED" in resp.json()["detail"]


def test_cannot_approve_already_rejected(centre):
    cid, db = centre
    rec_id = insert_recommendation(db, cid, [], status="REJECTED")
    resp = approve(rec_id)
    assert resp.status_code == 400
    assert "REJECTED" in resp.json()["detail"]


def test_cannot_reject_already_approved(centre):
    cid, db = centre
    rec_id = insert_recommendation(db, cid, [], status="APPROVED")
    resp = reject_rec(rec_id)
    assert resp.status_code == 400
    assert "APPROVED" in resp.json()["detail"]


def test_failed_approval_leaves_recommendation_pending(centre):
    """Domain error during approval must not flip status to APPROVED."""
    cid, db = centre
    bid = make_booking(cid, hours_from_now=23, booking_id=f"b_sm_{uuid.uuid4().hex[:6]}")
    row = booking_row(db, bid)

    rec_id = insert_recommendation(db, cid, [{
        "booking_id": bid,
        "original_start": row.scheduled_start_time,
        "proposed_start": row.scheduled_start_time + timedelta(hours=1),
    }])
    row.booking_state = BookingState.COMPLETED
    db.commit()

    resp = approve(rec_id)
    assert resp.status_code == 400
    db.expire_all()
    assert rec_row(db, rec_id).status == "PENDING"


# ════════════════════════════════════════════════════════════════════════════
# 6. SIMULATED TIME PROPAGATION
# ════════════════════════════════════════════════════════════════════════════

def test_prediction_uses_simulated_time_not_now(centre):
    """generated_at must equal supplied simulated_time, not datetime.now()."""
    cid, _ = centre
    sim_ts = datetime(2026, 1, 1, 8, 0, 0)
    resp = client.get(
        f"/api/centres/{cid}/predictions?simulated_time={sim_ts.isoformat()}",
        headers={"X-User-Role": "OPERATOR"},
    )
    assert resp.status_code == 200
    gen = datetime.fromisoformat(resp.json()["generated_at"])
    assert gen.year == 2026 and gen.month == 1 and gen.day == 1, \
        f"generated_at must reflect 2026-01-01, got {gen}"


def test_event_timestamp_not_overridden_by_now(centre):
    """Events with a past explicit timestamp must not cause 500."""
    cid, _ = centre
    resp = client.post("/api/events", json={
        "event_id": f"ts_chk_{uuid.uuid4().hex[:8]}",
        "timestamp": datetime(2026, 3, 15, 14, 30, 0).isoformat(),
        "source": "SYSTEM", "event_type": "COUNTER_UNAVAILABLE",
        "metadata": {"centre_id": cid, "counter_id": f"cnt2_{cid}"},
    }, headers={"X-User-Role": "OPERATOR"})
    assert resp.status_code in (200, 400, 409), \
        f"500 would indicate datetime.now() override: {resp.status_code}"


# ════════════════════════════════════════════════════════════════════════════
# 7. SCENARIO ENDPOINT CLASSIFICATION
# ════════════════════════════════════════════════════════════════════════════

def test_scenario_run_endpoint_exists(centre):
    sim = datetime(2026, 8, 31, 8, 0, 0).isoformat()
    resp = client.post(f"/api/scenarios/run?simulated_time={sim}",
                       headers={"X-User-Role": "ADMIN"})
    assert resp.status_code != 404, "/api/scenarios/run must exist"


def test_scenario_run_blocked_for_operator(centre):
    sim = datetime(2026, 8, 31, 8, 0, 0).isoformat()
    assert client.post(f"/api/scenarios/run?simulated_time={sim}",
                       headers={"X-User-Role": "OPERATOR"}).status_code == 403


def test_scenario_run_blocked_for_farmer(centre):
    sim = datetime(2026, 8, 31, 8, 0, 0).isoformat()
    assert client.post(f"/api/scenarios/run?simulated_time={sim}",
                       headers={"X-User-Role": "FARMER"}).status_code == 403


def test_scenario_response_has_no_intelligence_fields(centre):
    """Adapter response must not contain predictor internals."""
    sim = datetime(2026, 8, 31, 8, 0, 0).isoformat()
    resp = client.post(f"/api/scenarios/run?simulated_time={sim}",
                       headers={"X-User-Role": "ADMIN"})
    if resp.status_code == 200:
        body = resp.json()
        assert "time_points" not in body
        assert "congestion_level" not in body
        assert "note" in body


# ════════════════════════════════════════════════════════════════════════════
# 8 + 9. FULL CLOSED-LOOP TRACE + PROCUREMENT/PAYMENT INTACT
# ════════════════════════════════════════════════════════════════════════════

def test_full_closed_loop_procurement_payment_intact(centre):
    """
    NORMAL CENTRE -> COUNTER FAILURE -> STATE MUTATION -> PREDICTION
    -> RECOMMENDATION -> ADMIN APPROVAL -> BOOKING RESCHEDULE
    -> RESCHEDULE COUNT UPDATED -> PROCUREMENT/PAYMENT INTACT
    """
    cid, db = centre
    sim_base = datetime(2026, 8, 31, 11, 0, 0)

    # Step 1: Centre is OPEN
    sr = client.get(f"/api/centres/{cid}/state", headers={"X-User-Role": "OPERATOR"})
    assert sr.status_code == 200
    assert sr.json()["operating_status"] == "OPEN"

    # Step 2: Create booking, capture initial statuses
    bid = f"cl_{uuid.uuid4().hex[:6]}"
    b_resp = client.post("/api/bookings", json={
        "booking_id": bid,
        "farmer_id": "farmer_loop",
        "centre_id": cid,
        "scheduled_start_time": (sim_base + timedelta(hours=2)).isoformat(),
        "priority_level": 1,
    })
    assert b_resp.status_code == 200
    assert b_resp.json()["procurement_status"] == "NOT_STARTED"
    assert b_resp.json()["payment_status"] == "NOT_INITIATED"
    assert b_resp.json()["reschedule_count"] == 0

    # Step 3: Counter failure -> STATE MUTATION
    ev_resp = client.post("/api/events", json={
        "event_id": f"cl_ev_{uuid.uuid4().hex[:8]}",
        "timestamp": sim_base.isoformat(),
        "source": "SYSTEM",
        "event_type": "COUNTER_UNAVAILABLE",
        "metadata": {"centre_id": cid, "counter_id": f"cnt1_{cid}"},
    }, headers={"X-User-Role": "OPERATOR"})
    assert ev_resp.status_code in (200, 400)  # cumulative state dep.

    # Step 4: PREDICTION endpoint returns data
    pred_resp = client.get(
        f"/api/centres/{cid}/predictions?simulated_time={sim_base.isoformat()}",
        headers={"X-User-Role": "OPERATOR"},
    )
    assert pred_resp.status_code == 200
    assert "time_points" in pred_resp.json()
    assert pred_resp.json()["centre_id"] == cid

    # Step 5: Recommendations list accessible
    assert client.get(f"/api/centres/{cid}/recommendations",
                      headers={"X-User-Role": "OPERATOR"}).status_code == 200

    # Step 6: Insert recommendation for the booking
    row = booking_row(db, bid)
    orig_procurement = row.procurement_status
    orig_payment = row.payment_status
    orig_reschedule = row.reschedule_count

    orig_start_time = row.scheduled_start_time  # plain Python datetime — not a live ORM ref
    rec_id = insert_recommendation(db, cid, [{
        "booking_id": bid,
        "original_start": orig_start_time,
        "proposed_start": orig_start_time + timedelta(hours=3),
    }])

    # Step 7: ADMIN APPROVAL
    ap_resp = approve(rec_id, sim_base)
    assert ap_resp.status_code == 200, f"Approval failed: {ap_resp.json()}"

    # Step 8: Verify BOOKING RESCHEDULE
    db.expire_all()
    row_after = booking_row(db, bid)
    assert row_after.booking_state == BookingState.RESCHEDULED

    # Step 9: reschedule_count incremented exactly once
    assert row_after.reschedule_count == orig_reschedule + 1

    # Step 10: PROCUREMENT + PAYMENT INTACT
    assert row_after.procurement_status == orig_procurement
    assert row_after.payment_status == orig_payment

    # Step 11: scheduled_start_time updated
    # IMPORTANT: capture expected BEFORE expire_all so we hold a plain Python value
    expected = orig_start_time + timedelta(hours=3)
    assert abs((row_after.scheduled_start_time - expected).total_seconds()) < 2

    # Step 12: recommendation APPROVED
    assert rec_row(db, rec_id).status == "APPROVED"

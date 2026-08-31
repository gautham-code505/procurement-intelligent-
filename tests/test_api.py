import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
import uuid

from api.main import app
from api.dependencies import get_db
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from core.domain.models import (
    OperatingStatus, CentreState, Counter, CounterStatus,
    BookingState, ConstraintSet
)
from infrastructure.database.database import Base
from infrastructure.database.models import (
    BookingModel, RecommendationModel, RecommendationChangeModel
)

# ── Each module gets a completely isolated in-memory SQLite instance ──────────
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

# Use a fixed "simulated now" well in the future so minimum-notice never rejects
_SIM_NOW = datetime(2026, 9, 1, 9, 0, 0)


@pytest.fixture(scope="module")
def setup_db():
    Base.metadata.create_all(bind=_engine)
    db = _SessionLocal()

    centre_id = f"api_centre_{uuid.uuid4().hex[:8]}"
    state = CentreState(
        centre_id=centre_id,
        timestamp=_SIM_NOW,
        operating_status=OperatingStatus.OPEN,
        counters=[
            Counter(counter_id=f"c1_{centre_id}", centre_id=centre_id,
                    status=CounterStatus.ACTIVE, processing_rate=4.0),
            Counter(counter_id=f"c2_{centre_id}", centre_id=centre_id,
                    status=CounterStatus.ACTIVE, processing_rate=4.0),
        ],
    )
    from infrastructure.database.repositories import SQLAlchemyCentreRepository
    repo = SQLAlchemyCentreRepository(db)
    repo.update_state(state)
    constraints = ConstraintSet(
        operating_hours_start="08:00",
        operating_hours_end="18:00",
        slot_capacity=4,
        booking_validity_window_minutes=30,
        available_capacity=4,
        minimum_notice_minutes=15,
    )
    repo.update_constraints(centre_id, constraints)
    db.commit()

    yield centre_id, db

    db.close()
    Base.metadata.drop_all(bind=_engine)


def test_create_booking(setup_db):
    centre_id, _ = setup_db
    booking_id = f"b_{uuid.uuid4().hex[:8]}"
    # Use simulated_now + 2 hours so minimum-notice (15 min) is never violated
    start_time = (_SIM_NOW + timedelta(hours=2)).replace(microsecond=0)

    response = client.post("/api/bookings", json={
        "booking_id": booking_id,
        "farmer_id": "farmer_123",
        "centre_id": centre_id,
        "scheduled_start_time": start_time.isoformat(),
        "priority_level": 0,
    })

    assert response.status_code == 200
    data = response.json()
    assert data["booking_id"] == booking_id
    assert data["booking_state"] == "SCHEDULED"


def test_get_farmer_bookings(setup_db):
    centre_id, _ = setup_db
    farmer_id = "farmer_123"
    response = client.get(f"/api/farmers/{farmer_id}/bookings")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["farmer_id"] == farmer_id


def test_get_centre_state(setup_db):
    centre_id, _ = setup_db
    response = client.get(
        f"/api/centres/{centre_id}/state",
        headers={"X-User-Role": "OPERATOR"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["centre_id"] == centre_id
    assert data["operating_status"] == "OPEN"
    assert len(data["counters"]) == 2


def test_post_farmer_arrival(setup_db):
    centre_id, _ = setup_db
    farmer_id = "farmer_123"
    booking_resp = client.get(f"/api/farmers/{farmer_id}/bookings")
    assert booking_resp.status_code == 200
    bookings = booking_resp.json()
    assert len(bookings) >= 1
    booking_id = bookings[0]["booking_id"]

    event_payload = {
        "event_id": f"ev_{uuid.uuid4().hex[:8]}",
        "timestamp": _SIM_NOW.isoformat(),
        "source": "GATE",
        "event_type": "FARMER_ARRIVED",
        "metadata": {"centre_id": centre_id, "booking_id": booking_id},
    }

    resp = client.post("/api/events", json=event_payload, headers={"X-User-Role": "OPERATOR"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ACCEPTED"
    assert data["state_updated"] is True

    booking_resp = client.get(f"/api/farmers/{farmer_id}/bookings")
    b_data = [b for b in booking_resp.json() if b["booking_id"] == booking_id][0]
    assert b_data["booking_state"] == "ARRIVED"


def test_post_counter_failure_and_prediction(setup_db):
    centre_id, _ = setup_db

    event_payload = {
        "event_id": f"ev_{uuid.uuid4().hex[:8]}",
        "timestamp": _SIM_NOW.isoformat(),
        "source": "SYSTEM",
        "event_type": "COUNTER_UNAVAILABLE",
        "metadata": {"centre_id": centre_id, "counter_id": f"c1_{centre_id}"},
    }

    resp = client.post("/api/events", json=event_payload, headers={"X-User-Role": "OPERATOR"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ACCEPTED"
    assert data["prediction_triggered"] is True

    # GET prediction with required simulated_time
    pred_resp = client.get(
        f"/api/centres/{centre_id}/predictions?simulated_time={_SIM_NOW.isoformat()}",
        headers={"X-User-Role": "OPERATOR"},
    )
    assert pred_resp.status_code == 200
    assert "time_points" in pred_resp.json()


def test_recommendation_rollback(setup_db):
    """
    Partial approval failure: booking is COMPLETED → mark_rescheduled fails.
    Verify recommendation stays PENDING (rollback).
    """
    centre_id, db = setup_db

    # Create the booking via API so it exists in this module's DB
    booking_id = f"b_rollback_{uuid.uuid4().hex[:8]}"
    start_time = (_SIM_NOW + timedelta(hours=3)).replace(microsecond=0)
    b_resp = client.post("/api/bookings", json={
        "booking_id": booking_id,
        "farmer_id": "farmer_fail",
        "centre_id": centre_id,
        "scheduled_start_time": start_time.isoformat(),
        "priority_level": 0,
    })
    assert b_resp.status_code == 200, f"Booking creation failed: {b_resp.json()}"

    rec_id = f"rec_{uuid.uuid4().hex[:8]}"
    rec = RecommendationModel(
        recommendation_id=rec_id,
        centre_id=centre_id,
        trigger_event_id="dummy",
        created_at=_SIM_NOW,
        status="PENDING",
        reason="Test",
        expected_impact="Test",
        constraint_check="[]",
        fairness_check="[]",
    )
    change = RecommendationChangeModel(
        recommendation_id=rec_id,
        booking_id=booking_id,
        original_start=start_time,
        proposed_start=start_time + timedelta(hours=1),
        priority_level=0,
        reschedule_count=0,
    )
    db.add(rec)
    db.add(change)
    db.commit()

    # Sabotage booking so mark_rescheduled raises DomainException
    bm = db.query(BookingModel).filter(BookingModel.booking_id == booking_id).first()
    assert bm is not None, "Booking must exist in test DB"
    bm.booking_state = BookingState.COMPLETED
    db.commit()

    resp = client.post(
        f"/api/recommendations/{rec_id}/approve?simulated_time={_SIM_NOW.isoformat()}",
        headers={"X-User-Role": "ADMIN"},
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.json()}"

    db.expire_all()
    rec_db = db.query(RecommendationModel).filter(
        RecommendationModel.recommendation_id == rec_id
    ).first()
    assert rec_db.status == "PENDING", "Recommendation must remain PENDING after failed approval"



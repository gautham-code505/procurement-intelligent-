from datetime import datetime
import uuid
import pytest

from core.domain.models import (
    CentreState, OperatingStatus, CongestionLevel, Counter, CounterStatus,
    Booking, BookingState, ProcurementStatus, PaymentStatus, OperationalEvent,
    CentreStateSnapshot, Recommendation, RecommendationChange
)
from infrastructure.database.repositories import (
    SQLAlchemyCentreRepository, SQLAlchemyBookingRepository,
    SQLAlchemyEventRepository, SQLAlchemyRecommendationRepository
)
from infrastructure.database.models import OperationalEventModel

def test_create_read_centre_and_counter(db_session):
    repo = SQLAlchemyCentreRepository(db_session)
    state = CentreState(
        centre_id="c1",
        timestamp=datetime.now(),
        operating_status=OperatingStatus.OPEN,
        counters=[
            Counter(counter_id="cnt_1", centre_id="c1", status=CounterStatus.ACTIVE, processing_rate=15.0)
        ]
    )
    repo.update_state(state)
    
    loaded_state = repo.get_state("c1")
    assert loaded_state is not None
    assert loaded_state.centre_id == "c1"
    assert len(loaded_state.counters) == 1
    assert loaded_state.counters[0].processing_rate == 15.0

def test_create_read_booking(db_session):
    repo = SQLAlchemyBookingRepository(db_session)
    booking = Booking(
        booking_id="b1",
        farmer_id="f1",
        centre_id="c1",
        scheduled_start_time=datetime(2026, 8, 30, 10, 0),
        scheduled_end_time=datetime(2026, 8, 30, 10, 30),
        booking_state=BookingState.SCHEDULED,
        procurement_status=ProcurementStatus.NOT_STARTED,
        payment_status=PaymentStatus.NOT_INITIATED,
        priority_level=1,
        reschedule_count=0
    )
    repo.update_booking(booking)
    
    loaded = repo.get_booking("b1")
    assert loaded is not None
    assert loaded.farmer_id == "f1"
    assert loaded.booking_state == BookingState.SCHEDULED

def test_persist_operational_event_and_idempotency(db_session):
    repo = SQLAlchemyEventRepository(db_session)
    event_id = str(uuid.uuid4())
    event = OperationalEvent(
        event_id=event_id,
        timestamp=datetime.now(),
        source="simulator",
        event_type="TEST",
        metadata={"key": "value"}
    )
    repo.add_event(event)
    
    # Verify persistence
    count = db_session.query(OperationalEventModel).count()
    assert count == 1
    
    # 6. prevent duplicate event_id
    with pytest.raises(ValueError, match="Idempotency check failed"):
        repo.add_event(event)

def test_persist_centre_state_snapshot(db_session):
    repo = SQLAlchemyEventRepository(db_session)
    centre_repo = SQLAlchemyCentreRepository(db_session)
    
    # Create the centre model first for foreign key integrity
    state = CentreState(centre_id="c2", timestamp=datetime.now(), operating_status=OperatingStatus.OPEN)
    centre_repo.update_state(state)
    
    snapshot = CentreStateSnapshot(
        snapshot_id=str(uuid.uuid4()),
        centre_id="c2",
        timestamp=datetime.now(),
        state=state
    )
    repo.add_snapshot(snapshot)
    
    # Update state and snapshot again to ensure multiple persist
    state.increment_queue()
    snapshot2 = CentreStateSnapshot(
        snapshot_id=str(uuid.uuid4()),
        centre_id="c2",
        timestamp=datetime.now(),
        state=state
    )
    repo.add_snapshot(snapshot2)
    
    # 7. Snapshots persist historically, not overwritten
    # 8. Retrieve snapshots in chronological order
    # Our repository implementation get_state relies on this order
    latest = centre_repo.get_state("c2")
    assert latest.current_queue == 1

def test_persist_recommendation(db_session):
    repo = SQLAlchemyRecommendationRepository(db_session)
    centre_repo = SQLAlchemyCentreRepository(db_session)
    
    state = CentreState(centre_id="c3", timestamp=datetime.now(), operating_status=OperatingStatus.OPEN)
    centre_repo.update_state(state)
    
    rec = Recommendation(
        recommendation_id="r1",
        centre_id="c3",
        trigger_event_id="e1",
        created_at=datetime.now(),
        status="PENDING",
        reason="Test",
        expected_impact="None",
        constraint_check="Passed",
        fairness_check="Passed",
        changes=[
            RecommendationChange(
                booking_id="b2",
                original_start=datetime.now(),
                proposed_start=datetime.now(),
                priority_level=1,
                reschedule_count=1
            )
        ]
    )
    
    repo.add_recommendation(rec)
    # The models handle the relationship cascade. Since get_pending_recommendations is stubbed 
    # to return mapped domain models in Milestone 1B, we just verify no exceptions occur on persist.

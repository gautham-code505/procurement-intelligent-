from datetime import datetime
import uuid
from typing import List, Optional

from core.domain.models import (
    CentreState, OperatingStatus, CongestionLevel, OperationalEvent,
    Booking, BookingState, Counter, CounterStatus, ProcurementStatus,
    PaymentStatus, PredictionResult, Recommendation, ConstraintSet
)
from infrastructure.database.in_memory import (
    InMemoryCentreRepository, InMemoryBookingRepository,
    InMemoryEventRepository, InMemoryRecommendationRepository
)
from core.interfaces.engines import IPredictor, IDecisionEngine
from core.services.coordination import AdaptiveCoordinationService

class FakePredictor(IPredictor):
    def predict(self, centre_state, bookings, current_time, horizon_hours):
        return PredictionResult(
            centre_id=centre_state.centre_id,
            generated_at=current_time,
            horizon_start=current_time,
            horizon_end=current_time,
            time_points=[],
            summary="Fake prediction",
            explanation="Fake predictor"
        )

class FakeDecisionEngine(IDecisionEngine):
    def generate_recommendation(self, centre_state, prediction, bookings, constraints):
        return None

def create_setup():
    centre_repo = InMemoryCentreRepository()
    booking_repo = InMemoryBookingRepository()
    event_repo = InMemoryEventRepository()
    recommendation_repo = InMemoryRecommendationRepository()

    predictor = FakePredictor()
    decision_engine = FakeDecisionEngine()

    service = AdaptiveCoordinationService(
        centre_repo, booking_repo, event_repo, recommendation_repo,
        predictor, decision_engine
    )

    centre_id = "c1"
    initial_state = CentreState(
        centre_id=centre_id,
        timestamp=datetime(2026, 8, 30, 9, 0),
        operating_status=OperatingStatus.OPEN,
        counters=[
            Counter(counter_id="cnt_1", centre_id="c1", status=CounterStatus.ACTIVE, processing_rate=10.0),
            Counter(counter_id="cnt_2", centre_id="c1", status=CounterStatus.ACTIVE, processing_rate=10.0)
        ],
        current_queue=0,
        expected_arrivals=0,
        projected_queue=0,
        projected_wait_minutes=0.0,
        congestion_level=CongestionLevel.LOW
    )
    centre_repo.update_state(initial_state)
    
    booking = Booking(
        booking_id="b1",
        farmer_id="f1",
        centre_id="c1",
        scheduled_start_time=datetime(2026, 8, 30, 9, 0),
        scheduled_end_time=datetime(2026, 8, 30, 9, 30),
        booking_state=BookingState.SCHEDULED,
        procurement_status=ProcurementStatus.NOT_STARTED,
        payment_status=PaymentStatus.NOT_INITIATED,
        priority_level=1,
        reschedule_count=0
    )
    booking_repo.update_booking(booking)

    return service, centre_repo, booking_repo, event_repo

def test_farmer_arrived_increments_queue():
    service, centre_repo, booking_repo, event_repo = create_setup()
    
    event_time = datetime(2026, 8, 30, 9, 5)
    event = OperationalEvent(
        event_id="e1",
        timestamp=event_time,
        source="simulator",
        event_type="FARMER_ARRIVED",
        metadata={"centre_id": "c1", "booking_id": "b1"}
    )
    
    service.process_event(event)
    
    # 8. FARMER_ARRIVED increments queue
    state = centre_repo.get_state("c1")
    assert state.current_queue == 1
    
    # Check booking transitioned
    booking = booking_repo.get_booking("b1")
    assert booking.booking_state == BookingState.ARRIVED
    
    # 17. every state-changing event produces a snapshot
    assert len(event_repo._snapshots) == 1
    
    # 18. snapshot timestamp equals event simulated timestamp
    # 20. processing a simulated event at a fixed timestamp produces a snapshot with exactly that timestamp
    snapshot = event_repo._snapshots[0]
    assert snapshot.timestamp == event_time
    
    # 19. snapshot reflects the UPDATED state, not the previous state
    assert snapshot.state.current_queue == 1

def test_farmer_completed_decrements_queue():
    service, centre_repo, booking_repo, event_repo = create_setup()
    
    # Setup ARRIVED then PROCESSING state
    booking = booking_repo.get_booking("b1")
    booking.mark_arrived()
    booking.mark_processing()
    booking_repo.update_booking(booking)
    
    state = centre_repo.get_state("c1")
    state.increment_queue()
    centre_repo.update_state(state)
    
    event = OperationalEvent(
        event_id="e2",
        timestamp=datetime(2026, 8, 30, 9, 30),
        source="simulator",
        event_type="FARMER_COMPLETED",
        metadata={"centre_id": "c1", "booking_id": "b1"}
    )
    service.process_event(event)
    
    # 9. FARMER_COMPLETED decrements queue
    updated_state = centre_repo.get_state("c1")
    assert updated_state.current_queue == 0
    
    b = booking_repo.get_booking("b1")
    assert b.booking_state == BookingState.COMPLETED

def test_counter_unavailable_and_restored_events():
    service, centre_repo, booking_repo, event_repo = create_setup()
    
    event_fail = OperationalEvent(
        event_id="e3",
        timestamp=datetime(2026, 8, 30, 9, 0),
        source="simulator",
        event_type="COUNTER_UNAVAILABLE",
        metadata={"centre_id": "c1", "counter_id": "cnt_1"}
    )
    service.process_event(event_fail)
    
    # 11. COUNTER_UNAVAILABLE decreases active counters
    # 12. COUNTER_UNAVAILABLE reduces effective processing rate
    state = centre_repo.get_state("c1")
    assert state.active_counters == 1
    assert state.effective_processing_rate == 10.0
    
    event_restore = OperationalEvent(
        event_id="e4",
        timestamp=datetime(2026, 8, 30, 9, 30),
        source="simulator",
        event_type="COUNTER_RESTORED",
        metadata={"centre_id": "c1", "counter_id": "cnt_1"}
    )
    service.process_event(event_restore)
    
    # 13. COUNTER_RESTORED restores active counters
    # 14. COUNTER_RESTORED restores effective rate
    state = centre_repo.get_state("c1")
    assert state.active_counters == 2
    assert state.effective_processing_rate == 20.0

def test_injection_works():
    # 21, 22, 23
    service, centre_repo, booking_repo, event_repo = create_setup()
    assert isinstance(service.predictor, FakePredictor)
    assert isinstance(service.decision_engine, FakeDecisionEngine)

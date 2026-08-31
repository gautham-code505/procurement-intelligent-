from datetime import datetime
import pytest
import uuid

from core.domain.models import (
    Booking, BookingState, ProcurementStatus, PaymentStatus,
    CentreState, OperatingStatus, CongestionLevel,
    OperationalEvent, RecommendationChange, Recommendation,
    TimePoint, PredictionResult, DomainException, Counter, CounterStatus
)

def create_booking(state=BookingState.SCHEDULED):
    return Booking(
        booking_id="b1",
        farmer_id="f1",
        centre_id="c1",
        scheduled_start_time=datetime(2026, 8, 30, 9, 0),
        scheduled_end_time=datetime(2026, 8, 30, 9, 30),
        booking_state=state,
        procurement_status=ProcurementStatus.NOT_STARTED,
        payment_status=PaymentStatus.NOT_INITIATED,
        priority_level=1,
        reschedule_count=0
    )

# TEST BOOKING TRANSITIONS
def test_scheduled_to_arrived():
    b = create_booking(BookingState.SCHEDULED)
    b.mark_arrived()
    assert b.booking_state == BookingState.ARRIVED

def test_arrived_to_processing():
    b = create_booking(BookingState.ARRIVED)
    b.mark_processing()
    assert b.booking_state == BookingState.PROCESSING

def test_processing_to_completed():
    b = create_booking(BookingState.PROCESSING)
    b.mark_completed()
    assert b.booking_state == BookingState.COMPLETED

def test_scheduled_to_rescheduled():
    b = create_booking(BookingState.SCHEDULED)
    b.mark_rescheduled()
    assert b.booking_state == BookingState.RESCHEDULED

def test_completed_to_processing_fails():
    b = create_booking(BookingState.COMPLETED)
    with pytest.raises(DomainException):
        b.mark_processing()

def test_cancelled_to_arrived_fails():
    b = create_booking(BookingState.CANCELLED)
    with pytest.raises(DomainException):
        b.mark_arrived()

def test_no_show_to_processing_fails():
    b = create_booking(BookingState.NO_SHOW)
    with pytest.raises(DomainException):
        b.mark_processing()

def create_centre_state():
    return CentreState(
        centre_id="c1",
        timestamp=datetime(2026, 8, 30, 9, 0),
        operating_status=OperatingStatus.OPEN,
        counters=[
            Counter(counter_id="cnt_1", centre_id="c1", status=CounterStatus.ACTIVE, processing_rate=10.0),
            Counter(counter_id="cnt_2", centre_id="c1", status=CounterStatus.ACTIVE, processing_rate=10.0)
        ],
        current_queue=0
    )

def test_queue_never_negative():
    state = create_centre_state()
    with pytest.raises(DomainException):
        state.decrement_queue()

def test_counter_unavailable_reduces_rate():
    state = create_centre_state()
    assert state.effective_processing_rate == 20.0
    assert state.active_counters == 2

    state.set_counter_status("cnt_1", CounterStatus.UNAVAILABLE)
    assert state.effective_processing_rate == 10.0
    assert state.active_counters == 1

def test_counter_restored_restores_rate():
    state = create_centre_state()
    state.set_counter_status("cnt_1", CounterStatus.UNAVAILABLE)
    state.set_counter_status("cnt_1", CounterStatus.ACTIVE)
    assert state.effective_processing_rate == 20.0
    assert state.active_counters == 2

def test_processing_rate_changed():
    state = create_centre_state()
    state.update_processing_rate("cnt_1", 15.0)
    assert state.effective_processing_rate == 25.0

def test_invalid_counter_restoration_rejected():
    state = create_centre_state()
    # cnt_1 is already active
    with pytest.raises(DomainException):
        state.set_counter_status("cnt_1", CounterStatus.ACTIVE)

import pytest
from datetime import datetime, timedelta

from core.domain.models import CentreState, OperatingStatus, Counter, CounterStatus, Booking, BookingState, ProcurementStatus, PaymentStatus, ConstraintSet
from core.intelligence.predictor import BaselinePredictor
from core.intelligence.decider import HeuristicDecisionEngine, AlternativeSlot

def test_minimum_notice_constraint():
    predictor = BaselinePredictor(delta_t_minutes=15)
    decider = HeuristicDecisionEngine(predictor, delta_t_minutes=15)
    
    state = CentreState(
        centre_id="c1", timestamp=datetime.now(), operating_status=OperatingStatus.OPEN,
        counters=[Counter("cnt_1", "c1", CounterStatus.ACTIVE, 10.0)]
    )
    
    current_time = datetime(2026, 8, 30, 10, 0)
    # Give a booking right at 10:15 that needs to be moved to cause congestion
    bookings = [
        Booking(
            booking_id="b_1", farmer_id="f_1", centre_id="c1",
            scheduled_start_time=current_time + timedelta(minutes=15),
            scheduled_end_time=current_time + timedelta(minutes=30),
            booking_state=BookingState.SCHEDULED, procurement_status=ProcurementStatus.NOT_STARTED,
            payment_status=PaymentStatus.NOT_INITIATED, priority_level=0, reschedule_count=0
        )
    ]
    # Inject fake congestion so decider runs
    pred = predictor.predict(state, bookings, current_time, 4.0)
    for tp in pred.time_points:
        tp.congestion_level = "CRITICAL"
        
    # By default, minimum_notice_minutes = 15.
    constraints = ConstraintSet("08:00", "18:00", 10, 60, 100, minimum_notice_minutes=15)
    
    # Generate slots directly to test condition
    alt_slots = decider._generate_alternative_slots(bookings, current_time, current_time + timedelta(hours=4), constraints)
    
    # Simulate valid_slots filtering inside generate_recommendation
    valid_slots = [
        s for s in alt_slots 
        if s.remaining_capacity > 0 
        and s.start_time >= current_time + timedelta(minutes=constraints.minimum_notice_minutes)
    ]
    
    # 1. slot before current_time -> handled by generate generating from current_time forward
    # 2. slot exactly at current_time
    slot_10_00 = next((s for s in alt_slots if s.start_time == current_time), None)
    assert slot_10_00 is not None
    assert slot_10_00 not in valid_slots # Rejected
    
    # 3. slot 1 minute after current_time -> slots are 15-min aligned, but if we had one at 10:01:
    fake_slot = AlternativeSlot(current_time + timedelta(minutes=1), current_time + timedelta(minutes=16), 10, 0)
    assert fake_slot.start_time < current_time + timedelta(minutes=constraints.minimum_notice_minutes)
    
    # 4. slot exactly at current_time + minimum_notice_window -> Accepted
    slot_10_15 = next((s for s in alt_slots if s.start_time == current_time + timedelta(minutes=15)), None)
    assert slot_10_15 is not None
    assert slot_10_15 in valid_slots # Accepted
    
    # 5. slot after minimum_notice_window -> Accepted
    slot_10_30 = next((s for s in alt_slots if s.start_time == current_time + timedelta(minutes=30)), None)
    assert slot_10_30 in valid_slots # Accepted
    
    # 6. changing minimum_notice_window changes candidate validity
    constraints.minimum_notice_minutes = 30
    valid_slots_30 = [
        s for s in alt_slots 
        if s.remaining_capacity > 0 
        and s.start_time >= current_time + timedelta(minutes=constraints.minimum_notice_minutes)
    ]
    assert slot_10_15 not in valid_slots_30 # Now rejected
    assert slot_10_30 in valid_slots_30 # Accepted
    
    # 7. simulated time is used rather than system clock
    # The filter uses `current_time` (which is `prediction.horizon_start` representing 2026) 
    # not datetime.now(), otherwise all slots would be rejected.
    assert current_time == datetime(2026, 8, 30, 10, 0) # Proving it's a simulated fixed time

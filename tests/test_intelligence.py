import pytest
from datetime import datetime, timedelta
import uuid

from core.domain.models import (
    CentreState, OperatingStatus, Counter, CounterStatus, Booking, BookingState,
    ProcurementStatus, PaymentStatus, ConstraintSet, CongestionLevel, OperationalEvent
)
from core.intelligence.predictor import BaselinePredictor
from core.intelligence.decider import HeuristicDecisionEngine

def test_predictor_math():
    predictor = BaselinePredictor(delta_t_minutes=15)
    
    # 4 active counters, 10/hr each -> effective rate 40/hr
    state = CentreState(
        centre_id="c1",
        timestamp=datetime.now(),
        operating_status=OperatingStatus.OPEN,
        counters=[
            Counter("cnt_1", "c1", CounterStatus.ACTIVE, 10.0),
            Counter("cnt_2", "c1", CounterStatus.ACTIVE, 10.0),
            Counter("cnt_3", "c1", CounterStatus.ACTIVE, 10.0),
            Counter("cnt_4", "c1", CounterStatus.ACTIVE, 10.0)
        ]
    )
    
    # 40 arrivals in the first hour
    current_time = datetime(2026, 8, 30, 9, 0)
    bookings = []
    for i in range(40):
        # 10 bookings every 15 mins starting from 9:00
        slot_start = current_time + timedelta(minutes=(i // 10) * 15)
        bookings.append(Booking(
            booking_id=f"b_{i}",
            farmer_id=f"f_{i}",
            centre_id="c1",
            scheduled_start_time=slot_start,
            scheduled_end_time=slot_start + timedelta(minutes=15),
            booking_state=BookingState.SCHEDULED,
            procurement_status=ProcurementStatus.NOT_STARTED,
            payment_status=PaymentStatus.NOT_INITIATED,
            priority_level=0,
            reschedule_count=0
        ))
        
    result = predictor.predict(state, bookings, current_time, horizon_hours=2.0)
    
    # First 4 intervals (9:00-10:00) should have 10 arrivals each, 10 capacity each
    # Queue should remain 0
    assert result.time_points[0].projected_queue == 0
    assert result.time_points[3].projected_queue == 0
    assert result.time_points[3].estimated_wait_minutes == 0.0

def test_zero_capacity_handling():
    predictor = BaselinePredictor(delta_t_minutes=15)
    # Zero active counters -> effective rate 0
    state = CentreState(
        centre_id="c1",
        timestamp=datetime.now(),
        operating_status=OperatingStatus.OPEN,
        counters=[
            Counter("cnt_1", "c1", CounterStatus.UNAVAILABLE, 10.0)
        ],
        current_queue=5 # existing queue
    )
    
    result = predictor.predict(state, [], datetime.now(), horizon_hours=1.0)
    # With q>0 and cap=0, wait time is infinite, congestion is CRITICAL
    assert result.time_points[0].estimated_wait_minutes == float('inf')
    assert result.time_points[0].congestion_level == CongestionLevel.CRITICAL
    assert result.time_points[0].projected_queue == 5
    
def test_greedy_intervention():
    predictor = BaselinePredictor(delta_t_minutes=15)
    decider = HeuristicDecisionEngine(predictor, delta_t_minutes=15)
    
    state = CentreState(
        centre_id="c1",
        timestamp=datetime.now(),
        operating_status=OperatingStatus.OPEN,
        counters=[
            Counter("cnt_1", "c1", CounterStatus.ACTIVE, 10.0),
            Counter("cnt_2", "c1", CounterStatus.ACTIVE, 10.0)
        ]
    )
    
    current_time = datetime(2026, 8, 30, 10, 0)
    bookings = []
    # 40 arrivals scheduled from 10:00 to 11:00
    for i in range(40):
        # 10 bookings every 15 mins (0-15, 15-30, 30-45, 45-60)
        # Note: scheduling at 10:15 means arrival in (10:00, 10:15]
        slot_start = current_time + timedelta(minutes=(i // 10 + 1) * 15)
        bookings.append(Booking(
            booking_id=f"b_{i}",
            farmer_id=f"f_{i}",
            centre_id="c1",
            scheduled_start_time=slot_start,
            scheduled_end_time=slot_start + timedelta(minutes=15),
            booking_state=BookingState.SCHEDULED,
            procurement_status=ProcurementStatus.NOT_STARTED,
            payment_status=PaymentStatus.NOT_INITIATED,
            priority_level=0,
            reschedule_count=0
        ))
        
    pred = predictor.predict(state, bookings, current_time, 4.0)
    
    constraints = ConstraintSet(
        operating_hours_start="08:00",
        operating_hours_end="18:00",
        slot_capacity=10,
        booking_validity_window_minutes=60,
        available_capacity=100
    )
    
    rec = decider.generate_recommendation(state, pred, bookings, constraints)
    assert rec is not None
    assert rec.status == "FULL_RECOVERY"
    
    # Capacity is 20/hr, demand is 40/hr. Over 1 hour we have 20 excess. 
    # Engine should move approximately 19-20 farmers to idle slots to achieve FULL_RECOVERY.
    assert len(rec.changes) >= 19

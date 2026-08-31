import time
from datetime import datetime, timedelta

from core.domain.models import CentreState, OperatingStatus, Counter, CounterStatus, Booking, BookingState, ProcurementStatus, PaymentStatus, ConstraintSet, CongestionLevel, PredictionResult
from core.intelligence.predictor import BaselinePredictor
from core.intelligence.decider import HeuristicDecisionEngine

def run_demo_verification():
    predictor = BaselinePredictor(delta_t_minutes=15)
    decider = HeuristicDecisionEngine(predictor, delta_t_minutes=15)
    
    current_time = datetime(2026, 8, 30, 10, 0)
    
    state = CentreState(
        centre_id="c1",
        timestamp=current_time,
        operating_status=OperatingStatus.OPEN,
        counters=[
            Counter("cnt_1", "c1", CounterStatus.UNAVAILABLE, 10.0),
            Counter("cnt_2", "c1", CounterStatus.UNAVAILABLE, 10.0),
            Counter("cnt_3", "c1", CounterStatus.ACTIVE, 10.0),
            Counter("cnt_4", "c1", CounterStatus.ACTIVE, 10.0)
        ],
        current_queue=0
    )

    bookings = []
    for i in range(40):
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
        
    constraints = ConstraintSet('08:00', '18:00', 10, 60, 100, minimum_notice_minutes=15)
    
    pred = predictor.predict(state, bookings, current_time, 4.0)
    
    # We will manually extract the first generated alternative slots to show rejection
    alt_slots_raw = decider._generate_alternative_slots(bookings, pred.horizon_start, pred.horizon_end, constraints)
    
    rejected_slots = [s for s in alt_slots_raw if s.start_time < current_time + timedelta(minutes=constraints.minimum_notice_minutes)]
    valid_slots = [s for s in alt_slots_raw if s.start_time >= current_time + timedelta(minutes=constraints.minimum_notice_minutes)]
    
    rec = decider.generate_recommendation(state, pred, bookings, constraints)
    
    print("==================================================")
    print("DEMO VERIFICATION - MINIMUM NOTICE")
    print("==================================================")
    print(f"- Decision timestamp: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"- Configured minimum notice: {constraints.minimum_notice_minutes} minutes")
    print(f"- Earliest valid alternative slot: {valid_slots[0].start_time.strftime('%H:%M')} - {valid_slots[0].end_time.strftime('%H:%M')}")
    print(f"- All rejected earlier slots:")
    for rs in rejected_slots:
        print(f"    - {rs.start_time.strftime('%H:%M')} - {rs.end_time.strftime('%H:%M')} (REJECTED)")
        
    print(f"\n- Accepted slots (for moved bookings):")
    for c in rec.changes:
        print(f"    - Booking {c.booking_id}: moved to {c.proposed_start.strftime('%H:%M')}")
        assert c.proposed_start >= current_time + timedelta(minutes=constraints.minimum_notice_minutes), f"VIOLATION: {c.proposed_start}"
        
    print(f"\n- Final recommendation status: {rec.status}")
    
    print("\n- Final Congestion Metrics (Post-Intervention Projection):")
    import copy
    final_bookings = copy.deepcopy(bookings)
    for c in rec.changes:
        b = next(bk for bk in final_bookings if bk.booking_id == c.booking_id)
        b.scheduled_start_time = c.proposed_start
        b.scheduled_end_time = c.proposed_start + timedelta(minutes=15)
        
    final_pred = predictor.predict(state, final_bookings, current_time, 4.0)
    max_q = max(tp.projected_queue for tp in final_pred.time_points)
    max_wait = max(tp.estimated_wait_minutes for tp in final_pred.time_points)
    max_congestion = "NORMAL"
    if any(tp.congestion_level == CongestionLevel.CRITICAL for tp in final_pred.time_points): max_congestion = "CRITICAL"
    elif any(tp.congestion_level == CongestionLevel.HIGH for tp in final_pred.time_points): max_congestion = "HIGH"
    elif any(tp.congestion_level == CongestionLevel.MEDIUM for tp in final_pred.time_points): max_congestion = "MEDIUM"
    
    print(f"    - Final Max Queue: {max_q}")
    print(f"    - Final Max Wait: {max_wait:.1f}m")
    print(f"    - Final Max Congestion: {max_congestion}")

if __name__ == "__main__":
    run_demo_verification()

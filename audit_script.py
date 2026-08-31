import time
import copy
from datetime import datetime, timedelta
from typing import List

from core.domain.models import (
    CentreState, OperatingStatus, Counter, CounterStatus, Booking, BookingState,
    ProcurementStatus, PaymentStatus, ConstraintSet, CongestionLevel, PredictionResult,
    RecommendationChange
)
from core.intelligence.predictor import BaselinePredictor
from core.intelligence.decider import HeuristicDecisionEngine

def get_base_state(active_counters=2):
    counters = []
    for i in range(4):
        status = CounterStatus.ACTIVE if i < active_counters else CounterStatus.UNAVAILABLE
        counters.append(Counter(f"cnt_{i+1}", "c1", status, 10.0))
        
    return CentreState(
        centre_id="c1",
        timestamp=datetime(2026, 8, 30, 10, 0),
        operating_status=OperatingStatus.OPEN,
        counters=counters,
        current_queue=0
    )

def generate_bookings(count, current_time=datetime(2026, 8, 30, 10, 0), priority_indexes=None, rescheduled_indexes=None):
    if priority_indexes is None: priority_indexes = []
    if rescheduled_indexes is None: rescheduled_indexes = []
    
    bookings = []
    for i in range(count):
        # 10 bookings every 15 mins (0-15, 15-30, 30-45, 45-60)
        # Note: scheduling at 10:15 means arrival in (10:00, 10:15] if i // 10 + 1
        # Let's align exactly: 0-9 arrive at 10:00, 10-19 arrive at 10:15...
        slot_start = current_time + timedelta(minutes=(i // 10 + 1) * 15)
        
        priority = 1 if i in priority_indexes else 0
        reschedule_count = 1 if i in rescheduled_indexes else 0
        
        bookings.append(Booking(
            booking_id=f"b_{i}",
            farmer_id=f"f_{i}",
            centre_id="c1",
            scheduled_start_time=slot_start,
            scheduled_end_time=slot_start + timedelta(minutes=15),
            booking_state=BookingState.SCHEDULED,
            procurement_status=ProcurementStatus.NOT_STARTED,
            payment_status=PaymentStatus.NOT_INITIATED,
            priority_level=priority,
            reschedule_count=reschedule_count
        ))
    return bookings

def run_scenario(name, booking_count, capacity=10, horizon=4.0, debug=False, priority_idx=[], resched_idx=[]):
    print(f"\n{'='*60}\nSCENARIO: {name}\n{'='*60}")
    predictor = BaselinePredictor(delta_t_minutes=15)
    
    # We create a subclass of HeuristicDecisionEngine to intercept and print debug info
    class DebugDecider(HeuristicDecisionEngine):
        def _score_prediction(self, pred: PredictionResult):
            score = super()._score_prediction(pred)
            return score
            
        def generate_recommendation(self, centre_state, prediction, bookings, constraints):
            has_critical = any(tp.congestion_level == CongestionLevel.CRITICAL for tp in prediction.time_points)
            has_high = any(tp.congestion_level == CongestionLevel.HIGH for tp in prediction.time_points)
            
            if not (has_critical or has_high): return None
                
            last_issue_time = None
            for tp in reversed(prediction.time_points):
                if tp.congestion_level in [CongestionLevel.CRITICAL, CongestionLevel.HIGH]:
                    last_issue_time = tp.timestamp
                    break
                    
            eligible = [
                b for b in bookings 
                if b.booking_state in [BookingState.SCHEDULED, BookingState.RESCHEDULED]
                and b.scheduled_start_time <= last_issue_time
                and b.reschedule_count == 0 
                and b.priority_level == 0 
            ]
            
            alt_slots = self._generate_alternative_slots(bookings, prediction.horizon_start, prediction.horizon_end, constraints)
            if debug:
                print("\n[ALTERNATIVE SLOTS GENERATED]")
                for s in alt_slots:
                    print(f"  {s.start_time.strftime('%H:%M')} - {s.end_time.strftime('%H:%M')} | Cap: {s.capacity} | Booked: {s.current_bookings} | Rem: {s.remaining_capacity}")
                    
            current_bookings_state = copy.deepcopy(bookings)
            accepted_changes = []
            current_prediction = prediction
            
            iteration = 0
            while True:
                iteration += 1
                has_crit = any(tp.congestion_level == CongestionLevel.CRITICAL for tp in current_prediction.time_points)
                has_hi = any(tp.congestion_level == CongestionLevel.HIGH for tp in current_prediction.time_points)
                
                if not has_crit and not has_hi:
                    if debug: print(f"\n[STOP REASON]: Congestion fully resolved (FULL_RECOVERY).")
                    break 
                    
                best_move = None
                best_score = None
                
                for booking in eligible:
                    temp_b = next((b for b in current_bookings_state if b.booking_id == booking.booking_id), None)
                    if not temp_b or temp_b.booking_state != BookingState.SCHEDULED: continue
                    
                    valid_slots = [s for s in alt_slots if s.remaining_capacity > 0 and s.start_time >= prediction.horizon_start]
                    
                    if not valid_slots:
                        if debug: print(f"\n[STOP REASON]: No feasible alternative slots remaining with capacity.")
                        break
                        
                    valid_slots.sort(key=lambda s: s.current_bookings)
                    
                    for slot in valid_slots[:3]:
                        test_bookings = copy.deepcopy(current_bookings_state)
                        t_b = next(b for b in test_bookings if b.booking_id == booking.booking_id)
                        t_b.scheduled_start_time = slot.start_time
                        t_b.scheduled_end_time = slot.end_time
                        
                        test_pred = self.predictor.predict(centre_state, test_bookings, prediction.horizon_start, horizon)
                        score = self._score_prediction(test_pred)
                        
                        if best_score is None or score < best_score:
                            best_score = score
                            best_move = (booking.booking_id, slot, test_bookings, test_pred)
                            
                if best_move is None:
                    if debug: print(f"\n[STOP REASON]: best_move is None (no moves left to evaluate).")
                    break 
                    
                b_id, slot, next_bookings, next_pred = best_move
                curr_score = self._score_prediction(current_prediction)
                
                if best_score >= curr_score:
                    if debug: 
                        print(f"\n[STOP REASON]: No move improves the score. Current score: {curr_score}, Best valid move score: {best_score}")
                        print(f"                 The heuristic cannot further minimize max_wait, max_q, or total_q.")
                    break 
                    
                if debug:
                    print(f"\n[ITERATION {iteration}] Accepted move:")
                    print(f"  Booking: {b_id} -> {slot.start_time.strftime('%H:%M')}")
                    print(f"  Score improved from {curr_score} to {best_score}")
                    print(f"  Max Wait: {best_score[2]} | Max Q: {best_score[3]} | Total Wait: {best_score[4]} | Total Q: {best_score[5]}")
                    
                current_bookings_state = next_bookings
                current_prediction = next_pred
                slot.current_bookings += 1
                
                eligible = [b for b in eligible if b.booking_id != b_id]
                original_b = next(b for b in bookings if b.booking_id == b_id)
                accepted_changes.append(RecommendationChange(
                    booking_id=b_id,
                    original_start=original_b.scheduled_start_time,
                    proposed_start=slot.start_time,
                    priority_level=original_b.priority_level,
                    reschedule_count=original_b.reschedule_count + 1
                ))
                
            has_crit = any(tp.congestion_level == CongestionLevel.CRITICAL for tp in current_prediction.time_points)
            has_hi = any(tp.congestion_level == CongestionLevel.HIGH for tp in current_prediction.time_points)
            
            if len(accepted_changes) == 0:
                return self._build_recommendation("NO_FEASIBLE_INTERVENTION", centre_state, [], "No valid intervention found.", prediction)
            elif not has_crit and not has_hi:
                return self._build_recommendation("FULL_RECOVERY", centre_state, accepted_changes, "Resolved all critical and high congestion.", current_prediction)
            else:
                return self._build_recommendation("PARTIAL_RECOVERY", centre_state, accepted_changes, "Reduced congestion, but some backlog remains.", current_prediction)

    decider = DebugDecider(predictor, delta_t_minutes=15)
    
    state = get_base_state(active_counters=2) # 20/hr
    bookings = generate_bookings(booking_count, priority_indexes=priority_idx, rescheduled_indexes=resched_idx)
    constraints = ConstraintSet('08:00', '18:00', capacity, 60, 100)
    
    current_time = datetime(2026, 8, 30, 10, 0)
    
    pred = predictor.predict(state, bookings, current_time, horizon)
    
    if debug:
        print("\n[INITIAL PREDICTION]")
        for tp in pred.time_points[:8]:
            print(f"  {tp.timestamp.strftime('%H:%M')} | Arr: {tp.expected_arrivals} | Comp: {tp.expected_completions} | Q: {tp.projected_queue} | Wait: {tp.estimated_wait_minutes:.1f}m | Congestion: {tp.congestion_level.name}")
    
    rec = decider.generate_recommendation(state, pred, bookings, constraints)
    
    print(f"\n[FINAL STATUS] {rec.status}")
    print(f"[REASON] {rec.reason}")
    print(f"[CHANGES] {len(rec.changes)}")
    
    if debug and rec:
        print("\n[ACCEPTED CHANGES]")
        for c in rec.changes:
            print(f"  {c.booking_id}: {c.original_start.strftime('%H:%M')} -> {c.proposed_start.strftime('%H:%M')}")
            
    return rec

if __name__ == "__main__":
    run_scenario("40-BOOKING MATH AUDIT", 40, debug=True)
    run_scenario("30-BOOKING FULL RECOVERY", 30, debug=True)
    run_scenario("FAIRNESS AUDIT (Priority at b_10, Resched at b_11)", 40, priority_idx=[10], resched_idx=[11])
    run_scenario("PARTIAL_RECOVERY", 40, capacity=2)
    run_scenario("NO_FEASIBLE_INTERVENTION", 40, capacity=0)

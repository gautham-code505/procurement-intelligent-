import copy
from typing import List, Optional, Tuple
from datetime import datetime, timedelta

from core.domain.models import (
    CentreState, Booking, PredictionResult, Recommendation, 
    RecommendationChange, ConstraintSet, BookingState, CongestionLevel
)
from core.interfaces.engines import IDecisionEngine, IPredictor

class AlternativeSlot:
    def __init__(self, start_time: datetime, end_time: datetime, capacity: int, current_bookings: int):
        self.start_time = start_time
        self.end_time = end_time
        self.capacity = capacity
        self.current_bookings = current_bookings
        
    @property
    def remaining_capacity(self) -> int:
        return max(0, self.capacity - self.current_bookings)

class HeuristicDecisionEngine(IDecisionEngine):
    def __init__(self, predictor: IPredictor, delta_t_minutes: int = 15):
        self.predictor = predictor
        self.delta_t_minutes = delta_t_minutes
        
    def generate_recommendation(
        self,
        centre_state: CentreState,
        prediction: PredictionResult,
        bookings: List[Booking],
        constraints: ConstraintSet
    ) -> Optional[Recommendation]:
        
        has_critical = any(tp.congestion_level == CongestionLevel.CRITICAL for tp in prediction.time_points)
        has_high = any(tp.congestion_level == CongestionLevel.HIGH for tp in prediction.time_points)
        
        if not (has_critical or has_high):
            return None
            
        last_issue_time = None
        for tp in reversed(prediction.time_points):
            if tp.congestion_level in [CongestionLevel.CRITICAL, CongestionLevel.HIGH]:
                last_issue_time = tp.timestamp
                break
                
        eligible_bookings = [
            b for b in bookings 
            if b.booking_state in [BookingState.SCHEDULED, BookingState.RESCHEDULED]
            and b.scheduled_start_time <= last_issue_time
            and b.reschedule_count == 0 
            and b.priority_level == 0 
        ]
        
        eligible_bookings.sort(key=lambda b: b.booking_id)
        
        alt_slots = self._generate_alternative_slots(bookings, prediction.horizon_start, prediction.horizon_end, constraints)
        
        if not alt_slots:
            return self._build_recommendation("NO_FEASIBLE_INTERVENTION", centre_state, [], "No valid alternative slots available.", prediction)

        current_bookings_state = copy.deepcopy(bookings)
        accepted_changes = []
        
        current_prediction = prediction
        horizon_hours = (prediction.horizon_end - prediction.horizon_start).total_seconds() / 3600.0
        
        while True:
            has_crit = any(tp.congestion_level == CongestionLevel.CRITICAL for tp in current_prediction.time_points)
            has_hi = any(tp.congestion_level == CongestionLevel.HIGH for tp in current_prediction.time_points)
            
            if not has_crit and not has_hi:
                break 
                
            best_move = None
            best_score = None
            
            for booking in eligible_bookings:
                temp_b = next((b for b in current_bookings_state if b.booking_id == booking.booking_id), None)
                if not temp_b or temp_b.booking_state != BookingState.SCHEDULED: continue
                
                valid_slots = [
                    s for s in alt_slots 
                    if s.remaining_capacity > 0 
                    and s.start_time >= prediction.horizon_start + timedelta(minutes=constraints.minimum_notice_minutes)
                ]
                if not valid_slots:
                    continue
                    
                valid_slots.sort(key=lambda s: s.current_bookings)
                
                # Check top few valid slots
                for slot in valid_slots[:3]:
                    test_bookings = copy.deepcopy(current_bookings_state)
                    t_b = next(b for b in test_bookings if b.booking_id == booking.booking_id)
                    t_b.scheduled_start_time = slot.start_time
                    t_b.scheduled_end_time = slot.end_time
                    
                    test_pred = self.predictor.predict(centre_state, test_bookings, prediction.horizon_start, horizon_hours)
                    
                    score = self._score_prediction(test_pred)
                    
                    if best_score is None or score < best_score:
                        best_score = score
                        best_move = (booking.booking_id, slot, test_bookings, test_pred)
                        
            if best_move is None:
                break 
                
            b_id, slot, next_bookings, next_pred = best_move
            
            curr_score = self._score_prediction(current_prediction)
            
            # The issue is likely here: we require `best_score < curr_score`.
            # Moving 1 booking might not immediately drop CRITICAL to non-CRITICAL, so the tuple score
            # (has_crit, has_hi, max_wait) might remain identical, e.g. (1, 0, 0.95 -> 0.90) wait time might change, but if wait > 1h, it remains CRITICAL.
            # Wait, our score is (has_crit, has_hi, max_wait). 
            # If max_wait reduces, best_score < curr_score WILL trigger!
            # Let's add debugging print statements
            # print(f"Move {b_id} to {slot.start_time}: curr={curr_score}, new={best_score}")
            if best_score >= curr_score:
                break 
                
            current_bookings_state = next_bookings
            current_prediction = next_pred
            slot.current_bookings += 1
            
            eligible_bookings = [b for b in eligible_bookings if b.booking_id != b_id]
            
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
            
    def _score_prediction(self, pred: PredictionResult) -> Tuple:
        has_crit = 1 if any(tp.congestion_level == CongestionLevel.CRITICAL for tp in pred.time_points) else 0
        has_hi = 1 if any(tp.congestion_level == CongestionLevel.HIGH for tp in pred.time_points) else 0
        max_wait = max((tp.estimated_wait_minutes for tp in pred.time_points), default=0)
        max_q = max((tp.projected_queue for tp in pred.time_points), default=0)
        total_q = sum(tp.projected_queue for tp in pred.time_points)
        total_wait = sum(tp.estimated_wait_minutes for tp in pred.time_points)
        return (has_crit, has_hi, max_wait, max_q, total_wait, total_q)
        
    def _generate_alternative_slots(self, bookings: List[Booking], start_time: datetime, end_time: datetime, constraints: ConstraintSet) -> List[AlternativeSlot]:
        slots = []
        try:
            op_start = datetime.strptime(constraints.operating_hours_start, "%H:%M").time()
            op_end = datetime.strptime(constraints.operating_hours_end, "%H:%M").time()
        except Exception:
            op_start = datetime.strptime("08:00", "%H:%M").time()
            op_end = datetime.strptime("18:00", "%H:%M").time()
            
        current = start_time
        
        while current < end_time:
            if op_start <= current.time() and current.time() < op_end:
                slot_end = current + timedelta(minutes=self.delta_t_minutes)
                count = sum(1 for b in bookings if b.scheduled_start_time == current and b.booking_state in [BookingState.SCHEDULED, BookingState.RESCHEDULED])
                
                slots.append(AlternativeSlot(
                    start_time=current,
                    end_time=slot_end,
                    capacity=constraints.slot_capacity,
                    current_bookings=count
                ))
            current += timedelta(minutes=self.delta_t_minutes)
            
        return slots
        
    def _build_recommendation(self, status: str, state: CentreState, changes: List[RecommendationChange], reason: str, final_pred: PredictionResult) -> Recommendation:
        max_wait = max((tp.estimated_wait_minutes for tp in final_pred.time_points), default=0)
        import uuid
        return Recommendation(
            recommendation_id=f"REC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:8]}",
            centre_id=state.centre_id,
            trigger_event_id="SYSTEM",
            created_at=datetime.now(),
            status=status,
            reason=reason,
            expected_impact=f"[{status}] Max wait reduced to {max_wait:.1f}m. Affected {len(changes)} bookings.",
            constraint_check="Operating hours and slot capacities verified.",
            fairness_check="0 priority farmers displaced. Tie-breaking deterministic.",
            changes=changes
        )

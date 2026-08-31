from datetime import datetime, timedelta
import math
from typing import List

from core.domain.models import (
    CentreState, Booking, PredictionResult, TimePoint, CongestionLevel, BookingState
)
from core.interfaces.engines import IPredictor

class BaselinePredictor(IPredictor):
    def __init__(self, delta_t_minutes: int = 15, physical_queue_capacity: int = 100):
        self.delta_t_minutes = delta_t_minutes
        self.delta_t_hours = delta_t_minutes / 60.0
        self.physical_queue_capacity = physical_queue_capacity

    def predict(
        self,
        centre_state: CentreState,
        bookings: List[Booking],
        current_time: datetime,
        horizon_hours: float
    ) -> PredictionResult:
        
        # Determine intervals
        num_intervals = int(math.ceil(horizon_hours / self.delta_t_hours))
        
        # We need a stable view of capacity. For the simulation, we assume current effective rate 
        # continues unless we model future known changes. We'll use current effective_processing_rate.
        effective_rate = centre_state.effective_processing_rate
        capacity_interval = effective_rate * self.delta_t_hours
        
        time_points = []
        q_current = centre_state.current_queue
        
        # Bin upcoming bookings into intervals
        # Consider only SCHEDULED or RESCHEDULED bookings for future arrivals
        valid_bookings = [b for b in bookings if b.booking_state in [BookingState.SCHEDULED, BookingState.RESCHEDULED]]

        for i in range(num_intervals):
            interval_start = current_time + timedelta(minutes=i * self.delta_t_minutes)
            interval_end = current_time + timedelta(minutes=(i+1) * self.delta_t_minutes)
            
            # Count arrivals in this window (t-1, t]
            # Since interval_start is t-1, we count bookings scheduled to start in (interval_start, interval_end]
            expected_arrivals = sum(
                1 for b in valid_bookings
                if interval_start < b.scheduled_start_time <= interval_end
            )
            
            total_demand = q_current + expected_arrivals
            
            expected_completions = min(total_demand, capacity_interval)
            
            # If rate is float, completion might be float, but we keep it logical
            q_next = max(0.0, q_current + expected_arrivals - expected_completions)
            
            # Calculate wait time (in hours)
            capacity_failure = False
            if effective_rate > 0:
                estimated_wait_hours = q_next / effective_rate
                demand_capacity_ratio = total_demand / capacity_interval if capacity_interval > 0 else float('inf')
                processing_utilization = expected_completions / capacity_interval if capacity_interval > 0 else 1.0
            else:
                if q_next == 0 and expected_arrivals == 0:
                    estimated_wait_hours = 0.0
                    demand_capacity_ratio = 0.0
                    processing_utilization = 0.0
                else:
                    estimated_wait_hours = float('inf')
                    demand_capacity_ratio = float('inf')
                    processing_utilization = 1.0
                    capacity_failure = True
                    
            # Determine congestion level
            congestion = CongestionLevel.LOW
            if capacity_failure or estimated_wait_hours >= 1.0 or q_next > self.physical_queue_capacity:
                congestion = CongestionLevel.CRITICAL
            elif estimated_wait_hours >= 0.5 or demand_capacity_ratio > 1.2:
                congestion = CongestionLevel.HIGH
            elif estimated_wait_hours >= 0.25 or demand_capacity_ratio > 1.0:
                congestion = CongestionLevel.MEDIUM
                
            time_points.append(TimePoint(
                timestamp=interval_end,
                expected_arrivals=expected_arrivals,
                expected_completions=int(expected_completions), # type match
                projected_queue=int(math.ceil(q_next)),
                estimated_wait_minutes=estimated_wait_hours * 60,
                utilization=processing_utilization, # this maps to utilization in TimePoint model
                congestion_level=congestion
            ))
            
            # We can stash demand_capacity_ratio somewhere or just keep it local for level calculation
            
            q_current = q_next

        # Summarize
        max_wait = max((tp.estimated_wait_minutes for tp in time_points), default=0)
        has_critical = any(tp.congestion_level == CongestionLevel.CRITICAL for tp in time_points)
        has_high = any(tp.congestion_level == CongestionLevel.HIGH for tp in time_points)
        
        status = "CRITICAL" if has_critical else ("HIGH" if has_high else "NORMAL")
        
        return PredictionResult(
            centre_id=centre_state.centre_id,
            generated_at=current_time,
            horizon_start=current_time,
            horizon_end=current_time + timedelta(hours=horizon_hours),
            time_points=time_points,
            summary=f"Projected congestion is {status}.",
            explanation=f"Maximum wait time in horizon is {max_wait:.1f} minutes."
        )

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime

class DomainException(Exception):
    pass

class BookingState(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULED = "RESCHEDULED"
    ARRIVED = "ARRIVED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"

class ProcurementStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    QUALITY_CHECK = "QUALITY_CHECK"
    WEIGHING = "WEIGHING"
    COMPLETED = "COMPLETED"

class PaymentStatus(str, Enum):
    NOT_INITIATED = "NOT_INITIATED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ACTION_REQUIRED = "ACTION_REQUIRED"

class OperatingStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EMERGENCY = "EMERGENCY"

class CongestionLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class CounterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNAVAILABLE = "UNAVAILABLE"

@dataclass
class Counter:
    counter_id: str
    centre_id: str
    status: CounterStatus
    processing_rate: float

@dataclass
class CentreState:
    centre_id: str
    timestamp: datetime
    operating_status: OperatingStatus
    counters: List[Counter] = field(default_factory=list)
    current_queue: int = 0
    expected_arrivals: int = 0
    projected_queue: int = 0
    projected_wait_minutes: float = 0.0
    congestion_level: CongestionLevel = CongestionLevel.LOW

    @property
    def total_counters(self) -> int:
        return len(self.counters)
    
    @property
    def active_counters(self) -> int:
        return sum(1 for c in self.counters if c.status == CounterStatus.ACTIVE)

    @property
    def effective_processing_rate(self) -> float:
        return sum(c.processing_rate for c in self.counters if c.status == CounterStatus.ACTIVE)
        
    @property
    def base_processing_rate(self) -> float:
        return sum(c.processing_rate for c in self.counters)

    def increment_queue(self):
        self.current_queue += 1

    def decrement_queue(self):
        if self.current_queue <= 0:
            raise DomainException("Queue cannot be negative")
        self.current_queue -= 1

    def get_counter(self, counter_id: str) -> Counter:
        for c in self.counters:
            if c.counter_id == counter_id:
                return c
        raise DomainException(f"Counter {counter_id} not found")

    def set_counter_status(self, counter_id: str, status: CounterStatus):
        c = self.get_counter(counter_id)
        if c.status == status:
            raise DomainException(f"Counter {counter_id} is already {status}")
        c.status = status

    def update_processing_rate(self, counter_id: str, new_rate: float):
        if new_rate < 0:
            raise DomainException("Processing rate cannot be negative")
        c = self.get_counter(counter_id)
        c.processing_rate = new_rate

@dataclass
class CentreStateSnapshot:
    snapshot_id: str
    centre_id: str
    timestamp: datetime
    state: CentreState

@dataclass
class OperationalEvent:
    event_id: str
    timestamp: datetime
    source: str
    event_type: str
    metadata: Dict[str, Any]

@dataclass
class TimePoint:
    timestamp: datetime
    expected_arrivals: int
    expected_completions: int
    projected_queue: int
    estimated_wait_minutes: float
    utilization: float
    congestion_level: CongestionLevel

@dataclass
class PredictionResult:
    centre_id: str
    generated_at: datetime
    horizon_start: datetime
    horizon_end: datetime
    time_points: List[TimePoint]
    summary: str
    explanation: str

@dataclass
class ConstraintSet:
    operating_hours_start: str 
    operating_hours_end: str   
    slot_capacity: int
    booking_validity_window_minutes: int
    available_capacity: int
    minimum_notice_minutes: int = 15

@dataclass
class RecommendationChange:
    booking_id: str
    original_start: datetime
    proposed_start: datetime
    priority_level: int
    reschedule_count: int

@dataclass
class Recommendation:
    recommendation_id: str
    centre_id: str
    trigger_event_id: str
    created_at: datetime
    status: str
    reason: str
    expected_impact: str
    constraint_check: str
    fairness_check: str
    changes: List[RecommendationChange]

@dataclass
class Booking:
    booking_id: str
    farmer_id: str
    centre_id: str
    scheduled_start_time: datetime
    scheduled_end_time: datetime
    booking_state: BookingState
    procurement_status: ProcurementStatus
    payment_status: PaymentStatus
    priority_level: int
    reschedule_count: int

    def _transition_to(self, new_state: BookingState, allowed_from: List[BookingState]):
        if self.booking_state not in allowed_from:
            raise DomainException(f"Invalid transition from {self.booking_state} to {new_state}")
        self.booking_state = new_state

    def mark_arrived(self):
        self._transition_to(BookingState.ARRIVED, [BookingState.SCHEDULED, BookingState.RESCHEDULED])

    def mark_rescheduled(self):
        self._transition_to(BookingState.RESCHEDULED, [BookingState.SCHEDULED, BookingState.RESCHEDULED])
        self.reschedule_count += 1

    def mark_cancelled(self):
        self._transition_to(BookingState.CANCELLED, [BookingState.SCHEDULED, BookingState.RESCHEDULED, BookingState.ARRIVED])

    def mark_no_show(self):
        self._transition_to(BookingState.NO_SHOW, [BookingState.SCHEDULED, BookingState.RESCHEDULED])

    def mark_processing(self):
        self._transition_to(BookingState.PROCESSING, [BookingState.ARRIVED])

    def mark_completed(self):
        self._transition_to(BookingState.COMPLETED, [BookingState.PROCESSING])

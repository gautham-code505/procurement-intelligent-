from typing import List, Optional, Dict
from datetime import datetime
from core.domain.models import (
    CentreState, ConstraintSet, Booking, 
    OperationalEvent, Recommendation, CentreStateSnapshot
)
from core.interfaces.repositories import (
    CentreRepository, BookingRepository, 
    EventRepository, RecommendationRepository
)

class InMemoryCentreRepository(CentreRepository):
    def __init__(self):
        self._states: Dict[str, CentreState] = {}
        self._constraints: Dict[str, ConstraintSet] = {}
        
    def get_state(self, centre_id: str) -> Optional[CentreState]:
        return self._states.get(centre_id)
        
    def update_state(self, state: CentreState) -> None:
        self._states[state.centre_id] = state
        
    def get_constraints(self, centre_id: str) -> Optional[ConstraintSet]:
        return self._constraints.get(centre_id)

    def update_constraints(self, centre_id: str, constraints: ConstraintSet) -> None:
        self._constraints[centre_id] = constraints

class InMemoryBookingRepository(BookingRepository):
    def __init__(self):
        self._bookings: Dict[str, Booking] = {}
        
    def get_booking(self, booking_id: str) -> Optional[Booking]:
        return self._bookings.get(booking_id)
        
    def update_booking(self, booking: Booking) -> None:
        self._bookings[booking.booking_id] = booking
        
    def get_bookings_for_centre(self, centre_id: str, start_time: datetime, end_time: datetime) -> List[Booking]:
        return [
            b for b in self._bookings.values()
            if b.centre_id == centre_id and 
            b.scheduled_start_time >= start_time and 
            b.scheduled_start_time <= end_time
        ]

class InMemoryEventRepository(EventRepository):
    def __init__(self):
        self._events: List[OperationalEvent] = []
        self._snapshots: List[CentreStateSnapshot] = []
        
    def add_event(self, event: OperationalEvent) -> None:
        self._events.append(event)
        
    def add_snapshot(self, snapshot: CentreStateSnapshot) -> None:
        self._snapshots.append(snapshot)

class InMemoryRecommendationRepository(RecommendationRepository):
    def __init__(self):
        self._recommendations: Dict[str, Recommendation] = {}
        
    def add_recommendation(self, recommendation: Recommendation) -> None:
        self._recommendations[recommendation.recommendation_id] = recommendation
        
    def get_recommendation(self, recommendation_id: str) -> Optional[Recommendation]:
        return self._recommendations.get(recommendation_id)

    def update_recommendation_status(self, recommendation_id: str, new_status: str) -> None:
        rec = self._recommendations.get(recommendation_id)
        if not rec:
            raise ValueError(f"Recommendation {recommendation_id} not found")
        rec.status = new_status
        
    def get_pending_recommendations(self, centre_id: str) -> List[Recommendation]:
        return [
            r for r in self._recommendations.values()
            if r.centre_id == centre_id and r.status == "PENDING"
        ]

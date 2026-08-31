from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime
from core.domain.models import (
    CentreState, ConstraintSet, Booking, 
    OperationalEvent, Recommendation, CentreStateSnapshot
)

class CentreRepository(ABC):
    @abstractmethod
    def get_state(self, centre_id: str) -> Optional[CentreState]:
        pass
    
    @abstractmethod
    def update_state(self, state: CentreState) -> None:
        pass
        
    @abstractmethod
    def get_constraints(self, centre_id: str) -> Optional[ConstraintSet]:
        pass
        
    @abstractmethod
    def update_constraints(self, centre_id: str, constraints: ConstraintSet) -> None:
        pass

class BookingRepository(ABC):
    @abstractmethod
    def get_booking(self, booking_id: str) -> Optional[Booking]:
        pass
        
    @abstractmethod
    def update_booking(self, booking: Booking) -> None:
        pass
        
    @abstractmethod
    def get_bookings_for_centre(self, centre_id: str, start_time: datetime, end_time: datetime) -> List[Booking]:
        pass

class EventRepository(ABC):
    @abstractmethod
    def add_event(self, event: OperationalEvent) -> None:
        pass
        
    @abstractmethod
    def add_snapshot(self, snapshot: CentreStateSnapshot) -> None:
        pass

class RecommendationRepository(ABC):
    @abstractmethod
    def add_recommendation(self, recommendation: Recommendation) -> None:
        pass
        
    @abstractmethod
    def get_recommendation(self, recommendation_id: str) -> Optional[Recommendation]:
        pass

    @abstractmethod
    def update_recommendation_status(self, recommendation_id: str, new_status: str) -> None:
        """Atomically update just the status field of an existing recommendation row."""
        pass
        
    @abstractmethod
    def get_pending_recommendations(self, centre_id: str) -> List[Recommendation]:
        pass

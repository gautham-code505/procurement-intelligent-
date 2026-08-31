from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime
from core.domain.models import (
    CentreState, Booking, PredictionResult, Recommendation, ConstraintSet
)

class IPredictor(ABC):
    @abstractmethod
    def predict(
        self,
        centre_state: CentreState,
        bookings: List[Booking],
        current_time: datetime,
        horizon_hours: float
    ) -> PredictionResult:
        pass

class IDecisionEngine(ABC):
    @abstractmethod
    def generate_recommendation(
        self,
        centre_state: CentreState,
        prediction: PredictionResult,
        bookings: List[Booking],
        constraints: ConstraintSet
    ) -> Optional[Recommendation]:
        pass

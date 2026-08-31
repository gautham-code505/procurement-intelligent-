from pydantic import BaseModel
from datetime import datetime
from typing import List
from core.domain.models import CongestionLevel

class TimePointResponse(BaseModel):
    timestamp: datetime
    expected_arrivals: int
    expected_completions: int
    projected_queue: int
    estimated_wait_minutes: float
    utilization: float
    congestion_level: CongestionLevel

class PredictionResultResponse(BaseModel):
    centre_id: str
    generated_at: datetime
    horizon_start: datetime
    horizon_end: datetime
    time_points: List[TimePointResponse]
    summary: str
    explanation: str

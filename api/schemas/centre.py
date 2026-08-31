from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional
from core.domain.models import OperatingStatus, CongestionLevel, CounterStatus

class CounterResponse(BaseModel):
    counter_id: str
    status: CounterStatus
    processing_rate: float

class CentreStateResponse(BaseModel):
    centre_id: str
    timestamp: datetime
    operating_status: OperatingStatus
    counters: List[CounterResponse]
    current_queue: int
    expected_arrivals: int
    projected_queue: int
    projected_wait_minutes: float
    congestion_level: CongestionLevel
    effective_processing_rate: float

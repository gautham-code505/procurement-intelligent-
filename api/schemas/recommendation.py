from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

class RecommendationChangeResponse(BaseModel):
    booking_id: str
    original_start: datetime
    proposed_start: datetime
    priority_level: int
    reschedule_count: int

class RecommendationResponse(BaseModel):
    recommendation_id: str
    centre_id: str
    trigger_event_id: str
    created_at: datetime
    status: str
    reason: str
    expected_impact: str
    constraint_check: str
    fairness_check: str
    changes: List[RecommendationChangeResponse]

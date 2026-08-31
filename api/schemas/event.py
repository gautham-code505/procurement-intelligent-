from pydantic import BaseModel
from datetime import datetime
from typing import Dict, Any, Optional

class EventCreateRequest(BaseModel):
    event_id: str
    timestamp: datetime
    source: str
    event_type: str
    metadata: Dict[str, Any]

class EventOutcomeResponse(BaseModel):
    status: str
    state_updated: bool
    prediction_triggered: bool
    congestion_level: Optional[str] = None
    recommendation_id: Optional[str] = None
    recommendation_status: Optional[str] = None

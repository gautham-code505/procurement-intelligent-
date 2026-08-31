from pydantic import BaseModel
from datetime import datetime
from typing import List
from core.domain.models import BookingState, ProcurementStatus, PaymentStatus

class BookingCreateRequest(BaseModel):
    booking_id: str
    farmer_id: str
    centre_id: str
    scheduled_start_time: datetime
    priority_level: int = 0

class BookingResponse(BaseModel):
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

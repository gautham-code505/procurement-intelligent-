from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import timedelta

from api.dependencies import get_db, get_coordination_service
from api.schemas.booking import BookingCreateRequest, BookingResponse
from core.services.coordination import AdaptiveCoordinationService
from core.domain.models import Booking, BookingState, ProcurementStatus, PaymentStatus

router = APIRouter(prefix="/api/bookings", tags=["Bookings"])

@router.post("", response_model=BookingResponse)
def create_booking(request: BookingCreateRequest, db: Session = Depends(get_db), service: AdaptiveCoordinationService = Depends(get_coordination_service)):
    booking = Booking(
        booking_id=request.booking_id,
        farmer_id=request.farmer_id,
        centre_id=request.centre_id,
        scheduled_start_time=request.scheduled_start_time,
        scheduled_end_time=request.scheduled_start_time + timedelta(minutes=15),
        booking_state=BookingState.SCHEDULED,
        procurement_status=ProcurementStatus.NOT_STARTED,
        payment_status=PaymentStatus.NOT_INITIATED,
        priority_level=request.priority_level,
        reschedule_count=0
    )
    
    try:
        service.booking_repo.update_booking(booking)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
        
    return BookingResponse(
        booking_id=booking.booking_id,
        farmer_id=booking.farmer_id,
        centre_id=booking.centre_id,
        scheduled_start_time=booking.scheduled_start_time,
        scheduled_end_time=booking.scheduled_end_time,
        booking_state=booking.booking_state,
        procurement_status=booking.procurement_status,
        payment_status=booking.payment_status,
        priority_level=booking.priority_level,
        reschedule_count=booking.reschedule_count
    )

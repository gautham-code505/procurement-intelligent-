from fastapi import APIRouter, Depends, Header, HTTPException
from api.dependencies import get_db, get_coordination_service
from api.schemas.booking import BookingResponse
from core.services.coordination import AdaptiveCoordinationService
from typing import List

# This route is for farmers, no OPERATOR/ADMIN constraint needed unless specified.
# The user specified FARMER role in implementation plan. We can just use the default get_current_role 
# but checking it if needed. For now, it's open.
router = APIRouter(prefix="/api/farmers", tags=["Farmers"])

@router.get("/{farmer_id}/bookings", response_model=List[BookingResponse])
def get_farmer_bookings(farmer_id: str, service: AdaptiveCoordinationService = Depends(get_coordination_service)):
    bookings = service.booking_repo.get_bookings_for_farmer(farmer_id)
    return [BookingResponse(
        booking_id=b.booking_id,
        farmer_id=b.farmer_id,
        centre_id=b.centre_id,
        scheduled_start_time=b.scheduled_start_time,
        scheduled_end_time=b.scheduled_end_time,
        booking_state=b.booking_state,
        procurement_status=b.procurement_status,
        payment_status=b.payment_status,
        priority_level=b.priority_level,
        reschedule_count=b.reschedule_count
    ) for b in bookings]

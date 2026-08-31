from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from api.dependencies import get_db, get_coordination_service, require_operator_or_admin
from api.schemas.event import EventCreateRequest, EventOutcomeResponse
from core.services.coordination import AdaptiveCoordinationService
from core.domain.models import OperationalEvent, DomainException

router = APIRouter(prefix="/api/events", tags=["Events"], dependencies=[Depends(require_operator_or_admin)])

@router.post("", response_model=EventOutcomeResponse)
def create_event(
    request: EventCreateRequest, 
    db: Session = Depends(get_db), 
    service: AdaptiveCoordinationService = Depends(get_coordination_service)
):
    event = OperationalEvent(
        event_id=request.event_id,
        timestamp=request.timestamp,
        source=request.source,
        event_type=request.event_type,
        metadata=request.metadata
    )
    
    try:
        outcome = service.process_event(event)
        db.commit()
        return EventOutcomeResponse(**outcome)
    except DomainException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        db.rollback()
        # Duplicate event_id — return 409 Conflict with deterministic response
        if "Idempotency check failed" in str(e):
            raise HTTPException(
                status_code=409,
                detail={"code": "DUPLICATE_EVENT", "message": str(e)}
            )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


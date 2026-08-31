from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime

from api.dependencies import get_db, get_coordination_service, require_admin
from core.services.coordination import AdaptiveCoordinationService
from core.domain.models import DomainException

router = APIRouter(prefix="/api/recommendations", tags=["Recommendations"], dependencies=[Depends(require_admin)])

@router.post("/{recommendation_id}/approve")
def approve_recommendation(
    recommendation_id: str,
    simulated_time: datetime = Query(...),
    db: Session = Depends(get_db),
    service: AdaptiveCoordinationService = Depends(get_coordination_service)
):
    try:
        service.approve_recommendation(recommendation_id, simulated_time)
        db.commit()
        return {"status": "SUCCESS", "message": f"Recommendation {recommendation_id} approved and applied"}
    except DomainException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{recommendation_id}/reject")
def reject_recommendation(
    recommendation_id: str,
    db: Session = Depends(get_db),
    service: AdaptiveCoordinationService = Depends(get_coordination_service)
):
    try:
        service.reject_recommendation(recommendation_id)
        db.commit()
        return {"status": "SUCCESS", "message": f"Recommendation {recommendation_id} rejected"}
    except DomainException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

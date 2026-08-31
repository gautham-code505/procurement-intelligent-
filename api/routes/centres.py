from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from api.dependencies import get_db, get_coordination_service, require_operator_or_admin
from api.schemas.centre import CentreStateResponse, CounterResponse
from api.schemas.prediction import PredictionResultResponse, TimePointResponse
from api.schemas.recommendation import RecommendationResponse, RecommendationChangeResponse
from core.services.coordination import AdaptiveCoordinationService
from core.domain.models import DomainException

router = APIRouter(prefix="/api/centres", tags=["Centres"], dependencies=[Depends(require_operator_or_admin)])

@router.get("/{centre_id}/state", response_model=CentreStateResponse)
def get_centre_state(centre_id: str, service: AdaptiveCoordinationService = Depends(get_coordination_service)):
    state = service.centre_repo.get_state(centre_id)
    if not state:
        raise HTTPException(status_code=404, detail="Centre not found")
        
    return CentreStateResponse(
        centre_id=state.centre_id,
        timestamp=state.timestamp,
        operating_status=state.operating_status,
        counters=[CounterResponse(
            counter_id=c.counter_id,
            status=c.status,
            processing_rate=c.processing_rate
        ) for c in state.counters],
        current_queue=state.current_queue,
        expected_arrivals=state.expected_arrivals,
        projected_queue=state.projected_queue,
        projected_wait_minutes=state.projected_wait_minutes,
        congestion_level=state.congestion_level,
        effective_processing_rate=state.effective_processing_rate
    )

@router.get("/{centre_id}/predictions", response_model=PredictionResultResponse)
def get_centre_prediction(
    centre_id: str, 
    simulated_time: datetime = Query(default=None),
    service: AdaptiveCoordinationService = Depends(get_coordination_service)
):
    state = service.centre_repo.get_state(centre_id)
    if not state:
        raise HTTPException(status_code=404, detail="Centre not found")
        
    current_time = simulated_time if simulated_time else datetime.now()
    # Fetch forward bookings up to 8 hours
    bookings = service.booking_repo.get_bookings_for_centre(centre_id, current_time, current_time + timedelta(hours=8))
    
    # Calculate prediction dynamically
    pred = service.predictor.predict(state, bookings, current_time, 4.0)
    
    return PredictionResultResponse(
        centre_id=pred.centre_id,
        generated_at=pred.generated_at,
        horizon_start=pred.horizon_start,
        horizon_end=pred.horizon_end,
        summary=pred.summary,
        explanation=pred.explanation,
        time_points=[TimePointResponse(
            timestamp=tp.timestamp,
            expected_arrivals=tp.expected_arrivals,
            expected_completions=tp.expected_completions,
            projected_queue=tp.projected_queue,
            estimated_wait_minutes=tp.estimated_wait_minutes,
            utilization=tp.utilization,
            congestion_level=tp.congestion_level
        ) for tp in pred.time_points]
    )

@router.get("/{centre_id}/recommendations", response_model=list[RecommendationResponse])
def get_centre_recommendations(centre_id: str, service: AdaptiveCoordinationService = Depends(get_coordination_service)):
    recommendations = service.recommendation_repo.get_recommendations_for_centre(centre_id)
    return [RecommendationResponse(
        recommendation_id=r.recommendation_id,
        centre_id=r.centre_id,
        trigger_event_id=r.trigger_event_id,
        created_at=r.created_at,
        status=r.status,
        reason=r.reason,
        expected_impact=r.expected_impact,
        constraint_check=r.constraint_check,
        fairness_check=r.fairness_check,
        changes=[RecommendationChangeResponse(
            booking_id=c.booking_id,
            original_start=c.original_start,
            proposed_start=c.proposed_start,
            priority_level=c.priority_level,
            reschedule_count=c.reschedule_count
        ) for c in r.changes]
    ) for r in recommendations]

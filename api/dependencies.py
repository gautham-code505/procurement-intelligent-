from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session
from infrastructure.database.database import SessionLocal
from infrastructure.database.repositories import (
    SQLAlchemyCentreRepository,
    SQLAlchemyBookingRepository,
    SQLAlchemyEventRepository,
    SQLAlchemyRecommendationRepository
)
from core.intelligence.predictor import BaselinePredictor
from core.intelligence.decider import HeuristicDecisionEngine
from core.services.coordination import AdaptiveCoordinationService

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_role(x_user_role: str = Header(default="FARMER")):
    if x_user_role not in ["FARMER", "OPERATOR", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Invalid role")
    return x_user_role

def require_operator_or_admin(role: str = Depends(get_current_role)):
    if role not in ["OPERATOR", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return role

def require_admin(role: str = Depends(get_current_role)):
    if role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return role

def get_coordination_service(db: Session = Depends(get_db)):
    centre_repo = SQLAlchemyCentreRepository(db)
    booking_repo = SQLAlchemyBookingRepository(db)
    event_repo = SQLAlchemyEventRepository(db)
    rec_repo = SQLAlchemyRecommendationRepository(db)
    
    predictor = BaselinePredictor(delta_t_minutes=15)
    decision_engine = HeuristicDecisionEngine(predictor, delta_t_minutes=15)
    
    return AdaptiveCoordinationService(
        centre_repo=centre_repo,
        booking_repo=booking_repo,
        event_repo=event_repo,
        recommendation_repo=rec_repo,
        predictor=predictor,
        decision_engine=decision_engine
    )

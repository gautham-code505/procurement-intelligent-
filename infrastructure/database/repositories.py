from typing import List, Optional
from datetime import datetime
import json
from sqlalchemy.orm import Session

from core.domain.models import (
    CentreState, ConstraintSet, Booking, Counter, OperationalEvent, 
    Recommendation, CentreStateSnapshot, RecommendationChange,
    OperatingStatus, CongestionLevel, CounterStatus
)
from core.interfaces.repositories import (
    CentreRepository, BookingRepository, 
    EventRepository, RecommendationRepository
)
from infrastructure.database.models import (
    CentreModel, CounterModel, BookingModel, OperationalEventModel, 
    CentreStateSnapshotModel, RecommendationModel, RecommendationChangeModel,
    ConstraintSetModel
)

class SQLAlchemyCentreRepository(CentreRepository):
    def __init__(self, session: Session):
        self.session = session
        
    def get_state(self, centre_id: str) -> Optional[CentreState]:
        centre = self.session.query(CentreModel).filter(CentreModel.centre_id == centre_id).first()
        if not centre:
            return None
            
        # Get the latest snapshot to restore the pure state variables (like current_queue)
        # In a real app we'd have a 'current_state' table or compute it from events,
        # but for this prototype, we'll extract the volatile state from the latest snapshot if available.
        # Alternatively, we can add those fields to CentreModel.
        # Let's add them to the snapshot logic:
        latest_snapshot = self.session.query(CentreStateSnapshotModel)\
            .filter(CentreStateSnapshotModel.centre_id == centre_id)\
            .order_by(CentreStateSnapshotModel.timestamp.desc()).first()
            
        if latest_snapshot:
            payload = latest_snapshot.state_payload
            return CentreState(
                centre_id=payload["centre_id"],
                timestamp=datetime.fromisoformat(payload["timestamp"]),
                operating_status=OperatingStatus(payload["operating_status"]),
                counters=[
                    Counter(
                        counter_id=c["counter_id"],
                        centre_id=c["centre_id"],
                        status=CounterStatus(c["status"]),
                        processing_rate=c["processing_rate"]
                    ) for c in payload["counters"]
                ],
                current_queue=payload["current_queue"],
                expected_arrivals=payload["expected_arrivals"],
                projected_queue=payload["projected_queue"],
                projected_wait_minutes=payload["projected_wait_minutes"],
                congestion_level=CongestionLevel(payload["congestion_level"])
            )
        
        # If no snapshot, return empty state based on model
        return CentreState(
            centre_id=centre.centre_id,
            timestamp=datetime.now(),
            operating_status=OperatingStatus.OPEN, # Default
            counters=[
                Counter(
                    counter_id=c.counter_id, 
                    centre_id=c.centre_id, 
                    status=c.status, 
                    processing_rate=c.processing_rate
                ) for c in centre.counters
            ]
        )
        
    def update_state(self, state: CentreState) -> None:
        # Update the relational representation of counters if needed
        # We don't store volatile state directly in CentreModel, we store it in snapshots.
        centre = self.session.query(CentreModel).filter(CentreModel.centre_id == state.centre_id).first()
        if not centre:
            centre = CentreModel(centre_id=state.centre_id, name="Default Centre")
            self.session.add(centre)
            
        for c_domain in state.counters:
            c_model = self.session.query(CounterModel).filter(CounterModel.counter_id == c_domain.counter_id).first()
            if not c_model:
                c_model = CounterModel(
                    counter_id=c_domain.counter_id,
                    centre_id=c_domain.centre_id,
                    status=c_domain.status,
                    processing_rate=c_domain.processing_rate
                )
                self.session.add(c_model)
            else:
                c_model.status = c_domain.status
                c_model.processing_rate = c_domain.processing_rate

        self.session.flush()
        
    def get_constraints(self, centre_id: str) -> Optional[ConstraintSet]:
        model = self.session.query(ConstraintSetModel).filter(ConstraintSetModel.centre_id == centre_id).first()
        if not model:
            return None
        return ConstraintSet(
            operating_hours_start=model.operating_hours_start,
            operating_hours_end=model.operating_hours_end,
            slot_capacity=model.slot_capacity,
            booking_validity_window_minutes=model.booking_validity_window_minutes,
            available_capacity=model.available_capacity,
            minimum_notice_minutes=model.minimum_notice_minutes
        )

    def update_constraints(self, centre_id: str, constraints: ConstraintSet) -> None:
        model = self.session.query(ConstraintSetModel).filter(ConstraintSetModel.centre_id == centre_id).first()
        if not model:
            model = ConstraintSetModel(centre_id=centre_id)
            self.session.add(model)
        
        model.operating_hours_start = constraints.operating_hours_start
        model.operating_hours_end = constraints.operating_hours_end
        model.slot_capacity = constraints.slot_capacity
        model.booking_validity_window_minutes = constraints.booking_validity_window_minutes
        model.available_capacity = constraints.available_capacity
        model.minimum_notice_minutes = constraints.minimum_notice_minutes
        self.session.flush()

class SQLAlchemyBookingRepository(BookingRepository):
    def __init__(self, session: Session):
        self.session = session
        
    def _to_domain(self, model: BookingModel) -> Booking:
        return Booking(
            booking_id=model.booking_id,
            farmer_id=model.farmer_id,
            centre_id=model.centre_id,
            scheduled_start_time=model.scheduled_start_time,
            scheduled_end_time=model.scheduled_end_time,
            booking_state=model.booking_state,
            procurement_status=model.procurement_status,
            payment_status=model.payment_status,
            priority_level=model.priority_level,
            reschedule_count=model.reschedule_count
        )
        
    def get_booking(self, booking_id: str) -> Optional[Booking]:
        model = self.session.query(BookingModel).filter(BookingModel.booking_id == booking_id).first()
        if not model:
            return None
        return self._to_domain(model)
        
    def update_booking(self, booking: Booking) -> None:
        model = self.session.query(BookingModel).filter(BookingModel.booking_id == booking.booking_id).first()
        if not model:
            model = BookingModel(booking_id=booking.booking_id)
            self.session.add(model)
            
        model.farmer_id = booking.farmer_id
        model.centre_id = booking.centre_id
        model.scheduled_start_time = booking.scheduled_start_time
        model.scheduled_end_time = booking.scheduled_end_time
        model.booking_state = booking.booking_state
        model.procurement_status = booking.procurement_status
        model.payment_status = booking.payment_status
        model.priority_level = booking.priority_level
        model.reschedule_count = booking.reschedule_count
        self.session.flush()
        
    def get_bookings_for_centre(self, centre_id: str, start_time: datetime, end_time: datetime) -> List[Booking]:
        models = self.session.query(BookingModel).filter(
            BookingModel.centre_id == centre_id,
            BookingModel.scheduled_start_time >= start_time,
            BookingModel.scheduled_start_time <= end_time
        ).all()
        return [self._to_domain(m) for m in models]

    def get_bookings_for_farmer(self, farmer_id: str) -> List[Booking]:
        models = self.session.query(BookingModel).filter(BookingModel.farmer_id == farmer_id).all()
        return [self._to_domain(m) for m in models]

class SQLAlchemyEventRepository(EventRepository):
    def __init__(self, session: Session):
        self.session = session
        
    def add_event(self, event: OperationalEvent) -> None:
        # Check for duplicate BEFORE attempting insert to avoid tainting the session
        existing = self.session.query(OperationalEventModel).filter(
            OperationalEventModel.event_id == event.event_id
        ).first()
        if existing:
            raise ValueError(f"Event with id {event.event_id} already exists (Idempotency check failed)")
        
        model = OperationalEventModel(
            event_id=event.event_id,
            timestamp=event.timestamp,
            source=event.source,
            event_type=event.event_type,
            metadata_payload=event.metadata
        )
        self.session.add(model)
        self.session.flush()
            
    def add_snapshot(self, snapshot: CentreStateSnapshot) -> None:
        # Convert state to dict for JSON storage
        state_dict = {
            "centre_id": snapshot.state.centre_id,
            "timestamp": snapshot.state.timestamp.isoformat(),
            "operating_status": snapshot.state.operating_status.value,
            "counters": [{"counter_id": c.counter_id, "centre_id": c.centre_id, "status": c.status.value, "processing_rate": c.processing_rate} for c in snapshot.state.counters],
            "current_queue": snapshot.state.current_queue,
            "expected_arrivals": snapshot.state.expected_arrivals,
            "projected_queue": snapshot.state.projected_queue,
            "projected_wait_minutes": snapshot.state.projected_wait_minutes,
            "congestion_level": snapshot.state.congestion_level.value
        }
        model = CentreStateSnapshotModel(
            snapshot_id=snapshot.snapshot_id,
            centre_id=snapshot.centre_id,
            timestamp=snapshot.timestamp,
            state_payload=state_dict
        )
        self.session.add(model)
        self.session.flush()
        
    def get_snapshots_chronological(self, centre_id: str) -> List[CentreStateSnapshot]:
        models = self.session.query(CentreStateSnapshotModel).filter(
            CentreStateSnapshotModel.centre_id == centre_id
        ).order_by(CentreStateSnapshotModel.timestamp.asc()).all()
        # Stub implementation returning domain objects
        return [] # Can be implemented fully if needed

class SQLAlchemyRecommendationRepository(RecommendationRepository):
    def __init__(self, session: Session):
        self.session = session
        
    def _to_domain(self, model: RecommendationModel) -> Recommendation:
        changes = [RecommendationChange(
            booking_id=c.booking_id,
            original_start=c.original_start,
            proposed_start=c.proposed_start,
            priority_level=c.priority_level,
            reschedule_count=c.reschedule_count
        ) for c in model.changes]
        
        return Recommendation(
            recommendation_id=model.recommendation_id,
            centre_id=model.centre_id,
            trigger_event_id=model.trigger_event_id,
            created_at=model.created_at,
            status=model.status,
            reason=model.reason,
            expected_impact=model.expected_impact,
            constraint_check=model.constraint_check,
            fairness_check=model.fairness_check,
            changes=changes
        )

    def add_recommendation(self, recommendation: Recommendation) -> None:
        model = RecommendationModel(
            recommendation_id=recommendation.recommendation_id,
            centre_id=recommendation.centre_id,
            trigger_event_id=recommendation.trigger_event_id,
            created_at=recommendation.created_at,
            status=recommendation.status,
            reason=recommendation.reason,
            expected_impact=recommendation.expected_impact,
            constraint_check=recommendation.constraint_check,
            fairness_check=recommendation.fairness_check
        )
        self.session.add(model)
        
        for c in recommendation.changes:
            c_model = RecommendationChangeModel(
                recommendation_id=recommendation.recommendation_id,
                booking_id=c.booking_id,
                original_start=c.original_start,
                proposed_start=c.proposed_start,
                priority_level=c.priority_level,
                reschedule_count=c.reschedule_count
            )
            self.session.add(c_model)
            
        self.session.flush()
        
    def get_pending_recommendations(self, centre_id: str) -> List[Recommendation]:
        # Return mapped domain models
        return []

    def get_recommendations_for_centre(self, centre_id: str) -> List[Recommendation]:
        models = self.session.query(RecommendationModel).filter(RecommendationModel.centre_id == centre_id).all()
        return [self._to_domain(m) for m in models]
        
    def get_recommendation(self, recommendation_id: str) -> Optional[Recommendation]:
        model = self.session.query(RecommendationModel).filter(RecommendationModel.recommendation_id == recommendation_id).first()
        if not model:
            return None
        return self._to_domain(model)

    def update_recommendation_status(self, recommendation_id: str, new_status: str) -> None:
        """Atomically update just the status column of an existing recommendation row."""
        model = self.session.query(RecommendationModel).filter(
            RecommendationModel.recommendation_id == recommendation_id
        ).first()
        if not model:
            raise ValueError(f"Recommendation {recommendation_id} not found")
        model.status = new_status
        self.session.flush()

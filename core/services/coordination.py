from datetime import datetime
import uuid
from typing import Optional

from core.domain.models import OperationalEvent, CentreStateSnapshot, CounterStatus, DomainException
from core.interfaces.repositories import (
    CentreRepository, BookingRepository, 
    EventRepository, RecommendationRepository
)
from core.interfaces.engines import IPredictor, IDecisionEngine

class AdaptiveCoordinationService:
    def __init__(
        self,
        centre_repo: CentreRepository,
        booking_repo: BookingRepository,
        event_repo: EventRepository,
        recommendation_repo: RecommendationRepository,
        predictor: IPredictor,
        decision_engine: IDecisionEngine
    ):
        self.centre_repo = centre_repo
        self.booking_repo = booking_repo
        self.event_repo = event_repo
        self.recommendation_repo = recommendation_repo
        self.predictor = predictor
        self.decision_engine = decision_engine

    def process_event(self, event: OperationalEvent) -> dict:
        """
        Process an operational event and orchestrate the adaptive loop.
        Returns a rich outcome dictionary.
        """
        centre_id = event.metadata.get("centre_id")
        if not centre_id:
            raise ValueError("Event metadata must contain centre_id")

        state = self.centre_repo.get_state(centre_id)
        if not state:
            raise ValueError(f"Centre {centre_id} not found")
            
        # Check idempotency FIRST, before any domain changes are applied.
        # This ensures a duplicate event_id always raises ValueError (→ 409)
        # rather than hitting a domain error (→ 400) from re-applied state.
        self.event_repo.add_event(event)

        # Apply event to domain state
        self._apply_event_to_state(event, state)


        # Persist updated state
        self.centre_repo.update_state(state)

        # Create snapshot
        snapshot = CentreStateSnapshot(
            snapshot_id=str(uuid.uuid4()),
            centre_id=centre_id,
            timestamp=event.timestamp,
            state=state
        )
        self.event_repo.add_snapshot(snapshot)

        outcome = {
            "status": "ACCEPTED",
            "state_updated": True,
            "prediction_triggered": False,
            "congestion_level": state.congestion_level.value,
            "recommendation_id": None,
            "recommendation_status": None
        }

        # Run predictor if appropriate
        if event.event_type in ["COUNTER_UNAVAILABLE", "COUNTER_RESTORED", "SURGE_DETECTED", "ARRIVAL_DELAY", "CENTRE_OPENED"]:
            # Get upcoming bookings for prediction window
            from datetime import timedelta
            upcoming_bookings = self.booking_repo.get_bookings_for_centre(
                centre_id, event.timestamp, event.timestamp + timedelta(hours=8)
            )
            prediction = self.predictor.predict(
                centre_state=state,
                bookings=upcoming_bookings,
                current_time=event.timestamp,
                horizon_hours=4.0
            )
            
            outcome["prediction_triggered"] = True
            
            # Run decision engine if appropriate
            constraints = self.centre_repo.get_constraints(centre_id)
            if constraints:
                recommendation = self.decision_engine.generate_recommendation(
                    centre_state=state,
                    prediction=prediction,
                    bookings=upcoming_bookings,
                    constraints=constraints
                )
                
                if recommendation:
                    self.recommendation_repo.add_recommendation(recommendation)
                    outcome["recommendation_id"] = recommendation.recommendation_id
                    outcome["recommendation_status"] = recommendation.status
                    
        return outcome

    def _apply_event_to_state(self, event: OperationalEvent, state):
        event_type = event.event_type
        metadata = event.metadata
        
        if event_type == "FARMER_ARRIVED":
            booking_id = metadata.get("booking_id")
            booking = self.booking_repo.get_booking(booking_id)
            if not booking:
                raise DomainException(f"Booking {booking_id} not found")
            booking.mark_arrived()
            self.booking_repo.update_booking(booking)
            state.increment_queue()
            
        elif event_type == "FARMER_COMPLETED":
            booking_id = metadata.get("booking_id")
            booking = self.booking_repo.get_booking(booking_id)
            if not booking:
                raise DomainException(f"Booking {booking_id} not found")
            booking.mark_completed()
            self.booking_repo.update_booking(booking)
            state.decrement_queue()
            
        elif event_type == "COUNTER_UNAVAILABLE":
            counter_id = metadata.get("counter_id")
            state.set_counter_status(counter_id, CounterStatus.UNAVAILABLE)
            
        elif event_type == "COUNTER_RESTORED":
            counter_id = metadata.get("counter_id")
            state.set_counter_status(counter_id, CounterStatus.ACTIVE)
            
        elif event_type == "PROCESSING_RATE_CHANGED":
            counter_id = metadata.get("counter_id")
            new_rate = metadata.get("new_rate")
            state.update_processing_rate(counter_id, new_rate)
            
        elif event_type == "FARMER_NO_SHOW":
            booking_id = metadata.get("booking_id")
            booking = self.booking_repo.get_booking(booking_id)
            if not booking:
                raise DomainException(f"Booking {booking_id} not found")
            booking.mark_no_show()
            self.booking_repo.update_booking(booking)

    def approve_recommendation(self, recommendation_id: str, simulated_time: datetime) -> None:
        rec = self.recommendation_repo.get_recommendation(recommendation_id)
        if not rec:
            raise DomainException(f"Recommendation {recommendation_id} not found")
            
        if rec.status in ["APPROVED", "REJECTED", "NO_FEASIBLE_INTERVENTION"]:
            raise DomainException(f"Cannot approve recommendation with status '{rec.status}'")

        # Stale-recommendation protection: verify each booking's current scheduled start
        # still matches the original_start recorded in the change. If any booking has been
        # moved or cancelled since the recommendation was generated, the recommendation is stale.
        for change in rec.changes:
            booking = self.booking_repo.get_booking(change.booking_id)
            if not booking:
                raise DomainException(
                    f"Stale recommendation: booking {change.booking_id} no longer exists"
                )
            # Allow a 1-second tolerance for floating-point/serialisation differences
            delta = abs((booking.scheduled_start_time - change.original_start).total_seconds())
            if delta > 1:
                raise DomainException(
                    f"Stale recommendation: booking {change.booking_id} has been moved "
                    f"(expected {change.original_start.isoformat()}, "
                    f"found {booking.scheduled_start_time.isoformat()})"
                )
            if booking.booking_state in ["CANCELLED", "NO_SHOW"]:
                raise DomainException(
                    f"Stale recommendation: booking {change.booking_id} is in state "
                    f"{booking.booking_state} and cannot be rescheduled"
                )

        # All stale checks passed — apply every change
        from datetime import timedelta
        for change in rec.changes:
            booking = self.booking_repo.get_booking(change.booking_id)
            booking.scheduled_start_time = change.proposed_start
            booking.scheduled_end_time = change.proposed_start + timedelta(minutes=15)
            booking.mark_rescheduled()
            self.booking_repo.update_booking(booking)
            
            # Emit notification event
            notification_event = OperationalEvent(
                event_id=str(uuid.uuid4()),
                timestamp=simulated_time,
                source="AdaptiveCoordinationService",
                event_type="FARMER_NOTIFIED_OF_RESCHEDULE",
                metadata={
                    "booking_id": booking.booking_id,
                    "new_start_time": change.proposed_start.isoformat()
                }
            )
            self.event_repo.add_event(notification_event)
            
        # Only update status AFTER all changes succeed
        self.recommendation_repo.update_recommendation_status(recommendation_id, "APPROVED")

    def reject_recommendation(self, recommendation_id: str) -> None:
        rec = self.recommendation_repo.get_recommendation(recommendation_id)
        if not rec:
            raise DomainException(f"Recommendation {recommendation_id} not found")
            
        if rec.status in ["APPROVED", "REJECTED", "NO_FEASIBLE_INTERVENTION"]:
            raise DomainException(f"Cannot reject recommendation with status '{rec.status}'")
            
        self.recommendation_repo.update_recommendation_status(recommendation_id, "REJECTED")


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime
import json
import os

from api.dependencies import get_db, get_coordination_service, require_admin
from core.services.coordination import AdaptiveCoordinationService
from core.domain.models import OperationalEvent

router = APIRouter(prefix="/api/scenarios", tags=["Scenarios"], dependencies=[Depends(require_admin)])


def _inject_demo_disruptions(
    simulated_time: datetime,
    service: AdaptiveCoordinationService,
) -> int:
    """
    Deterministic demo adapter: loads COUNTER_UNAVAILABLE events from demo.json
    and injects them at sequential timestamps starting at simulated_time.
    Contains NO intelligence logic — delegates every event to process_event.
    """
    demo_path = os.path.join(os.path.dirname(__file__), "../../simulation/scenarios/demo.json")
    try:
        with open(demo_path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load scenario: {e}")

    from datetime import timedelta
    events_injected = 0
    for i, ev_data in enumerate(data.get("events", [])):
        if ev_data["event_type"] == "COUNTER_UNAVAILABLE":
            ts = simulated_time + timedelta(seconds=i)
            event = OperationalEvent(
                event_id=f"demo_ev_{events_injected}",
                timestamp=ts,
                source="ScenarioHook",
                event_type=ev_data["event_type"],
                metadata=ev_data["metadata"]
            )
            service.process_event(event)
            events_injected += 1
    return events_injected


@router.post("/run")
def run_scenario(
    simulated_time: datetime = Query(...),
    db: Session = Depends(get_db),
    service: AdaptiveCoordinationService = Depends(get_coordination_service),
):
    """
    Deterministic simulation/demo adapter. Injects pre-defined scenario events.
    Does NOT contain intelligence or decision logic.
    """
    try:
        n = _inject_demo_disruptions(simulated_time, service)
        db.commit()
        return {"status": "SUCCESS", "events_injected": n,
                "note": "Scenario adapter — intelligence resides in core service layer"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trigger_disruption")
def trigger_disruption(
    simulated_time: datetime = Query(...),
    db: Session = Depends(get_db),
    service: AdaptiveCoordinationService = Depends(get_coordination_service),
):
    """Legacy alias for /run."""
    try:
        n = _inject_demo_disruptions(simulated_time, service)
        db.commit()
        return {"status": "SUCCESS", "message": f"Injected {n} disruption events"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/reset")
def reset_demo(
    simulated_time: datetime = Query(...),
    db: Session = Depends(get_db),
    service: AdaptiveCoordinationService = Depends(get_coordination_service),
):
    """
    ADMIN-only deterministic reset adapter. 
    Strictly scoped to 'demo_centre'. Wipes demo data and re-seeds.
    """
    from infrastructure.database.models import (
        BookingModel, RecommendationModel, CentreStateSnapshotModel, OperationalEventModel,
        CentreModel, ConstraintSetModel
    )
    from core.domain.models import (
        CentreState, Counter, CounterStatus, OperatingStatus, CongestionLevel,
        Booking, BookingState, ProcurementStatus, PaymentStatus, ConstraintSet
    )
    from datetime import timedelta
    
    centre_id = "c1"
    
    try:
        # 1. Delete all demo-scoped records
        db.query(BookingModel).filter(BookingModel.centre_id == centre_id).delete()
        db.query(RecommendationModel).filter(RecommendationModel.centre_id == centre_id).delete()
        db.query(CentreStateSnapshotModel).filter(CentreStateSnapshotModel.centre_id == centre_id).delete()
        
        # Events don't have centre_id column, filter manually
        all_events = db.query(OperationalEventModel).all()
        for ev in all_events:
            meta = ev.metadata_payload or {}
            if meta.get("centre_id") == centre_id:
                db.delete(ev)
                
        # 2. Recreate Centre State (4 counters at 10.0/hr)
        state = CentreState(
            centre_id=centre_id,
            timestamp=simulated_time,
            operating_status=OperatingStatus.OPEN,
            counters=[
                Counter(counter_id="cnt_1", centre_id=centre_id, status=CounterStatus.ACTIVE, processing_rate=10.0),
                Counter(counter_id="cnt_2", centre_id=centre_id, status=CounterStatus.ACTIVE, processing_rate=10.0),
                Counter(counter_id="cnt_3", centre_id=centre_id, status=CounterStatus.ACTIVE, processing_rate=10.0),
                Counter(counter_id="cnt_4", centre_id=centre_id, status=CounterStatus.ACTIVE, processing_rate=10.0)
            ]
        )
        service.centre_repo.update_state(state)
        
        # 3. Recreate Constraints
        constraints = ConstraintSet(
            operating_hours_start=8,
            operating_hours_end=18,
            slot_capacity=8, 
            booking_validity_window_minutes=60,
            available_capacity=8,
            minimum_notice_minutes=15
        )
        service.centre_repo.update_constraints(centre_id, constraints)
        
        # 4. Seed Bookings (8 bookings every 15 mins for 4 hours)
        bookings_seeded = 0
        for i in range(16):
            slot_time = simulated_time + timedelta(minutes=15 * i)
            for j in range(8):
                b = Booking(
                    booking_id=f"bk_{i}_{j}",
                    farmer_id=f"farmer_{i}_{j}",
                    centre_id=centre_id,
                    scheduled_start_time=slot_time,
                    scheduled_end_time=slot_time + timedelta(minutes=15),
                    booking_state=BookingState.SCHEDULED,
                    procurement_status=ProcurementStatus.NOT_STARTED,
                    payment_status=PaymentStatus.NOT_INITIATED,
                    priority_level=0,
                    reschedule_count=0
                )
                service.booking_repo.update_booking(b)
                bookings_seeded += 1
                
        db.commit()
        return {
            "status": "SUCCESS", 
            "centre_id": centre_id, 
            "bookings_seeded": bookings_seeded,
            "message": "Demo centre reset and seeded successfully."
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

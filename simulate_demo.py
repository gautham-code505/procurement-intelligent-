import os
import json
from datetime import datetime, timedelta

from infrastructure.database.database import SessionLocal, Base, engine
from infrastructure.database.repositories import (
    SQLAlchemyCentreRepository, SQLAlchemyBookingRepository,
    SQLAlchemyEventRepository, SQLAlchemyRecommendationRepository
)
from core.intelligence.predictor import BaselinePredictor
from core.intelligence.decider import HeuristicDecisionEngine
from core.services.coordination import AdaptiveCoordinationService
from core.domain.models import (
    CentreState, Counter, CounterStatus, OperatingStatus, CongestionLevel,
    Booking, BookingState, ProcurementStatus, PaymentStatus, ConstraintSet,
    OperationalEvent
)

def run_simulation():
    # 1. Setup in-memory SQLite DB for testing
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    centre_repo = SQLAlchemyCentreRepository(db)
    booking_repo = SQLAlchemyBookingRepository(db)
    event_repo = SQLAlchemyEventRepository(db)
    rec_repo = SQLAlchemyRecommendationRepository(db)
    
    predictor = BaselinePredictor(delta_t_minutes=15)
    decision_engine = HeuristicDecisionEngine(predictor, delta_t_minutes=15)
    
    service = AdaptiveCoordinationService(
        centre_repo=centre_repo,
        booking_repo=booking_repo,
        event_repo=event_repo,
        recommendation_repo=rec_repo,
        predictor=predictor,
        decision_engine=decision_engine
    )
    
    # 2. Seed Data
    T0 = datetime(2026, 8, 30, 9, 0, 0)
    sim_time = T0
    
    centre_id = "demo_centre"
    # Seed Centre
    # 4 counters, 10 per hour each = 40 per hour total capacity.
    state = CentreState(
        centre_id=centre_id,
        timestamp=T0,
        operating_status=OperatingStatus.OPEN,
        counters=[
            Counter(counter_id="cnt_1", centre_id=centre_id, status=CounterStatus.ACTIVE, processing_rate=10.0),
            Counter(counter_id="cnt_2", centre_id=centre_id, status=CounterStatus.ACTIVE, processing_rate=10.0),
            Counter(counter_id="cnt_3", centre_id=centre_id, status=CounterStatus.ACTIVE, processing_rate=10.0),
            Counter(counter_id="cnt_4", centre_id=centre_id, status=CounterStatus.ACTIVE, processing_rate=10.0)
        ]
    )
    centre_repo.update_state(state)
    
    # If we book 8 farmers every 15 minutes, that's 32 farmers per hour.
    # Steady state: 32 arrivals / 40 capacity -> no queue.
    constraints = ConstraintSet(
        operating_hours_start=8,
        operating_hours_end=18,
        slot_capacity=8, 
        booking_validity_window_minutes=60,
        available_capacity=8,
        minimum_notice_minutes=15
    )
    centre_repo.update_constraints(centre_id, constraints)
    
    for i in range(16): # 4 hours of bookings
        slot_time = T0 + timedelta(minutes=15 * i)
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
            booking_repo.update_booking(b)
            
    db.commit()
    
    print("\n--- PHASE 1: STEADY STATE ---")
    current_state = centre_repo.get_state(centre_id)
    bookings = booking_repo.get_bookings_for_centre(centre_id, sim_time, sim_time + timedelta(hours=8))
    pred_steady = predictor.predict(current_state, bookings, sim_time, 2.0)
    print(f"Active Counters: {current_state.active_counters}")
    print(f"Effective Rate: {current_state.effective_processing_rate}")
    peak_steady = max(tp.projected_queue for tp in pred_steady.time_points)
    max_wait_steady = max(tp.estimated_wait_minutes for tp in pred_steady.time_points)
    print(f"Peak Queue: {peak_steady} | Peak Wait: {max_wait_steady:.1f}m")
    
    print("\n--- PHASE 2: DISRUPTION ---")
    sim_time = T0 + timedelta(minutes=30)
    ev1 = OperationalEvent(event_id="ev_fail_1", timestamp=sim_time, source="demo", event_type="COUNTER_UNAVAILABLE", metadata={"centre_id": centre_id, "counter_id": "cnt_1"})
    outcome1 = service.process_event(ev1)
    
    # Must wait for second event due to the way snapshots work? Let's commit between.
    db.commit()
    ev2 = OperationalEvent(event_id="ev_fail_2", timestamp=sim_time + timedelta(seconds=1), source="demo", event_type="COUNTER_UNAVAILABLE", metadata={"centre_id": centre_id, "counter_id": "cnt_2"})
    outcome2 = service.process_event(ev2)
    db.commit()
    
    print(f"Event 2 Outcome: {outcome2}")
    rec_id = outcome2.get("recommendation_id")
    print(f"Recommendation generated: {rec_id is not None}")
    
    print("\n--- PHASE 3: DISRUPTED (PRE-APPROVAL) ---")
    current_state = centre_repo.get_state(centre_id)
    # The predictor is called DURING process_event.
    # The queue projection spiked, creating the recommendation.
    # Let's get the exact prediction the decision engine used:
    bookings = booking_repo.get_bookings_for_centre(centre_id, sim_time, sim_time + timedelta(hours=8))
    pred_disrupted = predictor.predict(current_state, bookings, sim_time, 2.0)
    print(f"Active Counters: {current_state.active_counters}")
    print(f"Effective Rate: {current_state.effective_processing_rate}")
    peak_disrupted = max(tp.projected_queue for tp in pred_disrupted.time_points)
    max_wait_disrupted = max(tp.estimated_wait_minutes for tp in pred_disrupted.time_points)
    print(f"Peak Queue: {peak_disrupted} | Peak Wait: {max_wait_disrupted:.1f}m")
    
    print("\n--- PHASE 4: RECOMMENDATION ---")
    if rec_id:
        rec = rec_repo.get_recommendation(rec_id)
        print(f"Reason: {rec.reason}")
        print(f"Expected Impact: {rec.expected_impact}")
        print(f"Bookings changed: {len(rec.changes)}")
        
        print("\n--- PHASE 5: APPROVAL ---")
        sim_time += timedelta(minutes=1)
        service.approve_recommendation(rec_id, sim_time)
        db.commit()
        
        print("\n--- PHASE 6: RECOVERED ---")
        current_state = centre_repo.get_state(centre_id)
        bookings = booking_repo.get_bookings_for_centre(centre_id, sim_time, sim_time + timedelta(hours=8))
        pred_recovered = predictor.predict(current_state, bookings, sim_time, 2.0)
        peak_recovered = max(tp.projected_queue for tp in pred_recovered.time_points)
        max_wait_recovered = max(tp.estimated_wait_minutes for tp in pred_recovered.time_points)
        print(f"Peak Queue: {peak_recovered} | Peak Wait: {max_wait_recovered:.1f}m")
        print(f"Recovery Delta Queue: {peak_disrupted - peak_recovered}")
        print(f"Recovery Delta Wait: {max_wait_disrupted - max_wait_recovered:.1f}m")
        
        print("\n--- PHASE 7: FARMER IMPACT ---")
        farmer_bk_id = rec.changes[0].booking_id
        bk = booking_repo.get_booking(farmer_bk_id)
        print(f"Booking {farmer_bk_id} State: {bk.booking_state.value}")
        print(f"Reschedule Count: {bk.reschedule_count}")
        print(f"Old Slot: {rec.changes[0].original_start}")
        print(f"New Slot (live): {bk.scheduled_start_time}")
        
    db.close()

if __name__ == "__main__":
    run_simulation()

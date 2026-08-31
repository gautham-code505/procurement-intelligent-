import json
import time
from datetime import datetime, timedelta

from infrastructure.database.database import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

from infrastructure.database.repositories import (
    SQLAlchemyCentreRepository, SQLAlchemyBookingRepository,
    SQLAlchemyEventRepository, SQLAlchemyRecommendationRepository
)
from core.services.coordination import AdaptiveCoordinationService
from core.intelligence.predictor import BaselinePredictor
from core.intelligence.decider import HeuristicDecisionEngine
from core.domain.models import (
    CentreState, OperatingStatus, Counter, CounterStatus, Booking, BookingState,
    ProcurementStatus, PaymentStatus, ConstraintSet
)
from simulation.engine import DeterministicSimulator

def setup_simulation(db_session, bookings_count=40, priority_index=-1):
    # Setup state
    centre_repo = SQLAlchemyCentreRepository(db_session)
    booking_repo = SQLAlchemyBookingRepository(db_session)
    event_repo = SQLAlchemyEventRepository(db_session)
    rec_repo = SQLAlchemyRecommendationRepository(db_session)
    
    state = CentreState(
        centre_id="c1",
        timestamp=datetime(2026, 8, 30, 9, 0),
        operating_status=OperatingStatus.OPEN,
        counters=[
            Counter("cnt_1", "c1", CounterStatus.ACTIVE, 10.0),
            Counter("cnt_2", "c1", CounterStatus.ACTIVE, 10.0),
            Counter("cnt_3", "c1", CounterStatus.ACTIVE, 10.0),
            Counter("cnt_4", "c1", CounterStatus.ACTIVE, 10.0)
        ]
    )
    centre_repo.update_state(state)
    
    constraints = ConstraintSet(
        operating_hours_start="08:00",
        operating_hours_end="18:00",
        slot_capacity=10,
        booking_validity_window_minutes=60,
        available_capacity=100
    )
    # We should add the model directly since repo lacks add_constraint
    from infrastructure.database.models import ConstraintSetModel
    db_session.add(ConstraintSetModel(
        centre_id="c1",
        operating_hours_start="08:00",
        operating_hours_end="18:00",
        slot_capacity=10,
        booking_validity_window_minutes=60,
        available_capacity=100
    ))
    db_session.flush()

    # Setup bookings
    current_time = datetime(2026, 8, 30, 10, 0)
    for i in range(bookings_count):
        slot_start = current_time + timedelta(minutes=(i // 10 + 1) * 15)
        # Give one booking high priority
        priority = 1 if i == priority_index else 0
        booking = Booking(
            booking_id=f"b_{i}",
            farmer_id=f"f_{i}",
            centre_id="c1",
            scheduled_start_time=slot_start,
            scheduled_end_time=slot_start + timedelta(minutes=15),
            booking_state=BookingState.SCHEDULED,
            procurement_status=ProcurementStatus.NOT_STARTED,
            payment_status=PaymentStatus.NOT_INITIATED,
            priority_level=priority,
            reschedule_count=0
        )
        booking_repo.update_booking(booking)

    predictor = BaselinePredictor(delta_t_minutes=15)
    decider = HeuristicDecisionEngine(predictor, delta_t_minutes=15)
    
    service = AdaptiveCoordinationService(
        centre_repo, booking_repo, event_repo, rec_repo, predictor, decider
    )
    
    simulator = DeterministicSimulator(service)
    simulator.load_scenario("simulation/scenarios/demo.json")
    
    return simulator, rec_repo, centre_repo, booking_repo

def run_trace_scenario(scenario_name, bookings_count=40, priority_index=-1, modify_capacity=False):
    print(f"\n{'='*50}\nSCENARIO: {scenario_name}\n{'='*50}")
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        simulator, rec_repo, centre_repo, booking_repo = setup_simulation(session, bookings_count, priority_index)
        
        # Modify capacity constraint for PARTIAL or NO_FEASIBLE testing
        if modify_capacity:
            from infrastructure.database.models import ConstraintSetModel
            c = session.query(ConstraintSetModel).filter_by(centre_id="c1").first()
            c.slot_capacity = 2 # Extremely restricted capacity
            session.flush()

        start_time = time.perf_counter()
        simulator.run()
        execution_time = time.perf_counter() - start_time
        
        print(f"\n[EXECUTION TIME]: {execution_time * 1000:.2f} ms")
        
        # We can extract the recommendation directly from DB
        from infrastructure.database.models import RecommendationModel
        recs = session.query(RecommendationModel).all()
        
        if recs:
            rec = recs[-1]
            print(f"\n[FINAL RECOMMENDATION]")
            print(f"Status: {rec.status}")
            print(f"Reason: {rec.reason}")
            print(f"Impact: {rec.expected_impact}")
            print(f"Changes Proposed: {len(rec.changes)}")
            
            # Show fairness verification (priority wasn't touched)
            if priority_index != -1:
                b_id_priority = f"b_{priority_index}"
                priority_moved = any(c.booking_id == b_id_priority for c in rec.changes)
                print(f"Fairness Check: Priority Booking {b_id_priority} moved? {priority_moved}")
                
            # Show slot capacity tracking
            slots_used = {}
            for c in rec.changes:
                key = c.proposed_start.strftime('%H:%M')
                slots_used[key] = slots_used.get(key, 0) + 1
            print(f"Slot Utilization: {slots_used}")
            
        else:
            print("\n[FINAL RECOMMENDATION] None generated.")
            
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

if __name__ == "__main__":
    # 5. Exact Demo Scenario (40 bookings, FULL_RECOVERY)
    run_trace_scenario("DEMO_FULL_RECOVERY", bookings_count=40)
    
    # 7. No Hardcoding (30 bookings, FULL_RECOVERY, expects 10 changes instead of 20)
    run_trace_scenario("NO_HARDCODING_30_BOOKINGS", bookings_count=30)
    
    # 8B. Partial Recovery (Restricted slot capacity so we can't move everyone)
    run_trace_scenario("PARTIAL_RECOVERY", bookings_count=40, modify_capacity=True)
    
    # 9. Fairness (Priority Booking at index 35)
    run_trace_scenario("FAIRNESS_CHECK", bookings_count=40, priority_index=35)
    
    # 11. Determinism (Run exactly the same as first to prove identically)
    run_trace_scenario("DETERMINISM_CHECK", bookings_count=40)

import time
import copy
import statistics
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
    ProcurementStatus, PaymentStatus, ConstraintSet, OperationalEvent
)
from simulation.engine import DeterministicSimulator
from infrastructure.database.models import ConstraintSetModel

def get_base_state():
    return CentreState(
        centre_id="c1",
        timestamp=datetime(2026, 8, 30, 10, 0),
        operating_status=OperatingStatus.OPEN,
        counters=[
            Counter("cnt_1", "c1", CounterStatus.ACTIVE, 10.0),
            Counter("cnt_2", "c1", CounterStatus.ACTIVE, 10.0)
        ],
        current_queue=0
    )

def get_bookings(count=40):
    bookings = []
    current_time = datetime(2026, 8, 30, 10, 0)
    for i in range(count):
        slot_start = current_time + timedelta(minutes=(i // 10 + 1) * 15)
        bookings.append(Booking(
            booking_id=f"b_{i}",
            farmer_id=f"f_{i}",
            centre_id="c1",
            scheduled_start_time=slot_start,
            scheduled_end_time=slot_start + timedelta(minutes=15),
            booking_state=BookingState.SCHEDULED,
            procurement_status=ProcurementStatus.NOT_STARTED,
            payment_status=PaymentStatus.NOT_INITIATED,
            priority_level=0,
            reschedule_count=0
        ))
    return bookings

def get_constraints():
    return ConstraintSet('08:00', '18:00', 10, 60, 100)

def measure_predictor():
    predictor = BaselinePredictor(15)
    state = get_base_state()
    bookings = get_bookings()
    current_time = datetime(2026, 8, 30, 10, 0)
    
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        predictor.predict(state, bookings, current_time, 4.0)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    return times

def measure_decider():
    predictor = BaselinePredictor(15)
    decider = HeuristicDecisionEngine(predictor, 15)
    state = get_base_state()
    bookings = get_bookings()
    constraints = get_constraints()
    current_time = datetime(2026, 8, 30, 10, 0)
    pred = predictor.predict(state, bookings, current_time, 4.0)
    
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        # Deepcopy because decider mutates internal copies
        decider.generate_recommendation(state, pred, bookings, constraints)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    return times

def measure_full_simulation():
    times = []
    persistence_times = []
    for _ in range(5):
        Base.metadata.create_all(bind=engine)
        session = TestingSessionLocal()
        
        centre_repo = SQLAlchemyCentreRepository(session)
        booking_repo = SQLAlchemyBookingRepository(session)
        event_repo = SQLAlchemyEventRepository(session)
        rec_repo = SQLAlchemyRecommendationRepository(session)
        
        state = get_base_state()
        state.counters = [
            Counter("cnt_1", "c1", CounterStatus.ACTIVE, 10.0),
            Counter("cnt_2", "c1", CounterStatus.ACTIVE, 10.0),
            Counter("cnt_3", "c1", CounterStatus.ACTIVE, 10.0),
            Counter("cnt_4", "c1", CounterStatus.ACTIVE, 10.0)
        ]
        
        t0_pers = time.perf_counter()
        centre_repo.update_state(state)
        session.add(ConstraintSetModel(
            centre_id="c1", operating_hours_start="08:00", operating_hours_end="18:00",
            slot_capacity=10, booking_validity_window_minutes=60, available_capacity=100
        ))
        session.flush()
        
        bookings = get_bookings()
        for b in bookings:
            booking_repo.update_booking(b)
        session.commit()
        t1_pers = time.perf_counter()
        persistence_times.append((t1_pers - t0_pers) * 1000)
        
        predictor = BaselinePredictor(15)
        decider = HeuristicDecisionEngine(predictor, 15)
        service = AdaptiveCoordinationService(centre_repo, booking_repo, event_repo, rec_repo, predictor, decider)
        
        simulator = DeterministicSimulator(service)
        simulator.load_scenario("simulation/scenarios/demo.json")
        
        t0 = time.perf_counter()
        simulator.run()
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
        
        session.close()
        Base.metadata.drop_all(bind=engine)
        
    return times, persistence_times

print("A. Predictor only")
p_times = measure_predictor()
print(f"Min: {min(p_times):.2f}ms | Max: {max(p_times):.2f}ms | Mean: {statistics.mean(p_times):.2f}ms")

print("\nB. Decision engine only")
d_times = measure_decider()
print(f"Min: {min(d_times):.2f}ms | Max: {max(d_times):.2f}ms | Mean: {statistics.mean(d_times):.2f}ms")

print("\nC. Full simulation & D. Persistence overhead")
f_times, pers_times = measure_full_simulation()
print(f"Simulation - Min: {min(f_times):.2f}ms | Max: {max(f_times):.2f}ms | Mean: {statistics.mean(f_times):.2f}ms")
print(f"Initial Setup Persistence - Min: {min(pers_times):.2f}ms | Max: {max(pers_times):.2f}ms | Mean: {statistics.mean(pers_times):.2f}ms")

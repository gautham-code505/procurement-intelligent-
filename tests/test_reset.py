import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import app
from api.dependencies import get_db
from infrastructure.database.database import Base

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

def _override_get_db():
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(scope="module", autouse=True)
def _install_db_override():
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db
    yield
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous

@pytest.fixture(scope="module", autouse=True)
def setup_database():
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)

@pytest.fixture
def client():
    return TestClient(app)

def test_reset_endpoint(client: TestClient):
    sim_time = "2026-08-30T09:00:00"
    headers = {"X-User-Role": "ADMIN"}
    
    # 1. Reset
    res1 = client.post(f"/api/scenarios/reset?simulated_time={sim_time}", headers=headers)
    assert res1.status_code == 200
    assert res1.json()["bookings_seeded"] == 128
    
    # 2. Reset again (Repeatability)
    res2 = client.post(f"/api/scenarios/reset?simulated_time={sim_time}", headers=headers)
    assert res2.status_code == 200
    assert res2.json()["bookings_seeded"] == 128
    
    # Check state
    res_state = client.get("/api/centres/c1/state", headers=headers)
    assert res_state.status_code == 200
    assert len(res_state.json()["counters"]) == 4
    
    # 3. Run scenario (Disruption)
    sim_time_run = "2026-08-30T09:30:00"
    res_run = client.post(f"/api/scenarios/run?simulated_time={sim_time_run}", headers=headers)
    if res_run.status_code != 200:
        print("RUN ERROR:", res_run.json())
    assert res_run.status_code == 200
    
    # 4. Get Recommendations
    res_recs = client.get("/api/centres/c1/recommendations", headers=headers)
    assert res_recs.status_code == 200
    recs = res_recs.json()
    assert len(recs) >= 1
    rec_id = recs[-1]["recommendation_id"]
    
    # 5. Approve recommendation
    sim_time_approve = "2026-08-30T09:31:00"
    res_app = client.post(f"/api/recommendations/{rec_id}/approve?simulated_time={sim_time_approve}", headers=headers)
    assert res_app.status_code == 200
    
    # 6. Reset again to verify it cleans up post-approval
    res3 = client.post(f"/api/scenarios/reset?simulated_time={sim_time}", headers=headers)
    assert res3.status_code == 200
    
    # 7. Verify no stale recommendations exist
    res_recs2 = client.get("/api/centres/c1/recommendations", headers=headers)
    assert res_recs2.status_code == 200
    assert len(res_recs2.json()) == 0

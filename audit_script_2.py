import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"
HEADERS_ADMIN = {"X-User-Role": "ADMIN"}
HEADERS_OP = {"X-User-Role": "OPERATOR"}
HEADERS_FARM = {"X-User-Role": "FARMER"}

def create_non_demo_record():
    print("Creating non-demo centre...")
    # For a non-demo record, we'll try to use DB directly or API if available.
    # Actually, we can use the DB engine to insert directly.
    from infrastructure.database.database import SessionLocal
    from infrastructure.database.models import CentreModel
    db = SessionLocal()
    if not db.query(CentreModel).filter_by(centre_id="real_centre").first():
        db.add(CentreModel(centre_id="real_centre", name="Real Centre"))
        db.commit()
    return db.query(CentreModel).filter_by(centre_id="real_centre").first()

def test_reset_isolation():
    create_non_demo_record()
    print("Executing reset...")
    res = requests.post(f"{BASE_URL}/api/scenarios/reset?simulated_time=2026-08-30T09:00:00", headers=HEADERS_ADMIN)
    assert res.status_code == 200, "Reset failed"
    
    from infrastructure.database.database import SessionLocal
    from infrastructure.database.models import CentreModel
    db = SessionLocal()
    assert db.query(CentreModel).filter_by(centre_id="real_centre").first() is not None, "Non-demo record deleted!"
    print("Isolation test passed.")

def test_reset_repeatability():
    print("Testing repeatability...")
    res1 = requests.post(f"{BASE_URL}/api/scenarios/reset?simulated_time=2026-08-30T09:00:00", headers=HEADERS_ADMIN).json()
    res2 = requests.post(f"{BASE_URL}/api/scenarios/reset?simulated_time=2026-08-30T09:00:00", headers=HEADERS_ADMIN).json()
    assert res1["bookings_seeded"] == 128
    assert res2["bookings_seeded"] == 128
    print("Repeatability test passed.")

if __name__ == "__main__":
    time.sleep(2) # wait for uvicorn
    try:
        test_reset_isolation()
        test_reset_repeatability()
        print("ALL AUDIT SCRIPT TESTS PASSED.")
    except Exception as e:
        print(f"FAILED: {e}")

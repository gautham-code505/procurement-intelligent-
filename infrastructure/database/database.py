import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

# We use TEST_DATABASE_URL if running tests, otherwise DATABASE_URL
# In a real app we'd inject this configuration cleanly, but for Milestone 1B we read from env
db_url = os.getenv("TEST_DATABASE_URL") if os.getenv("TESTING") == "true" else os.getenv("DATABASE_URL")
if not db_url:
    # Fallback to sqlite for tests if env not provided, though PG is preferred
    db_url = "sqlite:///./procurement.db"

engine = create_engine(
    db_url, 
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in db_url else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

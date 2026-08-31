from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import centres, farmers, bookings, events, recommendations, scenarios

from infrastructure.database.database import Base, engine
from infrastructure.database.models import *

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Adaptive Procurement Coordination API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(centres.router)
app.include_router(farmers.router)
app.include_router(bookings.router)
app.include_router(events.router)
app.include_router(recommendations.router)
app.include_router(scenarios.router)

@app.get("/health")
def health_check():
    return {"status": "ok"}

from fastapi.staticfiles import StaticFiles
import os

# Mount the frontend directory. This MUST be after all API routes.
frontend_path = os.path.join(os.path.dirname(__file__), "../frontend")
app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

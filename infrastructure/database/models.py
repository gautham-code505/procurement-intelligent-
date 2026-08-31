from sqlalchemy import Column, String, Integer, Float, DateTime, Enum as SQLEnum, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime

from infrastructure.database.database import Base
import core.domain.models as domain

class CentreModel(Base):
    __tablename__ = "centres"
    
    centre_id = Column(String, primary_key=True, index=True)
    name = Column(String)
    
    # Relationships
    counters = relationship("CounterModel", back_populates="centre", cascade="all, delete-orphan")
    snapshots = relationship("CentreStateSnapshotModel", back_populates="centre", cascade="all, delete-orphan")

class CounterModel(Base):
    __tablename__ = "counters"
    
    counter_id = Column(String, primary_key=True, index=True)
    centre_id = Column(String, ForeignKey("centres.centre_id"))
    status = Column(SQLEnum(domain.CounterStatus), default=domain.CounterStatus.ACTIVE)
    processing_rate = Column(Float)
    
    centre = relationship("CentreModel", back_populates="counters")

class BookingModel(Base):
    __tablename__ = "bookings"
    
    booking_id = Column(String, primary_key=True, index=True)
    farmer_id = Column(String, index=True)
    centre_id = Column(String, ForeignKey("centres.centre_id"), index=True)
    scheduled_start_time = Column(DateTime)
    scheduled_end_time = Column(DateTime)
    booking_state = Column(SQLEnum(domain.BookingState))
    procurement_status = Column(SQLEnum(domain.ProcurementStatus))
    payment_status = Column(SQLEnum(domain.PaymentStatus))
    priority_level = Column(Integer)
    reschedule_count = Column(Integer)

class OperationalEventModel(Base):
    __tablename__ = "operational_events"
    
    event_id = Column(String, primary_key=True, index=True) # Uniqueness constraint ensures idempotency
    timestamp = Column(DateTime, index=True)
    source = Column(String)
    event_type = Column(String)
    metadata_payload = Column(JSON) # 'metadata' is reserved in SQLAlchemy

class CentreStateSnapshotModel(Base):
    __tablename__ = "centre_state_snapshots"
    
    snapshot_id = Column(String, primary_key=True, index=True)
    centre_id = Column(String, ForeignKey("centres.centre_id"), index=True)
    timestamp = Column(DateTime, index=True)
    # Storing the entire state as JSON to preserve history perfectly
    state_payload = Column(JSON)
    
    centre = relationship("CentreModel", back_populates="snapshots")

class RecommendationModel(Base):
    __tablename__ = "recommendations"
    
    recommendation_id = Column(String, primary_key=True, index=True)
    centre_id = Column(String, ForeignKey("centres.centre_id"), index=True)
    trigger_event_id = Column(String)
    created_at = Column(DateTime)
    status = Column(String)
    reason = Column(String)
    expected_impact = Column(String)
    constraint_check = Column(String)
    fairness_check = Column(String)
    
    changes = relationship("RecommendationChangeModel", back_populates="recommendation", cascade="all, delete-orphan")

class RecommendationChangeModel(Base):
    __tablename__ = "recommendation_changes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    recommendation_id = Column(String, ForeignKey("recommendations.recommendation_id"))
    booking_id = Column(String)
    original_start = Column(DateTime)
    proposed_start = Column(DateTime)
    priority_level = Column(Integer)
    reschedule_count = Column(Integer)
    
    recommendation = relationship("RecommendationModel", back_populates="changes")

class ConstraintSetModel(Base):
    __tablename__ = "constraint_sets"
    
    centre_id = Column(String, ForeignKey("centres.centre_id"), primary_key=True)
    operating_hours_start = Column(String)
    operating_hours_end = Column(String)
    slot_capacity = Column(Integer)
    booking_validity_window_minutes = Column(Integer)
    available_capacity = Column(Integer)
    minimum_notice_minutes = Column(Integer, default=15)

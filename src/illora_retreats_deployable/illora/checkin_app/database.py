# pre_check_in/database.py
import os
from sqlalchemy import create_engine, Column, Integer, String, Date, DateTime, Float, Enum, JSON, ForeignKey, Table, MetaData
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from datetime import datetime
import enum

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./illora.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class BookingStatus(enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"

class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    room_type = Column(String, nullable=False, index=True)
    base_price = Column(Float, nullable=False)
    total_units = Column(Integer, default=1)
    capacity = Column(Integer, default=2)
    description = Column(String, nullable=True)
    media = Column(JSON, default=[])  # list of media URLs (images/youtube/instagram)
    created_at = Column(DateTime, default=datetime.utcnow)

class FestivalPricing(Base):
    __tablename__ = "festival_pricing"
    id = Column(Integer, primary_key=True)
    start_date = Column(String)   # YYYY-MM-DD
    end_date = Column(String)
    multiplier = Column(Float, default=1.0)
    note = Column(String, nullable=True)

class Booking(Base):
    __tablename__ = "bookings"
    id = Column(String, primary_key=True)  # use uuid generated elsewhere
    guest_name = Column(String, nullable=False)
    guest_phone = Column(String, nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    check_in = Column(Date, nullable=False)
    check_out = Column(Date, nullable=False)
    price = Column(Float, nullable=False)
    status = Column(Enum(BookingStatus), default=BookingStatus.pending)
    stripe_session_id = Column(String, nullable=True)
    qr_path = Column(String, nullable=True)
    channel = Column(String, default="web")
    channel_user = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    room = relationship("Room", lazy="joined")

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# illora/checkin_app/models.py
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Enum, ForeignKey, JSON
from sqlalchemy.orm import relationship, declarative_base
import enum
import datetime

Base = declarative_base()

class BookingStatus(enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"

class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False, unique=True)
    room_type = Column(String(80), nullable=False)
    base_price = Column(Float, nullable=False)
    total_units = Column(Integer, default=1)
    capacity = Column(Integer, default=2)
    # media: list of URLs (images, youtube links, instagram links)
    media = Column(JSON, default=[])
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    bookings = relationship("Booking", back_populates="room", cascade="all, delete-orphan")

class Booking(Base):
    __tablename__ = "bookings"
    # we use UUID strings in your web_ui for booking id, so keep string PK
    id = Column(String(64), primary_key=True)
    guest_name = Column(String(200), nullable=False)
    guest_phone = Column(String(32), nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    check_in = Column(Date, nullable=False)
    check_out = Column(Date, nullable=False)
    price = Column(Float, nullable=False)
    status = Column(Enum(BookingStatus), default=BookingStatus.pending)
    stripe_session_id = Column(String(255), nullable=True)
    qr_path = Column(String(1024), nullable=True)
    channel = Column(String(50), default="web")        # "web" or "whatsapp"
    channel_user = Column(String(64), nullable=True)   # e.g., phone number
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    room = relationship("Room", back_populates="bookings")

# note: keep only this models.py as the canonical model definition in the process

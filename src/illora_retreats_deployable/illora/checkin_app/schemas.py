# app/schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date

class RoomOut(BaseModel):
    id: int
    name: str
    room_type: str
    base_price: int
    total_units: int
    capacity: int
    media: List[str] = []

    class Config:
        orm_mode = True

class AvailabilityRequest(BaseModel):
    check_in: date
    check_out: date
    guests: int = 1

class AvailabilityOption(BaseModel):
    room_id: int
    name: str
    total_price: float
    nights: int
    media: List[str] = []

class CreateBookingRequest(BaseModel):
    guest_name: str
    guest_phone: str
    room_id: int
    check_in: date
    check_out: date
    payment_method: str = Field("stripe", regex="^(stripe|cash)$")

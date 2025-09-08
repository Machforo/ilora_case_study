# pre_check_in/pricing.py
from datetime import datetime, timedelta
from .database import get_db, Room, FestivalPricing
from sqlalchemy.orm import Session
from math import ceil

def nights_between(ci, co):
    return (co - ci).days

def is_in_festival(check_in, check_out, db: Session):
    fps = db.query(FestivalPricing).all()
    for f in fps:
        try:
            s = datetime.strptime(f.start_date, "%Y-%m-%d").date()
            e = datetime.strptime(f.end_date, "%Y-%m-%d").date()
            # if any overlap, return multiplier (take max)
            if (check_in <= e and check_out >= s):
                return f.multiplier
        except Exception:
            continue
    return 1.0

def demand_factor(db: Session, room: Room, check_in, check_out):
    # count bookings overlapping (confirmed or pending)
    from .database import Booking
    booked = db.query(Booking).filter(
        Booking.room_id == room.id,
        Booking.status != Booking.status.enum_class.cancelled,
        Booking.check_in < check_out,
        Booking.check_out > check_in
    ).count()
    capacity = max(1, room.total_units)
    occupancy = booked / capacity
    factor = 1.0
    if occupancy >= 0.9:
        factor += 0.35
    elif occupancy >= 0.75:
        factor += 0.2
    elif occupancy >= 0.5:
        factor += 0.1
    return factor

def weekend_surcharge(check_in, check_out):
    weekends = 0
    cur = check_in
    while cur < check_out:
        if cur.weekday() in (5,6):
            weekends += 1
        cur += timedelta(days=1)
    return 1.0 + 0.10 * weekends

def calculate_price_for_room(db: Session, room: Room, check_in, check_out):
    nights = nights_between(check_in, check_out)
    if nights <= 0:
        raise ValueError("check_out must be after check_in")
    base_total = room.base_price * nights
    demand = demand_factor(db, room, check_in, check_out)
    festival_mul = is_in_festival(check_in, check_out, db)
    weekend_mul = weekend_surcharge(check_in, check_out)
    total = base_total * demand * festival_mul * weekend_mul
    return round(total,2), nights

# pre_check_in/booking_flow.py
import uuid
from datetime import datetime
from .database import init_db, get_db, Room, Booking
from .pricing import calculate_price_for_room
from .media import get_youtube_preview, get_instagram_preview
from .payment import create_stripe_checkout_for_booking, generate_qr_image_bytes
from sqlalchemy.orm import Session

init_db()

def create_booking_record(db: Session, guest_name, guest_phone, room_id, check_in, check_out, price, channel="web", channel_user=None):
    booking_id = str(uuid.uuid4())
    b = Booking(
        id=booking_id,
        guest_name=guest_name,
        guest_phone=guest_phone,
        room_id=room_id,
        check_in=check_in,
        check_out=check_out,
        price=price,
        status=Booking.status.property.columns[0].type.enum_class.pending,  # fallback handled next
        channel=channel,
        channel_user=channel_user
    )
    # SQLAlchemy enum typing is handled; do generic assignment
    b.status = Booking.status.type.enum_class.pending if False else b.status  # noop to avoid lint; we'll set explicitly below
    # Instead set directly:
    from .database import BookingStatus
    b.status = BookingStatus.pending
    db.add(b)
    db.commit()
    db.refresh(b)
    return b

def start_booking_flow(db: Session, room: Room, check_in, check_out, guest_name=None, guest_phone=None, channel="web", channel_user=None):
    """
    Orchestrate price calculation + media previews + create pending booking + stripe session.
    Returns a dict with price, nights, media previews, stripe checkout url and booking_id.
    """
    price, nights = calculate_price_for_room(db, room, check_in, check_out)
    media_previews = []
    for m in (room.media or []):
        if "youtube.com" in m or "youtu.be" in m:
            media_previews.append(get_youtube_preview(m))
        else:
            media_previews.append(get_instagram_preview(m))

    # create booking record with pending status
    booking = create_booking_record(db, guest_name or "Guest", guest_phone or "", room.id, check_in, check_out, price, channel=channel, channel_user=channel_user)

    # create stripe session
    session = create_stripe_checkout_for_booking(booking.id, price)
    booking.stripe_session_id = session.id
    db.commit()

    return {
        "booking_id": booking.id,
        "price": price,
        "nights": nights,
        "media": media_previews,
        "checkout_url": session.url
    }

def generate_qr_for_booking(booking_id: str, booking_summary_text: str):
    filename = f"qr_{booking_id}.png"
    local = generate_qr_image_bytes(booking_summary_text, filename)
    public = (os.getenv("MEDIA_BASE_URL").rstrip("/") + "/static/" + filename) if os.getenv("MEDIA_BASE_URL") else local
    return {"local_path": local, "public_url": public}

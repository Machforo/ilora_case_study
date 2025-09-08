# pre_check_in/payment.py
import os
import stripe
import qrcode
from io import BytesIO
from pathlib import Path

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
SUCCESS_URL = os.getenv("SUCCESS_URL")
CANCEL_URL = os.getenv("CANCEL_URL")
MEDIA_BASE_URL = os.getenv("MEDIA_BASE_URL")  # used to construct public QR URL if static hosted
STATIC_DIR = Path("static")
STATIC_DIR.mkdir(parents=True, exist_ok=True)

def create_stripe_checkout_for_booking(booking_id: str, amount_inr: float, success_url=SUCCESS_URL, cancel_url=CANCEL_URL):
    """
    amount_inr: rupees (float)
    """
    if not stripe.api_key:
        raise EnvironmentError("STRIPE_SECRET_KEY not set")
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "inr",
                "product_data": {"name": f"ILLORA Booking {booking_id}"},
                "unit_amount": int(round(amount_inr * 100)),
            },
            "quantity": 1,
        }],
        success_url=(success_url or "") + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=(cancel_url or ""),
        metadata={"booking_id": booking_id}
    )
    return session

def generate_qr_image_bytes(booking_payload: str, filename: str):
    img = qrcode.make(booking_payload)
    path = STATIC_DIR / filename
    img.save(path)
    return str(path)  # local path; public path must be constructed by caller using MEDIA_BASE_URL

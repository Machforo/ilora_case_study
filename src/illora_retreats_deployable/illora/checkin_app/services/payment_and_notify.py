# app/services/payment_and_notify.py
import os
import stripe
from twilio.rest import Client

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.getenv("TWILIO_WHATSAPP_FROM")  # e.g. "whatsapp:+1415..."

def create_stripe_checkout(booking_id: str, amount_inr: float, success_url: str, cancel_url: str):
    # amount_inr is float rupees. Stripe expects paise (INR) as integer.
    unit_amount = int(round(amount_inr * 100))
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "inr",
                "product_data": {"name": f"AI Chieftain Booking {booking_id}"},
                "unit_amount": unit_amount,
            },
            "quantity": 1,
        }],
        success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=cancel_url,
        metadata={"booking_id": booking_id}
    )
    return session

def send_whatsapp_message(to_whatsapp_number: str, body: str, media_url: str = None):
    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM):
        raise EnvironmentError("Twilio credentials are not set")
    client = Client(TWILIO_SID, TWILIO_TOKEN)
    kwargs = {"from_": TWILIO_FROM, "to": to_whatsapp_number, "body": body}
    if media_url:
        kwargs["media_url"] = [media_url]
    return client.messages.create(**kwargs)

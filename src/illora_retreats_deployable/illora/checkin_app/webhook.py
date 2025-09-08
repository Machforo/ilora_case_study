# pre_check_in/webhook.py
import os, json, stripe
from fastapi import FastAPI, Request, Header, HTTPException
from sqlalchemy.orm import Session
from .database import SessionLocal, Booking, BookingStatus
from .payment import generate_qr_image_bytes
from twilio.rest import Client

app = FastAPI()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
MEDIA_BASE_URL = os.getenv("MEDIA_BASE_URL")
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.getenv("TWILIO_WHATSAPP_FROM")
twilio_client = Client(TWILIO_SID, TWILIO_TOKEN) if TWILIO_SID and TWILIO_TOKEN else None

@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    payload = await request.body()
    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, stripe_signature, STRIPE_WEBHOOK_SECRET)
        else:
            event = json.loads(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook error {e}")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        booking_id = session.get("metadata", {}).get("booking_id")
        db = SessionLocal()
        try:
            if not booking_id:
                booking = db.query(Booking).filter(Booking.stripe_session_id==session.get("id")).first()
            else:
                booking = db.query(Booking).filter(Booking.id==booking_id).first()
            if booking:
                booking.status = BookingStatus.confirmed
                # generate QR
                qr_payload = f"booking:{booking.id}|name:{booking.guest_name}|from:{booking.check_in}|to:{booking.check_out}"
                filename = f"qr_{booking.id}.png"
                local_path = generate_qr_image_bytes(qr_payload, filename)
                if MEDIA_BASE_URL:
                    booking.qr_path = MEDIA_BASE_URL.rstrip("/") + "/static/" + filename
                else:
                    booking.qr_path = local_path
                db.commit()
                # send WhatsApp if available
                if booking.channel == "whatsapp" and booking.channel_user and twilio_client:
                    try:
                        to_wh = f"whatsapp:{booking.channel_user}"
                        body = (f"🎉 Your booking is confirmed!\nBooking ID: {booking.id}\nCheck-in: {booking.check_in}\nCheck-out: {booking.check_out}")
                        media = [booking.qr_path] if booking.qr_path and MEDIA_BASE_URL else None
                        twilio_client.messages.create(from_=TWILIO_FROM, to=to_wh, body=body, media_url=media)
                    except Exception as e:
                        print("Twilio send failed:", e)
        finally:
            db.close()

    return {"received": True}

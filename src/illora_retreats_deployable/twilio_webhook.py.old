# app/twilio_webhook.py

from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from services.qa_agent import ConciergeBot
from services.payment_gateway import create_checkout_session, create_addon_checkout_session
from logger import log_chat
from services.intent_classifier import classify_intent

import uuid

app = Flask(__name__)
bot = ConciergeBot()
session_data = {}

ROOM_PRICES = {
    "Standard": 12500,
    "Deluxe": 17000,
    "Executive": 23000,
    "Family": 27500,
    "Suite": 34000
}
ROOM_OPTIONS = list(ROOM_PRICES.keys())

ADDON_MAPPING = {
    "spa": "spa",
    "massage": "spa",
    "mocktail": "mocktail",
    "juice": "juice",
    "brownie": "brownie",
    "cheese": "cheese_platter"
}

@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    incoming_msg = request.form.get('Body', "").strip()
    user_number = request.form.get('From')
    msg = MessagingResponse()
    response = ""

    if user_number not in session_data:
        session_data[user_number] = {"stage": "identify"}

    user_session = session_data[user_number]
    stage = user_session["stage"]

    print(f"[Stage: {stage}] Incoming: {incoming_msg}")

    # Step 0: Identify guest or non-guest
    if stage == "identify":
        if "guest" in incoming_msg.lower():
            user_session["user_type"] = "guest"
            user_session["stage"] = "start"
            response = "✅ Great! You're marked as a guest of ILLORA Retreat. How can I assist you today?"
        elif "non-guest" in incoming_msg.lower() or "visitor" in incoming_msg.lower():
            user_session["user_type"] = "non-guest"
            user_session["stage"] = "start"
            response = "✅ Noted. You're marked as a visitor. Some services are exclusive to our guests. Feel free to ask any questions!"
        else:
            response = (
                "👋 Welcome to *ILLORA Retreat*.\nAre you a *guest* staying with us or a *non-guest* (e.g., restaurant or spa visitor)?\n"
                "Please reply with *guest* or *non-guest* to proceed."
            )
        log_chat("WhatsApp", user_number, incoming_msg, response, user_session.get("user_type", "guest"))
        msg.message(response)
        return str(msg)

    # Step A: Chatbot Response Always
    user_type = user_session.get("user_type", "guest")
    intent = classify_intent(incoming_msg.lower())
    answer = bot.ask(incoming_msg, user_type=user_type)
    response = f"💬 {answer}"

    # Step B: Detect Room Booking Intent
    if intent == "payment_request" and user_type == "guest":
        user_session["stage"] = "room"
        room_list = "\n".join([f"{idx+1}️⃣ {room} – ₹{price}/night" for idx, (room, price) in enumerate(ROOM_PRICES.items())])
        response += (
            "\n\n💼 Let's book your stay:\n"
            f"{room_list}\n\nReply with the number (1–{len(ROOM_OPTIONS)}) to proceed."
        )

    # Step C: Add-on Detection (Spa, Food, etc.)
    elif intent.startswith("book_addon"):
        matches = [key for key in ADDON_MAPPING if key in incoming_msg.lower()]
        if matches:
            extras = list(set(ADDON_MAPPING[m] for m in matches))
            pay_url = create_addon_checkout_session(session_id=str(uuid.uuid4()), extras=extras)
            if pay_url:
                response += f"\n\n🧾 Here is your payment link for {', '.join(extras).title()}:\n{pay_url}"
            else:
                response += "\n\n⚠️ Could not generate a payment link for your request. Please try again."
            session_data[user_number] = {"stage": "identify"}  # Reset session
        else:
            response += "\n\n❓ Please specify which add-on you'd like (e.g., spa, mocktail, brownie)."

    # Step 1: Room type selection
    elif stage == "room":
        if incoming_msg.isdigit() and 1 <= int(incoming_msg) <= len(ROOM_OPTIONS):
            selected_room = ROOM_OPTIONS[int(incoming_msg) - 1]
            user_session["room_type"] = selected_room
            user_session["stage"] = "nights"
            response = f"🛏️ Great! How many nights would you like to stay in our *{selected_room} Room*?\nReply with a number."

    # Step 2: Nights input
    elif stage == "nights":
        if incoming_msg.isdigit() and int(incoming_msg) > 0:
            user_session["nights"] = int(incoming_msg)
            user_session["stage"] = "payment"
            response = (
                "💳 How would you like to pay?\n"
                "1️⃣ Online Payment\n"
                "2️⃣ Cash on Arrival\n\nReply with *1* or *2*."
            )

    # Step 3: Payment method
    elif stage == "payment":
        if incoming_msg in ["1", "2"]:
            payment_mode = "Online" if incoming_msg == "1" else "Cash"
            user_session["payment"] = payment_mode
            user_session["stage"] = "confirm"

            room = user_session["room_type"]
            nights = user_session["nights"]
            price = ROOM_PRICES[room] * nights
            user_session["price"] = price

            response = (
                f"🧾 *Booking Summary:*\n"
                f"🏨 Room: *{room}*\n"
                f"🌙 Nights: *{nights}*\n"
                f"💰 Payment: *{payment_mode}*\n"
                f"💵 Total: ₹{price}\n\n"
                "✅ Please reply with *Yes* to confirm your booking."
            )

    # Step 4: Confirmation
    elif stage == "confirm":
        if incoming_msg.lower() == "yes":
            room = user_session["room_type"]
            nights = user_session["nights"]
            payment_mode = user_session["payment"]

            pay_url = create_checkout_session(
                session_id=user_number,
                room_type=room,
                nights=nights,
                cash=(payment_mode == "Cash")
            )

            if pay_url:
                response = (
                    f"🎉 *Your booking at ILLORA Retreat is confirmed!*\n\n"
                    f"To complete the process, please follow this payment link:\n{pay_url}"
                )
            else:
                response = "⚠ Payment link generation failed. Please try again."

            session_data[user_number] = {"stage": "identify"}
        else:
            response = "❌ Booking not confirmed. Please reply *Yes* to confirm or restart."

    # Final response
    log_chat("WhatsApp", user_number, incoming_msg, response, user_session.get("user_type", "guest"))
    msg.message(response)
    return str(msg)


if __name__ == "__main__":
    app.run(debug=True, port=5002)

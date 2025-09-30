# app/twilio_webhook.py

from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from services.qa_agent import ConciergeBot
from services.payment_gateway import create_checkout_session, create_addon_checkout_session
from logger import log_chat, setup_logger
from services.intent_classifier import classify_intent

import uuid
import json
import os

# Set up logging
logger = setup_logger("TwilioWebhook")

app = Flask(__name__)
bot = ConciergeBot()
session_data = {}

# Load room prices from a configuration file
try:
    with open(os.path.join("data", "room_config.json"), "r") as f:
        config = json.load(f)
        ROOM_PRICES = config.get("room_prices", {
            "Standard": 12500,
            "Deluxe": 17000,
            "Executive": 23000,
            "Family": 27500,
            "Suite": 34000
        })
except Exception as e:
    logger.warning(f"Could not load room config, using defaults: {e}")
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
    try:
        incoming_msg = request.form.get('Body', "").strip()
        user_number = request.form.get('From')
        msg = MessagingResponse()
        response = ""

        logger.info(f"Incoming message from {user_number}: {incoming_msg}")

        if user_number not in session_data:
            session_data[user_number] = {"stage": "identify"}

        user_session = session_data[user_number]
        stage = user_session["stage"]

        logger.info(f"[Stage: {stage}] Processing message")

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
        logger.info(f"Classified intent: {intent}")

        # Get user identifier from session if available
        user_identifier = user_session.get("user_identifier")
        
        try:
            answer = bot.ask(incoming_msg, user_type=user_type, user_identifier=user_identifier)
            response = f"💬 {answer}"
        except Exception as e:
            logger.error(f"Error getting bot response: {e}")
            response = "⚠️ I apologize, but I'm having trouble processing your request. Please try again in a moment."

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
                try:
                    extras = list(set(ADDON_MAPPING[m] for m in matches))
                    session_id = str(uuid.uuid4())
                    pay_url = create_addon_checkout_session(session_id=session_id, extras=extras)
                    if pay_url:
                        response += f"\n\n🧾 Here is your payment link for {', '.join(extras).title()}:\n{pay_url}"
                    else:
                        logger.error(f"Payment URL generation failed for add-ons: {extras}")
                        response += "\n\n⚠️ Could not generate a payment link for your request. Please try again."
                    session_data[user_number] = {"stage": "identify"}  # Reset session
                except Exception as e:
                    logger.error(f"Error processing add-on booking: {e}")
                    response += "\n\n⚠️ There was an issue processing your add-on request. Please try again."
            else:
                response += "\n\n❓ Please specify which add-on you'd like (e.g., spa, mocktail, brownie)."

        # Step 1: Room type selection
        elif stage == "room":
            if incoming_msg.isdigit() and 1 <= int(incoming_msg) <= len(ROOM_OPTIONS):
                selected_room = ROOM_OPTIONS[int(incoming_msg) - 1]
                user_session["room_type"] = selected_room
                user_session["stage"] = "nights"
                response = f"🛏️ Great! How many nights would you like to stay in our *{selected_room} Room*?\nReply with a number."
            else:
                response = f"❌ Please select a valid room number (1-{len(ROOM_OPTIONS)})."

        # Step 2: Nights input
        elif stage == "nights":
            try:
                nights = int(incoming_msg)
                if nights > 0:
                    user_session["nights"] = nights
                    user_session["stage"] = "payment"
                    response = (
                        "💳 How would you like to pay?\n"
                        "1️⃣ Online Payment\n"
                        "2️⃣ Cash on Arrival\n\nReply with *1* or *2*."
                    )
                else:
                    response = "❌ Please enter a number greater than 0 for the number of nights."
            except ValueError:
                response = "❌ Please enter a valid number for the number of nights."

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
            else:
                response = "❌ Please select 1 for Online Payment or 2 for Cash on Arrival."

        # Step 4: Confirmation
        elif stage == "confirm":
            if incoming_msg.lower() == "yes":
                try:
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
                        logger.error("Payment URL generation failed")
                        response = "⚠️ Payment link generation failed. Please try again."

                    session_data[user_number] = {"stage": "identify"}  # Reset session
                except Exception as e:
                    logger.error(f"Error processing booking confirmation: {e}")
                    response = "⚠️ There was an issue confirming your booking. Please try again."
            else:
                response = "❌ Booking not confirmed. Please reply *Yes* to confirm or restart."

        # Final response
        log_chat("WhatsApp", user_number, incoming_msg, response, user_session.get("user_type", "guest"))
        msg.message(response)
        return str(msg)

    except Exception as e:
        logger.error(f"Unexpected error in webhook: {e}")
        msg = MessagingResponse()
        msg.message("⚠️ I apologize, but something went wrong. Please try again.")
        return str(msg)


if __name__ == "__main__":
    app.run(debug=True, port=5002)
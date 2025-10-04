# app/twilio_webhook.py

from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from Hotel_AI_Bot import IloraRetreatsConciergeBot
from services.payment_gateway import create_checkout_session, create_addon_checkout_session
from services.google_sheets_service import GoogleSheetsService
from logger import log_chat, setup_logger
from services.intent_classifier import classify_intent
from config import Config
import uuid
import json
import os
import hashlib
import re
from datetime import datetime, timedelta

# Set up logging
logger = setup_logger("TwilioWebhook")

app = Flask(__name__)
bot = IloraRetreatsConciergeBot()
session_data = {}
sheets_service = GoogleSheetsService()

# Load room prices from configuration
try:
    with open(os.path.join("data", "room_config.json"), "r") as f:
        config = json.load(f)
        ROOM_PRICES = config.get("room_prices", {
            "Luxury Tent": 50000  # Base price per night in INR
        })
        TOTAL_TENTS = config.get("total_tents", 14)
except Exception as e:
    logger.warning(f"Could not load room config, using defaults: {e}")
    ROOM_PRICES = {"Luxury Tent": 50000}
    TOTAL_TENTS = 14

ROOM_OPTIONS = list(ROOM_PRICES.keys())

ADDON_MAPPING = {
    "spa": "spa",
    "massage": "spa",
    "hot air balloon": "hot_air_balloon",
    "balloon ride": "hot_air_balloon",
    "game drive": "game_drive",
    "safari": "game_drive",
    "walking safari": "walking_safari",
    "bush dinner": "bush_dinner",
    "maasai cultural": "maasai_experience",
    "stargazing": "stargazing"
}

# Guest-only services
GUEST_ONLY_SERVICES = [
    "room service", "in-room", "spa", "swimming pool", "pool access",
    "gym", "yoga", "bush dinner", "stargazing", "game drive", "safari"
]

def hash_password(password):
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_date(date_str):
    """Validate date format DD-MM-YYYY"""
    try:
        datetime.strptime(date_str, "%d-%m-%Y")
        return True
    except ValueError:
        return False

def send_media_message(msg, media_url, caption=""):
    """Helper function to send media with caption"""
    try:
        msg.message(caption).media(media_url)
    except Exception as e:
        logger.error(f"Error sending media: {e}")
        msg.message(caption)

@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    try:
        incoming_msg = request.form.get('Body', "").strip()
        user_number = request.form.get('From')
        msg = MessagingResponse()
        response = ""

        logger.info(f"Incoming message from {user_number}: {incoming_msg}")

        # Initialize session
        if user_number not in session_data:
            session_data[user_number] = {
                "stage": "welcome",
                "attempts": 0
            }

        user_session = session_data[user_number]
        stage = user_session.get("stage", "welcome")

        logger.info(f"[Stage: {stage}] Processing message for {user_number}")

        # ==================== AUTHENTICATION FLOW ====================
        
        # Stage 0: Welcome
        if stage == "welcome":
            response = (
                "🌿 *Welcome to ILORA RETREATS* 🌿\n\n"
                "Your gateway to luxury safari experiences in Kenya's Masai Mara.\n\n"
                "To get started, please provide your *email address* to continue."
            )
            user_session["stage"] = "email_input"
            msg.message(response)
            log_chat("WhatsApp", user_number, incoming_msg, response, "unauthenticated")
            return str(msg)

        # Stage 1: Email Input
        elif stage == "email_input":
            if not validate_email(incoming_msg):
                response = "❌ Invalid email format. Please provide a valid email address (e.g., user@example.com)."
                msg.message(response)
                return str(msg)
            
            user_session["email"] = incoming_msg.lower()
            
            # Check if user exists in Client_workflow sheet
            user_data = sheets_service.get_user_by_email(incoming_msg.lower())

            print()
            print(user_data)
            print()

            if user_data:
                user_session["user_data"] = user_data
                user_session["client_id"] = user_data.get("client_id")
                user_session["stage"] = "password_verify"
                response = f"✅ Email found: *{incoming_msg}*\n\nPlease enter your password to continue."
            else:
                user_session["stage"] = "password_setup"
                response = (
                    f"👋 Welcome! We don't have an account for *{incoming_msg}* yet.\n\n"
                    "Let's create one! Please set a password (minimum 6 characters):"
                )
            
            msg.message(response)
            log_chat("WhatsApp", user_number, incoming_msg, response, "authenticating")
            return str(msg)

        # Stage 2: Password Verification
        elif stage == "password_verify":
            stored_password = user_session["user_data"].get("password")
            input_hash = hash_password(incoming_msg)
            
            # Check both plain text (if stored) and hashed password
            password_match = (stored_password == incoming_msg or stored_password == input_hash)
            
            if password_match:
                user_session["authenticated"] = True
                user_session["attempts"] = 0
                
                # Check Workflow Stage column
                workflow_stage = user_session["user_data"].get("Workfow Stage", "").lower()
                booking_id = user_session["user_data"].get("booking_id", "")
                room_alloted = user_session["user_data"].get("room_alloted", "")
                
                # Determine if guest or non-guest based on workflow stage
                if workflow_stage in ["id_verified", "checked_in", "confirmed"] or booking_id or room_alloted:
                    user_session["user_type"] = "guest"
                    user_session["stage"] = "guest_chat"
                    
                    checkin = user_session["user_data"].get("checkin", "N/A")
                    checkout = user_session["user_data"].get("checkout", "N/A")
                    
                    response = (
                        f"🎉 Welcome back, *{user_session['user_data'].get('name', 'Guest')}*!\n\n"
                        f"✅ Status: *VERIFIED GUEST*\n"
                        f"🏕️ Room: {room_alloted if room_alloted else 'TBD'}\n"
                        f"📅 Check-in: {checkin}\n"
                        f"📅 Check-out: {checkout}\n"
                        f"🆔 Booking ID: {booking_id if booking_id else 'Pending'}\n\n"
                        "You have full access to all our services:\n"
                        "🛏️ Room service (24/7)\n"
                        "💆 Spa & wellness\n"
                        "🏊 Swimming pool\n"
                        "🏋️ Gym & yoga\n"
                        "🦁 Safari experiences\n"
                        "🍽️ Bush dinners & dining\n\n"
                        "How can I assist you today?"
                    )
                else:
                    user_session["user_type"] = "non-guest"
                    user_session["stage"] = "non_guest_chat"
                    response = (
                        f"✅ Welcome back, *{user_session['user_data'].get('name', 'Visitor')}*!\n\n"
                        "You're currently marked as a *VISITOR*.\n\n"
                        "You can:\n"
                        "📋 Ask general questions about ILORA RETREATS\n"
                        "🏕️ Book a luxury tent stay\n"
                        "🍽️ Learn about our dining options\n"
                        "🦁 Explore safari experiences\n\n"
                        "How can I help you today?"
                    )
            else:
                user_session["attempts"] = user_session.get("attempts", 0) + 1
                if user_session["attempts"] >= 3:
                    response = "❌ Too many failed attempts. Please restart by sending any message."
                    session_data[user_number] = {"stage": "welcome"}
                else:
                    response = f"❌ Incorrect password. Attempt {user_session['attempts']}/3. Please try again."
            
            msg.message(response)
            log_chat("WhatsApp", user_number, "***", response, user_session.get("user_type", "authenticating"))
            return str(msg)

        # Stage 3: Password Setup (New User)
        elif stage == "password_setup":
            if len(incoming_msg) < 6:
                response = "❌ Password must be at least 6 characters. Please try again."
                msg.message(response)
                return str(msg)
            
            password_hash = hash_password(incoming_msg)
            user_session["stage"] = "name_input"
            user_session["password"] = incoming_msg  # Store plain for sheet
            user_session["password_hash"] = password_hash
            response = "🔒 Password set successfully!\n\nPlease provide your *full name*:"
            
            msg.message(response)
            log_chat("WhatsApp", user_number, "***", response, "registering")
            return str(msg)

        # Stage 4: Name Input (New User)
        elif stage == "name_input":
            user_session["name"] = incoming_msg
            user_session["stage"] = "phone_input"
            response = "📱 Great! Now please provide your *phone number*:"
            
            msg.message(response)
            log_chat("WhatsApp", user_number, incoming_msg, response, "registering")
            return str(msg)

        # Stage 5: Phone Input (New User)
        elif stage == "phone_input":
            user_session["phone"] = incoming_msg
            
            # Generate new Client ID
            client_id = f"ILR{datetime.now().strftime('%Y%m%d')}{str(uuid.uuid4().hex[:6]).upper()}"
            
            # Create new user in Google Sheets
            new_user_data = {
                "Client Id": client_id,
                "Name": user_session["name"],
                "Email": user_session["email"],
                "Phone Number": incoming_msg,
                "Password": user_session["password"],  # Store as per sheet structure
                "Booking Id": "",
                "Workfow Stage": "Registered",
                "Room Alloted": "",
                "CheckIn": "",
                "Check Out": "",
                "Id Link": ""
            }
            
            success = sheets_service.create_new_user(new_user_data)
            
            if success:
                user_session["authenticated"] = True
                user_session["user_type"] = "non-guest"
                user_session["user_data"] = new_user_data
                user_session["client_id"] = client_id
                user_session["stage"] = "non_guest_chat"
                
                response = (
                    f"✅ *Registration Complete!*\n\n"
                    f"🆔 Client ID: *{client_id}*\n"
                    f"Welcome to ILORA RETREATS, *{user_session['name']}*!\n\n"
                    "You can now:\n"
                    "📋 Ask questions about our retreat\n"
                    "🏕️ Book a luxury tent\n"
                    "🍽️ Explore our dining options\n"
                    "🦁 Learn about safari experiences\n\n"
                    "How can I assist you today?"
                )
            else:
                response = "⚠️ Registration failed. Please try again later."
                session_data[user_number] = {"stage": "welcome"}
            
            msg.message(response)
            log_chat("WhatsApp", user_number, incoming_msg, response, "non-guest")
            return str(msg)

        # ==================== CHAT & BOOKING FLOW ====================
        
        # Check authentication
        if not user_session.get("authenticated", False):
            response = "⚠️ Session expired. Please restart by sending any message."
            session_data[user_number] = {"stage": "welcome"}
            msg.message(response)
            return str(msg)

        user_type = user_session.get("user_type", "non-guest")
        user_identifier = user_session.get("email")

        # Non-Guest Chat
        if stage == "non_guest_chat":
            intent = classify_intent(incoming_msg.lower())
            logger.info(f"Non-guest intent: {intent}")
            
            # Check if requesting guest-only service
            is_guest_service = any(service in incoming_msg.lower() for service in GUEST_ONLY_SERVICES)
            
            if is_guest_service and intent != "payment_request":
                response = (
                    "🔒 This service is exclusive to our guests.\n\n"
                    "Would you like to book a stay with us? Reply *book* to see available tents!"
                )
            elif intent == "payment_request" or "book" in incoming_msg.lower():
                # Show property images and available tents
                user_session["stage"] = "show_property"
                response = "🌿 Let me show you our beautiful retreat..."
            else:
                # General query - use bot
                try:
                    answer = bot.ask(incoming_msg, user_type="non-guest", user_session=user_identifier, session_key=user_identifier)
                    response = f"💬 {answer}"
                except Exception as e:
                    logger.error(f"Bot error: {e}")
                    response = "⚠️ I'm having trouble processing that. Please try again."
            
            msg.message(response)
            log_chat("WhatsApp", user_number, incoming_msg, response, "non-guest")
            return str(msg)

        # Show Property (Images)
        elif stage == "show_property":
            # Send property images
            property_images = Config.PROPERTY_IMAGES if hasattr(Config, 'PROPERTY_IMAGES') else []
            
            response = "🏕️ *ILORA RETREATS - Luxury Safari Experience*\n\n"
            
            # Send images if available
            for idx, img_url in enumerate(property_images[:6]):
                send_media_message(msg, img_url, f"📸 {['ILORA RETREATS View', 'ILORA RETREATS View', 'ILORA RETREATS View','Other Facilities','Other Facilities','Other Facilities'][idx]}")
            
            # Check availability
            available_tents = sheets_service.get_available_tents()
            
            if available_tents > 0:
                user_session["stage"] = "booking_nights"
                response = (
                    f"✨ We have *{available_tents} luxury tents* available out of {TOTAL_TENTS}!\n\n"
                    f"💰 *Rate:* ₹{ROOM_PRICES['Luxury Tent']:,}/night\n"
                    f"(Approximately USD 500-650)\n\n"
                    "✅ *Includes:*\n"
                    "🛏️ Fully equipped tent with en-suite bathroom\n"
                    "🌅 Private veranda\n"
                    "🍽️ Full-board dining (breakfast, lunch, dinner)\n"
                    "🏊 Pool, spa & gym access\n"
                    "🧘 Yoga sessions\n\n"
                    "*How many nights* would you like to stay?\n"
                    "Reply with a number (e.g., 3)"
                )
            else:
                response = (
                    "😔 We're currently fully booked!\n\n"
                    "📧 Please contact us at reservations@iloraretreat.com\n"
                    "📞 Or call us for future availability."
                )
                user_session["stage"] = "non_guest_chat"
            
            msg.message(response)
            log_chat("WhatsApp", user_number, incoming_msg, response, "non-guest")
            return str(msg)

        # Booking: Number of Nights
        elif stage == "booking_nights":
            try:
                nights = int(incoming_msg)
                if nights <= 0 or nights > 30:
                    response = "❌ Please enter a valid number between 1 and 30 nights."
                    msg.message(response)
                    return str(msg)
                
                user_session["nights"] = nights
                user_session["stage"] = "booking_checkin"
                
                total = ROOM_PRICES["Luxury Tent"] * nights
                user_session["total_amount"] = total
                
                response = (
                    f"🌙 *{nights} night(s)* - Excellent choice!\n"
                    f"💰 Estimated Total: ₹{total:,}\n\n"
                    "📅 When would you like to *check in*?\n"
                    "Please provide the date in format: *DD-MM-YYYY*\n"
                    "(e.g., 15-12-2025)"
                )
            except ValueError:
                response = "❌ Please enter a valid number of nights (e.g., 2, 3, 5)!!" + "\n" + bot.ask(incoming_msg, user_type="non-guest")
                stage = "non_guest_chat"
            
            msg.message(response)
            return str(msg)

        # Booking: Check-in Date
        elif stage == "booking_checkin":
            if not validate_date(incoming_msg):
                response = "❌ Invalid date format. Please use DD-MM-YYYY (e.g., 15-12-2025). Exiting the flow" + "\n" + bot.ask(incoming_msg, user_type="non-guest")
                stage = "non_guest_chat"
                msg.message(response)
                return str(msg)
            
            try:
                checkin_date = datetime.strptime(incoming_msg, "%d-%m-%Y")
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                
                if checkin_date < today:
                    response = "❌ Check-in date cannot be in the past. Please enter a future date."
                    msg.message(response)
                    return str(msg)
                
                # Calculate checkout date
                nights = user_session["nights"]
                checkout_date = checkin_date + timedelta(days=nights)
                
                user_session["checkin_date"] = incoming_msg
                user_session["checkout_date"] = checkout_date.strftime("%d-%m-%Y")
                user_session["stage"] = "booking_payment"
                
                total = user_session["total_amount"]
                
                response = (
                    "💳 *Payment Method*\n\n"
                    f"📋 *Booking Summary:*\n"
                    f"👤 Name: {user_session['name']}\n"
                    f"🏕️ Room: Luxury Tent\n"
                    f"📅 Check-in: {incoming_msg}\n"
                    f"📅 Check-out: {user_session['checkout_date']}\n"
                    f"🌙 Nights: {nights}\n"
                    f"💰 Total: ₹{total:,}\n\n"
                    "How would you like to pay?\n"
                    "1️⃣ Online Payment (Secure)\n"
                    "2️⃣ Pay on Arrival\n\n"
                    "Reply with *1* or *2*"
                )
            except Exception as e:
                logger.error(f"Date processing error: {e}")
                response = "❌ Error processing date. Please try again with format DD-MM-YYYY"
            
            msg.message(response)
            return str(msg)

        # Booking: Payment Method
        elif stage == "booking_payment":
            if incoming_msg not in ["1", "2"]:
                response = "❌ Please select 1 for Online Payment or 2 for Pay on Arrival." + "\n" + bot.ask(incoming_msg, user_type="non-guest")
                stage = "non_guest_chat"
                msg.message(response)
                return str(msg)
            
            payment_mode = "Online" if incoming_msg == "1" else "Cash on Arrival"
            user_session["payment_mode"] = payment_mode
            user_session["stage"] = "booking_confirm"
            
            response = (
                "✅ *Please confirm your booking:*\n\n"
                f"👤 Name: {user_session['name']}\n"
                f"📧 Email: {user_session['email']}\n"
                f"📱 Phone: {user_session['phone']}\n"
                f"🏕️ Room: Luxury Tent\n"
                f"📅 Check-in: {user_session['checkin_date']}\n"
                f"📅 Check-out: {user_session['checkout_date']}\n"
                f"🌙 Nights: {user_session['nights']}\n"
                f"💳 Payment: {payment_mode}\n"
                f"💰 Total: ₹{user_session['total_amount']:,}\n\n"
                "Reply *YES* to confirm or *NO* to cancel."
            )
            
            msg.message(response)
            return str(msg)

        # Booking: Confirmation
        elif stage == "booking_confirm":
            if incoming_msg.lower() == "yes":
                try:
                    # Generate Booking ID
                    booking_id = f"ILORA{datetime.now().strftime('%Y%m%d')}{str(uuid.uuid4().hex[:6]).upper()}"
                    
                    # Update user in Google Sheets with booking details
                    booking_data = {
                        "email": user_session["email"],
                        "booking_id": booking_id,
                        "workflow_stage": "booking_confirmed",
                        "room_alloted": "Luxury Tent",
                        "checkin": user_session["checkin_date"],
                        "checkout": user_session["checkout_date"]
                    }
                    
                    booking_success = sheets_service.update_booking(booking_data)
                    
                    if booking_success:
                        # Generate payment link if online
                        if user_session["payment_mode"] == "Online":
                            pay_url = create_checkout_session(
                                session_id=booking_id,
                                room_type="Luxury Tent",
                                nights=user_session["nights"],
                                cash=False
                            )
                            
                            if pay_url:
                                response = (
                                    "🎉 *Booking Confirmed!*\n\n"
                                    f"🆔 Booking ID: *{booking_id}*\n"
                                    f"👤 Name: {user_session['name']}\n"
                                    f"📧 Email: {user_session['email']}\n\n"
                                    "💳 *Complete your payment here:*\n"
                                    f"{pay_url}\n\n"
                                    "After payment, your status will be updated to *VERIFIED GUEST* "
                                    "and you'll have full access to all services!\n\n"
                                    "📧 A confirmation email has been sent to your inbox."
                                    f"How would you like to do the checkin?\n"  "1️⃣ Web Checkin (Secure)\n" , "2️⃣ CheckIn on Arrival\n\n"
                                    "Reply with *1* or *2*"
                                )
                                user_session["stage"] = "checkin_method"
                            else:
                                response = (
                                    "🎉 *Booking Confirmed!*\n\n"
                                    f"🆔 Booking ID: *{booking_id}*\n\n"
                                    "⚠️ Payment link generation failed.\n"
                                    "Please contact us at reservations@iloraretreat.com"
                                )
                        else:
                            response = (
                                "🎉 *Booking Confirmed!*\n\n"
                                f"🆔 Booking ID: *{booking_id}*\n"
                                f"👤 Name: {user_session['name']}\n"
                                f"📧 Email: {user_session['email']}\n"
                                f"📅 Check-in: {user_session['checkin_date']}\n"
                                f"📅 Check-out: {user_session['checkout_date']}\n"
                                f"💰 Total: ₹{user_session['total_amount']:,}\n\n"
                                "💵 Payment will be collected on arrival.\n\n"
                                "We look forward to welcoming you to ILORA RETREATS! 🌿\n\n"
                                "📧 A confirmation email has been sent."
                                f"How would you like to do the checkin?\n"  "1️⃣ Web Checkin (Secure)\n" , "2️⃣ CheckIn on Arrival\n\n"
                                "Reply with *1* or *2*"
                            )
                        
                        # Update workflow stage in sheet to id_verified after payment
                        if user_session["payment_mode"] == "Cash on Arrival":
                            sheets_service.update_workflow_stage(user_session["email"], "booked")
                            user_session["user_type"] = "guest"
                            user_session["stage"] = "guest_chat"
                        else:
                            user_session["stage"] = "non_guest_chat"
                    else:
                        response = "⚠️ Booking failed. Please try again or contact support."
                except Exception as e:
                    logger.error(f"Booking error: {e}")
                    response = "⚠️ An error occurred during booking. Please try again."
            else:
                response = "❌ Booking cancelled. How else can I help you?"
                user_session["stage"] = "non_guest_chat"
            
            msg.message(response)
            log_chat("WhatsApp", user_number, incoming_msg, response, user_session.get("user_type"))
            return str(msg)
            
        elif stage == "checkin_method":
            if incoming_msg == "1":
                checkin_url = f"https://forms.gle/RvnsymRmBoKu3Ns26"
                response = f"🔒 You have selected Web Checkin (Secure). Please follow the link to complete your checkin: {checkin_url}"
                
            elif incoming_msg == "2":
                response = "🚶 You have selected CheckIn on Arrival. Please proceed to the reception upon arrival."
            else:
                response = "❓ Invalid option. Please reply with *1* for Web Checkin or *2* for CheckIn on Arrival." + "\n" + bot.ask(incoming_msg, user_type="non-guest")

        # Guest Chat (Verified Guests)
        elif stage == "guest_chat":
            intent = classify_intent(incoming_msg.lower())
            logger.info(f"Guest intent: {intent}")
            checkin_url = "https://forms.gle/RvnsymRmBoKu3Ns26"

            # Handle add-on bookings
            if intent.startswith("book_addon"):
                matches = [key for key in ADDON_MAPPING if key in incoming_msg.lower()]
                if matches:
                    try:
                        extras = list(set(ADDON_MAPPING[m] for m in matches))
                        session_id = user_session.get("client_id", str(uuid.uuid4()))
                        pay_url = create_addon_checkout_session(session_id=session_id, extras=extras)
                        
                        if pay_url:
                            addon_names = ', '.join([e.replace('_', ' ').title() for e in extras])
                            response = (
                                f"🎯 *Add-on Booking*\n\n"
                                f"📋 Selected: {addon_names}\n"
                                f"🆔 Booking ID: {user_session.get('booking_id', 'N/A')}\n\n"
                                f"Complete payment here:\n{pay_url}"
                            )
                        else:
                            response = "⚠️ Could not generate payment link. Please contact our concierge."
                    except Exception as e:
                        logger.error(f"Add-on error: {e}")
                        response = "⚠️ Error processing add-on. Please try again or contact concierge."
                else:
                    response = (
                        "❓ Which add-on would you like to book?\n\n"
                        "Available options:\n"
                        "🧖 Spa & Massage\n"
                        "🎈 Hot Air Balloon Ride\n"
                        "🦁 Game Drive\n"
                        "🚶 Walking Safari\n"
                        "🍽️ Bush Dinner\n"
                        "⭐ Stargazing Experience\n"
                        "🎭 Maasai Cultural Experience"
                    )
            else:
                # General guest query - use bot with guest context
                try:
                    answer = bot.ask(incoming_msg, user_type="guest", user_identifier=user_identifier)
                    response = f"💬 {answer}"
                except Exception as e:
                    logger.error(f"Bot error: {e}")
                    response = "⚠️ I'm having trouble with that. Let me connect you with our concierge team."
            
            msg.message(response)
            log_chat("WhatsApp", user_number, incoming_msg, response, "guest")
            return str(msg)

        # Default fallback
        else:
            response = "⚠️ Something went wrong. Please restart by sending any message."
            session_data[user_number] = {"stage": "welcome"}
            msg.message(response)
            return str(msg)

    except Exception as e:
        logger.error(f"Unexpected error in webhook: {e}", exc_info=True)
        msg = MessagingResponse()
        msg.message("⚠️ An unexpected error occurred. Please try again or contact support.")
        return str(msg)


if __name__ == "__main__":
    app.run(debug=True, port=5002)

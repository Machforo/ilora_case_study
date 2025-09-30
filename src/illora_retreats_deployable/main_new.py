import os
import uuid
import json
import random
import logging
import asyncio
from typing import List, Optional, Dict, Any, Generator
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Query, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field, EmailStr
from config import Config

# Project imports
import web_ui_final as web
from services.intent_classifier import classify_intent
from logger import log_chat
from services.qa_agent_new import ConciergeBot
from services.payment_gateway import (
    create_checkout_session,
    create_addon_checkout_session,
    create_pending_checkout_session,
)

import requests  # For making HTTP calls to Google Sheets

# ------------------------- Helper functions -------------------------
def menu_file_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "services", "menu.json")

TICKET_SHEET_NAME = getattr(Config, "GSHEET_TICKET_SHEET", "ticket_management")
GUEST_LOG_SHEET_NAME = getattr(Config, "GSHEET_GUEST_LOG_SHEET", "guest_interaction_log")
GSHEET_WEBAPP_URL = getattr(Config, "GSHEET_WEBAPP_URL", None)

def is_ticket_request(message: str, intent: str, addon_matches: list = None) -> bool:
    """Detect if message requests a service requiring a ticket."""
    if not message:
        return False
    lower = message.lower()

    ticket_intents = {
        "book_addon_spa",
        "book_addon_beverage",
        "book_addon_food",
        "request_service",
        "room_service_request",
        "maintenance_request",
        "order_addon",
    }
    if intent in ticket_intents:
        return True

    keywords = [
        "coffee", "tea", "order", "bring", "deliver", "room service", "food", "meal", "snack",
        "towel", "clean", "housekeeping", "makeup room", "turn down", "repair", "fix", "ac", "wifi",
        "tv", "light", "broken", "leak", "toilet", "bathroom", "shower"
    ]
    if any(k in lower for k in keywords):
        return True

    if addon_matches and len(addon_matches) > 0:
        return True

    return False

def create_ticket_row_payload(message: str, email: str = None) -> Dict[str, str]:
    """Create a ticket row for the sheet."""
    room_no = "Not Assigned"
    if email and GSHEET_WEBAPP_URL:
        try:
            payload = {
                "action": "getUserData",
                "sheet": "Client_workflow",
                "username": email
            }
            resp = requests.post(GSHEET_WEBAPP_URL, json=payload, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("found") and data.get("userData"):
                user_data = data.get("userData", {})
                room_alloted = user_data.get("Room Alloted")
                if room_alloted and room_alloted not in ["-", "", "None", "not assigned"]:
                    room_no = room_alloted

        except Exception as e:
            logger.warning(f"Failed to get room number for {email}: {e}")
    
    ticket_id = f"TCK-{random.randint(1000, 99999)}"
    guest_name = email or "Guest"
    category = classify_ticket_category(message)
    assigned_to = assign_staff_for_category(category)
    status = "In Progress"
    created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "Ticket ID": ticket_id,
        "Guest Name": guest_name,
        "Room No": room_no,
        "Request/Query": message,
        "Category": category,
        "Assigned To": assigned_to,
        "Status": status,
        "Created At": created_at,
        "Resolved At": "",
        "Notes": message
    }

def classify_ticket_category(message: str) -> str:
    """Map message to ticket category."""
    m = message.lower()
    if any(w in m for w in ["coffee", "tea", "drink", "food", "meal", "snack", "beverage", "breakfast", "lunch", "dinner"]):
        return "Food"
    if any(w in m for w in ["towel", "clean", "housekeeping", "room service", "bed", "makeup", "turn down", "linen"]):
        return "Room Service"
    if any(w in m for w in ["ac", "wifi", "tv", "light", "repair", "engineer", "fix", "leak", "broken", "toilet", "plumb", "electr"]):
        return "Engineering"
    return "General"

def assign_staff_for_category(category: str) -> str:
    """Assign staff based on ticket category."""
    return {
        "Food": "Food Staff",
        "Room Service": "Room Service",
        "Engineering": "Engineering",
        "General": "Front Desk"
    }.get(category, "Front Desk")

def create_guest_log_row(req_session_id: Optional[str], email: Optional[str], user_input: str, bot_response: str,
                       intent: str, is_guest_flag: bool, ref_ticket_id: Optional[str] = None) -> Dict[str, Any]:
    """Create a guest interaction log row."""
    log_id = f"LOG-{random.randint(1000,999999)}"
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "Log ID": log_id,
        "Timestamp": timestamp,
        "Source": "web",
        "Session ID": req_session_id or "",
        "Guest Email": email or "",
        "Guest Name": "Guest",
        "User Input": user_input or "",
        "Bot Response": bot_response or "",
        "Intent": intent or "",
        "Guest Type": "guest" if bool(is_guest_flag) else "non-guest",
        "Sentiment": _naive_sentiment(user_input),
        "Reference Ticket ID": ref_ticket_id or "",
        "Conversation URL": "",
    }

def _naive_sentiment(message: str) -> str:
    """Simple sentiment analysis."""
    if not message:
        return ""
    m = message.lower()
    negative_words = ["not", "no", "never", "bad", "disappointed", "angry", "hate", "worst", "problem", "issue", "delay"]
    positive_words = ["good", "great", "awesome", "excellent", "happy", "love", "enjoy"]
    if any(w in m for w in negative_words) and not any(w in m for w in positive_words):
        return "negative"
    if any(w in m for w in positive_words) and not any(w in m for w in negative_words):
        return "positive"
    return ""

def push_row_to_sheet(sheet_name: str, row_data: Dict[str, Any]) -> Dict[str, Any]:
    """Push a row to Google Sheet."""
    if not GSHEET_WEBAPP_URL:
        raise RuntimeError("GSHEET_WEBAPP_URL not configured")
    
    payload = {"action": "addRow", "sheet": sheet_name, "rowData": row_data}
    try:
        resp = requests.post(GSHEET_WEBAPP_URL, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Error pushing to sheet: {e}")
        return {"success": False, "message": str(e)}

def push_ticket_to_sheet(sheet_name: str, ticket_data: Dict[str, str]) -> Dict:
    """Push a ticket to the sheet."""
    if not GSHEET_WEBAPP_URL:
        raise RuntimeError("GSHEET_WEBAPP_URL not configured")

    payload = {"action": "addRow", "sheet": sheet_name, "rowData": ticket_data}
    try:
        resp = requests.post(GSHEET_WEBAPP_URL, json=payload, timeout=10)
        return resp.json()
    except Exception:
        resp.raise_for_status()
        return {"ok": True, "status_code": resp.status_code}

# ------------------------- Logging -------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_chieftain")

# ------------------------- FastAPI app -------------------------
app = FastAPI(title="AI Chieftain API", version="1.0.0")

# ------------------------- CORS -------------------------
FRONTEND_ORIGINS = [
    "http://localhost:8080",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ------------------------- Static files -------------------------
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ------------------------- Concierge bot -------------------------
bot = ConciergeBot()

# ------------------------- SSE Broker -------------------------
class EventBroker:
    def __init__(self):
        self.connections: List[asyncio.Queue] = []

    async def connect(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.connections.append(q)
        return q

    async def disconnect(self, q: asyncio.Queue):
        if q in self.connections:
            try:
                self.connections.remove(q)
            except Exception:
                pass

    async def broadcast(self, event: str, data: Dict[str, Any]):
        msg = json.dumps({"event": event, "data": data}, default=str)
        for q in list(self.connections):
            try:
                await q.put(msg)
            except Exception:
                try:
                    self.connections.remove(q)
                except Exception:
                    pass

broker = EventBroker()

async def safe_broadcast(event: str, data: Dict[str, Any], error_msg: str = "broadcast failed"):
    """Safely broadcast an event with error handling"""
    try:
        await broker.broadcast(event, data)
    except Exception as e:
        logger.warning(f"{error_msg}: {e}")

@app.get("/events")
async def sse_events(request: Request):
    async def event_generator(q: asyncio.Queue):
        try:
            await q.put(json.dumps({"event": "connected", "data": {}}))
            while True:
                if await request.is_disconnected():
                    break
                msg = await q.get()
                yield f"data: {msg}\n\n"
        finally:
            await broker.disconnect(q)

    q = await broker.connect()
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(event_generator(q), headers=headers, media_type="text/event-stream")

# ------------------------- Models -------------------------
# Auth models
class LoginReq(BaseModel):
    email: str
    password: str
    remember: bool = True

class LoginResp(BaseModel):
    success: bool
    message: str
    token: Optional[str] = None
    user: Optional[Dict[str, Any]] = None

# Auth endpoint response model
class AuthResp(BaseModel):
    success: bool
    message: str
    user: Optional[Dict[str, Any]] = None

@app.get("/auth/me", response_model=AuthResp)
async def get_current_user(token: str = Query(...)):
    """Get the current authenticated user based on their token."""
    try:
        if not token.startswith("session_"):
            return AuthResp(success=False, message="Invalid token format")

        if not GSHEET_WEBAPP_URL:
            raise HTTPException(status_code=500, detail="Sheet API not configured")
        
        # Extract email from token if stored in sheet, or return error
        payload = {
            "action": "getCurrentUser",
            "sheet": "Client_workflow",
            "token": token
        }

        resp = requests.post(GSHEET_WEBAPP_URL, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            return AuthResp(success=False, message="Session expired or invalid")

        user_data = data.get("userData", {})
        if not user_data:
            return AuthResp(success=False, message="User not found")

        return AuthResp(
            success=True,
            message="User retrieved successfully",
            user={
                "email": user_data.get("Email"),
                "name": user_data.get("Name", "Guest"),
                "role": user_data.get("Role", "guest"),
                "room": user_data.get("Room Alloted"),
                "booked": bool(user_data.get("Booking Id")),
                "id_verified": bool(user_data.get("Id Link"))
            }
        )

    except requests.RequestException as e:
        logger.error(f"Failed to verify user session: {e}")
        raise HTTPException(status_code=500, detail="Authentication service unavailable")

@app.post("/auth/login", response_model=LoginResp)
async def login(req: LoginReq):
    try:
        if not GSHEET_WEBAPP_URL:
            raise HTTPException(status_code=500, detail="Sheet API not configured")

        payload = {
            "action": "verifyUser",
            "sheet": "Client_workflow",  # Using the same sheet name
            "email": req.email,
            "password": req.password
        }

        # Call Google Sheets to verify user
        resp = requests.post(GSHEET_WEBAPP_URL, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            return LoginResp(success=False, message="Invalid credentials")

        # Generate a session token
        token = f"session_{uuid.uuid4().hex}"
        user_data = data.get("userData", {})

        # Return success with user data
        return LoginResp(
            success=True,
            message="Login successful",
            token=token,
            user={
                "email": req.email,
                "name": user_data.get("Name", "Guest"),
                "role": user_data.get("Role", "guest"),
                "room": user_data.get("Room Alloted"),
                "booked": bool(user_data.get("Booking Id")),
                "id_verified": bool(user_data.get("Id Link"))
            }
        )

    except requests.RequestException as e:
        logger.error(f"Failed to verify login with sheets: {e}")
        raise HTTPException(status_code=500, detail="Authentication service unavailable")

# Chat models
class ChatReq(BaseModel):
    message: str
    is_guest: Optional[bool] = False
    session_id: Optional[str] = None
    email: Optional[str] = None

class ChatActions(BaseModel):
    show_booking_form: bool = False
    addons: List[str] = Field(default_factory=list)
    payment_link: Optional[str] = None
    pending_balance: Optional[Dict[str, Any]] = None

class ChatResp(BaseModel):
    reply: str
    reply_parts: Optional[List[str]] = None
    intent: Optional[str] = None
    actions: ChatActions = Field(default_factory=ChatActions)

@app.post("/chat", response_model=ChatResp)
async def chat(req: ChatReq):
    user_input = req.message or ""
    is_guest = bool(req.is_guest)
    bot_reply_text = bot.ask(user_input, user_type=is_guest)
    intent = classify_intent(user_input)
    actions = ChatActions()

    # Load menu data
    MENU_FILE = menu_file_path()
    try:
        with open(MENU_FILE, "r", encoding="utf-8") as f:
            MENU = json.load(f)
    except FileNotFoundError:
        MENU = {}

    # Process menu items
    AVAILABLE_EXTRAS = {}
    EXTRAS_PRICE_BY_KEY = {}
    for category, items in MENU.items():
        if category == "complimentary":
            continue
        for display_name, _price in items.items():
            label = display_name.replace("_", " ").title()
            key = display_name.lower().replace(" ", "_")
            AVAILABLE_EXTRAS[label] = key
            EXTRAS_PRICE_BY_KEY[key] = _price

    message_lower = user_input.lower()
    addon_matches = [k for k in AVAILABLE_EXTRAS if k.lower() in message_lower]

    # Handle ticket creation
    created_ticket_id: Optional[str] = None
    try:
        if is_ticket_request(user_input, intent, addon_matches):
            ticket_row = create_ticket_row_payload(user_input, req.email)
            try:
                resp_json = push_ticket_to_sheet(TICKET_SHEET_NAME, ticket_row)
                created_ticket_id = ticket_row.get("Ticket ID")
                logger.info("Ticket created: %s (sheet resp: %s)", created_ticket_id, resp_json)
                
                # Broadcast ticket creation
                await safe_broadcast("ticket_created", {
                    "ticket_id": created_ticket_id,
                    "guest_email": req.email,
                    "room_no": ticket_row.get("Room No"),
                    "category": ticket_row.get("Category"),
                    "assigned_to": ticket_row.get("Assigned To"),
                    "status": ticket_row.get("Status"),
                    "created_at": ticket_row.get("Created At"),
                    "notes": ticket_row.get("Notes"),
                }, "Failed to broadcast ticket creation")
                
            except Exception as e:
                logger.warning("Failed to push ticket to sheet: %s", e)
    except Exception as e:
        logger.warning("Ticket subsystem error: %s", e)

    # Handle booking form
    booking_keywords = ["book a room", "book room", "book", "reserve", "reservation", "room availability"]
    if any(kw in message_lower for kw in booking_keywords):
        actions.show_booking_form = True

    # Handle addon checkout
    if intent in ('book_addon_spa', 'book_addon_beverage', 'book_addon_food'):
        actions.addons = addon_matches
        try:
            checkout_url = create_addon_checkout_session(
                session_id=req.session_id or str(uuid.uuid4()),
                extras=[AVAILABLE_EXTRAS[k] for k in addon_matches]
            )
            actions.payment_link = checkout_url
        except Exception as e:
            logger.warning("create_addon_checkout_session failed: %s", e)
            actions.payment_link = None

    # Log chat
    log_chat("web", req.session_id or "", user_input, bot_reply_text, intent, is_guest)

    # Log guest interaction
    try:
        log_row = create_guest_log_row(req.session_id, req.email, user_input, bot_reply_text, intent, is_guest, created_ticket_id)
        try:
            resp_log = push_row_to_sheet(GUEST_LOG_SHEET_NAME, log_row)
            logger.info("Guest interaction logged to sheet (Log ID=%s): %s", log_row.get("Log ID"), resp_log)
            
            # Broadcast guest log
            await safe_broadcast("guest_log_created", {
                "log_id": log_row.get("Log ID"),
                "session_id": log_row.get("Session ID"),
                "guest_email": log_row.get("Guest Email"),
                "intent": intent,
                "ticket_ref": created_ticket_id,
                "timestamp": log_row.get("Timestamp")
            }, "Failed to broadcast guest log")
            
        except Exception as e:
            logger.warning("Failed to push guest log to sheet: %s", e)
    except Exception as e:
        logger.warning("Guest log subsystem error: %s", e)

    # Broadcast chat message
    await safe_broadcast("chat_message", {
        "session_id": req.session_id,
        "email": req.email,
        "user": user_input,
        "assistant": bot_reply_text,
        "intent": intent
    }, "Failed to broadcast chat message")

    reply_parts = bot_reply_text.split("\n\n")
    return ChatResp(reply=bot_reply_text, reply_parts=reply_parts, intent=intent, actions=actions)

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting AI Concierge API server...")
    uvicorn.run("main_new:app", host="0.0.0.0", port=8000, reload=True)  # Use import string for reload
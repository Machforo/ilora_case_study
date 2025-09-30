# main_final.py
## importing essential libraries

import os
import uuid
import json
import random
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
import httpx
import requests
import re
from fastapi import FastAPI, HTTPException, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import Config

# Project imports (kept)
import web_ui_final as web
from services.intent_classifier import classify_intent
from logger import log_chat
from services.qa_agent import ConciergeBot
from services.payment_gateway import (
    create_checkout_session,
    create_addon_checkout_session,
    create_pending_checkout_session,
)

# Illora checkin app / models
from illora.checkin_app.models import Room, Booking, BookingStatus
from illora.checkin_app.pricing import calculate_price_for_room as calculate_price
from illora.checkin_app.database import Base, engine, SessionLocal
from illora.checkin_app.booking_flow import create_booking_record
from illora.checkin_app.chat_models import ChatMessage

from sqlalchemy import func
from sqlalchemy.orm import Session

#########################################################################

# ------------------------- Logging setup -------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------- FastAPI app -------------------------
app = FastAPI(title="AI Chieftain API", version="1.0.0")

# ------------------------- Constants -------------------------
CLIENT_WORKFLOW_SHEET = "Client_workflow"

# ------------------------- CORS -------------------------
FRONTEND_ORIGINS = [
    "http://localhost:8080",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://ai-chieftain.webisdomtech.com"
]

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

# In-memory user session store
USER_SESSIONS: Dict[str, Dict[str, Any]] = {}


###########################################################################
# ------------------------- Models -------------------------
class SignupReq(BaseModel):
    name: str = Field(..., min_length=2)
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)
    phoneNo: str = Field(default="")

class LoginReq(BaseModel):
    username: str = Field(..., description="User's username/email")
    password: str = Field(..., description="User's password")
    remember: bool = Field(default=True)

class UpdateWorkflowReq(BaseModel):
    username: str
    stage: str
    booking_id: Optional[str] = None
    id_proof_link: Optional[str] = None

class MeReq(BaseModel):
    username: Optional[str] = None
    remember_token: Optional[str] = None

###########################################################################
# ------------------------- Helpers / debug utils -------------------------
def _normalize_key(k: Any) -> str:
    return "".join(ch.lower() for ch in str(k) if ch.isalnum())

def _parse_float(val: Any) -> float:
    if val is None or str(val).strip() == "":
        return 0.0
    try:
        s = str(val).strip().replace("$", "").replace(",", "")
        return float(s)
    except Exception:
        return 0.0

def _short(s: str, n: int = 400) -> str:
    if s is None:
        return ""
    s = str(s)
    return s if len(s) <= n else s[:n] + " ...[truncated]"

def get_first_value(d: Dict[str, Any], candidates: List[str], default: Any = "") -> Any:
    if not d:
        return default
    for k in candidates:
        if k in d and d[k] not in (None, ""):
            return d[k]
    lowered = {str(k).lower(): v for k, v in d.items() if v not in (None, "")}
    for k in candidates:
        if k.lower() in lowered:
            return lowered[k.lower()]
    return default

def map_sheet_row_to_user_details(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map exact columns to the frontend-friendly object used by HotelSidebar."""
    if not row:
        return {}
    # Keep exact keys as in sheet when useful
    uid = row.get("Client Id", "") or row.get("ClientId", "") or row.get("client_id", "")
    booking_status = row.get("Workfow Stage", "") or row.get("Workflow Stage", "") or row.get("Booking Status", "") or "Not Booked"
    # id proof may be a status or a link
    id_proof = row.get("Id Link", "") or row.get("IdLink", "") or row.get("ID Proof", "") or ""
    pending_balance = _parse_float(row.get("Pending Balance", 0) or row.get("Balance", 0) or 0)
    status = row.get("Status", "") or booking_status or "Still"
    room_number = row.get("Room Alloted", "") or row.get("Room Number", "") or ""
    check_in = row.get("CheckIn", "") or row.get("Check In", "")
    check_out = row.get("Check Out", "") or row.get("CheckOut", "")

    return {
        "uid": uid,
        "bookingStatus": booking_status,
        "bookingId": row.get("Booking Id", "") or row.get("BookingId", "") or "",
        "idProof": id_proof,
        "pendingBalance": pending_balance,
        "status": status,
        "roomNumber": room_number,
        "checkIn": check_in,
        "checkOut": check_out,
        "_raw_row": {k: (v if _normalize_key(k) != "password" else "****") for k, v in (row or {}).items()}
    }

def normalize_raw_user_data(raw_user_data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalized snake_case mapping (useful for other endpoints)."""
    return {
        "client_id": raw_user_data.get("Client Id", "") or raw_user_data.get("ClientId", ""),
        "name": raw_user_data.get("Name", "") or raw_user_data.get("Full Name", ""),
        "email": raw_user_data.get("Email", ""),
        "booking_id": raw_user_data.get("Booking Id", ""),
        "workflow_stage": raw_user_data.get("Workfow Stage", "") or raw_user_data.get("Workflow Stage", ""),
        "room_alloted": raw_user_data.get("Room Alloted", ""),
        "check_in": raw_user_data.get("CheckIn", "") or raw_user_data.get("Check In", ""),
        "check_out": raw_user_data.get("Check Out", "") or raw_user_data.get("CheckOut", ""),
        "id_link": raw_user_data.get("Id Link", ""),
        "pending_balance": _parse_float(raw_user_data.get("Pending Balance", 0)),
        "status": raw_user_data.get("Status", "") or raw_user_data.get("Workfow Stage", "")
    }

def _update_session_from_raw(username: str, raw_user_data: Dict[str, Any], remember_token: Optional[str] = None):
    normalized = normalize_raw_user_data(raw_user_data)
    frontend_view = map_sheet_row_to_user_details(raw_user_data)
    USER_SESSIONS[username] = {
        "normalized": normalized,
        "raw": raw_user_data,
        "frontend": frontend_view,
        "last_login": datetime.utcnow().isoformat() + "Z",
        "remember_token": remember_token or USER_SESSIONS.get(username, {}).get("remember_token"),
    }
    logger.debug("Session for %s updated/saved (sanitized): %s", username, json.dumps({
        "normalized": normalized,
        "frontend": frontend_view,
        "last_login": USER_SESSIONS[username]["last_login"],
        "remember_token": USER_SESSIONS[username]["remember_token"]
    }, default=str))

###########################################################################
# ------------------------- Sheets helpers (with debug) -------------------------
def push_row_to_sheet(sheet_name: str, row_data: Dict[str, Any]) -> Dict[str, Any]:
    if not Config.GSHEET_WEBAPP_URL:
        raise RuntimeError("GSHEET_WEBAPP_URL not configured in Config")

    safe_preview = {k: (v if _normalize_key(k) != "password" else "****") for k, v in row_data.items() if k in ("Client Id", "Email", "Name", "Password")}
    logger.debug("push_row_to_sheet: payload preview: %s", safe_preview)
    payload = {"action": "addRow", "sheet": sheet_name, "rowData": row_data}
    try:
        resp = requests.post(Config.GSHEET_WEBAPP_URL, json=payload, timeout=15, allow_redirects=True)
        logger.debug("push_row_to_sheet: response url=%s status=%s", getattr(resp, "url", None), resp.status_code)
        text = _short(resp.text, 1000)
        logger.debug("push_row_to_sheet: response text (truncated) = %s", text)
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            return {"success": resp.ok, "status_code": resp.status_code, "text": text}
    except Exception as e:
        logger.exception("push_row_to_sheet: exception while calling sheet")
        return {"success": False, "message": str(e)}

def fetch_client_row_from_sheet_by_email(email: str) -> Optional[Dict[str, Any]]:
    if not Config.GSHEET_WEBAPP_URL:
        logger.error("GSHEET_WEBAPP_URL not configured")
        return None

    try:
        params = {"action": "getSheetData", "sheet": CLIENT_WORKFLOW_SHEET}
        logger.debug("fetch_client_row_from_sheet_by_email: calling GET %s params=%s", Config.GSHEET_WEBAPP_URL, params)
        resp = requests.get(Config.GSHEET_WEBAPP_URL, params=params, timeout=15, allow_redirects=True)
        logger.debug("fetch_client_row_from_sheet_by_email: response status=%s url=%s", resp.status_code, getattr(resp, "url", None))
        try:
            rows = resp.json()
        except ValueError:
            logger.error("fetch_client_row_from_sheet_by_email: getSheetData returned non-JSON: %s", _short(resp.text, 800))
            return None

        if not isinstance(rows, list):
            logger.error("fetch_client_row_from_sheet_by_email: unexpected sheet response type=%s", type(rows))
            return None

        target = (email or "").strip().lower()
        for idx, row in enumerate(rows):
            for key, val in (row or {}).items():
                if _normalize_key(key) in ("email", "username"):
                    if str(val or "").strip().lower() == target:
                        logger.debug("fetch_client_row_from_sheet_by_email: found matching row index=%s, row=%s", idx, {k: (v if _normalize_key(k) != "password" else "****") for k, v in row.items()})
                        return row
        logger.debug("fetch_client_row_from_sheet_by_email: no match for %s", target)
        return None
    except Exception as e:
        logger.exception("Error fetching sheet for email lookup")
        return None

###########################################################################
# ------------------------- Endpoints (login/signup/update + debug) -------------------------

@app.post("/auth/login", tags=["authentication"])
async def login(req: LoginReq = Body(...)):
    logger.info("Login attempt for username=%s (remember=%s)", req.username, req.remember)
    payload = {
        "action": "verifyUser",
        "sheet": CLIENT_WORKFLOW_SHEET,
        "username": req.username,
        "password": req.password,
    }
    logger.debug("Login payload (not showing password): %s", {"action": payload["action"], "sheet": payload["sheet"], "username": payload["username"]})

    try:
        # follow redirects to handle Apps Script 302 -> googleusercontent
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.post(Config.GSHEET_WEBAPP_URL, json=payload)
            logger.debug("httpx POST to GSHEET_WEBAPP_URL returned status=%s final_url=%s", resp.status_code, resp.url)
            resp_text = _short(resp.text, 1000)
            logger.debug("httpx response text (truncated) = %s", resp_text)

            try:
                data = resp.json()
            except ValueError:
                logger.error("Login: upstream returned non-JSON. resp_text=%s", resp_text)
                # fallback: attempt a full-sheet search
                data = {}

        logger.debug("Login: parsed data keys = %s", list(data.keys()) if isinstance(data, dict) else type(data))

        # If Apps Script returned structured response, use it. Otherwise fallback to full sheet lookup.
        raw_user_data = data.get("userData") if isinstance(data, dict) else None
        if not raw_user_data:
            logger.info("Login: apps-script did not return userData - trying fallback GET sheet by email for %s", req.username)
            fallback_row = fetch_client_row_from_sheet_by_email(req.username)
            if fallback_row:
                raw_user_data = fallback_row
                logger.debug("Login: fallback found row: %s", {k: (v if _normalize_key(k) != "password" else "****") for k, v in raw_user_data.items()})
            else:
                # If the Apps Script returned "found" or "verified" flags, prefer them. Otherwise fail.
                if isinstance(data, dict) and (data.get("found") or data.get("verified")):
                    # still allow empty userData if found/verified flags are set (rare)
                    raw_user_data = data.get("userData", {}) or {}
                else:
                    logger.warning("Login: no userData and fallback not found - denying login for %s", req.username)
                    raise HTTPException(status_code=401, detail="Invalid credentials or user not found")

        # If Apps Script returned an error, stop
        if isinstance(data, dict) and "error" in data:
            logger.warning("Login: apps-script error=%s", data.get("error"))
            raise HTTPException(status_code=401, detail=data["error"])

        # Map exactly according to your sheet columns and create a frontend-ready view
        frontend_view = map_sheet_row_to_user_details(raw_user_data)
        normalized = normalize_raw_user_data(raw_user_data)
        token = uuid.uuid4().hex if req.remember else None

        # persist into session store
        _update_session_from_raw(req.username, raw_user_data, remember_token=token)

        logger.info("Login success for %s; frontend_view.bookingStatus=%s roomNumber=%s", req.username, frontend_view.get("bookingStatus"), frontend_view.get("roomNumber"))
        logger.debug("Login final frontend_view (sanitized): %s", json.dumps(frontend_view, default=str))
        logger.debug("Login normalized (sanitized): %s", json.dumps(normalized, default=str))

        return {
            "username": req.username,
            "remember_token": token,
            "userData": {
                "raw": USER_SESSIONS[req.username]["raw"],
                "normalized": USER_SESSIONS[req.username]["normalized"],
                "frontend": USER_SESSIONS[req.username]["frontend"],
            }
        }

    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        logger.error("Upstream HTTPStatusError: %s", str(e))
        raise HTTPException(status_code=502, detail="Upstream service error")
    except Exception as e:
        logger.exception("Login: unexpected exception")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/auth/signup", tags=["authentication"])
async def signup(req: SignupReq = Body(...)):
    logger.info("Signup attempt username=%s", req.username)
    client_id = f"ILR-{datetime.utcnow().year}-{random.randint(1000,9999)}"
    workflow_stage = "Not Booked"
    row_data = {
        "Client Id": client_id,
        "Name": req.name,
        "Email": req.username,
        "Password": req.password,
        "Booking Id": "",
        "Workfow Stage": workflow_stage,
        "Room Alloted": "",
        "CheckIn": "",
        "Check Out": "",
        "Id Link": "",
    }
    resp = push_row_to_sheet(CLIENT_WORKFLOW_SHEET, row_data)
    logger.debug("signup: push_row_to_sheet returned: %s", resp)
    if resp.get("success") or resp.get("ok") or resp.get("status_code") == 200:
        return {"success": True, "workflowStage": workflow_stage, "clientId": client_id, "message": "Registration successful"}
    else:
        error_msg = resp.get("message", resp.get("error", "Unknown error"))
        logger.error("signup failed: %s", error_msg)
        raise HTTPException(status_code=400, detail=error_msg)


@app.post("/auth/update-workflow", tags=["authentication"])
async def update_workflow(req: UpdateWorkflowReq = Body(...)):
    logger.info("update_workflow: username=%s -> stage=%s", req.username, req.stage)
    update_data = {
        "action": "updateUserWorkflow",
        "sheet": CLIENT_WORKFLOW_SHEET,
        "email": req.username,
        "updates": {
            "Workflow Stage": req.stage
        }
    }
    if req.booking_id:
        update_data["updates"]["Booking Id"] = req.booking_id
    if req.id_proof_link:
        update_data["updates"]["Id Link"] = req.id_proof_link

    logger.debug("update_workflow: payload=%s", update_data)
    try:
        resp = requests.post(Config.GSHEET_WEBAPP_URL, json=update_data, timeout=15, allow_redirects=True)
        logger.debug("update_workflow: response status=%s url=%s", resp.status_code, getattr(resp, "url", None))
        try:
            data = resp.json()
        except ValueError:
            logger.error("update_workflow: non-JSON response: %s", _short(resp.text))
            raise HTTPException(status_code=502, detail="Invalid response from upstream service")

        logger.debug("update_workflow: parsed response: %s", data)
        if "error" in data:
            raise HTTPException(status_code=400, detail=data["error"])

        returned_user_data = data.get("userData")
        if returned_user_data:
            logger.info("update_workflow: apps-script returned userData - updating session for %s", req.username)
            _update_session_from_raw(req.username, returned_user_data)

        return {"success": True, "message": f"Workflow stage updated to {req.stage}", "userData": returned_user_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("update_workflow: unexpected")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/auth/session/{username}", tags=["authentication"])
def get_session(username: str):
    logger.debug("get_session called for %s", username)
    session = USER_SESSIONS.get(username)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    # return a sanitized session for frontend
    return {"username": username, "session": {"normalized": session["normalized"], "frontend": session["frontend"], "last_login": session["last_login"]}}


@app.post("/auth/logout", tags=["authentication"])
def logout(username: str = Body(..., embed=True)):
    logger.info("logout called for %s", username)
    if username in USER_SESSIONS:
        del USER_SESSIONS[username]
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Session not found")


@app.post("/auth/me", tags=["authentication"])
def me_post(body: MeReq = Body(...)):
    logger.debug("me_post called with body=%s", body.dict())
    if body.remember_token:
        for uname, sess in USER_SESSIONS.items():
            if sess.get("remember_token") == body.remember_token:
                logger.debug("me_post: found session by token for %s", uname)
                return {"username": uname, "session": sess}
        raise HTTPException(status_code=404, detail="Session not found for provided token")
    if body.username:
        sess = USER_SESSIONS.get(body.username)
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"username": body.username, "session": sess}
    raise HTTPException(status_code=400, detail="Provide either username or remember_token")

@app.get("/auth/me", tags=["authentication"])
def get_current_user(request: Any):
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    print()
    print(USER_SESSIONS)
    print()

    # Find the user from sessions
    for username, sess in USER_SESSIONS.items():
        if sess.get("session_token") == session_token:
            return {
                "username": username,
                "frontend": sess.get("frontend", {}),
                "normalized": sess.get("normalized", {}),
                "last_login": sess.get("last_login"),
            }

    raise HTTPException(status_code=404, detail="User not found")


# ------------------------- New endpoint: return all sessions (sanitized) -------------------------
@app.get("/auth/sessions", tags=["authentication"])
def get_all_sessions():
    """
    Return all active user sessions in-memory.
    Raw rows are returned but any 'password' key is masked.
    Useful for frontend admin display or session debugging.
    """
    print()
    print(USER_SESSIONS)
    print()

    logger.debug("get_all_sessions called - returning %d sessions", len(USER_SESSIONS))
    safe_sessions: Dict[str, Dict[str, Any]] = {}
    for username, s in USER_SESSIONS.items():
        raw_s = s.get("raw", {}) or {}
        # mask any password-like keys
        raw_s_sanitized = {k: ("****" if _normalize_key(k) == "password" else v) for k, v in raw_s.items()}
        safe_sessions[username] = {
            "raw": raw_s_sanitized,
            "normalized": s.get("normalized", {}),
            "frontend": s.get("frontend", {}),
            "last_login": s.get("last_login"),
            "remember_token": s.get("remember_token"),
        }
    return {"sessions": safe_sessions}


###########################################################################

logger.info("Initial USER_SESSIONS snapshot (sanitized): %s", {k: {"last_login": v.get("last_login"), "client_id": v.get("normalized", {}).get("client_id")} for k, v in USER_SESSIONS.items()})

################### Now Lets Move to the main part (responses) #####################


DEMO_ROOM_TYPES = ["Luxury Tent"]
sample_bookings: List[Dict[str, Any]] = []

TICKET_SHEET_NAME = getattr(Config, "GSHEET_TICKET_SHEET", "ticket_management")
GSHEET_WEBAPP_URL = getattr(Config, "GSHEET_WEBAPP_URL", "https://script.google.com/macros/s/AKfycbwfh2HvU5E0Y0Ruv5Ylfwdh524c0PWLCU0NduferN4etm08ovIMO6WoFoJVszmQx__O/exec")
GUEST_LOG_SHEET_NAME = getattr(Config, "GSHEET_GUEST_LOG_SHEET", "guest_interaction_log")
MENU_SHEET_NAME = getattr(Config, "GSHEET_MENU_SHEET", "menu_manager")
menu_rows: List[Dict[str, Any]] = []

# ------------- Generic helper to push a row to any sheet via your Apps Script Web App -------------
def push_row_to_sheet(sheet_name: str, row_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call Apps Script webapp with: { action: 'addRow', sheet: sheet_name, rowData: {...} }.
    Returns parsed JSON from webapp or raises on error.
    """
    if not GSHEET_WEBAPP_URL:
        raise RuntimeError("GSHEET_WEBAPP_URL not configured in Config")

    payload = {"action": "addRow", "sheet": sheet_name, "rowData": row_data}
    resp = requests.post(GSHEET_WEBAPP_URL, json=payload, timeout=10)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code, "text": resp.text}

# ------------- Guest interaction logging helper -------------
def _naive_sentiment(message: str) -> str:
    """Very small sentiment heuristic (optional). Returns 'positive' / 'negative' / ''."""
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

def create_guest_log_row(req_session_id: Optional[str], email: Optional[str], user_input: str, bot_response: str,
                         intent: str, is_guest_flag: bool, ref_ticket_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Build a row matching headers:
    Log ID | Timestamp | Source | Session ID | Guest Email | Guest Name | User Input | Bot Response | Intent | Guest Type | Sentiment | Reference Ticket ID | Conversation URL
    """
    log_id = f"LOG-{random.randint(1000,999999)}"
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    source = "web"
    session_id = req_session_id or ""
    guest_email = email or ""
    guest_name = "Guest"
    user_input_val = user_input or ""
    bot_response_val = bot_response or ""
    intent_val = intent or ""
    guest_type = "guest" if bool(is_guest_flag) else "non-guest"
    sentiment = _naive_sentiment(user_input)
    reference_ticket_id = ref_ticket_id or ""
    conversation_url = ""  # optional — left blank or build if you have a UI link

    return {
        "Log ID": log_id,
        "Timestamp": timestamp,
        "Source": source,
        "Session ID": session_id,
        "Guest Email": guest_email,
        "Guest Name": guest_name,
        "User Input": user_input_val,
        "Bot Response": bot_response_val,
        "Intent": intent_val,
        "Guest Type": guest_type,
        "Sentiment": sentiment,
        "Reference Ticket ID": reference_ticket_id,
        "Conversation URL": conversation_url,
    }

def is_ticket_request(message: str, intent: str, addon_matches: list = None) -> bool:
    """
    Return True when message likely requests a service/add-on that should create a ticket.
    Combines intent signals + simple keyword scanning + menu addon hints.
    """
    if not message:
        return False
    lower = message.lower()

    # Strong intents from your classifier that clearly map to service requests
    ticket_intents = {
        "book_addon_spa",
        "book_addon_beverage",
        "book_addon_food",
        "request_service",
        "room_service_request",
        "maintenance_request",
        "order_addon",
        "wake-up-call",
        "urgent_assistance",
        # (add other classifier intent names you use)
    }
    if intent in ticket_intents:
        return True

    # Keyword-based fallback (covers "order a coffee", "please bring towel", "fix ac", etc.)
    keywords = [
        "coffee", "tea", "order", "bring", "deliver", "room service", "food", "meal", "snack",
        "towel", "clean", "housekeeping", "makeup room", "turn down", "repair", "fix", "ac", "wifi",
        "tv", "light", "broken", "leak", "toilet", "bathroom", "shower", "wake-up-call","pickup and drop","laundry","taxi","transportation", "request", "need", "help", "assist", "urgent"
    ]
    if any(k in lower for k in keywords):
        return True

    # If we already matched menu addons (e.g., "club sandwich" matched), that's also a ticket trigger
    if addon_matches and len(addon_matches) > 0:
        return True

    return False

def classify_ticket_category(message: str) -> str:
    """Map message content to a ticket category."""
    m = message.lower()
    if any(w in m for w in ["coffee", "tea", "drink", "food", "meal", "snack", "beverage", "breakfast", "lunch", "dinner"]):
        return "Food"
    if any(w in m for w in ["towel", "clean", "housekeeping", "room service", "bed", "makeup", "turn down", "linen"]):
        return "Room Service"
    if any(w in m for w in ["ac", "wifi", "tv", "light", "repair", "engineer", "fix", "leak", "broken", "toilet", "plumb", "electr"]):
        return "Engineering"
    return "General"

def assign_staff_for_category(category: str) -> str:
    return {
        "Food": "Food Staff",
        "Room Service": "Room Service",
        "Engineering": "Engineering",
        "General": "Front Desk"
    }.get(category, "Front Desk")

def create_ticket_row_payload(message: str, email: str = None) -> Dict[str, str]:
    """
    Build the exact rowData dict matching your sheet's headers:
    Ticket ID | Guest Name | Room No | Request/Query | Category | Assigned To | Status | Created At | Resolved At | Notes
    
    Note: This function now tries to get the actual room number from Client_workflow sheet if possible
    """

    # get the latest session (key + object)
    session_key, session_obj = get_latest_session(USER_SESSIONS)
    # Get actual room number from Client_workflow sheet if possible

    print("\nSelected session_key:", session_key)
    print("Selected session_obj (sanitized):")
    if session_obj:
        # mask password in raw if present for logging
        raw_preview = {k: ("****" if re.sub(r"[^a-zA-Z0-9]", "", str(k)).lower() == "password" else v)
                       for k, v in (session_obj.get("raw", {}) or {}).items()}
        print("normalized:", session_obj.get("normalized"))
        print("frontend:", session_obj.get("frontend"))
        print("raw (masked):", raw_preview)
    else:
        print("No session selected (session_obj is None)")
    print()



    normalized = session_obj.get("normalized") if session_obj else {}

    guest_email = normalized.get("email") if isinstance(normalized, dict) else None
    room_no = normalized.get("room_alloted") if isinstance(normalized, dict) else None

    
    ticket_id = f"TCK-{random.randint(1000, 99999)}"
    guest_name = guest_email 
    category = classify_ticket_category(message)
    assigned_to = assign_staff_for_category(category)
    status = "In Progress"
    created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    resolved_at = ""  # empty initially
    notes = message

    # Use exact header names present in the spreadsheet (case + spaces matter for the Apps Script mapping)
    # Return the ticket data with the room number
    return {
        "Ticket ID": ticket_id,
        "Guest Name": guest_email,
        "Room No": room_no,  # Now using actual room number from Client_workflow sheet
        "Request/Query": message,
        "Category": category,
        "Assigned To": assigned_to,
        "Status": status,
        "Created At": created_at,
        "Resolved At": resolved_at,
        "Notes": notes
    }

def push_ticket_to_sheet(row_data: Dict[str, str]) -> Dict:
    """
    Call your Apps Script webapp with { action: 'addRow', sheet: <sheetName>, rowData: {...} }.
    Returns the parsed JSON response or raises on network error.
    """
    if not GSHEET_WEBAPP_URL:
        raise RuntimeError("GSHEET_WEBAPP_URL not configured in Config")

    payload = {
        "action": "addRow",
        "sheet": TICKET_SHEET_NAME,
        "rowData": row_data
    }
    try:
        resp = requests.post(GSHEET_WEBAPP_URL, json=payload, timeout=10)
        # Apps Script returns JSON like { success: true, message: 'Row added successfully' }
        try:
            return resp.json()
        except Exception:
            resp.raise_for_status()
            return {"ok": True, "status_code": resp.status_code}
    except Exception as e:
        # bubble up error to caller for graceful logging
        raise

import os
import uuid
import json
import random
import logging
import asyncio
import requests
from typing import List, Optional, Dict, Any, Generator
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Query, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from config import Config

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



# ------------------------- Pydantic Models -------------------------
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


########## helper functions ##########

def _fetch_sheet_data(self, sheet_name: str) -> List[Dict[str, Any]]:
    """
    Calls the deployed Apps Script web app and returns the list of row objects for the sheet.
    The web app must implement ?action=getSheetData&sheet=<sheetName> (matching your provided Apps Script).
    """
    if not self.sheet_api:
        raise RuntimeError("GSHEET_WEBAPP_URL is not configured in Config.")

    params = {"action": "getSheetData", "sheet": sheet_name}
    try:
        resp = requests.get(self.sheet_api, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # Data should be a list of objects (one per row). If the webapp returns {error:...}, raise.
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"Sheets webapp returned error: {data.get('error')}")
        if not isinstance(data, list):
            # sometimes the webapp might wrap results; be permissive
            raise RuntimeError("Unexpected sheet response format (expected list of row objects).")
        return data
    except Exception as e:
        logger.error(f"Error fetching sheet '{sheet_name}' from {self.sheet_api}: {e}")
        raise

'''
# -------------------- Updated /chat endpoint (drop-in replacement) --------------------
menu = _fetch_sheet_data(MENU_SHEET_NAME) or []
menu_text = ""
if menu:
    menu_text = "\n\n\n📣 **Menu / Item / Price / Description:**\n"
    for c in menu[:]:
        # try to pick a title/description
        type = c.get("Type") or c.get("Type") or c.get("Type") or c.get("Type") or ""
        item = c.get("Item") or c.get("Item") or c.get("Item") or ""
        price = c.get("Price") or "0"
        desc = c.get("Descripton") or ""
        if type or desc:
            menu_text += f"- {type} {('- ' + desc) if desc else ''} {('- ' + item) if item else ''} {('- ' + price) if price else ''} {('- ' + desc) if desc else ''}\n"
'''

menu = []

from datetime import datetime
from typing import Tuple, Optional, Dict, Any

# --- Helper: pick latest session by last_login ---
def get_latest_session(user_sessions: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Return (session_key, session_obj) for the session with the newest last_login.
    If none found, returns (None, None).
    """
    if not user_sessions:
        return None, None

    latest_key = None
    latest_ts = None

    for key, sess in user_sessions.items():
        last_login_str = sess.get("last_login")
        if last_login_str:
            try:
                # handle trailing Z
                ts = datetime.fromisoformat(last_login_str.replace("Z", "+00:00"))
            except Exception:
                ts = None
        else:
            ts = None

        # treat missing timestamps as very old so they won't override real ones
        if ts is None:
            continue

        if latest_ts is None or ts > latest_ts:
            latest_ts = ts
            latest_key = key

    # If we didn't find any with parseable timestamps but there are sessions, pick an arbitrary one
    if latest_key is None and len(user_sessions) > 0:
        # pick last inserted key (stable for dicts in Python 3.7+)
        try:
            latest_key = next(reversed(user_sessions))
        except Exception:
            latest_key = next(iter(user_sessions))

    if latest_key:
        return latest_key, user_sessions.get(latest_key)
    return None, None


# --- Corrected /chat endpoint ---
@app.post("/chat", response_model=ChatResp)
async def chat(req: ChatReq):
    pending_balance = 0.0
    user_input = req.message or ""
    print(user_input)

    # determine guest flag safely
    is_guest = bool(getattr(req, "is_guest", False))

    # get the latest session (key + object)
    session_key, session_obj = get_latest_session(USER_SESSIONS)

    # If you want to prefer req.email over stored sessions when present:
    # if req.email:
    #     session_key = req.email
    #     session_obj = USER_SESSIONS.get(session_key, session_obj)

    # Call bot.ask with session context (session_obj may be None, which is fine)

    # bot.ask signature: ask(query, user_type=None, user_session=None, session_key=None)
    print('ASKED')
    bot_reply_text = bot.ask(query= user_input, user_type = "guest" , user_session=session_obj, session_key=session_key)


    intent = classify_intent(user_input)
    actions = ChatActions()

    # Diagnostic printing (safe)
    print("\nSelected session_key:", session_key)
    print("Selected session_obj (sanitized):")
    if session_obj:
        # mask password in raw if present for logging
        raw_preview = {k: ("****" if re.sub(r"[^a-zA-Z0-9]", "", str(k)).lower() == "password" else v)
                       for k, v in (session_obj.get("raw", {}) or {}).items()}
        print("normalized:", session_obj.get("normalized"))
        print("frontend:", session_obj.get("frontend"))
        print("raw (masked):", raw_preview)
    else:
        print("No session selected (session_obj is None)")
    print()

    normalized = session_obj.get("normalized") if session_obj else {}
    print()
    print(normalized)
    print(type(normalized))
    print()

    guest_email = normalized.get("email") if isinstance(normalized, dict) else None
    room_no = normalized.get("room_alloted") if isinstance(normalized, dict) else None

    ## menu:
    AVAILABLE_EXTRAS = {}
    EXTRAS_PRICE_BY_KEY = {}
    for c in menu[:]:
        if c.get("Type") == "Complimentary":
            continue
        label = c.get("Item") or ""
        key = c.get("Item")
        try:
            price = float(c.get("Price") or 0)
        except Exception:
            price = 0.0
        if label:
            AVAILABLE_EXTRAS[label] = key
        if key:
            EXTRAS_PRICE_BY_KEY[key] = price

    message_lower = user_input.lower()
    addon_matches = [k for k in AVAILABLE_EXTRAS if k.lower() in message_lower]

    for price_addon in addon_matches:
        pending_balance += EXTRAS_PRICE_BY_KEY.get(AVAILABLE_EXTRAS[price_addon], 0)

    # ------------------ Ticket creation (if detected) ------------------
    created_ticket_id: Optional[str] = None
    try:
        if is_ticket_request(user_input, intent, addon_matches):
            ticket_row = create_ticket_row_payload(user_input, req.email)
            try:
                resp_json = push_row_to_sheet(TICKET_SHEET_NAME, ticket_row)
                created_ticket_id = ticket_row.get("Ticket ID")
                logger.info("Ticket created: %s (sheet resp: %s)", created_ticket_id, resp_json)
                # broadcast ticket_created SSE event (best-effort)
                try:
                    await broker.broadcast("ticket_created", {
                        "ticket_id": created_ticket_id,
                        "guest_email": guest_email,
                        "room_no": room_no,
                        "category": ticket_row.get("Category"),
                        "assigned_to": ticket_row.get("Assigned To"),
                        "status": ticket_row.get("Status"),
                        "created_at": ticket_row.get("Created At"),
                        "notes": ticket_row.get("Notes"),
                    })
                except Exception as e:
                    logger.warning(f"Failed to broadcast ticket creation: {e}")
            except Exception as e:
                logger.warning("Failed to push ticket to sheet: %s", e)
    except Exception as e:
        logger.warning("Ticket subsystem error: %s", e)

    # file-based log (keep existing)
    log_chat("web", req.session_id or "", user_input, bot_reply_text, intent, is_guest)

    # ------------------ append guest interaction log to sheet ------------------
    try:
        log_row = create_guest_log_row(req.session_id, req.email, user_input, bot_reply_text, intent, is_guest, created_ticket_id)
        try:
            resp_log = push_row_to_sheet(GUEST_LOG_SHEET_NAME, log_row)
            logger.info("Guest interaction logged to sheet (Log ID=%s): %s", log_row.get("Log ID"), resp_log)
            # optionally broadcast a guest_log_created SSE event
            try:
                await broker.broadcast("guest_log_created", {
                    "log_id": log_row.get("Log ID"),
                    "session_id": log_row.get("Session ID"),
                    "guest_email": log_row.get("Guest Email"),
                    "intent": intent,
                    "ticket_ref": created_ticket_id,
                    "timestamp": log_row.get("Timestamp")
                })
            except Exception as e:
                logger.warning(f"Failed to broadcast guest log: {e}")
        except Exception as e:
            logger.warning("Failed to push guest log to sheet: %s", e)
    except Exception as e:
        logger.warning("Guest log subsystem error: %s", e)

    reply_parts = bot_reply_text.split("\n\n") if isinstance(bot_reply_text, str) else [str(bot_reply_text)]
    return ChatResp(reply=bot_reply_text, reply_parts=reply_parts, intent=intent, actions=actions)


# ------------------------- Run locally -------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main_final:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)

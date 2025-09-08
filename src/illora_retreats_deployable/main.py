# main.py (cleaned & corrected)
import os
import uuid
import json
import random
import logging
import asyncio
from typing import List, Optional, Dict, Any

from datetime import date, datetime, timedelta

from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Query, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from pydantic import BaseModel, Field

# Project imports (preserved as in your original file)
import web_ui_final as web
from services.intent_classifier import classify_intent
from logger import log_chat
from services.qa_agent import ConciergeBot
from services.payment_gateway import create_checkout_session, create_addon_checkout_session, create_pending_checkout_session

# Illora checkin app / models
from illora.checkin_app.models import Room, Booking, BookingStatus
from illora.checkin_app.pricing import calculate_price_for_room as calculate_price
from illora.checkin_app.database import Base, engine, SessionLocal
from illora.checkin_app.booking_flow import create_booking_record
from illora.checkin_app.chat_models import ChatMessage

from sqlalchemy import func
from sqlalchemy.orm import Session

# -------------------------
# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_chieftain")

# --- FastAPI app
app = FastAPI(title="AI Chieftain API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # or restrict to ["http://localhost:5173"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Concierge bot instance
bot = ConciergeBot()

# Demo in-memory sample bookings data (kept for dashboard/demo)
DEMO_NAMES = [
    "John Doe", "Jane Smith", "Michael Johnson", "Emily Davis",
    "Daniel Wilson", "Sophia Martinez", "James Brown", "Olivia Taylor",
    "Liam Anderson", "Ava Thomas", "Noah Jackson", "Isabella White",
    "Ethan Harris", "Mia Clark", "Alexander Lewis", "Amelia Hall",
    "William Young", "Charlotte King", "Benjamin Wright", "Harper Scott"
]
DEMO_ROOM_TYPES = ["Deluxe Suite", "Executive Room", "Standard Room", "Presidential Suite"]
sample_bookings: List[Dict[str, Any]] = []

# ---------- Helpers ----------
def get_db() -> Session:
    """
    Simple DB session helper. Use in endpoints where explicit session management is needed.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def menu_file_path() -> str:
    # cross-platform path
    return os.path.join("services", "menu.json")

# ---------------- STARTUP ----------------
@app.on_event("startup")
def on_startup():
    """
    Create DB tables, initialize user DB and seed both DB & demo in-memory sample bookings.
    """
    # create SQLAlchemy tables
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.warning("Failed to create DB tables: %s", e)

    # init user DB (file-based)
    try:
        USER_DB_PATH = "illora_user_gate.db"
        web.init_user_db(USER_DB_PATH)
    except Exception as e:
        logger.warning("Warning: failed to init user DB: %s", e)

    # seed Rooms, a demo Booking, and example ChatMessages (idempotent)
    db = SessionLocal()
    try:
        # Seed Rooms if none exist
        try:
            room_count = db.query(func.count(Room.id)).scalar()
        except Exception:
            room_count = 0

        if not room_count:
            logger.info("Seeding default rooms...")
            demo_rooms = [
                Room(name="Deluxe King", room_type="deluxe", capacity=2, base_price=5000, total_units=5, media=[]),
                Room(name="Standard Twin", room_type="standard", capacity=2, base_price=3000, total_units=8, media=[]),
                Room(name="Suite Ocean", room_type="suite", capacity=4, base_price=12000, total_units=2, media=[]),
            ]
            db.add_all(demo_rooms)
            db.commit()

        # Seed a demo booking so dashboard has at least one
        booking_count = db.query(func.count(Booking.id)).scalar()
        if not booking_count:
            logger.info("Seeding a demo DB booking...")
            first_room = db.query(Room).first()
            demo_booking = Booking(
                guest_name="Demo Guest",
                guest_phone="0000000000",
                room_id=getattr(first_room, "id", None),
                check_in=date.today(),
                check_out=(date.today() + timedelta(days=1)),
                price=getattr(first_room, "base_price", 0),
                channel="seed",
                channel_user="demo@example.com",
            )
            db.add(demo_booking)
            db.commit()

        # Seed chat examples
        chat_exists = db.query(func.count(ChatMessage.session_id)).scalar() if hasattr(ChatMessage, "session_id") else 0
        if not chat_exists:
            cm_user = ChatMessage(session_id="seed-session", email="demo@example.com", channel="web", role="user", text="Hi, is breakfast included?", intent="ask_breakfast", is_guest=True)
            cm_bot = ChatMessage(session_id="seed-session", email="demo@example.com", channel="web", role="assistant", text="Breakfast is included for bookings with breakfast plan.", intent="reply", is_guest=True)
            db.add_all([cm_user, cm_bot])
            db.commit()

    except Exception as e:
        logger.warning("Startup seeding error: %s", e)
        db.rollback()
    finally:
        db.close()

    # seed demo in-memory bookings used by dashboards that rely on in-memory data
    global sample_bookings
    sample_bookings = []
    base_date = datetime.today()
    for i, name in enumerate(DEMO_NAMES, start=1):
        check_in = base_date + timedelta(days=random.randint(0, 10))
        check_out = check_in + timedelta(days=random.randint(1, 5))
        sample_bookings.append({
            "id": i,
            "guest": name,
            "room_no": random.randint(1, 100),
            "room": random.choice(DEMO_ROOM_TYPES),
            "check_in": check_in.strftime("%Y-%m-%d"),
            "check_out": check_out.strftime("%Y-%m-%d"),
            "status": random.choice(["Confirmed", "Checked-in", "Checked-out", "Cancelled"]),
            "amount": random.randint(5000, 20000)
        })


# ---------------- SIMPLE SSE BROKER ----------------
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
        # fan out to all queues
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
    """
    Simple Server-Sent Events endpoint.
    """
    async def event_generator(q: asyncio.Queue):
        try:
            await q.put(json.dumps({"event": "connected", "data": {}}))
            while True:
                # if client disconnected, break
                if await request.is_disconnected():
                    break
                msg = await q.get()
                yield f"data: {msg}\n\n"
        finally:
            await broker.disconnect(q)

    q = await broker.connect()
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(event_generator(q), headers=headers, media_type="text/event-stream")


# ---------------- Pydantic models ----------------
class LoginReq(BaseModel):
    email: str
    password: str
    remember: bool = True

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

class BookingStageReq(BaseModel):
    room_id: int
    check_in: date
    check_out: date
    guest_name: str
    guest_phone: Optional[str] = None

class BookingConfirmReq(BaseModel):
    booking_id: str
    room_type: str
    nights: int
    cash: bool = False
    extras: List[str] = Field(default_factory=list)

class BookingForm(BaseModel):
    check_in: date
    check_out: date
    guests: int
    preferences: Optional[str] = ""
    whatsapp_number: Optional[str] = ""

class DemoBookingUpdate(BaseModel):
    guest: Optional[str] = None
    room: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    status: Optional[str] = None
    amount: Optional[int] = None

class DBBookingUpdate(BaseModel):
    guest_name: Optional[str] = None
    guest_phone: Optional[str] = None
    room_id: Optional[int] = None
    check_in: Optional[date] = None
    check_out: Optional[date] = None
    price: Optional[float] = None
    status: Optional[str] = None  # e.g., "CONFIRMED", "CHECKED_IN", etc.


# ---------------- Demo / In-memory endpoints (kept for your dashboard demos) ----------------
@app.get("/demo/bookings/all")
def demo_get_all_bookings():
    return {"bookings": sample_bookings}

@app.get("/demo/bookings/{booking_id}")
def demo_get_booking(booking_id: int):
    for b in sample_bookings:
        if b["id"] == booking_id:
            return b
    raise HTTPException(status_code=404, detail="Demo booking not found")

@app.patch("/demo/bookings/{booking_id}")
def demo_update_booking(booking_id: int, patch: DemoBookingUpdate):
    for b in sample_bookings:
        if b["id"] == booking_id:
            for field, value in patch.dict(exclude_unset=True).items():
                b[field] = value
            return {"ok": True, "booking": b}
    raise HTTPException(status_code=404, detail="Demo booking not found")

@app.post("/admin/seed")
def admin_seed_demo(count: int = Query(20, ge=1, le=100)):
    """
    Overwrite in-memory demo sample_bookings with `count` items for dashboard/demo.
    """
    global sample_bookings
    sample_bookings = []
    base_date = datetime.today()
    for i in range(count):
        name = random.choice(DEMO_NAMES)
        check_in = base_date + timedelta(days=random.randint(0, 10))
        check_out = check_in + timedelta(days=random.randint(1, 5))
        sample_bookings.append({
            "id": i + 1,
            "guest": name,
            "room": random.choice(DEMO_ROOM_TYPES),
            "check_in": check_in.strftime("%Y-%m-%d"),
            "check_out": check_out.strftime("%Y-%m-%d"),
            "status": random.choice(["Confirmed", "Checked-in", "Checked-out", "Cancelled"]),
            "amount": random.randint(5000, 20000)
        })
    return {"ok": True, "seeded": len(sample_bookings)}


# ---------------- Auth endpoints ----------------
@app.post("/auth/login")
def login(req: LoginReq):
    USER_DB_PATH = "illora_user_gate.db"
    web.ensure_user(req.email, req.password, USER_DB_PATH)
    row = web.get_user_row(req.email, USER_DB_PATH)
    token = None
    if req.remember:
        token = uuid.uuid4().hex
        web.set_remember_token(req.email, token, USER_DB_PATH)
    return {"email": row[0], "booked": int(row[2] or 0), "id_proof_uploaded": int(row[3] or 0), "remember_token": token}

@app.get("/auth/me")
def me(token: str = Query(...)):
    USER_DB_PATH = "illora_user_gate.db"
    row = web.get_user_by_token(token, USER_DB_PATH)
    if not row:
        raise HTTPException(status_code=404, detail="Invalid token")
    return {"email": row[0], "booked": int(row[2] or 0), "id_proof_uploaded": int(row[3] or 0)}


# ---------------- Chat endpoint ----------------
@app.post("/chat", response_model=ChatResp)
def chat(req: ChatReq):
    user_input = req.message
    is_guest = bool(req.is_guest)
    bot_reply_text = bot.ask(user_input, user_type=is_guest)
    intent = classify_intent(user_input)
    actions = ChatActions()

    # --- menu/extras logic unchanged (but portable path usage) ---
    MENU_FILE = menu_file_path()
    try:
        with open(MENU_FILE, "r", encoding="utf-8") as f:
            MENU = json.load(f)
    except FileNotFoundError:
        MENU = {}

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

    if intent in ("payment_request", "booking_request"):
        actions.show_booking_form = True

    if intent == "checkout_balance":
        details, total = web.get_due_items_details(req.email)
        if total and total > 0:
            try:
                pay_url = create_pending_checkout_session(total)
                actions.pending_balance = {"amount": total, "items": details, "payment_link": pay_url}
            except Exception as e:
                logger.warning("Pending checkout creation failed: %s", e)
                actions.pending_balance = {"amount": total, "items": details, "payment_link": None}

    # file-based log
    log_chat("web", req.session_id or "", user_input, bot_reply_text, intent, is_guest)

    # persist to DB and broadcast
    db = SessionLocal()
    try:
        cm_user = ChatMessage(
            session_id=req.session_id,
            email=req.email,
            channel="web",
            role="user",
            text=user_input,
            intent=intent,
            is_guest=is_guest
        )
        db.add(cm_user)
        db.commit(); db.refresh(cm_user)

        cm_bot = ChatMessage(
            session_id=req.session_id,
            email=req.email,
            channel="web",
            role="assistant",
            text=bot_reply_text,
            intent=intent,
            is_guest=is_guest
        )
        db.add(cm_bot)
        db.commit(); db.refresh(cm_bot)

        # broadcast (best-effort)
        try:
            # use create_task safely if loop exists
            asyncio.create_task(broker.broadcast("chat_message", {
                "session_id": req.session_id,
                "email": req.email,
                "user": cm_user.text,
                "assistant": cm_bot.text,
                "intent": intent
            }))
        except RuntimeError:
            # not in loop - ignore
            pass

    except Exception as e:
        logger.warning("Failed to persist chat message: %s", e)
        db.rollback()
    finally:
        db.close()

    reply_parts = bot_reply_text.split("\n\n")
    return ChatResp(reply=bot_reply_text, reply_parts=reply_parts, intent=intent, actions=actions)


# ---------------- Add-ons ----------------
@app.get("/addons/catalog")
def addons_catalog():
    MENU_FILE = menu_file_path()
    try:
        with open(MENU_FILE, "r", encoding="utf-8") as f:
            MENU = json.load(f)
    except FileNotFoundError:
        MENU = {}

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

    catalog = [{"key": k, "label": k.replace("_", " ").title(), "price": EXTRAS_PRICE_BY_KEY.get(k)} for k in AVAILABLE_EXTRAS.values()]
    return {"catalog": catalog}

@app.post("/addons/tab")
def addons_tab(email: str, keys: List[str]):
    added = web.add_due_items(email, keys)
    total = web.due_total_from_items(web.get_due_items(email))
    return {"added": bool(added), "pending_total": total}

@app.post("/addons/checkout")
def addons_checkout(session_id: str, extras: List[str]):
    url = create_addon_checkout_session(session_id=session_id, extras=extras)
    return {"checkout_url": url}


# ---------------- Rooms / pricing ----------------
@app.get("/rooms")
def rooms(check_in: date = Query(...), check_out: date = Query(...), db: Session = Depends(get_db)):
    rooms = db.query(Room).all()
    out = []

    for r in rooms:
        try:
            price, nights = calculate_price(db=db, room=r, check_in=check_in, check_out=check_out)
        except Exception:
            price, nights = r.base_price, 1
        out.append({
            "id": r.id,
            "name": r.name,
            "room_type": r.room_type,
            "capacity": r.capacity,
            "media": r.media,
            "quote": {"price": price, "nights": nights}
        })
    return {"rooms": out}


# ---------------- Booking form endpoint (frontend sends form) ----------------
@app.post("/booking/form")
def booking_form(form: BookingForm, db: Session = Depends(get_db)):
    rooms_out: List[Dict[str, Any]] = []
    rooms = db.query(Room).all()
    if not rooms:
        return {"rooms": [], "message": "No rooms found in DB. Seed rooms first."}

    ci = form.check_in
    co = form.check_out
    for r in rooms:
        try:
            price, nights = calculate_price(db=db, room=r, check_in=ci, check_out=co)
        except Exception:
            price, nights = r.base_price, 1

        rooms_out.append({
            "id": r.id,
            "name": r.name,
            "room_type": r.room_type,
            "capacity": r.capacity,
            "units": getattr(r, "total_units", None),
            "media": r.media or [],
            "price": price,
            "nights": nights,
            "base_price": getattr(r, "base_price", None),
        })

    return {"rooms": rooms_out, "check_in": form.check_in.isoformat(), "check_out": form.check_out.isoformat(), "guests": form.guests, "preferences": form.preferences or "", "whatsapp_number": form.whatsapp_number or ""}


# ---------------- Bookings (DB-backed) ----------------
@app.post("/bookings/stage")
async def bookings_stage(req: BookingStageReq, email: Optional[str] = Query(None)):
    db = SessionLocal()
    try:
        booking = None
        try:
            booking = create_booking_record(
                db=db,
                guest_name=req.guest_name,
                guest_phone=req.guest_phone,
                room_id=req.room_id,
                check_in=req.check_in,
                check_out=req.check_out,
                price=0,
                channel='web',
                channel_user=email
            )
        except Exception as e:
            logger.warning("create_booking_record error: %s", e)

        if booking is None:
            fallback = Booking(
                guest_name=req.guest_name,
                guest_phone=req.guest_phone,
                room_id=req.room_id,
                check_in=req.check_in,
                check_out=req.check_out,
                price=0,
                channel='web',
                channel_user=email
            )
            db.add(fallback)
            db.commit()
            db.refresh(fallback)
            booking = fallback

        booking_id = str(getattr(booking, "id"))
        try:
            await broker.broadcast("booking_created", {"booking_id": booking_id})
        except Exception:
            pass

        return {"booking_id": booking_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to stage booking: {e}")
    finally:
        db.close()

@app.post("/bookings/confirm")
async def bookings_confirm(req: BookingConfirmReq):
    db = SessionLocal()
    try:
        booking = None
        try:
            booking = db.query(Booking).filter(Booking.id == int(req.booking_id)).first()
        except Exception:
            booking = db.query(Booking).filter(Booking.id == req.booking_id).first()

        if not booking:
            raise HTTPException(status_code=404, detail="Staged booking not found")

        canonical_booking_id = str(getattr(booking, "id"))
        stripe_sess = create_checkout_session(session_id=canonical_booking_id, room_type=req.room_type, nights=req.nights, cash=req.cash, extras=req.extras)

        if isinstance(stripe_sess, dict):
            stripe_id = stripe_sess.get("id")
            checkout_url = web._checkout_url_from_session(stripe_sess)
        else:
            stripe_id = getattr(stripe_sess, "id", None)
            checkout_url = web._checkout_url_from_session(stripe_sess)

        if hasattr(booking, "stripe_session_id"):
            booking.stripe_session_id = stripe_id
        if hasattr(booking, "checkout_url"):
            booking.checkout_url = checkout_url

        db.add(booking)
        db.commit()
        db.refresh(booking)

        try:
            qr_local, qr_public = web.save_qr_to_static(checkout_url, f"checkout_{canonical_booking_id}.png")
        except Exception:
            qr_public = None

        try:
            await broker.broadcast("booking_confirmed", {
                "booking_id": canonical_booking_id,
                "stripe_session_id": stripe_id,
                "checkout_url": checkout_url
            })
        except Exception:
            pass

        return {"checkout_url": checkout_url, "qr_url": qr_public, "stripe_session_id": stripe_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to confirm booking: {e}")
    finally:
        db.close()

@app.get("/bookings/{booking_id}")
def get_booking_db(booking_id: str):
    db = SessionLocal()
    try:
        # try numeric id first
        try:
            b = db.query(Booking).filter(Booking.id == int(booking_id)).first()
        except Exception:
            b = db.query(Booking).filter(Booking.id == booking_id).first()

        if not b:
            raise HTTPException(status_code=404, detail="Booking not found")

        return {
            "booking_id": b.id,
            "guest_name": getattr(b, "guest_name", None),
            "guest_phone": getattr(b, "guest_phone", None),
            "room_id": getattr(b, "room_id", None),
            "check_in": getattr(b, "check_in", None).isoformat() if getattr(b, "check_in", None) else None,
            "check_out": getattr(b, "check_out", None).isoformat() if getattr(b, "check_out", None) else None,
            "price": getattr(b, "price", None),
            "status": getattr(b, "status", None).name if getattr(b, "status", None) else None,
            "stripe_session_id": getattr(b, "stripe_session_id", None) if hasattr(b, "stripe_session_id") else None,
        }
    finally:
        db.close()

@app.get("/bookings/all_db")
def get_all_bookings_db():
    db = SessionLocal()
    try:
        rows = db.query(Booking).all()
        out = []
        for b in rows:
            out.append({
                "id": getattr(b, "id", None),
                "guest_name": getattr(b, "guest_name", None),
                "room_id": getattr(b, "room_id", None),
                "check_in": getattr(b, "check_in", None).isoformat() if getattr(b, "check_in", None) else None,
                "check_out": getattr(b, "check_out", None).isoformat() if getattr(b, "check_out", None) else None,
                "price": getattr(b, "price", None),
                "status": getattr(b, "status", None).name if getattr(b, "status", None) else None,
            })
        return {"bookings": out}
    finally:
        db.close()

@app.patch("/bookings/{booking_id}/update")
def bookings_update(booking_id: str, patch: DBBookingUpdate):
    db = SessionLocal()
    try:
        try:
            b = db.query(Booking).filter(Booking.id == int(booking_id)).first()
        except Exception:
            b = db.query(Booking).filter(Booking.id == booking_id).first()

        if not b:
            raise HTTPException(status_code=404, detail="Booking not found")

        for field, val in patch.dict(exclude_unset=True).items():
            if field == "status" and val:
                # try to set Enum safely, attempt different casing strategies
                try:
                    if isinstance(val, str) and val.upper() in BookingStatus.__members__:
                        setattr(b, "status", BookingStatus[val.upper()])
                    elif hasattr(BookingStatus, val):
                        setattr(b, "status", getattr(BookingStatus, val))
                    else:
                        # fallback: leave as-is or raise
                        raise ValueError(f"Invalid status: {val}")
                except Exception as e:
                    raise HTTPException(status_code=400, detail=str(e))
            else:
                setattr(b, field, val)

        db.add(b)
        db.commit(); db.refresh(b)

        # broadcast update (best-effort)
        try:
            asyncio.create_task(broker.broadcast("booking_updated", {
                "id": getattr(b, "id"),
                "guest_name": getattr(b, "guest_name", None),
                "status": getattr(b, "status", None).name if getattr(b, "status", None) else None,
                "price": getattr(b, "price", None),
            }))
        except RuntimeError:
            pass

        return {"ok": True}
    finally:
        db.close()


# ---------------- Billing ----------------
@app.get("/billing/due-items")
def billing_due(email: str):
    details, total = web.get_due_items_details(email)
    return {"items": details, "total": total}

@app.post("/billing/checkout")
def billing_checkout(amount: int):
    sess = create_pending_checkout_session(amount)
    url = web._checkout_url_from_session(sess)
    return {"checkout_url": url}


# ---------------- ID-proof upload ----------------
@app.post("/users/{email}/id_proof")
def id_proof(email: str, file: UploadFile = File(...)):
    url = web.save_id_proof(email, file)
    USER_DB_PATH = "illora_user_gate.db"
    web.set_id_proof(email, 1, USER_DB_PATH)
    return {"url": url}


# ---------------- Misc admin/demo endpoints ----------------
@app.get("/health")
def health():
    return {"ok": True, "timestamp": datetime.utcnow().isoformat()}


# Optional: allow running with `python main.py` for local quick tests
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 5002)), reload=True)

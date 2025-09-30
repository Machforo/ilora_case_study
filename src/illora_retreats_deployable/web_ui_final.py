# web_ui.py (UPDATED — uses illora.checkin_app.models as single source-of-truth)
import os
import uuid
import qrcode
import base64
import sqlite3
import json
from io import BytesIO
from datetime import datetime, date
from pathlib import Path
from collections import Counter

import streamlit as st
import streamlit.components.v1 as components   # new: for localStorage & tiny JS snippets
from PIL import Image
from logger import log_chat

# existing project imports (kept; adjusted)
from services.payment_gateway import create_checkout_session, create_addon_checkout_session, create_pending_checkout_session
from services.qa_agent import ConciergeBot
from services.intent_classifier import classify_intent

# SINGLE source-of-truth models & DB session
from illora.checkin_app.models import Room, Booking, BookingStatus
from illora.checkin_app.pricing import calculate_price_for_room as calculate_price
from illora.checkin_app.database import SessionLocal   # must already exist in your project


# --- Feature toggles / constants ------------------------------------------------
TESTING_FORCE_ID_AFTER_PAYMENT = True   # if True: force uploader after checkout link for testing flows
REMEMBER_LOCALSTORAGE_KEY = "illora_remember"

# --- Page Config ---
st.set_page_config(page_title="ILORA Retreat – AI Concierge", page_icon="🛎️", layout="wide")

# --- Branding & constants ---
LOGO_PATH = "add_ons/logo.jpg"
BACKGROUND_IMAGE = "add_ons/illora_retreats.jpg"
QR_LINK = "https://illorafinal-lhxrkgjufxiqhwjsakm2py.streamlit.app/"
WHATSAPP_LINK = "https://wa.me/919876543210"

# Static dirs
STATIC_DIR = Path("static")
STATIC_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = Path("uploads/id_proofs")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MENU_FILE =  "services/menu.json"
with open(MENU_FILE, "r", encoding="utf-8") as f:
    MENU = json.load(f)

# Flatten items for UI selection
AVAILABLE_EXTRAS = {}        # display_label -> key
EXTRAS_PRICE_BY_KEY = {}     # key -> price
for category, items in MENU.items():
    if category == "complimentary":
        continue
    for display_name, _price in items.items():
        label = display_name.replace("_", " ").title()
        key = display_name.lower().replace(" ", "_")
        AVAILABLE_EXTRAS[label] = key
        EXTRAS_PRICE_BY_KEY[key] = _price

# reverse map: key -> display label
KEY_TO_LABEL = {v: k for k, v in AVAILABLE_EXTRAS.items()}

# --- Minimal user db (SQLite; tiny, non-invasive) ---------------------------
USER_DB_PATH = "illora_user_gate.db"

import os
from pathlib import Path
from fastapi import UploadFile

UPLOAD_DIR = Path("data/id_proofs")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def save_id_proof(email: str, file: UploadFile) -> str:
    # Create a directory for each user (based on email)
    user_dir = UPLOAD_DIR / email.replace("@", "_").replace(".", "_")
    user_dir.mkdir(parents=True, exist_ok=True)

    # Save file
    file_path = user_dir / file.filename
    with open(file_path, "wb") as f:
        f.write(file.file.read())

    # Return relative/absolute URL
    return str(file_path.resolve())

def init_user_db(USER_DB_PATH):
    conn = sqlite3.connect(USER_DB_PATH)
    c = conn.cursor()
    # Note: adding remember_token (nullable). If table already exists, this statement will be ignored.
    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        email TEXT PRIMARY KEY,
        password TEXT,
        booked INTEGER DEFAULT 0,
        id_proof_uploaded INTEGER DEFAULT 0,
        due_items TEXT DEFAULT '[]',
        remember_token TEXT,
        remember_expires TEXT
    )""")
    conn.commit()
    conn.close()

def get_user_row(email, USER_DB_PATH):
    conn = sqlite3.connect(USER_DB_PATH)
    c = conn.cursor()
    c.execute("SELECT email, password, booked, id_proof_uploaded, due_items, remember_token FROM users WHERE email=?", (email,))
    row = c.fetchone()
    conn.close()
    return row

def get_user_by_token(token, USER_DB_PATH):
    if not token:
        return None
    conn = sqlite3.connect(USER_DB_PATH)
    c = conn.cursor()
    c.execute("SELECT email, password, booked, id_proof_uploaded, due_items, remember_token FROM users WHERE remember_token=?", (token,))
    row = c.fetchone()
    conn.close()
    return row

def ensure_user(email, password, USER_DB_PATH):
    """Create a new user or verify existing user's credentials"""
    conn = sqlite3.connect(USER_DB_PATH)
    c = conn.cursor()
    
    # First check if user exists
    c.execute("SELECT email, password FROM users WHERE email=?", (email,))
    existing_user = c.fetchone()
    
    if existing_user:
        # User exists, verify password
        if existing_user[1] != password:
            conn.close()
            raise ValueError("Invalid credentials")
    else:
        # Create new user
        c.execute("INSERT INTO users(email, password) VALUES(?,?)", (email, password))
        conn.commit()
    
    conn.close()

def set_booked(email, booked: int, USER_DB_PATH):
    conn = sqlite3.connect(USER_DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET booked=? WHERE email=?", (booked, email))
    conn.commit()
    conn.close()

def set_id_proof(email, uploaded: int = 1, USER_DB_PATH = USER_DB_PATH):
    conn = sqlite3.connect(USER_DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET id_proof_uploaded=? WHERE email=?", (uploaded, email))
    conn.commit()
    conn.close()

def get_due_items(email) -> list:
    row = get_user_row(email)
    if not row:
        return []
    try:
        return json.loads(row[4] or "[]")
    except Exception:
        return []

def set_remember_token(email, token, expires=None, USER_DB_PATH = USER_DB_PATH):
    conn = sqlite3.connect(USER_DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET remember_token=?, remember_expires=? WHERE email=?", (token, expires, email))
    conn.commit()
    conn.close()

def clear_remember_token(email, USER_DB_PATH):
    conn = sqlite3.connect(USER_DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET remember_token=NULL, remember_expires=NULL WHERE email=?", (email,))
    conn.commit()
    conn.close()

def _flatten_list(maybe_list):
    out = []
    if maybe_list is None:
        return out
    if isinstance(maybe_list, (list, tuple)):
        for item in maybe_list:
            out.extend(_flatten_list(item))
    else:
        out.append(maybe_list)
    return out

def add_due_items(email, new_items: list, USER_DB_PATH):
    """
    Add extras to user's due_items list in DB. Accepts nested lists, display labels, or keys.
    Filters unknown items. Returns True when something was actually added.
    """
    # flatten incoming items
    flattened = _flatten_list(new_items)

    # normalize: accept either key or display label; produce keys
    normalized = []
    for item in flattened:
        if not item:
            continue
        s = str(item)
        # if already a key
        if s in EXTRAS_PRICE_BY_KEY:
            normalized.append(s)
            continue
        # maybe it's a display label
        if s in AVAILABLE_EXTRAS:
            normalized.append(AVAILABLE_EXTRAS[s])
            continue
        # try common normalized forms (space->underscore, lower)
        s_key = s.lower().replace(" ", "_")
        if s_key in EXTRAS_PRICE_BY_KEY:
            normalized.append(s_key)
            continue
        # unknown -> skip
        print(f"add_due_items: skipped unknown extra '{s}'")

    if not normalized:
        return False

    # merge with existing (flatten existing too)
    current = _flatten_list(get_due_items(email))
    new_current = current + normalized

    conn = sqlite3.connect(USER_DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET due_items=? WHERE email=?", (json.dumps(new_current), email))
    conn.commit()
    conn.close()
    return True

def clear_due_items(email, USER_DB_PATH):
    conn = sqlite3.connect(USER_DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET due_items='[]' WHERE email=?", (email,))
    conn.commit()
    conn.close()

def due_total_from_items(items: list) -> int:
    flat = _flatten_list(items)
    total = 0
    for k in flat:
        if k in EXTRAS_PRICE_BY_KEY:
            total += EXTRAS_PRICE_BY_KEY[k]
        else:
            # try to resolve display label
            if k in AVAILABLE_EXTRAS:
                key = AVAILABLE_EXTRAS[k]
                total += EXTRAS_PRICE_BY_KEY.get(key, 0)
            else:
                # try normalized
                kn = str(k).lower().replace(" ", "_")
                total += EXTRAS_PRICE_BY_KEY.get(kn, 0)
    return total

def get_due_items_details(email):
    """
    Returns structured list of pending extras:
    [{'key':k, 'label':label, 'qty':n, 'unit_price':p, 'line_total':q*p}, ...], total
    """
    items = _flatten_list(get_due_items(email))
    counts = Counter(items)
    details = []
    total = 0
    for key, qty in counts.items():
        # normalize key if needed
        k = key
        if k not in EXTRAS_PRICE_BY_KEY:
            # try to resolve from label
            if key in AVAILABLE_EXTRAS:
                k = AVAILABLE_EXTRAS[key]
            else:
                k = str(key).lower().replace(" ", "_")
        unit = EXTRAS_PRICE_BY_KEY.get(k, 0)
        label = KEY_TO_LABEL.get(k, k.replace("_", " ").title())
        line = unit * qty
        details.append({"key": k, "label": label, "qty": qty, "unit_price": unit, "line_total": line})
        total += line
    # sort by label for consistent view
    details.sort(key=lambda x: x["label"])
    return details, total

# --- Helpers ----------------------------------------------------------------
def get_base64_of_bin_file(bin_file):
    with open(bin_file, "rb") as f:
        return base64.b64encode(f.read()).decode()

def generate_qr_code_bytes(link: str) -> bytes:
    """Return PNG bytes of a QR for a given link (temporary checkout QR)."""
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()

def save_qr_to_static(link: str, filename: str):
    """Save QR PNG under static/ and return local path and public path if MEDIA_BASE_URL set."""
    img_bytes = generate_qr_code_bytes(link)
    path = STATIC_DIR / filename
    with open(path, "wb") as f:
        f.write(img_bytes)
    media_base = os.getenv("MEDIA_BASE_URL")
    public = f"{media_base.rstrip('/')}/static/{filename}" if media_base else str(path)
    return str(path), public

def _checkout_url_from_session(sess):
    """Given a returned checkout object or URL, normalize to a URL string (best-effort)."""
    if sess is None:
        return None
    if isinstance(sess, str):
        return sess
    if hasattr(sess, "url"):
        try:
            return getattr(sess, "url")
        except Exception:
            pass
    try:
        if isinstance(sess, dict):
            if "url" in sess:
                return sess["url"]
            if "checkout_url" in sess:
                return sess["checkout_url"]
    except Exception:
        pass
    return None

# --- Minimal YouTube / Instagram preview helpers -----------------------------
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")

def youtube_thumbnail(video_url: str):
    """Return YouTube thumbnail URL (fast fallback) or None if parse fails."""
    try:
        if "youtu.be/" in video_url:
            vid = video_url.split("youtu.be/")[-1].split("?")[0]
        else:
            import urllib.parse as up
            q = up.urlparse(video_url).query
            params = up.parse_qs(q)
            vid = params.get("v", [None])[0]
        if not vid:
            return None
        return f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
    except Exception:
        return None

def instagram_oembed_thumb(insta_url: str):
    """Try Instagram oEmbed endpoint (may need app-level config). Return thumbnail or None."""
    try:
        oembed = f"https://graph.facebook.com/v16.0/instagram_oembed?url={insta_url}"
        r = __import__("requests").get(oembed, timeout=6)
        if r.status_code == 200:
            data = r.json()
            return data.get("thumbnail_url")
    except Exception:
        pass
    return None

# --- Styling (preserve your existing style) ---------------------------------
if os.path.exists(BACKGROUND_IMAGE):
    bin_str = get_base64_of_bin_file(BACKGROUND_IMAGE)
    page_bg_img = f"""
    <style>
    .stApp {{
        background-image: url("data:image/jpg;base64,{bin_str}");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
        color: #fff;
        font-weight: 500;
    }}
    .stApp::before {{
        content: "";
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0,0,0,0.55);
        backdrop-filter: blur(4px);
        z-index: -1;
    }}
    section[data-testid="stSidebar"] {{
        background: rgba(30, 30, 30, 0.6) !important;
        backdrop-filter: blur(10px);
        color: white !important;
    }}
    .main-content-box {{
        background: rgba(255,255,255,0.08);
        border-radius: 16px;
        padding: 20px;
        box-shadow: 0 4px 30px rgba(0,0,0,0.2);
        border: 1px solid rgba(255,255,255,0.2);
    }}
        div.stButton > button[kind="formSubmit"] {{
        background-color: #28a745;
        color: black;
        font-weight: bold;
        border-radius: 8px;
        padding: 0.5em 1em;
    }}
    div.stButton > button[kind="formSubmit"]:hover {{
        background-color: #218838;
        color: white;
    }}
    .stChatMessage {{
        background-color: rgba(30, 30, 30, 0.6);
        padding: 12px;
        border-radius: 12px;
        margin: 6px 0;
        box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        font-weight: 700;
    }}
    .stButton>button {{
        background: linear-gradient(135deg, #4CAF50, #2E8B57); /* green gradient */
        color: #000000 !important;  /* text color */
        border-radius: 12px;
        padding: 10px 20px;
        border: none;
        font-weight: bold;
        font-size: 15px;
        box-shadow: 0 4px 10px rgba(0,0,0,0.25);
        transition: transform 0.2s ease, background 0.3s ease;
    }}
    .stButton>button:hover {{
        transform: scale(1.08);
        background: linear-gradient(135deg, #45a049, #1e7a46); /* hover effect */
    }}

    h1, h2, h3, h4 {{
        font-weight: 700 !important;
        color: #fff !important;
        text-shadow: 0 2px 4px rgba(0,0,0,0.6);
    }}
    p, label, .stMarkdown {{
        color: #f0f0f0 !important;
    }}

    /* WhatsApp-style chat window & bubbles */
    .chat-window {{
        max-height: calc(100vh - 280px);
        overflow-y: auto;
        padding: 12px;
        padding-bottom: 80px;     /* ← corrected */
        display: flex;
        flex-direction: column;
    }}

    .bubble {{
        max-width: 78%;
        padding: 10px 14px;
        border-radius: 18px;
        margin: 6px 8px;
        word-break: break-word;
        line-height: 1.35;
    }}

    .bubble.user {{
        align-self: flex-end;
        background: linear-gradient(135deg,#DCF8C6,#BFEFC7);
        color: #000;
        border-bottom-right-radius: 6px;
    }}
    .bubble.assistant {{
        align-self: flex-start;
        background: linear-gradient(135deg, #DCF0FF, #BFE7FF);
        color: #000;
        border-bottom-left-radius: 6px;
    }}
    .chat-input-area {{
        position: sticky;
        bottom: 0;
        background: transparent;
        padding-top: 8px;
    }}
    </style>
    """
    st.markdown(page_bg_img, unsafe_allow_html=True)

import streamlit as st
import streamlit.components.v1 as components

REMEMBER_LOCALSTORAGE_KEY = "remember_token"

# --- Utility: small client-side snippets for remember-me ----------------------
def inject_localstorage_redirect():
    """
    If the browser has a stored remember token in localStorage, redirect to add it as a
    query param so the server can pick it up and auto-login.
    This script will NOT do anything if the URL already has remember_token param.
    """
    js = f"""
    <script>
    (function(){{
      try {{
        const params = new URLSearchParams(window.location.search);
        if (!params.has('remember_token')) {{
          const t = localStorage.getItem('{REMEMBER_LOCALSTORAGE_KEY}');
          if (t) {{
            const baseUrl = window.location.href.split('?')[0];
            const sep = window.location.search.includes('?') ? '&' : '?';
            window.location.href = baseUrl + window.location.search + sep + 'remember_token=' + encodeURIComponent(t);
          }}
        }}
      }} catch(e){{console.log(e)}}
    }})();
    </script>
    """
    st.markdown(js, unsafe_allow_html=True)  # ⬅ safer than components.html here

def set_localstorage_token(token):
    """Set the remember token in browser localStorage (after login with Remember me)."""
    js = f"""
    <script>
    try {{
      localStorage.setItem('{REMEMBER_LOCALSTORAGE_KEY}','{token}');
    }} catch(e) {{console.log(e)}}
    </script>
    """
    st.markdown(js, unsafe_allow_html=True)

def clear_localstorage_token_and_reload():
    """Clear localStorage token and reload page (used for logout/forget device)."""
    js = f"""
    <script>
    try {{
      localStorage.removeItem('{REMEMBER_LOCALSTORAGE_KEY}');
      history.replaceState(null, '', window.location.pathname);
      window.location.reload();
    }} catch(e){{console.log(e)}}
    </script>
    """
    st.markdown(js, unsafe_allow_html=True)

'''

# --- Session state init -----------------------------------------------------
if "bot" not in st.session_state:
    st.session_state.bot = ConciergeBot()
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "guest_status" not in st.session_state:
    st.session_state.guest_status = None
if "pending_addon_request" not in st.session_state:
    st.session_state.pending_addon_request = []
# booking-specific state
if "booking_details" not in st.session_state:
    st.session_state.booking_details = {}
if "show_room_options" not in st.session_state:
    st.session_state.show_room_options = False
if "checkout_info" not in st.session_state:
    st.session_state.checkout_info = None
# staged booking confirmation
if "booking_to_confirm" not in st.session_state:
    st.session_state.booking_to_confirm = None
# user gate
if "user_profile" not in st.session_state:
    st.session_state.user_profile = None
# last results from fallback booking form (so we can offer Pay Later outside the form)
if "last_booking_form" not in st.session_state:
    st.session_state.last_booking_form = {}
# friendly labels for UI immediate feedback (not authoritative source-of-truth)
if "tab_items" not in st.session_state:
    st.session_state.tab_items = []


st.markdown("""
    <style>
    div.stButton > button[kind="formSubmit"] {
        background-color: #28a745;
        color: black;
        font-weight: bold;
        border-radius: 8px;
        padding: 0.5em 1em;
    }
    div.stButton > button[kind="formSubmit"]:hover {
        background-color: #218838;
        color: black;
    }
    </style>
""", unsafe_allow_html=True)

# --- Sidebar ----------------------------------------------------------------
with st.sidebar:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=180)
    st.markdown("### 🧾 Guest Status")
    with st.form("guest_status_form"):
        guest_option = st.radio("Are you staying at ILORA Retreat?", ["Yes", "No"])
        if st.form_submit_button("Submit"):
            st.session_state.guest_status = guest_option
    st.markdown("---")
    st.markdown("### 📞 Connect on WhatsApp")
    wa_qr = generate_qr_code_bytes(WHATSAPP_LINK)
    st.image(wa_qr, width=160, caption="Chat with us on WhatsApp")

    st.markdown("---")
    # Logout / Forget device control
    if st.session_state.get("user_profile"):
        if st.button("🔒 Logout & Forget this device"):
            # clear server-side token and localStorage
            try:
                clear_remember_token(st.session_state.user_profile["email"])
            except Exception:
                pass
            clear_localstorage_token_and_reload()
    else:
        st.markdown("Not logged in yet.")


# --- Main layout ------------------------------------------------------------
with st.container():
    st.markdown('<div class="main-content-box">', unsafe_allow_html=True)
    st.title("🏨 ILORA Retreat – Your AI Concierge")
    st.markdown("#### _Welcome to ILORA Retreat, where luxury meets the wilderness._")
    st.markdown("---")

    # ---- USERNAME + UID GATE (minimal, additive) ---------------------------
    init_user_db(USER_DB_PATH)

    # Attempt auto-login via localStorage token (client-side will redirect with remember_token)
    # Inject script which reads localStorage and adds remember_token param (only if param missing)
    if not st.session_state.get("user_profile"):
        inject_localstorage_redirect()
    
    
    # check for remember_token in URL params (populated by the JS redirect if present)
    # params = st.query_params
    remember_token_param = st.query_params.get("remember_token")
    print()
    print(remember_token_param)
    print()

    if remember_token_param and not st.session_state.user_profile:
        # lookup user by token
        row = get_user_by_token(remember_token_param)
        if row:
            # row -> (email, password, booked, id_proof_uploaded, due_items, remember_token)
            st.session_state.user_profile = {"email": row[0], "password": row[1], "booked": int(row[2] or 0), "id_proof_uploaded": int(row[3] or 0)}
            st.success(f"👋 Welcome back — you were remembered on this device as `{row[0]}`.")
            # remove remember_token from URL to avoid loops
            qp = st.query_params.to_dict()
            qp.pop("remember_token", None)
            st.query_params.from_dict(qp)

    if not st.session_state.user_profile:
        st.markdown("### 🔐 Log In to your personal Ilora Assistant")
        with st.form("user_gate_form"):
            in_email = st.text_input("Email")
            in_password = st.text_input("Password", type="password")
            remember_choice = True
            proceed = st.form_submit_button("Continue")
        if not proceed:
            st.info("👉 Please enter your **Email** and **Password** to continue.")
            st.markdown('</div>', unsafe_allow_html=True)
            st.stop()
        if in_email and in_password:
            ensure_user(in_email, in_password)
            row = get_user_row(in_email)
            st.session_state.user_profile = {
                "email": row[0],
                "password": row[1],
                "booked": int(row[2] or 0),
                "id_proof_uploaded": int(row[3] or 0),
            }
            # Set remember token if asked
            if remember_choice:
                token = uuid.uuid4().hex
                set_remember_token(in_email, token)
                # store in browser localStorage
                set_localstorage_token(token)
                st.success("✅ We'll remember you on this device.")
        else:
            st.warning("Please fill both Username and UID.")
            st.markdown('</div>', unsafe_allow_html=True)
            st.stop()

    email = st.session_state.user_profile["email"]
    password = st.session_state.user_profile["password"]
    booked_flag = int(st.session_state.user_profile["booked"])
    id_uploaded_flag = int(st.session_state.user_profile["id_proof_uploaded"])
    
    # status row
    due_items_now = get_due_items(email)
    due_total_now = due_total_from_items(due_items_now)
    st.markdown(
        f"**UID:** `{email}`  |  "
        f"**Booked:** {'✅' if booked_flag else '❌'}  |  "
        f"**ID Proof:** {'✅' if id_uploaded_flag else '❌'}  |  "
        f"**Pending Balance:** ₹{due_total_now}"
    )
    st.markdown("---")

    # ---- Mobile access QR
    st.markdown("### 📱 Access this Assistant on Mobile")
    qr_img = generate_qr_code_bytes(QR_LINK)
    st.image(qr_img, width=180, caption="Scan to open on your phone")
    st.markdown("---")

    html = '<div class="chat-window" id="chat-window">'
    # show chat history
    for role, msg in st.session_state.chat_history:
        safe_msg = str(msg).replace("\n", "<br>")
        if role == "user":
            html += f'<div class="bubble user">{safe_msg}</div>'
        else:
            html += f'<div class="bubble assistant">{safe_msg}</div>'

    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)
    # scroll-to-bottom snippet
    components.html("<script>var el=document.getElementById('chat-window'); if(el){el.scrollTop = el.scrollHeight;}</script>", height=0)

    # chat input
    st.markdown("### 💬 Concierge Chat")
    user_input = st.chat_input("Ask me anything about ILLORA Retreat")
    coming_from = "Web"

    if user_input:
        st.session_state.user_input = user_input
        st.session_state.predicted_intent = classify_intent(user_input)
        st.chat_message("user").markdown(user_input)
        st.session_state.chat_history.append(("user", user_input))

        # detect add-on mentions
        message_lower = user_input.lower()
        addon_matches = [k for k in AVAILABLE_EXTRAS if k.lower() in message_lower]
        st.session_state.pending_addon_request = addon_matches if addon_matches else []

        with st.spinner("🤖 Thinking..."):
            is_guest = st.session_state.guest_status == "Yes"
            response = "🤖  " +st.session_state.bot.ask(user_input, user_type=is_guest)
            st.session_state.response = response
            log_chat(coming_from, st.session_state.session_id, user_input, response,
                     st.session_state.predicted_intent, is_guest)

        st.chat_message("assistant").markdown(response)
        st.session_state.chat_history.append(("assistant", response))
    



    # --- Add-on quick flow (extended with Pay Later) -------------------------
    if st.session_state.get("pending_addon_request"):
        st.markdown("### 🧾 Confirm Add-on Services")
        chosen_labels = st.session_state.pending_addon_request
        st.info(f"Would you like to proceed with: {', '.join(chosen_labels)}?")
        col1, col2, col3 = st.columns(3)
        pending_keys = [AVAILABLE_EXTRAS[k] for k in chosen_labels if k in AVAILABLE_EXTRAS]

        with col1:
            confirm = st.button("💳 Pay Now (generate link)")
        with col2:
            pay_later = st.button("⏳ Pay Later")
        with col3:
            cancel = st.button("❌ Cancel")

        if confirm:
            addon_url = create_addon_checkout_session(session_id=st.session_state.session_id, extras=pending_keys)
            if addon_url:
                st.success("🧾 Add-on payment link generated.")
                st.markdown(f"[💳 Pay for Add-ons]({addon_url})", unsafe_allow_html=True)
                st.image(generate_qr_code_bytes(addon_url), width=220, caption="Scan to open add-on payment")
            else:
                st.error("⚠️ Could not generate payment link.")
            st.session_state.pending_addon_request = []

        if pay_later:
            # accumulate in user DB; sum will be computed from MENU at checkout time
            added = add_due_items(email, pending_keys)
            if added:
                # immediate friendly labels for the UI
                st.session_state.tab_items.extend([KEY_TO_LABEL.get(k, k.replace("_"," ").title()) for k in pending_keys])
                total_now = due_total_from_items(get_due_items(email))
                st.success(f"⏳ Added to your tab. Current pending balance: ₹{total_now}")
            else:
                st.warning("No add-ons were added to your tab (unknown or empty selection).")
            st.session_state.pending_addon_request = []

        if cancel:
            st.session_state.pending_addon_request = []

    
    st.markdown(
    """
    <style>
    .dark-container {
        background: rgba(0, 0, 0, 0.7); /* dark transparent background */
        padding: 20px;
        border-radius: 12px;
        margin-bottom: 20px;
        color: white; /* make text visible on dark bg */
    }
    .dark-container h3, 
    .dark-container h4, 
    .dark-container h2, 
    .dark-container strong {
        color: #f5f5f5; /* ensure headings/labels are bright */
    }
    </style>
    """,
    unsafe_allow_html=True, 
    )

    st.markdown('<div class="dark-container">', unsafe_allow_html=True)
    # --- Pre-check-in booking intent handling (kept) -------------------------
    if st.session_state.get("predicted_intent") in ("payment_request", "booking_request"):
        st.markdown("### 🛏️ Start Booking (Pre-check-in)")
        with st.form("booking_dates_form"):
            check_in = st.date_input("Check-in Date", value=date.today())
            check_out = st.date_input("Check-out Date", value=date.today())
            guests = st.number_input("Number of guests", min_value=1, step=1, value=2)
            preferences = st.text_input("Preferences (e.g., king bed, vegetarian breakfast)")
            collect_whatsapp = st.text_input("WhatsApp number (optional, E.164, e.g. +9198... )", value="")
            submitted = st.form_submit_button("Show available rooms")
            if submitted:
                st.session_state.booking_details = {
                    "check_in": check_in,
                    "check_out": check_out,
                    "guests": guests,
                    "preferences": preferences,
                    "whatsapp_number": collect_whatsapp.strip()
                }
                st.session_state.show_room_options = True

    # --- Show room options using DB + dynamic pricing (kept) -----------------
    if st.session_state.get("show_room_options"):
        st.markdown("### 🏨 Available Rooms & Media Previews")
        db = SessionLocal()
        try:
            rooms = db.query(Room).all()
            if not rooms:
                st.warning("No rooms found in DB. Seed rooms first.")
            else:
                ci = st.session_state.booking_details["check_in"]
                co = st.session_state.booking_details["check_out"]
                if isinstance(ci, str):
                    ci = datetime.fromisoformat(ci).date()
                if isinstance(co, str):
                    co = datetime.fromisoformat(co).date()

                for r in rooms:
                    try:
                        price, nights = calculate_price(db, r, ci, co)
                    except Exception:
                        price, nights = r.base_price, 1

                    cols = st.columns([1, 2])
                    with cols[0]:
                        first_media = (r.media or [None])[0]
                        if first_media:
                            if "youtube" in first_media or "youtu.be" in first_media:
                                thumb = youtube_thumbnail(first_media)
                                if thumb:
                                    st.image(thumb, caption=f"{r.name} — ₹{price} total ({nights} nights)")
                                else:
                                    st.write(f"{r.name} — ₹{price} total ({nights} nights)")
                            else:
                                thumb = instagram_oembed_thumb(first_media)
                                if thumb:
                                    st.image(thumb, caption=f"{r.name} — ₹{price} total ({nights} nights)")
                                else:
                                    st.image(first_media, caption=f"{r.name} — ₹{price} total ({nights} nights)")
                        else:
                            st.write(f"**{r.name}** — ₹{price} total ({nights} nights)")

                    with cols[1]:
                        st.write(f"**{r.name}** — {r.room_type}")
                        st.write(f"Capacity: {r.capacity}  • Units: {r.total_units}")
                        st.write(f"**Total: ₹{price}** for {nights} nights")
                        for m in (r.media or []):
                            if "youtube" in m or "youtu.be" in m:
                                st.video(m)

                        # ---------- Booking: start (stage) ----------
                        start_key = f"start_book_{r.id}"
                        if st.button(f"Book {r.name} — ₹{price}", key=start_key):
                            st.session_state.booking_to_confirm = {
                                "booking_id": str(uuid.uuid4()),
                                "room_id": r.id,
                                "room_name": r.name,
                                "check_in": ci.isoformat(),
                                "check_out": co.isoformat(),
                                "price": price,
                                "nights": nights,
                                "guest_name": (st.session_state.get("user_input") or email or "Guest"),
                                "guest_phone": st.session_state.booking_details.get("whatsapp_number", "")
                            }

                        # ---------- If staged booking matches this room, show confirm UI ----------
                        btc = st.session_state.get("booking_to_confirm")
                        if btc and btc.get("room_id") == r.id:
                            st.markdown("---")
                            st.markdown(f"**Confirm booking for**: **{btc['room_name']}**  •  ₹{btc['price']}  •  {btc['nights']} nights")
                            payment_method = st.selectbox("Payment Method", ["Online", "Cash on Arrival"], key=f"pm_{r.id}")
                            notes = st.text_input("Special requests (optional)", value=st.session_state.booking_details.get("preferences",""), key=f"notes_{r.id}")

                            col_confirm, col_cancel = st.columns([1,1])
                            with col_confirm:
                                if st.button("✅ Confirm & Create Payment", key=f"confirm_{r.id}"):
                                    booking_id = btc["booking_id"]
                                    try:
                                        booking = Booking(
                                            id=booking_id,
                                            guest_name=btc["guest_name"],
                                            guest_phone=btc["guest_phone"],
                                            room_id=btc["room_id"],
                                            check_in=datetime.fromisoformat(btc["check_in"]).date(),
                                            check_out=datetime.fromisoformat(btc["check_out"]).date(),
                                            price=btc["price"],
                                            status=BookingStatus.pending,
                                            channel="web",
                                            channel_user=btc["guest_phone"] or None
                                        )
                                        db.add(booking)
                                        db.commit()
                                    except Exception as e:
                                        db.rollback()
                                        st.error(f"Failed to create booking record: {e}")
                                        st.session_state.booking_to_confirm = None
                                        raise

                                    checkout_url = None
                                    stripe_session_id = None
                                    try:
                                        with st.spinner("Creating payment session..."):
                                            stripe_sess = create_checkout_session(
                                                session_id=booking_id,
                                                room_type=r.name,
                                                nights=btc["nights"],
                                                cash=(payment_method == "Cash on Arrival"),
                                                extras=[]
                                            )
                                            checkout_url = _checkout_url_from_session(stripe_sess)
                                            if hasattr(stripe_sess, "id"):
                                                stripe_session_id = getattr(stripe_sess, "id")
                                            elif isinstance(stripe_sess, dict) and "id" in stripe_sess:
                                                stripe_session_id = stripe_sess.get("id")
                                    except Exception as e:
                                        db.rollback()
                                        st.error(f"Failed to create checkout session: {e}")
                                        st.session_state.booking_to_confirm = None
                                        raise

                                    try:
                                        if stripe_session_id:
                                            if hasattr(booking, "stripe_session_id"):
                                                booking.stripe_session_id = stripe_session_id
                                            else:
                                                setattr(booking, "stripe_session_id", stripe_session_id)
                                            db.commit()
                                    except Exception:
                                        db.rollback()

                                    local_qr_path = None
                                    public_qr = None
                                    if checkout_url:
                                        try:
                                            qr_filename = f"checkout_{booking_id}.png"
                                            local_qr_path, public_qr = save_qr_to_static(checkout_url, qr_filename)
                                            try:
                                                if hasattr(booking, "qr_path"):
                                                    booking.qr_path = public_qr
                                                else:
                                                    setattr(booking, "qr_path", public_qr)
                                                db.commit()
                                            except Exception:
                                                db.rollback()
                                        except Exception:
                                            pass

                                        # show checkout link & QR
                                        st.success("Checkout created — complete payment to confirm booking.")
                                        st.markdown(f"[💳 Proceed to payment]({checkout_url})", unsafe_allow_html=True)
                                        st.image(generate_qr_code_bytes(checkout_url), width=240, caption="Scan to open payment on mobile")

                                        # --- TESTING: require ID proof upload immediately if toggle is set ---
                                        if TESTING_FORCE_ID_AFTER_PAYMENT:
                                            st.info("🔒 Testing mode: please upload your ID proof now to unlock full bot access and continue.")
                                            id_file = st.file_uploader("Upload ID proof (JPG/PNG/PDF) — required for testing", type=["jpg","jpeg","png","pdf"], key=f"id_{booking_id}")
                                            set_id_proof(email, 1)
                                            set_booked(email,1)
                                            if id_file is not None:
                                                ext = Path(id_file.name).suffix.lower() or ".bin"
                                                save_path = UPLOAD_DIR / f"{email}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
                                                with open(save_path, "wb") as f:
                                                    f.write(id_file.read())
                                                set_id_proof(email, 1)

                                                st.session_state.user_profile["id_proof_uploaded"] = 1
                                                st.success("✅ ID proof submitted. Full access enabled!")
                                                # mark user as 'booked' for testing
                                                set_booked(email, 1)
                                                st.session_state.user_profile["booked"] = 1
                                                # auto-advance: store checkout_info and clear booking_to_confirm
                                                st.session_state.checkout_info = {
                                                    "booking_id": booking_id,
                                                    "room_name": r.name,
                                                    "price": btc["price"],
                                                    "nights": btc["nights"],
                                                    "checkout_url": checkout_url,
                                                    "qr_local": local_qr_path,
                                                    "qr_public": public_qr
                                                }
                                                st.session_state.booking_to_confirm = None
                                                # refresh the app so UI updates reflect new profile flags
                                                st.rerun()
                                            else:
                                                st.warning("Please upload your ID proof to continue (testing).")
                                        else:
                                            # not forcing upload in testing, keep the existing optional behavior
                                            st.info("🔒 For testing/demo: you can upload your ID proof here to unlock full bot access.")
                                            id_file = st.file_uploader("Upload ID proof (JPG/PNG/PDF)", type=["jpg","jpeg","png","pdf"], key=f"idopt_{booking_id}")
                                            if id_file is not None:
                                                ext = Path(id_file.name).suffix.lower() or ".bin"
                                                save_path = UPLOAD_DIR / f"{email}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
                                                with open(save_path, "wb") as f:
                                                    f.write(id_file.read())
                                                set_id_proof(email, 1)
                                                st.session_state.user_profile["id_proof_uploaded"] = 1
                                                st.success("✅ ID proof submitted. Full access enabled!")
                                                # mark user as 'booked' for testing
                                                set_booked(email, 1)
                                                st.session_state.user_profile["booked"] = 1
                                        # store checkout info for further viewing
                                        st.session_state.checkout_info = {
                                            "booking_id": booking_id,
                                            "room_name": r.name,
                                            "price": btc["price"],
                                            "nights": btc["nights"],
                                            "checkout_url": checkout_url,
                                            "qr_local": local_qr_path,
                                            "qr_public": public_qr
                                        }
                                    else:
                                        st.warning("Checkout created but no public URL was returned. Check your payment gateway implementation or Stripe SDK version.")

                                    st.session_state.booking_to_confirm = None

                            with col_cancel:
                                if st.button("❌ Cancel booking", key=f"cancel_{r.id}"):
                                    st.session_state.booking_to_confirm = None
                                    st.info("Booking cancelled.")

        finally:
            db.close()
    st.markdown('</div>', unsafe_allow_html=True)

    # --- Show checkout summary if created (kept) -----------------------------
    if st.session_state.get("checkout_info"):
        info = st.session_state.checkout_info
        st.markdown("---")
        st.markdown("### ✅ Booking Created (Pending Payment)")
        st.write(f"Booking ID: `{info['booking_id']}`")
        st.write(f"Room: **{info['room_name']}**")
        st.write(f"Amount: ₹{info['price']}")
        if info.get("checkout_url"):
            st.markdown(f"[Click here to pay]({info['checkout_url']})")
        st.markdown("After successful payment Stripe will call your webhook and finalize the booking (generate final QR & send WhatsApp if WhatsApp number provided).")

    # --- Fallback booking form (kept intact) --------------------------------
    if st.session_state.get("predicted_intent") == "payment_request" and not st.session_state.get("pending_addon_request"):
        st.markdown("### 🛏️ Book a Room / Add-on Services (Fallback)")
        # Clear last_booking_form when entering the form area so stale data doesn't confuse the UI
        st.session_state.last_booking_form = {}

        with st.form("booking_form"):
            room_type = st.selectbox("Room Type (optional)", ["None", "Safari Tent", "Star Bed Suite", "double Room", "family", "suite"])
            nights = st.number_input("Number of nights", min_value=1, step=1, value=1)
            payment_method = st.radio("Payment Method", ["Online", "Cash on Arrival"])
            price_map = {
                "Safari Tent": 12000, "Star Bed Suite": 18000,
                "double room": 10000, "suite": 34000, "family": 27500
            }
            if room_type != "None":
                price_key = room_type if room_type in price_map else room_type.lower()
                room_price = price_map.get(price_key, None)
                if room_price is None:
                    st.warning("Price not found for selected room (check fallback price_map keys).")
                else:
                    st.markdown(f"💰 **Room Total: ₹{room_price * nights}**")
            else:
                st.markdown("💡 You can skip room booking and only pay for add-ons.")
            st.markdown("### 🧖‍♀️ Optional Add-ons")
            selected_extras = st.multiselect("Choose your add-ons:", list(AVAILABLE_EXTRAS.keys()))
            if st.form_submit_button("✅ Proceed"):
                room_selected = room_type != "None"
                any_addon_selected = len(selected_extras) > 0

                # prepare selection keys (normalized)
                selection_keys = [AVAILABLE_EXTRAS[item] for item in selected_extras if item in AVAILABLE_EXTRAS]

                # store what was selected so we can show Pay Later outside of the form
                st.session_state.last_booking_form = {
                    "room_selected": room_selected,
                    "room_type": room_type,
                    "nights": nights,
                    "room_price": (room_price * nights) if (room_type != "None" and room_price is not None) else None,
                    "selected_extras": selected_extras,
                    "selected_extra_keys": selection_keys,
                    "payment_method": payment_method
                }

                if room_selected:
                    room_url = create_checkout_session(
                        session_id=st.session_state.session_id,
                        room_type=room_type,
                        nights=nights,
                        cash=(payment_method == "Cash on Arrival"),
                        extras=[]
                    )
                    if room_url:
                        st.success("✅ Room booking link generated.")
                        st.markdown(f"[💳 Pay for Room Booking]({room_url})", unsafe_allow_html=True)
                        st.image(generate_qr_code_bytes(room_url), width=220, caption="Scan to open room payment")
                        # ask ID proof (testing)
                        if TESTING_FORCE_ID_AFTER_PAYMENT:
                            st.info("🔒 Testing mode: please upload your ID proof now to unlock full bot access.")
                            id_file_fb = st.file_uploader("Upload ID proof (JPG/PNG/PDF) — required for testing", type=["jpg","jpeg","png","pdf"], key="id_fb")
                            set_id_proof(email, 1)
                            set_booked(email,1)
                            if id_file_fb is not None:
                                ext = Path(id_file_fb.name).suffix.lower() or ".bin"
                                save_path = UPLOAD_DIR / f"{email}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
                                with open(save_path, "wb") as f:
                                    f.write(id_file_fb.read())
                                set_id_proof(email, 1)
                                st.session_state.user_profile["id_proof_uploaded"] = 1
                                st.success("✅ ID proof submitted. Full access enabled!")
                                set_booked(email, 1)
                                st.session_state.user_profile["booked"] = 1
                                st.rerun()
                        else:
                            st.info("🔒 For testing: please upload your ID proof to unlock full bot access.")
                            id_file_fb = st.file_uploader("Upload ID proof (JPG/PNG/PDF)", type=["jpg","jpeg","png","pdf"], key="id_fb_opt")
                            set_id_proof(email, 1)
                            set_booked(email,1)
                            if id_file_fb is not None:
                                ext = Path(id_file_fb.name).suffix.lower() or ".bin"
                                save_path = UPLOAD_DIR / f"{email}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
                                with open(save_path, "wb") as f:
                                    f.write(id_file_fb.read())
                                set_id_proof(email, 1)
                                st.session_state.user_profile["id_proof_uploaded"] = 1
                                st.success("✅ ID proof submitted. Full access enabled!")
                                set_booked(email, 1)
                                st.session_state.user_profile["booked"] = 1
                    else:
                        st.error("⚠️ Room payment link generation failed.")

                if any_addon_selected:
                    # Offer Pay Now (link) - generation here is immediate and shown inside the form result
                    addon_url = create_addon_checkout_session(session_id=st.session_state.session_id, extras=selection_keys)
                    if addon_url:
                        st.success("🧾 Add-on payment link generated.")
                        st.markdown(f"[💳 Pay for Add-ons]({addon_url})", unsafe_allow_html=True)
                        st.image(generate_qr_code_bytes(addon_url), width=220, caption="Scan to open add-on payment")
                    else:
                        st.error("⚠️ Add-on payment link generation failed.")

                if not room_selected and not any_addon_selected:
                    st.warning("⚠️ Please select a room or at least one add-on to proceed.")

        # --- OUTSIDE the form: Pay Later for the last selected add-ons ----------
        lf = st.session_state.get("last_booking_form", {})
        selected_keys = lf.get("selected_extra_keys", []) if lf else []
        selected_labels = lf.get("selected_extras", []) if lf else []

        if lf and selected_keys:
            st.markdown("#### Add-ons from your last booking attempt")
            if selected_labels:
                st.write(", ".join(selected_labels))

            # Standalone Pay Later button (not inside a form)
            if st.button("⏳ Add selected add-ons to tab (Pay Later)", key="pay_later_booking"):
                # defensive check
                if not selected_keys:
                    st.warning("No add-ons selected (already added or cleared).")
                else:
                    added = add_due_items(email, selected_keys)
                    if added:
                        # add friendly labels for immediate UI feedback
                        st.session_state.tab_items.extend([KEY_TO_LABEL.get(k, k.replace("_"," ").title()) for k in selected_keys])
                        new_total = due_total_from_items(get_due_items(email))
                        st.success(f"⏳ Added to your tab. Current pending balance: ₹{new_total}")
                        # clear saved selection to avoid duplicate adds if user clicks again
                        st.session_state.last_booking_form["selected_extra_keys"] = []
                    else:
                        st.warning("Could not add selected add-ons (unknown keys or empty selection).")
        elif lf and not selected_keys:
            if lf.get("selected_extras"):
                st.info("Selected add-ons already processed or none available to add to tab.")
            else:
                pass

    # --- show friendly tab items (immediate feedback) -----------------------
    if st.session_state.tab_items:
        st.markdown("### 📝 Items added to tab (local preview)")
        counts = Counter(st.session_state.tab_items)
        for label, qty in counts.items():
            st.write(f"- **{label}** × {qty}")

    # --- NEW: Checkout Pending Balance (improved) ----------------------------
    st.markdown("---")
    st.markdown("### 🚪 Checkout — Pay Remaining Balance")
    due_items = get_due_items(email)
    pending_amt = 0
    if due_items:
        pending_amt = 0
        details, pending_amt = get_due_items_details(email)
        print(pending_amt)
        st.info(f"🧾 You have **₹{pending_amt}** pending for the following items:")
        rows = []
        for d in details:
            rows.append(f"- **{d['label']}**  × {d['qty']}  →  ₹{d['unit_price']} each  •  **₹{d['line_total']}**")
        st.markdown("\n".join(rows))

        pay_col, mark_col = st.columns([2, 1])
        with pay_col:
            if st.button("💳 Pay Pending Balance"):
                due_url = create_pending_checkout_session(pending_amt)
                if due_url:
                    st.success("✅ Payment link generated for pending balance.")
                    st.markdown(f"[Pay Pending Balance]({due_url})", unsafe_allow_html=True)
                    st.image(generate_qr_code_bytes(due_url), width=220, caption="Scan to open pending payment")
                else:
                    st.error("⚠️ Could not generate payment link for pending balance.")
        with mark_col:
            if st.button("✔️ Mark pending as paid (testing)", key="mark_paid_test"):
                clear_due_items(email)
                st.session_state.tab_items = []
                st.success("✅ Pending items cleared (testing).")
    else:
        st.success("No pending balance. You're all set!")

    st.markdown('</div>', unsafe_allow_html=True)
'''

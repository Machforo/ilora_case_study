# dashboard_live.py (updated)
import os
import time
import requests
import pandas as pd
import streamlit as st
from datetime import date, datetime

# --------- CONFIG ---------
API = os.getenv("AIC_API", "http://localhost:5002")  # FastAPI base
st.set_page_config(page_title="AI Chieftain – Live Admin", layout="wide")

st.title("ILLORA RETREATS – Live Admin Dashboard")

# --- Utility ---
def to_df(bookings_json):
    """Accepts either {'bookings': [...]} or a raw list and returns a DataFrame with parsed dates."""
    if not bookings_json:
        return pd.DataFrame()
    if isinstance(bookings_json, dict) and "bookings" in bookings_json:
        data = bookings_json["bookings"] or []
    elif isinstance(bookings_json, list):
        data = bookings_json
    else:
        # unknown shape
        return pd.DataFrame()

    df = pd.DataFrame(data)
    for col in ["check_in", "check_out"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    return df

def fetch_bookings():
    """
    Try multiple endpoints (DB-backed then demo) and return a DataFrame.
    Endpoints tried (in order):
      - /bookings/all_db         (your main.py)
      - /bookings                (compat)
      - /bookings/all            (compat)
      - /demo/bookings/all       (demo in-memory)
    """
    endpoints = [
        f"{API}/bookings/all_db",
        f"{API}/bookings",
        f"{API}/bookings/all",
        f"{API}/demo/bookings/all",
    ]
    last_exc = None
    for url in endpoints:
        try:
            r = requests.get(url, timeout=20)
            # Accept 200; if 404/405 try next
            if r.status_code == 200:
                try:
                    data = r.json()
                except ValueError:
                    # non-json
                    continue
                df = to_df(data)
                return df
            else:
                # record last error and try next endpoint
                last_exc = Exception(f"{url} -> {r.status_code} {r.text}")
                continue
        except requests.RequestException as e:
            last_exc = e
            continue

    # if none succeeded, raise to caller
    raise last_exc or Exception("No bookings endpoint available")

def fetch_chats(limit=200):
    """
    Attempt to fetch recent chats from multiple possible endpoints.
    If none exist on the backend, returns an empty DataFrame and does not crash.
    """
    endpoints = [
        f"{API}/chats?limit={limit}",
        f"{API}/chats/all?limit={limit}",
        f"{API}/chat/messages?limit={limit}",
        f"{API}/chats/messages?limit={limit}",
    ]
    for url in endpoints:
        try:
            r = requests.get(url, timeout=20)
            if r.status_code != 200:
                continue
            try:
                payload = r.json()
            except ValueError:
                continue

            # payload might be {"messages": [...]} or list
            if isinstance(payload, dict) and "messages" in payload:
                msgs = payload["messages"] or []
            elif isinstance(payload, list):
                msgs = payload
            else:
                # try to find anything like messages key
                msgs = payload.get("data") if isinstance(payload, dict) else []
            df = pd.DataFrame(msgs)
            # make sure created_at exists for sorting
            if "created_at" in df.columns:
                df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
            return df
        except requests.RequestException:
            continue

    # No chat endpoint exposed; return empty DF with expected columns
    return pd.DataFrame(columns=["created_at", "session_id", "email", "role", "text", "intent"])

def patch_booking(booking_id, payload):
    """
    Try DB update endpoint first (/bookings/{id}/update) then fallback to demo (/demo/bookings/{id}).
    Returns the response JSON on success or raises an exception.
    """
    # Try DB update route used in main.py
    db_update_url = f"{API}/bookings/{booking_id}/update"
    demo_update_url = None
    try:
        # attempt DB update
        r = requests.patch(db_update_url, json=payload, timeout=20)
        if r.status_code in (200, 201):
            return r.json()
        # if 404, try demo update below
        if r.status_code == 404:
            # fall through to demo fallback
            pass
        else:
            r.raise_for_status()
    except requests.HTTPError as he:
        # if server returned 404 or other error, we'll try demo fallback
        if r is not None and r.status_code == 404:
            pass
        else:
            raise
    except requests.RequestException:
        # network error or other; try demo fallback
        pass

    # fallback: if booking_id is numeric, try demo in-memory update
    try:
        int_id = int(booking_id)
    except Exception:
        int_id = None

    if int_id is not None:
        demo_update_url = f"{API}/demo/bookings/{int_id}"
        try:
            r2 = requests.patch(demo_update_url, json=payload, timeout=20)
            r2.raise_for_status()
            return r2.json()
        except requests.RequestException as e:
            # bubble up a helpful error
            raise Exception(f"Both DB and demo update failed: DB-> {db_update_url}, Demo-> {demo_update_url}. Last error: {e}")

    # if booking_id not numeric or demo fallback unavailable, raise
    raise Exception(f"Failed to update booking {booking_id}. Tried {db_update_url} and no demo fallback available.")

# --- Controls row ---
colL, colM, colR = st.columns([1, 1, 2])
with colL:
    if st.button("Seed 20 Sample Bookings"):
        try:
            # main.py exposes POST /admin/seed with query param "count"
            r = requests.post(f"{API}/admin/seed?count=20", timeout=60)
            if r.status_code == 200:
                st.success(r.json())
                # refresh after seeding
                time.sleep(0.3)
                st.experimental_rerun()
            else:
                st.error(f"Seed failed: {r.status_code} {r.text}")
        except Exception as e:
            st.error(str(e))
with colM:
    refresh_sec = st.number_input("Auto-refresh (seconds)", min_value=3, max_value=60, value=5, step=1)
with colR:
    st.caption("Tip: This dashboard auto-refreshes. Your React frontend can subscribe to `/events` for push updates.")

# --- Auto refresh ---
try:
    st.cache_data.clear()
    st.cache_resource.clear()
except Exception:
    # older streamlit may not have these APIs
    pass

if "last_refresh" not in st.session_state:
    st.session_state["last_refresh"] = time.time()

if time.time() - st.session_state["last_refresh"] > refresh_sec:
    st.session_state["last_refresh"] = time.time()
    st.rerun()

# --- Data fetch ---
try:
    df = fetch_bookings()
except Exception as e:
    st.error(f"Failed to load bookings: {e}")
    df = pd.DataFrame()

# --- KPIs ---
with st.container():
    c1, c2, c3, c4 = st.columns(4)
    total = len(df)

    revenue = 0.0
    if "price" in df.columns:
        revenue = float(df["price"].fillna(0).sum())
    elif "amount" in df.columns:
        revenue = float(df["amount"].fillna(0).sum())

    today = date.today()
    todays_checkins = 0
    if "check_in" in df.columns:
        todays_checkins = int((df["check_in"] == today).sum())

    occ = 0
    if "status" in df.columns and len(df) > 0:
        # handle both "status" strings and enums that may be present
        occ = int((
            df["status"].astype(str).str.upper().isin(["CHECKED_IN", "CONFIRMED"]).sum()
            / max(1, len(df))
        ) * 100)

    c1.metric("Total Bookings", total)
    c2.metric("Revenue (quoted)", f"₹ {int(revenue):,}")
    c3.metric("Today's Check-ins", todays_checkins)
    c4.metric("Occupancy (rough)", f"{occ}%")

st.markdown("---")

# --- Bookings table + quick editor ---
st.subheader("Bookings")
if df.empty:
    st.info("No bookings yet.")
else:
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("### Edit a booking")
    with st.form("edit_booking"):
        bid = st.text_input("Booking ID")
        new_status = st.selectbox("Status", ["", "PENDING", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED"])
        new_price = st.number_input("Price (₹)", min_value=0, step=100, value=0)
        new_guest_name = st.text_input("Guest name")
        submitted = st.form_submit_button("Apply Update")
        if submitted:
            payload = {}
            if new_status:
                # backend expects status string; main.py maps it to enum server-side
                payload["status"] = new_status
            if new_price:
                # DB booking uses 'price'; demo uses 'amount' — include both where appropriate
                payload["price"] = new_price
            if new_guest_name:
                # DB uses guest_name; demo in-memory uses guest
                payload["guest_name"] = new_guest_name
                payload["guest"] = new_guest_name
            try:
                resp = patch_booking(bid, payload)
                st.success(f"Updated: {resp}")
                st.experimental_rerun()
            except Exception as e:
                st.error(str(e))

st.markdown("---")

# --- Chats tab ---
st.subheader("Conversations")
try:
    chats = fetch_chats(limit=300)
    if chats.empty:
        st.info("No chat-list endpoint available on the backend or no messages found.")
    else:
        # simple filters
        cA, cB = st.columns(2)
        with cA:
            f_email = st.text_input("Filter by email")
        with cB:
            f_session = st.text_input("Filter by session_id")

        if f_email:
            chats = chats[chats["email"].fillna("").str.contains(f_email, case=False)]
        if f_session:
            chats = chats[chats["session_id"].fillna("").str.contains(f_session, case=False)]

        # Ensure created_at exists and sort
        if "created_at" in chats.columns:
            chats = chats.sort_values("created_at", ascending=False)
        st.dataframe(chats, use_container_width=True, hide_index=True)
except Exception as e:
    st.error(f"Failed to load chats: {e}")

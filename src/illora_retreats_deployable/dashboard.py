# app/admin/dashboard.py

import pandas as pd
import streamlit as st
import os
import plotly.express as px
import re
from datetime import datetime, date
import json
import helper.summarizer as summarizer
import uuid

# run summarizer (keeps existing behaviour)
summarizer.main()
LOG_FILE = "data\\bot.log"
SUMMARY_PATH = "data\\summary_log.jsonl"

st.set_page_config(page_title="ILLORA_RETREATS – Admin Console", layout="wide")
st.title("🏨 Illora Retreats – Concierge AI Admin Dashboard")

# --- Helpers ---
def load_json(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2)
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def ensure_csv(path, cols):
    if not os.path.exists(path):
        pd.DataFrame(columns=cols).to_csv(path, index=False)
    return pd.read_csv(path)

# --- Data Sources ---
QA_CSV = "data\\qa_pairs.csv"
MENU_FILE = "services\\menu.json"
CAMPAIGNS_FILE = "data\\campaigns.json"

# --- Tabs ---
tabs = st.tabs(["📊 Analytics", "✅ UserInformation", "💬 Q&A Manager", "🏷️ Menu Manager", "📢 Campaigns Manager", "✅ Do's & ❌ Don'ts Manager", "🤖 Agents"])




# ======================================================
# 📊 ANALYTICS TAB
# ======================================================
with tabs[0]:
    if not os.path.exists(LOG_FILE):
        st.warning("No logs found yet.")
        st.stop()

    # --- Parse logs ---
    log_lines = []
    with open(LOG_FILE, "r", encoding="ISO-8859-1") as f:
        for line in f:
            parts = [part.strip() for part in line.strip().split("|")]
            if len(parts) >= 8:
                timestamp = parts[0]
                source = parts[3]
                session_id = parts[4]
                user_input = parts[5]
                response = parts[6]
                guest_type = parts[7]
                intent_match = re.search(r"Intent: (.+)", line)
                intent = intent_match.group(1) if intent_match else "Unknown"
                log_lines.append([timestamp, source, session_id, user_input, response, intent, guest_type])

    df = pd.DataFrame(
        log_lines,
        columns=["Timestamp", "Source", "Session ID", "User Input", "Response", "Intent", "Guest Type"],
    )
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df["Date"] = df["Timestamp"].dt.date

    # --- Sidebar filters ---
    st.sidebar.header("🔍 Filter Analytics")
    source_filter = st.sidebar.selectbox("📱 Channel", ["All"] + sorted(df["Source"].unique().tolist()))
    intent_filter = st.sidebar.selectbox("🎯 Intent", ["All"] + sorted(df["Intent"].unique().tolist()))
    guest_filter = st.sidebar.selectbox("🏷️ Guest Type", ["All", "Guest", "Non-Guest"])

    filtered_df = df.copy()
    if source_filter != "All":
        filtered_df = filtered_df[filtered_df["Source"] == source_filter]
    if intent_filter != "All":
        filtered_df = filtered_df[filtered_df["Intent"] == intent_filter]
    if guest_filter != "All":
        filtered_df = filtered_df[filtered_df["Guest Type"].str.lower() == guest_filter.lower()]

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🗨️ Total Interactions", len(filtered_df))
    col2.metric("👥 Unique Sessions", filtered_df["Session ID"].nunique())
    col3.metric("🔍 Unique Intents", filtered_df["Intent"].nunique())
    col4.metric("🏷️ Guest Type", guest_filter if guest_filter != "All" else "All Types")

    st.markdown("---")

    # Graphs
    st.subheader("Guest vs Non-Guest Breakdown")
    guest_counts = df["Guest Type"].value_counts().reset_index()
    guest_counts.columns = ["Guest Type", "Messages"]
    st.plotly_chart(px.pie(guest_counts, names="Guest Type", values="Messages"), use_container_width=True)

    st.subheader("Channel Distribution")
    source_counts = filtered_df["Source"].value_counts().reset_index()
    source_counts.columns = ["Channel", "Messages"]
    st.plotly_chart(px.pie(source_counts, names="Channel", values="Messages"), use_container_width=True)

    st.subheader("Daily Interaction Volume")
    daily = filtered_df.groupby("Date").size().reset_index(name="Messages")
    st.plotly_chart(px.line(daily, x="Date", y="Messages", markers=True), use_container_width=True)

    st.subheader("Guest Needs Breakdown")
    intent_counts = filtered_df["Intent"].value_counts().reset_index()
    intent_counts.columns = ["Intent", "Count"]
    st.plotly_chart(px.bar(intent_counts, x="Intent", y="Count", color="Intent"), use_container_width=True)

    st.subheader("Engagement by Session")
    session_counts = filtered_df["Session ID"].value_counts().reset_index()
    session_counts.columns = ["Session ID", "Messages"]
    st.plotly_chart(px.bar(session_counts, x="Session ID", y="Messages"), use_container_width=True)

    st.subheader("📜 Guest Interaction Log")
    st.dataframe(filtered_df)

    st.download_button("📥 Download Logs as CSV", filtered_df.to_csv(index=False), file_name="ILLORA_logs.csv")

    st.subheader("🧠 Guest Session Summaries")
    if os.path.exists(SUMMARY_PATH):
        summaries = []
        with open(SUMMARY_PATH, "r", encoding="ISO-8859-1") as f:
            for line in f:
                try:
                    summaries.append(json.loads(line.strip()))
                except:
                    continue
        if summaries:
            summary_df = pd.DataFrame(summaries)
            for _, row in summary_df.iterrows():
                with st.expander(f"Session: {row['session_id']}"):
                    st.write("📝", row["summary"])
                    st.write("📧", row["follow_up_email"])

# ======================================================
# 📊 USERINFORMATION TAB
# ======================================================
with tabs[1]:
    # dashboard_live.py (updated)
    import os
    import time
    import requests
    import pandas as pd
    import streamlit as st
    from datetime import date, datetime

    # --------- CONFIG ---------
    API = os.getenv("AIC_API", "http://localhost:5002")  # FastAPI base

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


# ======================================================
# 💬 Q&A MANAGER TAB
# ======================================================
with tabs[2]:
    st.header("💬 Q&A Manager")
    qa_df = ensure_csv('data\\qa_pairs.csv', ["question", "answer"])
    st.dataframe(qa_df, use_container_width=True)

    with st.form("addqa", clear_on_submit=True):
        q = st.text_input("Question")
        a = st.text_area("Answer")
        if st.form_submit_button("➕ Add Q&A"):
            qa_df = qa_df.append({"question": q, "answer": a}, ignore_index=True)
            qa_df.to_csv(QA_CSV, index=False)
            st.success("Q&A added!")

# ======================================================
# 🏷️ MENU MANAGER TAB
# ======================================================
with tabs[3]:
    st.header("🏷️ Menu Manager")
    default_menu = {"add_ons": {}, "rooms": {}, "complimentary": {}}
    menu = load_json(MENU_FILE, default_menu)

    for cat, items in menu.items():
        with st.expander(f"{cat.title()}"):
            if isinstance(items, dict):
                df_items = pd.DataFrame([{"key": k, "price": v} for k, v in items.items()])
                st.dataframe(df_items)
            elif isinstance(items, list):
                st.dataframe(pd.DataFrame(items))
            else:
                st.info("Empty category")

# ======================================================
# 📢 CAMPAIGNS MANAGER TAB
# ======================================================
with tabs[4]:
    st.header("📢 Campaigns Manager")
    campaigns = load_json(CAMPAIGNS_FILE, [])

    if campaigns:
        st.dataframe(pd.DataFrame(campaigns), use_container_width=True)
    else:
        st.info("No campaigns yet.")

    st.markdown("### ➕ Create New Campaign / Upsell")
    with st.form("create_campaign", clear_on_submit=True):
        name = st.text_input("Campaign Name")
        desc = st.text_area("Description")
        discount_type = st.selectbox("Discount Type", ["percent", "fixed"])
        discount_value = st.number_input("Discount Value", min_value=0.0, value=10.0, step=1.0)
        start_date = st.date_input("Start Date", value=date.today())
        end_date = st.date_input("End Date", value=date.today())
        active = st.checkbox("Active", value=True)

        if st.form_submit_button("Create Campaign"):
            camp_id = str(uuid.uuid4())
            new_campaign = {
                "id": camp_id,
                "name": name,
                "description": desc,
                "discount_type": discount_type,
                "discount_value": discount_value,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "active": active,
                "created_at": datetime.utcnow().isoformat()
            }
            campaigns.append(new_campaign)
            save_json(CAMPAIGNS_FILE, campaigns)
            st.success(f"Campaign '{name}' created!")


# ======================================================
# ✅ DO'S & ❌ DON'TS MANAGER TAB
# ======================================================
with tabs[5]:
    st.header("✅ Do's & ❌ Don'ts Manager")

    DOSDONTS_FILE = 'data\\dos_donts.json'    
    # Load existing instructions
    dos_donts = load_json(DOSDONTS_FILE, [])

    if dos_donts:
        st.dataframe(pd.DataFrame(dos_donts), use_container_width=True)
    else:
        st.info("No instructions added yet.")

    st.markdown("### ➕ Add New Instruction")
    with st.form("add_dos_donts", clear_on_submit=True):
        do_text = st.text_area("✅ Do (Instruction to say/encourage)", "")
        dont_text = st.text_area("❌ Don't (Instruction to avoid)", "")
        if st.form_submit_button("Add Instruction"):
            if do_text.strip() or dont_text.strip():
                new_entry = {"do": do_text.strip(), "dont": dont_text.strip()}
                dos_donts.append(new_entry)
                save_json(DOSDONTS_FILE, dos_donts)
                st.success("Instruction added successfully!")
            else:
                st.warning("Please fill at least one field.")


##########################################################################

# ======================================================
# ✅ AGENT MANAGER TAB
# ======================================================

with tabs[6]:
    st.header("✅ AGENT Manager")

    agents_file = 'data\\agents.json'

    # Load existing agents
    try:
        with open(agents_file, 'r') as f_new:
            agents = json.load(f_new)
    except (FileNotFoundError, json.JSONDecodeError):
        agents = []

    st.json(agents)

    if agents:
        st.dataframe(pd.DataFrame(agents), use_container_width=True)
    else:
        st.info("No agents added yet.")

    st.markdown("### ➕ Add New Agent")
    with st.form("add_agents", clear_on_submit=True):
        agent_name_text = st.text_area("✅ Add Agent Name", "")
        room_number_text = st.text_area("Give Hotel Room Number(s)", "")

        if st.form_submit_button("Add Agent"):
            if agent_name_text.strip() and room_number_text.strip():
                new_entry = {
                    "agent_name": agent_name_text.strip(),
                    "agent_allocation": room_number_text.strip()
                }

                # ✅ Check if room already exists
                updated = False
                for agent in agents:
                    if agent["agent_allocation"] == room_number_text.strip():
                        agent["agent_name"] = agent_name_text.strip()
                        updated = True
                        break

                # ✅ If not found, append new entry
                if not updated:
                    agents.append(new_entry)

                # ✅ Save back to JSON
                with open(agents_file, 'w') as f:
                    json.dump(agents, f, indent=4)

                if updated:
                    st.success(f"Updated agent for room {room_number_text.strip()} ✅")
                else:
                    st.success("New agent added successfully ✅")
            else:
                st.warning("Please fill in both fields.")


##################################################################################
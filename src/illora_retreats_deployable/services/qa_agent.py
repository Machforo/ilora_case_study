# qa_agent.py (final, updated)
from typing import Optional, List, Dict, Any, Tuple
from langchain_openai import ChatOpenAI
from vector_store import create_vector_store
from config import Config
from logger import setup_logger
import os
import json
import requests
import re
import difflib
import threading
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import re

logger = setup_logger("QAAgent")


def _normalize_text(s: str) -> str:
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


class ConciergeBot:
    """
    Concierge QA Agent with:
      - Sheet + vector store retrieval (with timeouts + fallbacks)
      - Safe chat history persistence (background threads)
      - Prompt building from sheets, campaigns, dos/donts, menu, user session
      - Debug logging for tracing
    """

    def __init__(self):
        print("[DEBUG] Initializing ConciergeBot...")
        start_init = time.time()
        try:
            # --- Google Sheets Web App endpoint ---
            self.sheet_api = getattr(
                Config,
                "GSHEET_WEBAPP_URL",
                "https://script.google.com/macros/s/AKfycbwfh2HvU5E0Y0Ruv5Ylfwdh524c0PWLCU0NduferN4etm08ovIMO6WoFoJVszmQx__O/exec",
            )

            self.qna_sheet = getattr(Config, "GSHEET_QNA_SHEET", "QnA_Manager")
            self.dos_sheet = getattr(Config, "GSHEET_DOS_SHEET", "Dos and Donts")
            self.campaign_sheet = getattr(Config, "GSHEET_CAMPAIGN_SHEET", "Campaigns_Manager")
            self.menu_sheet = getattr(Config, "GSHEET_MENU_SHEET", "menu_manager")

            self.retriever_k = int(getattr(Config, "RETRIEVER_K", 5))
            self.sheet_refresh_interval = int(getattr(Config, "SHEET_REFRESH_INTERVAL", 300))
            self.sheet_last_refresh = 0

            self.sheet_fetch_timeout = float(getattr(Config, "SHEET_FETCH_TIMEOUT", 7.0))
            self.retrieve_timeout = float(getattr(Config, "RETRIEVER_TIMEOUT", 2.0))
            self.llm_timeout = float(getattr(Config, "LLM_TIMEOUT", 8.0))

            self.use_sheet = bool(self.sheet_api)
            self.http = requests.Session()

            self.llm = ChatOpenAI(
                api_key=Config.OPENAI_API_KEY,
                model=Config.OPENAI_MODEL,
                base_url=Config.GROQ_API_BASE,
                temperature=0,
            )

            self._executor = ThreadPoolExecutor(max_workers=4)

            self.qna_rows: List[Dict[str, Any]] = []
            self.dos_donts: List[Dict[str, str]] = []
            self.campaigns: List[Dict[str, Any]] = []
            self.menu_rows: List[Dict[str, Any]] = []

            self.chat_histories: Dict[str, List[Dict[str, Any]]] = {}
            self.chat_lock = threading.Lock()
            self.chat_history_limit = int(getattr(Config, "CHAT_HISTORY_LIMIT", 10))
            self.chat_history_persist = bool(getattr(Config, "CHAT_HISTORY_PERSIST", True))
            self.chat_history_dir = getattr(Config, "CHAT_HISTORY_DIR", os.path.join("data", "chat_histories"))
            if self.chat_history_persist:
                os.makedirs(self.chat_history_dir, exist_ok=True)
            self.chat_save_every = int(getattr(Config, "CHAT_SAVE_EVERY", 5))

            if self.use_sheet:
                try:
                    self._refresh_sheets(force=True)
                    logger.info("Loaded Sheets data on init.")
                except Exception as e:
                    logger.warning(f"Sheets load failed: {e}, using vector fallback.")
                    self.use_sheet = False

            if not self.use_sheet:
                try:
                    self.vector_store = create_vector_store()
                    fetch_k = int(getattr(Config, "RETRIEVER_FETCH_K", 20))
                    self.retriever = self.vector_store.as_retriever(
                        search_type="mmr", search_kwargs={"k": self.retriever_k, "fetch_k": fetch_k}
                    )
                    logger.info("FAISS retriever loaded.")
                except Exception as e:
                    logger.error(f"Vector store init failed: {e}")
                    self.retriever = None

            if not self.dos_donts:
                self.dos_donts_path = os.path.join("data", "dos_donts.json")
                self.dos_donts = self._load_dos_donts_from_file()

            logger.info("ILORA RETREATS ConciergeBot ready.")
            print(f"[DEBUG] Init complete in {time.time() - start_init:.2f}s")
        except Exception as e:
            logger.error(f"Init error: {e}")
            raise

    # ---------------- Formatting helpers ----------------
    def _format_user_session_summary(self, session_obj: dict) -> str:
        """Summarize normalized user session into text for system prompt."""
        if not isinstance(session_obj, dict):
            return ""
        norm = session_obj.get("normalized") or session_obj
        parts = []
        if "client_id" in norm:
            parts.append(f"Client ID: {norm['client_id']}")
        if "name" in norm:
            parts.append(f"Name: {norm['name']}")
        if "email" in norm:
            parts.append(f"Email: {norm['email']}")
        if "booking_id" in norm:
            parts.append(f"Booking ID: {norm['booking_id']}")
        if "workflow_stage" in norm:
            parts.append(f"Workflow Stage: {norm['workflow_stage']}")
        if "room_alloted" in norm:
            parts.append(f"Room: {norm['room_alloted']}")
        if "check_in" in norm or "check_out" in norm:
            parts.append(f"Stay: {norm.get('check_in','')} → {norm.get('check_out','')}")
        if "id_link" in norm:
            parts.append(f"ID Proof: {norm['id_link']}")
        if "pending" in norm:
            parts.append(f"Pending: {norm['pending']}")
        return "\n".join(parts)

    def _format_conversation_for_prompt(self, history: list) -> str:
        """Format chat history into text for prompt injection."""
        if not history:
            return ""
        lines = []
        for msg in history[-self.chat_history_limit:]:
            role = msg.get("role", "")
            content = msg.get("content", "")
            lines.append(f"{role.title()}: {content}")
        return "\n".join(lines)


    def get_recent_history(self, session_key: str) -> list:
        """Get last N messages for session."""
        with self.chat_lock:
            return self.chat_histories.get(session_key, [])[-self.chat_history_limit:]

    def add_chat_message(self, session_key: str, role: str, content: str, meta: dict = None):
        """Add a chat message to history and persist if needed."""
        with self.chat_lock:
            if session_key not in self.chat_histories:
                self.chat_histories[session_key] = []
            self.chat_histories[session_key].append(
                {"role": role, "content": content, "meta": meta or {}}
            )

    # ---------------- Timeout wrapper ----------------
    def _run_with_timeout(self, fn, args: tuple = (), timeout: float = 5.0):
        future = self._executor.submit(fn, *args)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            try:
                future.cancel()
            except Exception:
                pass
            raise TimeoutError(f"Operation timed out after {timeout}s")
        except Exception as e:
            raise

    # ---------------- Sheet fetch ----------------
    def _fetch_sheet_data(self, sheet_name: str) -> List[Dict[str, Any]]:
        params = {"action": "getSheetData", "sheet": sheet_name}
        print(f"[DEBUG] Fetching sheet {sheet_name}...")
        resp = self.http.get(self.sheet_api, params=params, timeout=self.sheet_fetch_timeout)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"Sheets error: {data['error']}")
        if not isinstance(data, list):
            raise RuntimeError("Bad sheet format")
        return data

    def _refresh_sheets(self, force=False):
        now = time.time()
        if not force and now - self.sheet_last_refresh < self.sheet_refresh_interval:
            return
        self.qna_rows = [
            {**row, "page_content": self._row_to_doc_text(row), "page_content_norm": _normalize_text(self._row_to_doc_text(row))}
            for row in (self._fetch_sheet_data(self.qna_sheet) or [])
        ]
        raw_dos = self._fetch_sheet_data(self.dos_sheet) or []
        self.dos_donts = [{"do": row.get("Do") or "", "dont": row.get("Don't") or ""} for row in raw_dos]
        self.campaigns = self._fetch_sheet_data(self.campaign_sheet) or []
        raw_menu = self._fetch_sheet_data(self.menu_sheet) or []
        self.menu_rows = [
            {**row, "page_content": " ".join(str(x) for x in (row.get("Item"), row.get("Type"), row.get("Price"), row.get("Description")) if x)}
            for row in raw_menu
        ]
        self.sheet_last_refresh = now

    def _load_dos_donts_from_file(self):
        path = getattr(self, "dos_donts_path", os.path.join("data", "dos_donts.json"))
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    # ---------------- Retrieval ----------------
    def _row_to_doc_text(self, row):
        q = row.get("question") or row.get("q") or ""
        a = row.get("answer") or row.get("a") or ""
        return f"Q: {q}\nA: {a}" if q or a else " | ".join(str(v) for v in row.values() if v)

    def _score_doc(self, doc_text_norm, query_norm):
        if not doc_text_norm or not query_norm:
            return 0.0
        q_tokens, d_tokens = set(query_norm.split()), set(doc_text_norm.split())
        overlap = len(q_tokens & d_tokens) / max(1, min(len(q_tokens), len(d_tokens)))
        seq = difflib.SequenceMatcher(None, doc_text_norm, query_norm).ratio()
        return 0.65 * overlap + 0.35 * seq

    def _retrieve_from_sheets(self, query, k=None):
        k = k or self.retriever_k
        nq = _normalize_text(query)
        scored = [
            (self._score_doc(row["page_content_norm"], nq), row["page_content"], row)
            for row in self.qna_rows
        ]
        scored = [(s, t, r) for s, t, r in scored if s > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"page_content": t, "score": s, "metadata": r} for s, t, r in scored[:k]]

    # ---------------- Ask ----------------
    def _extract_session_object(self, user_session, session_key):
        if not user_session:
            return None, None
        if isinstance(user_session, dict) and ("frontend" in user_session or "normalized" in user_session):
            norm = user_session.get("normalized", {}) or {}
            key = norm.get("email") or norm.get("client_id") or session_key
            return key, user_session
        if isinstance(user_session, dict):
            if session_key and session_key in user_session:
                return session_key, user_session[session_key]
        return None, None
    def _build_prompt(self, hotel_data: str, query: str, user_profile_text: str = "", recent_conversation: str = "") -> str:
        agent_name = "AI Assistant"
        agents_file = os.path.join("data", "agents.json")
        try:
            if os.path.exists(agents_file):
                with open(agents_file, "r", encoding="utf-8") as f_new_1:
                    agents = json.load(f_new_1)
                for agent in agents:
                    if agent.get("Name") == "Front Desk":
                        agent_name = agent.get("agent_name", agent_name)
        except Exception:
            pass

        rules_text = ""
        if self.dos_donts:
            rules_text = "\n\n📋 **Important Communication Rules:**\n"
            for idx, entry in enumerate(self.dos_donts, start=1):
                do = str(entry.get("do", "")).strip()
                dont = str(entry.get("dont", "")).strip()
                if do:
                    rules_text += f"- ✅ Do: {do}\n"
                if dont:
                    rules_text += f"- ❌ Don't: {dont}\n"

        campaigns_text = ""
        if self.campaigns:
            campaigns_text = "\n\n📣 **Active Campaigns / Promos (summary):**\n"
            for c in self.campaigns[:5]:
                title = c.get("Name") or c.get("Title") or c.get("Campaign") or ""
                desc = c.get("Description") or c.get("Desc") or c.get("Details") or ""
                if title or desc:
                    campaigns_text += f"- {title} {('- ' + desc) if desc else ''}\n"

        menu_text = ""
        if self.menu_rows:
            menu_text = "\n\n📜 **Menu / Items (sample):**\n"
            for c in self.menu_rows[:20]:
                item = c.get("Item") or c.get("Name") or c.get("Title") or ""
                price = c.get("Price") or c.get("price") or ""
                typ = c.get("Type") or c.get("Category") or ""
                desc = c.get("Description") or c.get("Descripton") or c.get("Desc") or ""
                entry = []
                if item:
                    entry.append(f"{item}")
                if typ:
                    entry.append(f"({typ})")
                if price:
                    entry.append(f"- {price}")
                if desc:
                    entry.append(f": {desc}")
                if entry:
                    menu_text += "- " + " ".join(entry) + "\n"

        recent_conv_text = f"\n\nRecent Conversation (most recent messages):\n{recent_conversation}" if recent_conversation else ""
        user_profile_block = f"\n\nGuest Profile (from session):\n{user_profile_text}" if user_profile_text else ""

        prompt = (
            f"You are an AI agent named {agent_name} for the user {user_profile_block}, a knowledgeable, polite, and concise concierge assistant at *ILORA RETREATS*, "
            f"The following is the earlier chat {recent_conv_text} you need to reply accordingly"
            f"a premium hotel known for elegant accommodations, gourmet dining, rejuvenating spa treatments, "
            f"a fully-equipped gym, pool access, 24x7 room service, meeting spaces, and personalized hospitality.\n\n"
            "Answer guest queries using the Hotel Data and the Menu given below. If the data does not contain the answer, you may draw on general knowledge, "
            "but remember **DO NOT MAKE FALSE FACTS**. If unsure, ask clarifying questions. DO NOT GIVE PHONE NUMBERS unless very necessary.\n\n"
            f"Agent Name: {agent_name}\n\n"
            f"Hotel Data (most relevant excerpts):\n{hotel_data}\n\n"
            f"{menu_text}\n\n"
            f"{user_profile_block}\n\n"
            f"{recent_conv_text}\n\n"
            f"Guest Query: {query}\n"
            f"{rules_text}\n"
            f"{campaigns_text}\n"
            "\n\nProvide a helpful, concise response."
        )

        return prompt
    
    def ask(self, query: str, user_type=None, user_session=None, session_key=None) -> str:
        print(f"[DEBUG] >>> ask: {query}")
        sess_key, sess_obj = self._extract_session_object(user_session, session_key)

        # Retrieve docs
        docs = []
        if self.use_sheet:
            try:
                self._refresh_sheets()
                docs = self._run_with_timeout(self._retrieve_from_sheets, (query,), timeout=self.retrieve_timeout)
            except Exception as e:
                print(f"[WARN] Sheets retrieval failed: {e}")
                docs = []

        if not docs and getattr(self, "retriever", None):
            try:
                docs = self._run_with_timeout(lambda q: self.retriever.get_relevant_documents(q), (query,), timeout=self.retrieve_timeout)
            except Exception as e:
                print(f"[WARN] Vector retriever failed: {e}")
                docs = []

        hotel_data = "\n".join(d["page_content"] for d in docs[:5]) if docs else "No direct matches."

        user_profile_text = self._format_user_session_summary(sess_obj) if sess_obj else ""
        recent_conversation = self._format_conversation_for_prompt(self.get_recent_history(sess_key)) if sess_key else ""

        prompt = self._build_prompt(hotel_data, query, user_profile_text, recent_conversation)

        try:
            resp = self._run_with_timeout(lambda: self.llm.invoke(prompt), timeout=self.llm_timeout)
            answer = resp.content if hasattr(resp, "content") else str(resp)
        except Exception as e:
            print(f"[ERROR] LLM call failed: {e}")
            answer = "I'm sorry, I couldn't process that right now."

        if sess_key:
            self.add_chat_message(sess_key, "user", query, meta={"ts": datetime.utcnow().isoformat() + "Z"})
            self.add_chat_message(sess_key, "assistant", answer, meta={"ts": datetime.utcnow().isoformat() + "Z"})

        return answer

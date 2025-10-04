"""
ILORA RETREATS Concierge Bot with Groq/HuggingFace LLM
Only the LLM integration was updated - all sheet extraction, prompt builders,
chat history, and other features are left intact.
"""

import requests
import json
import logging
import os
import time
import threading
from typing import Optional, List, Dict, Any
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Tuple

# Try to import Groq SDK (optional)
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except Exception:
    GROQ_AVAILABLE = False

# (keep other imports the same)
from langchain_openai import ChatOpenAI  # left as-is if used elsewhere
from vector_store import create_vector_store
from config import Config
from logger import setup_logger

logger = logging.getLogger("QAAgent")


class IloraRetreatsConciergeBot:
    """
    Complete ILORA RETREATS Concierge Bot with intelligent guest/non-guest differentiation.
    Uses Groq (preferred) or HuggingFace as fallback. Only the LLM integration
    has been updated — the rest of your code (sheet extraction, prompts, etc.)
    remains unchanged.
    """
    def __init__(self):
        print("[DEBUG] Initializing IloraRetreatsConciergeBot...")
        start_init = time.time()

        self.config = Config

        # LLM configuration (prefer Config values, then environment)
        self.llm_api_key = (
            getattr(Config, "GROQ_API_KEY", None)
            or os.environ.get("GROQ_API_KEY")
            or None
        )
        # OpenAI-compatible Groq endpoint (keep as fallback if SDK not available)
        self.llm_api_url = getattr(Config, "GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")
        self.llm_model = getattr(Config, "GROQ_MODEL", "llama-3.1-8b-instant")
        self.llm_timeout = float(getattr(Config, "LLM_TIMEOUT", 15.0))

        # Build headers for HTTP fallback (if SDK not present)
        self.llm_headers = {}
        if self.llm_api_key:
            self.llm_headers = {
                "Authorization": f"Bearer {self.llm_api_key}",
                "Content-Type": "application/json",
            }

        # Should we use Groq? default True unless explicitly disabled in config/env
        env_use_groq = os.environ.get("USE_GROQ")
        if env_use_groq is not None:
            self.use_groq = env_use_groq.lower() not in ("0", "false", "no")
        else:
            # prefer Groq if SDK available or api key present
            self.use_groq = bool(getattr(Config, "USE_GROQ", True) and (GROQ_AVAILABLE or self.llm_api_key))

        # If SDK available and api key present, set env var for Groq SDK
        if GROQ_AVAILABLE and self.llm_api_key:
            # Groq SDK commonly reads GROQ_API_KEY from env var - set it for safety
            os.environ.setdefault("GROQ_API_KEY", self.llm_api_key)

        # Keep the rest of your configuration intact (sheet URLs, sheet names, timeouts)
        self.sheet_api = getattr(Config, "GSHEET_WEBAPP_URL", None)
        self.qna_sheet = getattr(Config, "GSHEET_QNA_SHEET", "QnA_Manager")
        self.dos_sheet = getattr(Config, "GSHEET_DOS_SHEET", "Dos and Donts")
        self.campaign_sheet = getattr(Config, "GSHEET_CAMPAIGN_SHEET", "Campaigns_Manager")
        self.menu_sheet = getattr(Config, "GSHEET_MENU_SHEET", "menu_manager")
        self.retriever_k = int(getattr(Config, "RETRIEVER_K", 5))
        self.sheet_refresh_interval = int(getattr(Config, "SHEET_REFRESH_INTERVAL", 300))
        self.sheet_fetch_timeout = float(getattr(Config, "SHEET_FETCH_TIMEOUT", 7.0))
        self.retrieve_timeout = float(getattr(Config, "RETRIEVER_TIMEOUT", 2.0))

        self.sheet_last_refresh = 0
        self.use_sheet = bool(self.sheet_api)
        self.http = requests.Session()

        # Data Storage
        self.qna_rows: List[Dict[str, Any]] = []
        self.dos_donts: List[Dict[str, str]] = []
        self.campaigns: List[Dict[str, Any]] = []
        self.menu_rows: List[Dict[str, Any]] = []

        # Chat History Management
        self.chat_histories: Dict[str, List[Dict[str, Any]]] = {}
        self.chat_lock = threading.Lock()
        self.chat_history_limit = 10
        self.chat_history_persist = True
        self.chat_history_dir = os.path.join("data", "chat_histories")
        if self.chat_history_persist:
            os.makedirs(self.chat_history_dir, exist_ok=True)

        # Thread Pool for Timeouts
        self._executor = ThreadPoolExecutor(max_workers=4)

        # Load Initial Data
        if self.use_sheet:
            try:
                self._refresh_sheets(force=True)
                logger.info("Loaded Sheets data on init.")
            except Exception as e:
                logger.warning(f"Sheets load failed: {e}")
                self.use_sheet = False

        # Load Dos/Donts from file as fallback
        if not self.dos_donts:
            self.dos_donts_path = os.path.join("data", "dos_donts.json")
            self.dos_donts = self._load_dos_donts_from_file()

        logger.info("ILORA RETREATS ConciergeBot ready with LLM.")
        print(f"[DEBUG] Init complete in {time.time() - start_init:.2f}s")

    # ==================== DATA LOADING ====================
    def _fetch_sheet_data(self, sheet_name: str) -> List[Dict[str, Any]]:
        params = {"action": "getSheetData", "sheet": sheet_name}
        print(f"[DEBUG] Fetching sheet {sheet_name}...")
        resp = self.http.get(self.sheet_api, params=params, timeout=self.sheet_fetch_timeout)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"Sheets error: {data['error']}")
        return data if isinstance(data, list) else []

    def _refresh_sheets(self, force=False):
        now = time.time()
        if not force and now - self.sheet_last_refresh < self.sheet_refresh_interval:
            return
        self.qna_rows = self._fetch_sheet_data(self.qna_sheet) or []
        raw_dos = self._fetch_sheet_data(self.dos_sheet) or []
        self.dos_donts = [{"do": row.get("Do", ""), "dont": row.get("Don't", "")} for row in raw_dos]
        self.campaigns = self._fetch_sheet_data(self.campaign_sheet) or []
        self.menu_rows = self._fetch_sheet_data(self.menu_sheet) or []
        self.sheet_last_refresh = now

    def _load_dos_donts_from_file(self):
        if not os.path.exists(self.dos_donts_path):
            return []
        try:
            with open(self.dos_donts_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    # ==================== CHAT HISTORY ====================
    def add_chat_message(self, session_key: str, role: str, content: str, meta: dict = None):
        with self.chat_lock:
            if session_key not in self.chat_histories:
                self.chat_histories[session_key] = []
            self.chat_histories[session_key].append({
                "role": role,
                "content": content,
                "meta": meta or {},
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })

    def get_recent_history(self, session_key: str) -> list:
        with self.chat_lock:
            return self.chat_histories.get(session_key, [])[-self.chat_history_limit:]

    def _format_conversation_for_prompt(self, history: list) -> str:
        if not history:
            return ""
        lines = []
        for msg in history[-self.chat_history_limit:]:
            role = msg.get("role", "")
            content = msg.get("content", "")
            lines.append(f"{role.title()}: {content}")
        return "\n".join(lines)

    # ==================== SESSION HANDLING ====================
    def _extract_session_object(self, user_session, session_key):
        if not user_session:
            return None, None
        if isinstance(user_session, dict) and ("frontend" in user_session or "normalized" in user_session):
            norm = user_session.get("normalized", {}) or {}
            key = norm.get("email") or norm.get("client_id") or session_key
            return key, user_session
        if isinstance(user_session, dict) and session_key and session_key in user_session:
            return session_key, user_session[session_key]
        return None, None

    def _format_user_session_summary(self, session_obj: dict) -> str:
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
        return "\n".join(parts)

    # ==================== PROMPT BUILDING ====================
    def _build_guest_prompt(self, hotel_data: str, query: str, user_profile_text: str,
                           recent_conversation: str, menu_text: str, rules_text: str,
                           campaigns_text: str, agent_name: str) -> str:
        user_profile_block = f"\n\nGuest Profile:\n{user_profile_text}" if user_profile_text else ""
        recent_conv_text = f"\n\nRecent Conversation:\n{recent_conversation}" if recent_conversation else ""
        prompt = (
            f"You are {agent_name}, a knowledgeable, polite, and concise concierge assistant at *ILORA RETREATS*.\n\n"
            f"Note: Give concise to the point answers which are helpful to the user query\n\n"
            f"Here is the user profile:{user_profile_block}. Note if the room is not alloted to the user do not give access to in-room services, laundry services , spa services etc. Politely let him know that your room is not alloted yet once its done you could be able to guide him\n\n"
            f"Recent Conversation:\n{recent_conv_text}\n\n"
            f"If someone asks for checkIn check whether the ID section is DONE or not . If not then we have to provide them with the following link: **https://forms.gle/RvnsymRmBoKu3Ns26** to complete the checkin"
            f"ILORA RETREATS INFORMATION:\n"
            f"- A luxury safari camp in Kenya's Masai Mara, near Olkiombo Airstrip\n"
            f"- 14 fully equipped LUXURY TENTS (our only room type)\n"
            f"- En-suite bathrooms, private verandas, accessible facilities\n"
            f"- Pool, spa, gym, yoga, bush dinners, stargazing\n"
            f"- Activities: game drives, walking safaris, hot air balloon rides, Maasai cultural experiences\n"
            f"- Full-board rates: USD 500–650 per night (premium activities extra)\n"
            f"- Emphasis on sustainability and comfort\n\n"
            f"GUEST STATUS - FULL ACCESS:\n"
            f"This user is a REGISTERED GUEST with complete access to:\n"
            f"✓ 24x7 Room Service\n"
            f"✓ Spa & Wellness Treatments (booking and inquiries)\n"
            f"✓ Gym & Fitness Center\n"
            f"✓ Pool Access\n"
            f"✓ In-room Dining (full menu access)\n"
            f"✓ Concierge Services\n"
            f"✓ Activity Bookings (safaris, balloons, cultural experiences)\n"
            f"✓ Special Requests & Arrangements\n"
            f"✓ Meeting Spaces\n"
            f"✓ Personalized Hospitality\n\n"
            f"HOTEL DATA (Relevant Information):\n{hotel_data}\n\n"
            f"{menu_text}\n\n"
            f"{rules_text}\n\n"
            f"{campaigns_text}\n\n"
            f"GUEST QUERY: {query}\n\n"
            f"IMPORTANT RULES:\n"
            f"1. ❌ Do NOT hallucinate or provide inaccurate information\n"
            f"2. ✓ Answer from Hotel Data first; use general knowledge cautiously\n"
            f"3. ✓ If answer unavailable, politely state so and offer to raise a ticket\n"
            f"4. ✓ Respect authority boundaries (maintenance, billing need approvals)\n"
            f"5. ✓ You CAN help with bookings, service requests, and arrangements for this guest\n"
            f"6. ✓ Be warm, personalized, and address guest by name when appropriate\n"
            f"7. ❌ DO NOT GIVE PHONE NUMBERS unless absolutely necessary\n"
            f"8. ✓ Ask clarifying questions if unsure\n\n"
            f"Provide a concise helpful, accurate, and concise response based on the above."
        )
        return prompt

    def _build_non_guest_prompt(self, query: str, recent_conversation: str, agent_name: str, hotel_data, rules_text, campaigns_text, user_profile_block) -> str:
        recent_conv_text = f"\n\nRecent Conversation:\n{recent_conversation}" if recent_conversation else ""
        prompt = (
            f"You are {agent_name}, a polite and helpful assistant at *ILORA RETREATS*.\n\n" 
            f"Note: Give concise to the point answers which are helpful to the user query\n\n"
            f"Here is the user profile:\n{user_profile_block}\n\n"
            f"Recent Conversation:\n{recent_conv_text}\n\n"
            f"If the user's ID section is empty encourage him to do web-checkin indeirectly (only once)"
            f"If user asks for checkIn check whether the ID section is DONE or not  . If not then we have to provide them with the following link: **https://forms.gle/RvnsymRmBoKu3Ns26** to complete the checkin"
            f"ILORA RETREATS OVERVIEW:\n"
            f"Ilora Retreats is a luxury safari camp in Kenya's Masai Mara, near Olkiombo Airstrip. "
            f"We offer 14 fully equipped luxury tents with en-suite bathrooms, private verandas, and modern amenities. "
            f"Our retreat features a pool, spa, gym, yoga facilities, and various safari activities including game drives, "
            f"walking safaris, hot air balloon rides, and Maasai cultural experiences.\n\n"
            f"NON-GUEST STATUS - LIMITED ACCESS:\n"
            f"This user is NOT currently a registered guest. You can help them with:\n"
            f"✓ General information about ILORA RETREATS\n"
            f"✓ Room types (14 luxury tents) and general availability\n"
            f"✓ Pricing ranges (USD 500-650/night full-board)\n"
            f"✓ Location and directions (Masai Mara, near Olkiombo Airstrip)\n"
            f"✓ Activities overview (safaris, balloons, cultural experiences)\n"
            f"✓ Facilities overview (spa, pool, gym, dining)\n"
            f"✓ Booking process and reservation assistance\n"
            f"✓ General inquiry handling\n\n"
            f"RESTRICTED - CANNOT ACCESS:\n"
            f"✗ Detailed menu prices or in-room dining options\n"
            f"✗ Cannot book specific spa treatments or room service\n"
            f"✗ Cannot make in-stay arrangements\n"
            f"✗ Cannot access guest-only services\n"
            f"✗ Cannot view or modify existing bookings\n\n"
            f"HOTEL DATA (Relevant Information):\n{hotel_data}\n\n"
            f"{rules_text}\n\n"
            f"{campaigns_text}\n\n"
            f"GUEST QUERY: {query}\n\n"
            f"IMPORTANT RULES:\n"
            f"1. ✓ Be welcoming and encouraging about booking a stay\n"
            f"2. ✓ If they ask about guest-only services (room service, spa bookings), politely explain "
            f"they need to be a registered guest to access these services\n"
            f"3. ✓ Encourage them to make a reservation for full access to amenities\n"
            f"4. ✓ Provide general pricing: Full-board rates start around USD 500–650 per night\n"
            f"5. ❌ Do NOT hallucinate. Stick to general facts about the retreat\n"
            f"6. ✓ If they want to book, guide them to contact reservations\n"
            f"7. ✓ Be professional, friendly, and persuasive about the unique luxury safari experience\n"
            f"8. ✓ Emphasize sustainability, comfort, and immersive nature experience\n\n"
            f"Provide a concise helpful response that encourages booking while answering their query accurately."
        )
        return prompt

    def _format_menu_text(self) -> str:
        if not self.menu_rows:
            return ""
        menu_text = "\n\n📜 **MENU (Sample Items):**\n"
        for item in self.menu_rows[:20]:
            name = item.get("Item") or item.get("Name") or ""
            price = item.get("Price") or ""
            typ = item.get("Type") or item.get("Category") or ""
            desc = item.get("Description") or item.get("Desc") or ""
            if name:
                entry = f"- {name}"
                if typ:
                    entry += f" ({typ})"
                if price:
                    entry += f" - {price}"
                if desc:
                    entry += f": {desc}"
                menu_text += entry + "\n"
        return menu_text

    def _format_rules_text(self) -> str:
        if not self.dos_donts:
            return ""
        rules_text = "\n\n📋 **COMMUNICATION RULES:**\n"
        for entry in self.dos_donts:
            do = str(entry.get("do", "")).strip()
            dont = str(entry.get("dont", "")).strip()
            if do:
                rules_text += f"✅ Do: {do}\n"
            if dont:
                rules_text += f"❌ Don't: {dont}\n"
        return rules_text

    def _format_campaigns_text(self) -> str:
        if not self.campaigns:
            return ""
        campaigns_text = "\n\n📣 **ACTIVE CAMPAIGNS:**\n"
        for c in self.campaigns[:5]:
            title = c.get("Name") or c.get("Title") or ""
            desc = c.get("Description") or c.get("Details") or ""
            if title or desc:
                campaigns_text += f"- {title}"
                if desc:
                    campaigns_text += f": {desc}"
                campaigns_text += "\n"
        return campaigns_text

    # ==================== LLM CALLS (UPDATED) ====================

    def _call_llm_groq(self, prompt: str, max_retries: int = 3) -> str:
        """
        Preferred Groq call:
         - Use Groq SDK streaming if available (collect chunks)
         - Otherwise fall back to HTTP POST to Groq's OpenAI-compatible endpoint
        """
        # First try SDK streaming if available
        if GROQ_AVAILABLE:
            try:
                # ensure api key is set in env (Groq SDK reads GROQ_API_KEY)
                if self.llm_api_key:
                    os.environ.setdefault("GROQ_API_KEY", self.llm_api_key)
                client = Groq()
                # streaming completion (sample-based)
                completion = client.chat.completions.create(
                    model=self.llm_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_completion_tokens=1024,
                    top_p=1,
                    stream=True,
                    stop=None,
                )
                collected = []
                for chunk in completion:
                    # sample SDK chunk structure per your sample: chunk.choices[0].delta.content
                    try:
                        delta = chunk.choices[0].delta
                        if hasattr(delta, "content"):
                            piece = delta.content or ""
                        else:
                            # some SDKs return dict-like objects
                            piece = (delta.get("content") if isinstance(delta, dict) else "") or ""
                    except Exception:
                        # best-effort fallback: try to extract message field
                        try:
                            piece = chunk.choices[0].message.content or ""
                        except Exception:
                            piece = ""
                    if piece:
                        collected.append(piece)
                text = "".join(collected).strip()
                if text:
                    return text
                # If streaming produced nothing, fall back to non-streaming below
            except Exception as e:
                logger.exception("Groq SDK streaming failed, falling back to HTTP: %s", e)

        # Fallback: HTTP POST to Groq OpenAI-compatible endpoint
        payload = {
            "model": self.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 1024,
            "top_p": 1
        }
        for attempt in range(max_retries):
            try:
                if not self.llm_headers:
                    logger.error("No Groq API key available for HTTP fallback.")
                    break
                resp = requests.post(self.llm_api_url, headers=self.llm_headers, json=payload, timeout=self.llm_timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    # OpenAI-compatible: choices[0].message.content
                    try:
                        return data["choices"][0]["message"]["content"].strip()
                    except Exception:
                        # Some endpoints return different shapes
                        # Try other plausible locations
                        if isinstance(data, dict) and "text" in data:
                            return str(data["text"]).strip()
                        return json.dumps(data)[:2000]
                elif resp.status_code in (429, 503) and attempt < max_retries - 1:
                    # rate limited or model loading - retry with backoff
                    sleep_for = 2 ** attempt
                    logger.warning("Groq HTTP retry %s after %ss (status=%s)", attempt + 1, sleep_for, resp.status_code)
                    time.sleep(sleep_for)
                    continue
                else:
                    logger.error("Groq HTTP error %s: %s", resp.status_code, resp.text)
                    break
            except Exception as e:
                logger.exception("Groq HTTP call failed on attempt %s: %s", attempt + 1, e)
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                break
        # If all else fails:
        return "I'm having trouble processing that right now. Please try again."

    def _call_llm_huggingface(self, prompt: str, max_retries: int = 3) -> str:
        """Call HuggingFace API (unchanged from original)."""
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 1000,
                "temperature": 0.7,
                "top_p": 0.9,
                "do_sample": True,
                "return_full_text": False
            }
        }
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.llm_api_url,
                    headers=self.llm_headers,
                    json=payload,
                    timeout=self.llm_timeout
                )
                if response.status_code == 200:
                    result = response.json()
                    if isinstance(result, list) and len(result) > 0:
                        return result[0].get('generated_text', '').strip()
                    elif isinstance(result, dict):
                        return result.get('generated_text', '').strip()
                    return "I'm processing your request. Please try again."
                elif response.status_code == 503:
                    logger.warning(f"Model loading, attempt {attempt + 1}")
                    if attempt < max_retries - 1:
                        time.sleep(3 ** attempt)
                        continue
                    return "The AI model is currently loading. Please try again in a moment."
                else:
                    logger.error(f"HF API error {response.status_code}")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    return "I'm having trouble connecting. Please try again."
            except Exception as e:
                logger.error(f"HF call error: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return "I encountered an error. Please try again."
        return "Unable to process your request. Please try again later."

    def _run_with_timeout(self, fn, args: tuple = (), timeout: float = 5.0):
        future = self._executor.submit(fn, *args)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            future.cancel()
            raise TimeoutError(f"Operation timed out after {timeout}s")

    # ==================== MAIN ASK METHOD ====================
    def ask(self, query: str, user_type: str = "non-guest", user_session=None, session_key=None) -> str:
        print(f"[DEBUG] >>> ask: {query} (user_type={user_type})")

        # Extract session data
        sess_key, sess_obj = self._extract_session_object(user_session, session_key)

        # Refresh sheets if needed
        if self.use_sheet:
            try:
                self._refresh_sheets()
            except Exception as e:
                logger.warning(f"Sheet refresh failed: {e}")

        # Get agent name
        agent_name = "ILORA Concierge"
        try:
            agents_file = os.path.join("data", "agents.json")
            if os.path.exists(agents_file):
                with open(agents_file, "r", encoding="utf-8") as f:
                    agents = json.load(f)
                for agent in agents:
                    if agent.get("Name") == "Front Desk":
                        agent_name = agent.get("agent_name", agent_name)
        except Exception:
            pass

        # Build prompt based on user type
        if user_type == "guest":
            hotel_data = "\n".join(str(row) for row in self.qna_rows[:10]) if self.qna_rows else "No specific data available."
            user_profile_text = self._format_user_session_summary(sess_obj) if sess_obj else ""
            recent_conversation = self._format_conversation_for_prompt(self.get_recent_history(sess_key)) if sess_key else ""
            menu_text = self._format_menu_text()
            rules_text = self._format_rules_text()
            campaigns_text = self._format_campaigns_text()

            prompt = self._build_guest_prompt(
                hotel_data, query, user_profile_text, recent_conversation,
                menu_text, rules_text, campaigns_text, agent_name
            )
        else:
            hotel_data = "\n".join(str(row) for row in self.qna_rows[:10]) if self.qna_rows else "No specific data available."
            user_profile_text = self._format_user_session_summary(sess_obj) if sess_obj else ""
            recent_conversation = self._format_conversation_for_prompt(self.get_recent_history(sess_key)) if sess_key else ""
            menu_text = self._format_menu_text()
            rules_text = self._format_rules_text()
            campaigns_text = self._format_campaigns_text()

            # NOTE: original code used guest prompt call here with wrong arguments —
            # I preserved behaviour but pass through an appropriate non-guest prompt
            prompt = self._build_non_guest_prompt(
                query, recent_conversation, agent_name, hotel_data, rules_text, campaigns_text, user_profile_text
            )

        # Call LLM
        try:
            if self.use_groq:
                answer = self._call_llm_groq(prompt)
            else:
                answer = self._call_llm_huggingface(prompt)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            answer = "I'm sorry, I couldn't process that right now. Please try again."

        # Save to chat history
        if sess_key:
            self.add_chat_message(sess_key, "user", query)
            self.add_chat_message(sess_key, "assistant", answer)

        return answer


'''
# If you want to test locally:
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    bot = IloraRetreatsConciergeBot()
    print(bot.ask("Hello, what are your lunch options?", user_type="non-guest", session_key="test_visitor"))
'''

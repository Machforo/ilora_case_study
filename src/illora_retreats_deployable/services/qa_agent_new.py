from typing import Optional, List, Dict, Any
from langchain_openai import ChatOpenAI
from vector_store import create_vector_store
from config import Config
from logger import setup_logger
import os
import json
import requests
import time
import re
import difflib
from datetime import datetime

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
    Extended ConciergeBot with pre-checkin / checkin flow.
    Public method: ask(query, user_type=None, user_identifier=None, frontend_action=None)
      - user_identifier: string used to identify the user (Client Id, Username/email, Booking Id, or Name).
      - frontend_action: dict/str used by frontend to call backend actions (e.g., "confirm_payment", "verify_id").
    """

    def __init__(self):
        try:
            # Chat history storage
            self.chat_history = {}  # Dictionary to store chat history by session ID
            
            # --- Configurable Google Sheets Web App endpoint (Apps Script) ---
            self.sheet_api = getattr(
                Config,
                "GSHEET_WEBAPP_URL",
                "https://script.google.com/macros/s/AKfycbwfh2HvU5E0Y0Ruv5Ylfwdh524c0PWLCU0NduferN4etm08ovIMO6WoFoJVszmQx__O/exec",
            )

            # Sheet/tab names
            self.qna_sheet = getattr(Config, "GSHEET_QNA_SHEET", "QnA_Manager")
            self.dos_sheet = getattr(Config, "GSHEET_DOS_SHEET", "Dos and Donts")
            self.campaign_sheet = getattr(Config, "GSHEET_CAMPAIGN_SHEET", "Campaigns_Manager")
            self.menu_sheet = getattr(Config, "GSHEET_MENU_SHEET", "menu_manager")
            # Workflow sheet containing clients
            self.client_sheet = getattr(Config, "GSHEET_CLIENT_SHEET", "Client_workflow")

            # Retriever params
            self.retriever_k = getattr(Config, "RETRIEVER_K", 5)

            # total rooms (user said they have 14)
            self.total_rooms = getattr(Config, "TOTAL_ROOMS", 14)

            # If sheet API is not provided, fallback to vector store approach
            self.use_sheet = bool(self.sheet_api)

            # LLM
            self.llm = ChatOpenAI(
                api_key=Config.OPENAI_API_KEY,
                model=Config.OPENAI_MODEL,
                base_url=Config.GROQ_API_BASE,
                temperature=0,
            )

            # Storage
            self.qna_rows: List[Dict[str, Any]] = []
            self.dos_donts: List[Dict[str, str]] = []
            self.campaigns: List[Dict[str, Any]] = []
            self.menu_rows: List[Dict[str, Any]] = []
            self.client_rows: List[Dict[str, Any]] = []

            if self.use_sheet:
                try:
                    self._refresh_sheets()
                    logger.info("Loaded QnA / Dos & Donts / Campaigns / Clients from Google Sheets web app.")
                except Exception as e:
                    logger.warning(f"Could not load sheets on init: {e}. Falling back to vector store if available.")
                    self.use_sheet = False

            if not self.use_sheet:
                try:
                    self.vector_store = create_vector_store()
                    k = getattr(Config, "RETRIEVER_K", 5)
                    fetch_k = getattr(Config, "RETRIEVER_FETCH_K", 20)
                    self.retriever = self.vector_store.as_retriever(
                        search_type="mmr", search_kwargs={"k": k, "fetch_k": fetch_k}
                    )
                    logger.info("FAISS vector store loaded as fallback retriever.")
                except Exception as e:
                    logger.error(f"Error initializing vector store fallback: {e}")
                    self.retriever = None

            # Load Do's & Don'ts from file if no sheet data
            if not self.dos_donts:
                self.dos_donts_path = os.path.join("data", "dos_donts.json")
                self.dos_donts = self._load_dos_donts_from_file()

            logger.info("ILORA RETREATS QA agent initialized successfully.")

        except Exception as e:
            logger.error(f"Error initializing QA agent: {e}")
            raise

    def _fetch_sheet_data(self, sheet_name: str) -> List[Dict[str, Any]]:
        """Fetch data from Google Sheet."""
        if not self.sheet_api:
            raise RuntimeError("GSHEET_WEBAPP_URL is not configured in Config.")
        params = {"action": "getSheetData", "sheet": sheet_name}
        try:
            resp = requests.get(self.sheet_api, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and data.get("error"):
                raise RuntimeError(f"Sheets webapp returned error: {data.get('error')}")
            if not isinstance(data, list):
                raise RuntimeError("Unexpected sheet response format (expected list of row objects).")
            return data
        except Exception as e:
            logger.error(f"Error fetching sheet '{sheet_name}' from {self.sheet_api}: {e}")
            raise

    def _refresh_sheets(self):
        """Refresh all sheet data."""
        self.qna_rows = self._fetch_sheet_data(self.qna_sheet) or []
        raw_dos = self._fetch_sheet_data(self.dos_sheet) or []
        processed = []
        for row in raw_dos:
            do_val = row.get("Do") or row.get("do") or row.get("Do's") or row.get("Do_s") or row.get("Do / Don't") or ""
            dont_val = row.get("Don't") or row.get("Dont") or row.get("dont") or row.get("Don'ts") or row.get("Dont_s") or ""
            processed.append({"do": str(do_val).strip(), "dont": str(dont_val).strip()})
        self.dos_donts = processed
        self.campaigns = self._fetch_sheet_data(self.campaign_sheet) or []
        self.menu = self._fetch_sheet_data(self.menu_sheet) or []
        self.client_rows = self._fetch_sheet_data(self.client_sheet) or []

    def _load_dos_donts_from_file(self) -> List[Dict[str, str]]:
        """Load Do's & Don'ts from file."""
        path = getattr(self, "dos_donts_path", os.path.join("data", "dos_donts.json"))
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load Do's & Don'ts file: {e}")
            return []

    def _get_chat_history_key(self, client_row: Optional[Dict[str, Any]], user_identifier: Optional[str] = None) -> str:
        """Get consistent chat history key based on user identifiers."""
        if client_row and client_row.get("Email"):  # Primary key - user's email
            key = client_row["Email"]
            logger.info(f"Using Email as chat key: {key}")
            return key
        elif client_row and client_row.get("Client Id"):  # Fallback to Client Id
            key = client_row["Client Id"]
            logger.info(f"Using Client Id as chat key: {key}")
            return key
        elif user_identifier:  # User-provided identifier
            key = f"user_{user_identifier}"
            logger.info(f"Using user identifier as chat key: {key}")
            return key
        else:  # Last resort - temporary session
            key = f"session_{int(time.time())}"
            logger.info(f"Using temporary session ID: {key}")
            return key

    def _find_client_row(self, identifier: str) -> Optional[Dict[str, Any]]:
        """Find client row using identifier."""
        if not identifier or not self.client_rows:
            return None
        iid = identifier.strip().lower()
        for row in self.client_rows:
            if row.get("Email", "").strip().lower() == iid:  # Try email first
                return row
            # Other identifiers as fallback
            client_id = str(row.get("Client Id") or "").strip().lower()
            booking_id = str(row.get("Booking Id") or "").strip().lower()
            name = str(row.get("Name") or "").strip().lower()
            if iid and (iid == client_id or iid == booking_id or iid == name):
                return row
        return None

    def _is_user_booked(self, client_row: Dict[str, Any]) -> bool:
        """Check if user has an active booking."""
        if not client_row:
            return False

        logger.info(f"Checking booking status for client row: {client_row}")
        
        # Primary check: Workflow Stage status
        wf = str(client_row.get("Workfow Stage") or 
                client_row.get("Workflow Stage") or 
                client_row.get("WorkFlow") or 
                client_row.get("Workfow") or "").strip().lower()
        
        # If Workflow Stage is "Confirmed", user is definitely booked
        if wf == "confirmed":
            logger.info("Found Confirmed workflow stage - User is booked")
            return True

        # Secondary checks
        booking_id = str(client_row.get("Booking Id") or "").strip()
        if booking_id and booking_id not in ["-", "none", "", "n/a"]:
            logger.info(f"Found valid booking ID: {booking_id}")
            return True

        # Room allocation check
        room = str(client_row.get("Room Alloted") or "").strip()
        if room and room not in ["-", "none", "", "n/a"]:
            logger.info(f"Found room allocation: {room}")
            return True

        logger.info("No active booking indicators found")
        return False

    def _is_id_verified(self, client_row: Dict[str, Any]) -> bool:
        """Check if user's ID is verified."""
        if not client_row:
            return False
        
        id_link = client_row.get("Id Link")
        if not id_link:
            return False
            
        id_link = str(id_link).strip().lower()
        # Consider "DONE" or any URL as verified
        if id_link == "done" or "http" in id_link:
            return True
            
        return False

    def ask(self, query: str, user_type: Optional[str] = None, user_identifier: Optional[str] = None) -> str:
        """Main entry point for chat interactions."""
        try:
            # Refresh sheet data for accuracy
            if self.use_sheet:
                try:
                    self._refresh_sheets()
                except Exception as e:
                    logger.warning(f"Could not refresh sheets at ask(): {e}")

            # Get client info
            client_row = None
            if user_identifier:
                client_row = self._find_client_row(user_identifier)
                logger.info(f"Found client row for {user_identifier}: {client_row}")

            # Get chat history key
            chat_history_key = self._get_chat_history_key(client_row, user_identifier)
            
            # Initialize chat history if needed
            if chat_history_key not in self.chat_history:
                self.chat_history[chat_history_key] = []
                logger.info(f"Created new chat history with key: {chat_history_key}")
            
            # Add user message to history
            self.chat_history[chat_history_key].append({
                "role": "user",
                "text": query,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            # Debug print current history
            logger.info("\n=== Complete Chat History ===")
            logger.info(f"History Key: {chat_history_key}")
            for idx, msg in enumerate(self.chat_history[chat_history_key], 1):
                logger.info(f"{idx}. {msg['role'].upper()}: {msg['text']}")
                logger.info(f"   Timestamp: {msg['timestamp']}")
            logger.info("==========================\n")

            # Format history for prompt
            chat_history_text = "\nPrevious conversation context:\n"
            for msg in self.chat_history[chat_history_key][-5:]:
                if msg["role"] == "user":
                    chat_history_text += f"User: {msg['text']}\n"
                else:
                    chat_history_text += f"Assistant: {msg['text']}\n"

            logger.info("\n=== Chat History Added to Prompt ===")
            logger.info(chat_history_text)
            logger.info("===================================\n")

            # Check user status
            is_booked = False
            id_verified = False
            if client_row:
                is_booked = self._is_user_booked(client_row)
                id_verified = self._is_id_verified(client_row)
                logger.info(f"User status - Booked: {is_booked}, ID Verified: {id_verified}")

            # Get relevant docs for context
            docs = []
            if self.use_sheet:
                try:
                    docs = self._retrieve_from_sheets(query, k=self.retriever_k)
                except Exception as e:
                    logger.warning(f"Sheet retrieval error: {e}")
                    
            if not docs and self.retriever:
                try:
                    docs = self.retriever.invoke(query)
                except Exception as e:
                    logger.warning(f"Vector retrieval error: {e}")
            
            hotel_data = "\n\n".join(d.get('page_content', '') for d in (docs or []))

            # Build and execute prompt
            system_prompt = self._build_prompt(
                hotel_data, 
                query, 
                session_id=chat_history_key,
                is_booked=is_booked,
                is_verified=id_verified
            )

            response = self.llm.invoke(system_prompt)
            final_answer = response.content.strip() if hasattr(response, "content") else str(response)

            # Add response to history
            self.chat_history[chat_history_key].append({
                "role": "assistant",
                "text": final_answer,
                "timestamp": datetime.utcnow().isoformat()
            })

            # Trim history if needed (keep last 50)
            if len(self.chat_history[chat_history_key]) > 50:
                self.chat_history[chat_history_key] = self.chat_history[chat_history_key][-50:]

            logger.info(f"Processed query at ILORA RETREATS: {query}")
            return final_answer

        except Exception as e:
            logger.error(f"Error processing query: {e}")
            return "I apologize, but I encountered an issue while processing your request. Please try again or contact our front desk for assistance."

    def _retrieve_from_sheets(self, query: str, k: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieve relevant QnA entries from sheets."""
        k = k or self.retriever_k
        if not self.qna_rows:
            return []
        
        scored_results = []
        for row in self.qna_rows:
            doc_text = self._row_to_doc_text(row)
            score = self._score_doc(doc_text, query)
            scored_results.append((score, doc_text, row))
        
        scored_results.sort(key=lambda x: x[0], reverse=True)
        selected = scored_results[:k]
        
        return [{
            "page_content": doc_text,
            "score": score,
            "metadata": row
        } for score, doc_text, row in selected]

    def _row_to_doc_text(self, row: Dict[str, Any]) -> str:
        """Convert a sheet row to searchable text."""
        text_parts = []
        
        # Extract question/query
        for key in ["question", "q", "query", "prompt"]:
            if row.get(key):
                text_parts.append(f"Q: {row[key]}")
                break
                
        # Extract answer/response
        for key in ["answer", "a", "response", "reply"]:
            if row.get(key):
                text_parts.append(f"A: {row[key]}")
                break
                
        # Fallback to joining all values
        if not text_parts:
            text = " | ".join(str(v) for v in row.values() if v)
            if text:
                text_parts.append(text)
                
        return "\n".join(text_parts)

    def _score_doc(self, doc_text: str, query: str) -> float:
        """Score document relevance to query."""
        if not query or not doc_text:
            return 0.0
            
        # Normalize texts
        query_norm = _normalize_text(query)
        doc_norm = _normalize_text(doc_text)
        
        # Get token sets
        query_tokens = set(query_norm.split())
        doc_tokens = set(doc_norm.split())
        
        if not query_tokens or not doc_tokens:
            return 0.0
            
        # Calculate token overlap
        overlap = len(query_tokens & doc_tokens) / min(len(query_tokens), len(doc_tokens))
        
        # Calculate sequence similarity
        seq_sim = difflib.SequenceMatcher(None, query_norm, doc_norm).ratio()
        
        # Combine scores (65% overlap, 35% sequence)
        score = (0.65 * overlap) + (0.35 * seq_sim)
        
        return float(score)

    def _build_prompt(self, hotel_data: str, query: str, session_id: str = None, is_booked: bool = False, is_verified: bool = False) -> str:
        """Build system prompt with context."""
        # Get agent name
        agent_name = "AI Assistant"
        agents_file = os.path.join("data", "agents.json")
        try:
            if os.path.exists(agents_file):
                with open(agents_file, "r", encoding="utf-8") as f:
                    agents = json.load(f)
                for agent in agents:
                    if agent.get("Name") == "Front Desk":
                        agent_name = agent.get("agent_name", agent_name)
        except Exception:
            pass

        # Build rules section
        rules_text = ""
        if self.dos_donts:
            rules_text = "\n\n📋 **Important Communication Rules:**\n"
            for entry in self.dos_donts:
                do = str(entry.get("do") or "").strip()
                dont = str(entry.get("dont") or "").strip()
                if do:
                    rules_text += f"- ✅ Do: {do}\n"
                if dont:
                    rules_text += f"- ❌ Don't: {dont}\n"

        # Build campaigns section for verified guests
        campaigns_text = ""
        if self.campaigns and (is_booked and is_verified):
            campaigns_text = "\n\n📣 **Active Campaigns / Promos:**\n"
            for campaign in self.campaigns[:5]:
                title = campaign.get("Name") or campaign.get("Title") or ""
                desc = campaign.get("Description") or campaign.get("Desc") or ""
                if title or desc:
                    campaigns_text += f"- {title} {('- ' + desc) if desc else ''}\n"

        # Build menu section for verified guests
        menu_text = ""
        if self.menu and (is_booked and is_verified):
            menu_text = "\n\n📋 **Menu / Services:**\n"
            for item in self.menu:
                type_ = item.get("Type") or ""
                name = item.get("Item") or ""
                price = item.get("Price") or ""
                desc = item.get("Description") or ""
                menu_text += f"- {type_} {name} {('- ' + str(price)) if price else ''} {('- ' + desc) if desc else ''}\n"

        # Get chat history text
        chat_history_text = ""
        if session_id and session_id in self.chat_history:
            chat_history_text = "\nPrevious conversation context:\n"
            for msg in self.chat_history[session_id][-5:]:
                chat_history_text += f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['text']}\n"

        # Build base prompt with status-specific instructions
        if not is_booked or not is_verified:
            base_prompt = (
                f"You are an AI agent named {agent_name}, a knowledgeable and polite concierge assistant at ILORA RETREATS. "
                "For in-room services, spa bookings, or amenity access, politely explain that a confirmed booking and ID verification are required.\n\n"
                f"Status: {'Not Booked' if not is_booked else 'Booked but ID Not Verified'}\n\n"
                f"Hotel Data:\n{hotel_data}\n\n"
                f"{chat_history_text}\n"
                f"Guest Query: {query}\n"
                f"{rules_text}"
            )
        else:
            base_prompt = (
                f"You are an AI agent named {agent_name}, a knowledgeable and polite concierge assistant at ILORA RETREATS. "
                "Handle all in-room service requests directly and create service tickets for guest requests.\n\n"
                f"Hotel Data:\n{hotel_data}\n\n"
                f"{menu_text}\n\n"
                f"{chat_history_text}\n"
                f"Guest Query: {query}\n"
                f"{rules_text}"
                f"{campaigns_text}"
            )

        return base_prompt
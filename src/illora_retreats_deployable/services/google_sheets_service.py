"""
GoogleSheetsService — updated to mirror your main_final.py behaviour exactly for
authentication and sheet interactions.

Key behaviour now matches your working code (main_final.py):
- For lookup of users by email we call the Apps Script WebApp GET action
  `getSheetData` and perform a strict row-by-row match on normalized email/username
  keys. This prevents false-positives when the webapp returns a generic success
  response.
- For login verification there is a `verify_user(username, password)` helper that
  performs a POST with `action=verifyUser` (same contract as your main_final login
  route). The webhook can call this to let the Apps Script do password comparison.
- For creating users we POST `action=addRow` with key `rowData` exactly like your
  `push_row_to_sheet` helper so behaviour is identical to your signup flow.
- For updating workflow/booking the service uses `updateUserWorkflow` action to
  match your `update_workflow` endpoint.

The service still falls back to Google Sheets API (service account) if webapp URL
is not configured and the Google client libraries/creds exist. If neither is
available, it uses a local JSON fallback at `data/users.json`.

Public methods you can call from the webhook/application:
- get_user_by_email(email) -> returns the raw row dict (or None)
- verify_user(username, password) -> returns userData dict if verified, else None
- create_new_user(new_user_data) -> returns a dict response from webapp or boolean
- get_available_tents() -> int
- update_booking(booking_data) -> dict/boolean
- update_workflow_stage(email, stage) -> boolean
- create_booking(booking_data) -> dict/boolean

Security note: This module intentionally mirrors the existing Sheets/webapp
behaviour for compatibility. If you want passwords hashed before writing to the
sheet, we can add that — but then the Apps Script that verifies passwords must
also be updated to compare hashes.
"""

import os
import json
import logging
import re
from typing import Optional, Dict, Any, List
from datetime import datetime

import requests

# Optional Google Sheets API support
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_AVAILABLE = True
except Exception:
    GOOGLE_AVAILABLE = False

# Optional Config import
try:
    from config import Config
except Exception:
    Config = None

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _normalize_key(k: Any) -> str:
    return "".join(ch.lower() for ch in str(k) if ch.isalnum())


def _normalize_header(h: str) -> str:
    if not h:
        return ""
    s = re.sub(r"[^0-9a-zA-Z]+", "_", h.strip().lower())
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


class GoogleSheetsService:
    def __init__(
        self,
        sheet_api: Optional[str] = None,
        client_workflow_sheet: Optional[str] = None,
        bookings_sheet: Optional[str] = None,
        local_store: Optional[str] = None,
        spreadsheet_id: Optional[str] = None,
        creds_json_path: Optional[str] = None,
    ) -> None:
        cfg = Config if Config is not None else None

        # Apps Script WebApp (preferred — matches your main_final usage)
        self.sheet_api = (
            sheet_api
            or (getattr(cfg, "GSHEET_WEBAPP_URL", None) if cfg else None)
            or os.environ.get("GSHEET_WEBAPP_URL")
            or ""
        )

        self.client_workflow_sheet = (
            client_workflow_sheet
            or (getattr(cfg, "GSHEET_CLIENT_WORKFLOW", None) if cfg else None)
            or "Client_workflow"
        )
        self.bookings_sheet = (
            bookings_sheet
            or (getattr(cfg, "GSHEET_BOOKINGS_SHEET", None) if cfg else None)
            or "Bookings"
        )

        # Additional optional sheets
        self.qna_sheet = (getattr(cfg, "GSHEET_QNA_SHEET", None) if cfg else None) or "QnA_Manager"
        self.dos_sheet = (getattr(cfg, "GSHEET_DOS_SHEET", None) if cfg else None) or "Dos and Donts"
        self.campaign_sheet = (getattr(cfg, "GSHEET_CAMPAIGN_SHEET", None) if cfg else None) or "Campaigns_Manager"
        self.menu_sheet = (getattr(cfg, "GSHEET_MENU_SHEET", None) if cfg else None) or "menu_manager"

        self.local_store = local_store or os.path.join("data", "users.json")

        self.spreadsheet_id = (
            spreadsheet_id
            or (getattr(cfg, "SPREADSHEET_ID", None) if cfg else None)
            or os.environ.get("SPREADSHEET_ID")
        )
        self.creds_json_path = (
            creds_json_path
            or (getattr(cfg, "GOOGLE_SERVICE_ACCOUNT_JSON", None) if cfg else None)
            or os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        )

        # total tents
        self._total_tents = 14
        try:
            with open(os.path.join("data", "room_config.json"), "r") as f:
                cfg_json = json.load(f)
                self._total_tents = cfg_json.get("total_tents", self._total_tents)
        except Exception:
            # ignore
            pass

        # Decide backend modes
        self.use_webapp = bool(self.sheet_api)
        self.use_sheets_api = False
        self.sheets = None

        # If webapp is not present and Google libs exist, try Sheets API
        if not self.use_webapp and GOOGLE_AVAILABLE and self.spreadsheet_id and self.creds_json_path and os.path.exists(self.creds_json_path):
            try:
                scopes = ["https://www.googleapis.com/auth/spreadsheets"]
                creds = service_account.Credentials.from_service_account_file(self.creds_json_path, scopes=scopes)
                self.sheets = build("sheets", "v4", credentials=creds)
                self.use_sheets_api = True
                logger.info("Google Sheets API initialised for %s", self.spreadsheet_id)
            except Exception as e:
                logger.warning("Failed to init Sheets API, falling back to local store: %s", e)

        # Ensure local store exists
        os.makedirs(os.path.dirname(self.local_store), exist_ok=True)
        if not os.path.exists(self.local_store):
            with open(self.local_store, "w") as f:
                json.dump([], f)

        logger.info("GoogleSheetsService ready. webapp=%s sheets_api=%s local_store=%s", self.use_webapp, self.use_sheets_api, self.local_store)

    # ---------------- WebApp helpers (match main_final contracts) ----------------
    def _fetch_sheet_rows_via_webapp(self, sheet_name: str, timeout: int = 15) -> Optional[List[Dict[str, Any]]]:
        """Call the Apps Script webapp using GET?action=getSheetData and return rows list.

        This mirrors `fetch_client_row_from_sheet_by_email` behaviour in your main_final.
        """
        if not self.sheet_api:
            return None
        try:
            params = {"action": "getSheetData", "sheet": sheet_name}
            resp = requests.get(self.sheet_api, params=params, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
            try:
                rows = resp.json()
                if isinstance(rows, list):
                    return rows
                else:
                    logger.debug("_fetch_sheet_rows_via_webapp: expected list, got %s", type(rows))
                    return None
            except ValueError:
                logger.error("_fetch_sheet_rows_via_webapp: non-JSON response: %s", resp.text[:500])
                return None
        except Exception as e:
            logger.exception("_fetch_sheet_rows_via_webapp failed")
            return None

    def _post_to_webapp(self, action: str, payload: Dict[str, Any], timeout: int = 15) -> Optional[Any]:
        if not self.sheet_api:
            return None
        body = {"action": action, "sheet": payload.pop("sheet", None) or self.client_workflow_sheet}
        body.update(payload)
        safe_preview = {k: (v if _normalize_key(k) != "password" else "****") for k, v in body.items() if k in ("action", "sheet", "username", "email", "Client Id", "Name")}
        logger.debug("_post_to_webapp: action=%s payload_preview=%s", action, safe_preview)
        try:
            resp = requests.post(self.sheet_api, json=body, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError:
                logger.debug("_post_to_webapp: non-JSON response (truncated)=%s", resp.text[:500])
                return {"success": resp.ok, "status_code": resp.status_code, "text": resp.text}
        except Exception as e:
            logger.exception("_post_to_webapp failed for action=%s", action)
            return None

    # ---------------- Local store helpers ----------------
    def _read_local_store(self) -> List[Dict[str, Any]]:
        try:
            with open(self.local_store, "r") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    return []
                return data
        except Exception as e:
            logger.error("_read_local_store error: %s", e)
            return []

    def _append_local_store(self, row: Dict[str, Any]) -> bool:
        try:
            with open(self.local_store, "r+") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    data = []
                data.append(row)
                f.seek(0)
                json.dump(data, f, indent=2)
                f.truncate()
            return True
        except Exception as e:
            logger.error("_append_local_store error: %s", e)
            return False

    def _update_local_store_by_email(self, email: str, updates: Dict[str, Any]) -> bool:
        try:
            email_norm = (email or "").strip().lower()
            with open(self.local_store, "r+") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    return False
                changed = False
                for rec in data:
                    rec_email = rec.get("Email") or rec.get("email") or rec.get("e_mail")
                    if rec_email and str(rec_email).strip().lower() == email_norm:
                        rec.update(updates)
                        changed = True
                        break
                if changed:
                    f.seek(0)
                    json.dump(data, f, indent=2)
                    f.truncate()
                    return True
                return False
        except Exception as e:
            logger.error("_update_local_store_by_email error: %s", e)
            return False

    # ---------------- Public methods ----------------
    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Return the exact raw row dict from the Client_workflow sheet for the email.

        This uses a strict per-row search (GET getSheetData) to avoid false
        positives. Returns None if no row matches.
        """
        if not email:
            return None
        target = email.strip().lower()

        # 1) WebApp: GET full sheet then search
        if self.use_webapp:
            rows = self._fetch_sheet_rows_via_webapp(self.client_workflow_sheet)
            if isinstance(rows, list):
                for idx, row in enumerate(rows):
                    # find any key that normalises to 'email' or 'username'
                    for k, v in (row or {}).items():
                        nk = _normalize_key(k)
                        if nk in ("email", "username"):
                            if str(v or "").strip().lower() == target:
                                logger.debug("get_user_by_email: found at index %s", idx)
                                return row
                logger.debug("get_user_by_email: no match for %s", target)
                return None
            else:
                logger.debug("get_user_by_email: webapp returned no rows")
                return None

        # 2) Sheets API: read and search
        if self.use_sheets_api:
            try:
                r = self.sheets.spreadsheets().values().get(spreadsheetId=self.spreadsheet_id, range=self.client_workflow_sheet).execute()
                values = r.get("values", [])
                if not values:
                    return None
                headers = values[0]
                headers_norm = [_normalize_header(h) for h in headers]
                for row in values[1:]:
                    padded = row + [""] * (len(headers) - len(row))
                    row_dict = { headers[i]: padded[i] for i in range(len(headers)) }
                    for h in headers:
                        if _normalize_key(h) in ("email", "username"):
                            if str(row_dict.get(h, "")).strip().lower() == target:
                                return row_dict
                return None
            except Exception as e:
                logger.error("get_user_by_email via API failed: %s", e)
                return None

        # 3) Local store
        rows = self._read_local_store()
        for row in rows:
            for k, v in (row or {}).items():
                if _normalize_key(k) in ("email", "username") and str(v or "").strip().lower() == target:
                    return row
        return None

    def verify_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Ask the Apps Script to verify a username+password pair using action=verifyUser.

        Returns the user data dict if verified, or None otherwise. This mirrors
        your main_final /auth/login behaviour which prefers the webapp verify
        endpoint.
        """
        if not username:
            return None
        if self.use_webapp:
            payload = {"username": username, "password": password}
            resp = self._post_to_webapp("verifyUser", payload)
            if not resp:
                return None
            # Apps Script may return {found: True/False, userData: {...}} or an error
            if isinstance(resp, dict):
                if resp.get("error"):
                    logger.debug("verify_user: webapp returned error=%s", resp.get("error"))
                    return None
                # if userData present, return it
                if resp.get("userData"):
                    return resp.get("userData")
                # Some webapps return 'found' and 'verified' flags with a raw row
                if resp.get("found") or resp.get("verified"):
                    return resp.get("userData") or {}
            return None

        # Sheets API/local fallback: do a simple local check (not recommended)
        row = self.get_user_by_email(username)
        if not row:
            return None
        # find password field in row (various possible keys)
        pw = row.get("Password") or row.get("password") or row.get("Password Hash") or row.get("password_hash")
        if not pw:
            return None
        if str(pw) == str(password) or str(pw) == hashlib.sha256(password.encode()).hexdigest():
            return row
        return None

    def create_new_user(self, new_user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new user row. Uses action=addRow with rowData (like your push_row_to_sheet).

        Returns the parsed webapp response (dict) when using webapp, or boolean-like
        dict for local/sheets-api.
        """
        # Basic email validation similar to your main_final
        email = new_user_data.get("Email") or new_user_data.get("email") or new_user_data.get("username")
        if not email:
            logger.error("create_new_user: missing email")
            return {"success": False, "error": "Missing email"}
        # dont mutate original
        payload_row = dict(new_user_data)

        # Use webapp addRow (payload key rowData) — matches push_row_to_sheet
        if self.use_webapp:
            resp = self._post_to_webapp("addRow", {"rowData": payload_row, "sheet": self.client_workflow_sheet})
            return resp if isinstance(resp, dict) else {"success": bool(resp)}

        # Sheets API fallback: append
        if self.use_sheets_api:
            try:
                r = self.sheets.spreadsheets().values().get(spreadsheetId=self.spreadsheet_id, range=self.client_workflow_sheet).execute()
                values = r.get("values", [])
                if values:
                    headers = values[0]
                else:
                    headers = list(payload_row.keys())
                    self.sheets.spreadsheets().values().update(spreadsheetId=self.spreadsheet_id, range=self.client_workflow_sheet + "!A1", valueInputOption="RAW", body={"values": [headers]}).execute()
                ordered = [ payload_row.get(h, "") for h in headers ]
                self.sheets.spreadsheets().values().append(spreadsheetId=self.spreadsheet_id, range=self.client_workflow_sheet, valueInputOption="RAW", insertDataOption="INSERT_ROWS", body={"values": [ordered]}).execute()
                return {"success": True}
            except Exception as e:
                logger.error("create_new_user via Sheets API failed: %s", e)
                return {"success": False, "error": str(e)}

        # local fallback
        ok = self._append_local_store(payload_row)
        return {"success": ok}

    def update_booking(self, booking_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update booking/workflow in Client_workflow sheet. Uses updateUserWorkflow action to match main_final."""
        email = booking_data.get("email") or booking_data.get("Email")
        if not email:
            return {"success": False, "error": "Missing email"}

        # Build payload similar to update_workflow in main_final
        updates = {}
        for k, v in booking_data.items():
            if k.lower() in ("email", "sheet"):
                continue
            updates[k] = v

        if self.use_webapp:
            payload = {"email": email, "updates": updates, "sheet": self.client_workflow_sheet}
            resp = self._post_to_webapp("updateUserWorkflow", payload)
            return resp if isinstance(resp, dict) else {"success": bool(resp)}

        if self.use_sheets_api:
            # use update logic similar to earlier implementation
            try:
                r = self.sheets.spreadsheets().values().get(spreadsheetId=self.spreadsheet_id, range=self.client_workflow_sheet).execute()
                values = r.get("values", [])
                if not values or len(values) < 2:
                    return {"success": False, "error": "Sheet empty"}
                headers = values[0]
                headers_norm = [_normalize_header(h) for h in headers]
                for idx, row in enumerate(values[1:], start=2):
                    padded = row + [""] * (len(headers) - len(row))
                    row_dict = { headers_norm[i]: padded[i] for i in range(len(headers)) }
                    if str(row_dict.get("email", "")).strip().lower() == str(email).strip().lower():
                        for k, v in updates.items():
                            k_norm = _normalize_header(k)
                            if k_norm in headers_norm:
                                pos = headers_norm.index(k_norm)
                                padded[pos] = v
                            else:
                                headers.append(k)
                                headers_norm.append(k_norm)
                                padded.append(v)
                        if len(headers) != len(values[0]):
                            self.sheets.spreadsheets().values().update(spreadsheetId=self.spreadsheet_id, range=self.client_workflow_sheet + "!A1", valueInputOption="RAW", body={"values": [headers]}).execute()
                        self.sheets.spreadsheets().values().update(spreadsheetId=self.spreadsheet_id, range=f"{self.client_workflow_sheet}!A{idx}", valueInputOption="RAW", body={"values": [padded]}).execute()
                        return {"success": True}
                return {"success": False, "error": "Email not found"}
            except Exception as e:
                logger.error("update_booking via API failed: %s", e)
                return {"success": False, "error": str(e)}

        # local fallback
        ok = self._update_local_store_by_email(email, updates)
        return {"success": ok}

    def update_workflow_stage(self, email: str, stage: str) -> bool:
        if not email:
            return False
        if self.use_webapp:
            resp = self._post_to_webapp("updateUserWorkflow", {"email": email, "updates": {"Workflow Stage": stage}})
            return bool(resp)
        result = self.update_booking({"email": email, "Workflow Stage": stage})
        return bool(result and result.get("success"))

    def get_available_tents(self) -> int:
        total = self._total_tents or int(os.environ.get("TOTAL_TENTS", 14))
        # Prefer webapp availability call if implemented
        if self.use_webapp:
            resp = self._post_to_webapp("get_availability", {"sheet": self.client_workflow_sheet})
            if isinstance(resp, dict) and "available_tents" in resp:
                try:
                    return int(resp.get("available_tents", total))
                except Exception:
                    return total
            if isinstance(resp, int):
                return resp
        # Fallback heuristic
        rows = None
        if self.use_sheets_api:
            try:
                rows = self._read_sheet_via_api(self.client_workflow_sheet)
            except Exception:
                rows = []
        else:
            rows = self._read_local_store()
        active_stages = {"id_verified", "checked_in", "confirmed", "booking_confirmed", "confirmed_guest", "paid"}
        booked = 0
        seen_booking_ids = set()
        for r in rows:
            stage = (r.get("Workfow Stage") or r.get("workflow_stage") or r.get("WorkfowStage") or r.get("workfow_stage") or "").strip().lower()
            booking_id = r.get("Booking Id") or r.get("booking_id") or r.get("booking")
            room_alloted = r.get("Room Alloted") or r.get("room_alloted") or r.get("room")
            if stage in active_stages or (room_alloted and str(room_alloted).strip()):
                if booking_id:
                    if booking_id in seen_booking_ids:
                        continue
                    seen_booking_ids.add(booking_id)
                booked += 1
        return max(0, total - booked)

    def create_booking(self, booking_data: Dict[str, Any]) -> Dict[str, Any]:
        if not booking_data:
            return {"success": False, "error": "Missing booking data"}
        if not booking_data.get("booking_id"):
            booking_data["booking_id"] = f"ILORA{datetime.utcnow().strftime('%Y%m%d')}{os.urandom(3).hex().upper()}"
        booking_data["booking_date"] = datetime.utcnow().isoformat()
        if self.use_webapp:
            resp = self._post_to_webapp("addRow", {"rowData": booking_data, "sheet": self.bookings_sheet})
            return resp if isinstance(resp, dict) else {"success": bool(resp)}
        # Sheets API/local fallback: append
        if self.use_sheets_api:
            try:
                r = self.sheets.spreadsheets().values().get(spreadsheetId=self.spreadsheet_id, range=self.bookings_sheet).execute()
                values = r.get("values", [])
                if values:
                    headers = values[0]
                else:
                    headers = list(booking_data.keys())
                    self.sheets.spreadsheets().values().update(spreadsheetId=self.spreadsheet_id, range=self.bookings_sheet + "!A1", valueInputOption="RAW", body={"values": [headers]}).execute()
                ordered = [ booking_data.get(h, "") for h in headers ]
                self.sheets.spreadsheets().values().append(spreadsheetId=self.spreadsheet_id, range=self.bookings_sheet, valueInputOption="RAW", insertDataOption="INSERT_ROWS", body={"values": [ordered]}).execute()
                return {"success": True}
            except Exception as e:
                logger.error("create_booking via API failed: %s", e)
                return {"success": False, "error": str(e)}
        ok = self._append_local_store(booking_data)
        return {"success": ok}

    # Helper for Sheets API usage
    def _read_sheet_via_api(self, sheet_name: str) -> List[Dict[str, Any]]:
        if not self.use_sheets_api:
            return []
        try:
            r = self.sheets.spreadsheets().values().get(spreadsheetId=self.spreadsheet_id, range=sheet_name).execute()
            values = r.get("values", [])
            if not values:
                return []
            headers = [ _normalize_header(h) for h in values[0] ]
            rows = []
            for row in values[1:]:
                padded = row + [""] * (len(headers) - len(row))
                rows.append({ headers[i]: padded[i] for i in range(len(headers)) })
            return rows
        except Exception as e:
            logger.error("_read_sheet_via_api error: %s", e)
            return []


'''
# Smoke test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    svc = GoogleSheetsService()
    print("webapp:", svc.use_webapp)
    print("sheets_api:", svc.use_sheets_api)
    print("sample lookup (test@example.com):", svc.get_user_by_email("test@example.com"))
    print("available tents:", svc.get_available_tents())
'''

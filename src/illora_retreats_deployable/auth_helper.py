import requests
import logging
from typing import Optional, Tuple, Dict, Any
from config import Config

GSHEET_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbxQjqqC_KM-zKlXAf2fs6B3jUjBBvuIES0a2VA4guZP0rZMR7A8JJGxDIUEzmcSZWFJ/exec"
CLIENT_WORKFLOW_SHEET = "Client_workflow"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_user_credentials(username: str, password: str) -> Tuple[bool, bool, Optional[Dict[str, Any]], str]:
    """
    Verify user credentials against the Google Sheet
    Returns: (found: bool, verified: bool, user_data: Optional[Dict], message: str)
    """
    if not GSHEET_WEBAPP_URL:
        raise RuntimeError("GSHEET_WEBAPP_URL not configured")

    try:
        # Call the Apps Script verifyUser action
        payload = {
            "action": "verifyUser",
            "sheet": CLIENT_WORKFLOW_SHEET,
            "username": username,  # Will be treated as email in Apps Script
            "password": password
        }
        
        logger.info(f"Attempting login with username: {username}")
        logger.info(f"Sending request to Apps Script URL: {GSHEET_WEBAPP_URL}")
        logger.info(f"Payload being sent: {payload}")
        
        # Make the request
        resp = requests.post(GSHEET_WEBAPP_URL, json=payload, timeout=10)
        
        # Log the raw response
        logger.info(f"Raw response status code: {resp.status_code}")
        logger.info(f"Raw response content: {resp.text}")
        
        resp.raise_for_status()
        
        # Parse response
        data = resp.json()
        logger.info(f"Parsed response data: {data}")
        
        # Check for error in response
        if "error" in data:
            error_msg = str(data["error"])
            logger.error(f"Error from Apps Script: {error_msg}")
            return False, False, None, error_msg
            
        # Extract values exactly as returned by Apps Script
        found = data.get("found", False)
        verified = data.get("verified", False)
        user_data = data.get("userData")
        message = data.get("message", "Unknown error")
        
        logger.info(f"Authentication result - Found: {found}, Verified: {verified}")
        logger.info(f"User data received: {user_data}")
        
        if found and verified:
            logger.info(f"User {username} successfully verified")
        else:
            logger.warning(f"Login failed for {username}: {message}")
            
        return found, verified, user_data, message
        
    except requests.RequestException as e:
        error_msg = f"Network error while verifying credentials: {str(e)}"
        logger.error(error_msg)
        return False, False, None, error_msg
        
    except Exception as e:
        error_msg = f"Unexpected error during verification: {str(e)}"
        logger.error(error_msg)
        return False, False, None, error_msg
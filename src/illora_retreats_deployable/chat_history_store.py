import sqlite3
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
import os

CHAT_DB_PATH = "illora_chat_history.db"

def init_chat_db():
    """Initialize the chat history database."""
    conn = sqlite3.connect(CHAT_DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS chat_history(
        email TEXT PRIMARY KEY,
        messages TEXT NOT NULL,
        last_updated TEXT NOT NULL
    )""")
    conn.commit()
    conn.close()

def save_chat_history(email: str, messages: List[Dict[str, Any]]):
    """Save chat history for a user."""
    if not email:
        return
    
    conn = sqlite3.connect(CHAT_DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO chat_history(email, messages, last_updated) VALUES(?,?,?)",
        (email.lower(), json.dumps(messages), datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()

def load_chat_history(email: str) -> List[Dict[str, Any]]:
    """Load chat history for a user."""
    if not email:
        return []
    
    conn = sqlite3.connect(CHAT_DB_PATH)
    c = conn.cursor()
    c.execute("SELECT messages FROM chat_history WHERE email=?", (email.lower(),))
    row = c.fetchone()
    conn.close()
    
    if row:
        try:
            return json.loads(row[0])
        except Exception:
            return []
    return []

def clear_chat_history(email: str):
    """Clear chat history for a user."""
    if not email:
        return
    
    conn = sqlite3.connect(CHAT_DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM chat_history WHERE email=?", (email.lower(),))
    conn.commit()
    conn.close()
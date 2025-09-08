# illora/checkin_app/chat_models.py
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.sql import func
from .database import Base

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=True)
    email = Column(String, index=True, nullable=True)
    channel = Column(String, default="web", index=True)
    role = Column(String, nullable=False)  # "user" or "assistant"
    text = Column(Text, nullable=False)
    intent = Column(String, nullable=True)
    is_guest = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

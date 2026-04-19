# Models module - data models

from __future__ import annotations

from typing import TYPE_CHECKING

from client.models.ai_assistant import AIMessage, AIMessageRole, AIMessageStatus, AIThread, AIThreadStatus
from client.models.message import ChatMessage, Session, AISession, MessageType

if TYPE_CHECKING:
    from client.models.message_model import MessageModel
    from client.models.session_model import SessionModel

__all__ = [
    "ChatMessage",
    "AIMessage",
    "AIMessageRole",
    "AIMessageStatus",
    "AIThread",
    "AIThreadStatus",
    "Session",
    "AISession",
    "MessageType",
    "MessageModel",
    "SessionModel",
]


def __getattr__(name: str):
    """Lazily import Qt-backed models so non-UI modules avoid PySide6 imports."""
    if name == "MessageModel":
        from client.models.message_model import MessageModel

        return MessageModel
    if name == "SessionModel":
        from client.models.session_model import SessionModel

        return SessionModel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

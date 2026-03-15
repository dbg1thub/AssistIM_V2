"""
Event Definitions

Define all application events using dataclasses.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class ConnectionState(Enum):
    """WebSocket connection states."""
    
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


@dataclass
class MessageReceivedEvent:
    """Event fired when a message is received."""
    
    message_id: str
    sender_id: str
    session_id: str
    content: str
    timestamp: datetime
    message_type: str = "text"
    
    def __str__(self) -> str:
        return f"MessageReceivedEvent(from={self.sender_id}, content={self.content[:20]}...)"


@dataclass
class MessageSentEvent:
    """Event fired when a message is sent."""
    
    message_id: str
    session_id: str
    content: str
    timestamp: datetime
    status: str = "sent"
    
    def __str__(self) -> str:
        return f"MessageSentEvent(id={self.message_id}, status={self.status})"


@dataclass
class ConnectionStateEvent:
    """Event fired when connection state changes."""
    
    state: ConnectionState
    reason: Optional[str] = None
    timestamp: datetime = None
    
    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    def __str__(self) -> str:
        return f"ConnectionStateEvent(state={self.state.value})"


@dataclass
class AIStreamChunkEvent:
    """Event fired when AI streaming returns a chunk."""
    
    session_id: str
    chunk: str
    is_first: bool = False
    is_last: bool = False
    timestamp: datetime = None
    
    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    def __str__(self) -> str:
        return f"AIStreamChunkEvent(session={self.session_id}, first={self.is_first}, last={self.is_last})"


@dataclass
class SessionUpdatedEvent:
    """Event fired when a session is updated."""
    
    session_id: str
    name: Optional[str] = None
    last_message: Optional[str] = None
    unread_count: int = 0
    timestamp: datetime = None
    
    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class FriendAddedEvent:
    """Event fired when a friend is added."""
    
    user_id: str
    nickname: str
    timestamp: datetime = None
    
    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class FriendRemovedEvent:
    """Event fired when a friend is removed."""
    
    user_id: str
    timestamp: datetime = None
    
    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class ErrorEvent:
    """Event fired when an error occurs."""
    
    error_type: str
    message: str
    details: Optional[dict] = None
    timestamp: datetime = None
    
    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now()


EVENT_NAMES = {
    "message_received": MessageReceivedEvent,
    "message_sent": MessageSentEvent,
    "connection_state": ConnectionStateEvent,
    "ai_stream_chunk": AIStreamChunkEvent,
    "session_updated": SessionUpdatedEvent,
    "friend_added": FriendAddedEvent,
    "friend_removed": FriendRemovedEvent,
    "error": ErrorEvent,
}

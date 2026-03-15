"""
Message Protocol Module

WebSocket message encoding and decoding with standardized format.
"""
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class WebSocketMessage:
    """
    Standardized WebSocket message format.
    
    Attributes:
        type: Message type (e.g., "chat", "ack", "heartbeat")
        seq: Message sequence number for ordering
        msg_id: Unique message identifier (UUID)
        timestamp: Unix timestamp in milliseconds
        data: Message payload
    """
    
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    seq: int = 0
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.type,
            "seq": self.seq,
            "msg_id": self.msg_id,
            "timestamp": self.timestamp,
            "data": self.data,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WebSocketMessage":
        """Create from dictionary."""
        return cls(
            type=data.get("type", ""),
            seq=data.get("seq", 0),
            msg_id=data.get("msg_id", str(uuid.uuid4())),
            timestamp=data.get("timestamp", int(time.time() * 1000)),
            data=data.get("data", {}),
        )


# Message type constants
class MessageType:
    """Standard message types."""
    
    # Chat messages
    CHAT = "chat"
    CHAT_ACK = "chat_ack"
    
    # AI messages
    AI_STREAM_START = "ai_stream_start"
    AI_STREAM_CHUNK = "ai_stream_chunk"
    AI_STREAM_END = "ai_stream_end"
    
    # System messages
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    
    # Connection
    AUTH = "auth"
    AUTH_ACK = "auth_ack"
    
    # Sync
    SYNC_REQUEST = "sync_request"
    SYNC_RESPONSE = "sync_response"
    
    # Error
    ERROR = "error"
    
    # Presence
    PRESENCE_UPDATE = "presence_update"
    PRESENCE_QUERY = "presence_query"


def encode_message(
    msg_type: str,
    data: Optional[dict[str, Any]] = None,
    msg_id: Optional[str] = None,
    seq: int = 0,
) -> str:
    """
    Encode a message to JSON string.
    
    Args:
        msg_type: Message type
        data: Message payload
        msg_id: Optional message ID (generated if not provided)
        seq: Sequence number
    
    Returns:
        JSON string
    
    Example:
        >>> encode_message("chat", {"content": "Hello"})
        '{"type": "chat", "seq": 0, "msg_id": "...", "timestamp": 123456, "data": {"content": "Hello"}}'
    """
    message = WebSocketMessage(
        type=msg_type,
        data=data or {},
        msg_id=msg_id or str(uuid.uuid4()),
        seq=seq,
        timestamp=int(time.time() * 1000),
    )
    return json.dumps(message.to_dict())


def decode_message(raw: str | dict) -> Optional[WebSocketMessage]:
    """
    Decode a message from JSON string or dict.
    
    Args:
        raw: JSON string or dict
    
    Returns:
        WebSocketMessage or None if invalid
    
    Example:
        >>> msg = decode_message('{"type": "chat", "data": {"content": "Hello"}}')
        >>> msg.type
        'chat'
    """
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
    elif isinstance(raw, dict):
        data = raw
    else:
        return None
    
    if not isinstance(data, dict):
        return None
    
    required_fields = ["type"]
    if not all(k in data for k in required_fields):
        return None
    
    return WebSocketMessage.from_dict(data)


def create_ack_message(original_msg: WebSocketMessage, success: bool = True, error: Optional[str] = None) -> str:
    """
    Create an acknowledgment message.
    
    Args:
        original_msg: The original message to acknowledge
        success: Whether the operation was successful
        error: Optional error message
    
    Returns:
        JSON string ack message
    """
    data = {
        "original_msg_id": original_msg.msg_id,
        "original_seq": original_msg.seq,
        "success": success,
    }
    
    if error:
        data["error"] = error
    
    return encode_message(MessageType.CHAT_ACK, data)


def create_heartbeat_message() -> str:
    """Create a heartbeat message."""
    return encode_message(MessageType.HEARTBEAT, {})


def is_valid_message(data: Any) -> bool:
    """
    Check if data is a valid WebSocket message.
    
    Args:
        data: Data to validate
    
    Returns:
        True if valid, False otherwise
    """
    if not isinstance(data, dict):
        return False
    
    if "type" not in data:
        return False
    
    return True


class MessageBuilder:
    """Builder for constructing messages with fluent API."""
    
    def __init__(self, msg_type: str):
        self._type = msg_type
        self._data: dict[str, Any] = {}
        self._msg_id: Optional[str] = None
        self._seq: int = 0
    
    def set_data(self, key: str, value: Any) -> "MessageBuilder":
        """Add data field."""
        self._data[key] = value
        return self
    
    def set_data_dict(self, data: dict[str, Any]) -> "MessageBuilder":
        """Set entire data dict."""
        self._data = data
        return self
    
    def set_msg_id(self, msg_id: str) -> "MessageBuilder":
        """Set message ID."""
        self._msg_id = msg_id
        return self
    
    def set_seq(self, seq: int) -> "MessageBuilder":
        """Set sequence number."""
        self._seq = seq
        return self
    
    def build(self) -> str:
        """Build and encode the message."""
        return encode_message(
            self._type,
            self._data,
            self._msg_id,
            self._seq,
        )
    
    def build_dict(self) -> dict[str, Any]:
        """Build and return as dict."""
        return decode_message(self.build()).to_dict()

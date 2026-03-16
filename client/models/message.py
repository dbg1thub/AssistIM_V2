"""
Data Models Module

Core data models using dataclasses.
"""
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


def _coerce_datetime(value: Any) -> Optional[datetime]:
    """Normalize timestamps from float/int/ISO string into datetime."""
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


class MessageStatus(Enum):
    """Message sending status."""

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    RECEIVED = "received"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    RECALLED = "recalled"
    EDITED = "edited"


class MessageType(Enum):
    """Message type."""
    
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    VIDEO = "video"
    VOICE = "voice"
    SYSTEM = "system"


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def infer_message_type_from_path(path: str) -> MessageType:
    """Infer a message type from a file path or URL."""
    extension = os.path.splitext((path or "").split("?", 1)[0])[1].lower()
    if extension in IMAGE_EXTENSIONS:
        return MessageType.IMAGE
    if extension in VIDEO_EXTENSIONS:
        return MessageType.VIDEO
    return MessageType.FILE


def format_message_preview(content: str, message_type: MessageType | str | None = None) -> str:
    """Format a short session preview for a message."""
    normalized_type = message_type
    if isinstance(normalized_type, str):
        try:
            normalized_type = MessageType(normalized_type)
        except ValueError:
            normalized_type = None

    if normalized_type == MessageType.IMAGE:
        return "[图片]"
    if normalized_type == MessageType.VIDEO:
        return "[视频]"
    if normalized_type == MessageType.FILE:
        return "[文件]"

    text = (content or "").strip()
    if not text:
        return ""

    inferred_type = infer_message_type_from_path(text) if text.startswith(("/", "http://", "https://")) or os.path.splitext(text)[1] else None
    if inferred_type == MessageType.IMAGE:
        return "[图片]"
    if inferred_type == MessageType.VIDEO:
        return "[视频]"
    if inferred_type == MessageType.FILE and (text.startswith("/uploads/") or text.startswith("http://") or text.startswith("https://")):
        return "[文件]"

    if text.count("|") >= 2:
        tail = text.split("|")[-1]
        inferred_tail_type = infer_message_type_from_path(tail)
        if inferred_tail_type == MessageType.IMAGE:
            return "[图片]"
        if inferred_tail_type == MessageType.VIDEO:
            return "[视频]"
        if inferred_tail_type == MessageType.FILE:
            return "[文件]"

    return text


class UserStatus(Enum):
    """User online status."""
    
    ONLINE = "online"
    OFFLINE = "offline"
    AWAY = "away"
    BUSY = "busy"


@dataclass
class User:
    """
    User model.
    
    Attributes:
        user_id: Unique user identifier
        nickname: User nickname
        avatar: Avatar URL
        status: Online status
        email: Email address
        created_at: Account creation time
        last_login: Last login time
    """
    
    user_id: str
    nickname: str
    avatar: Optional[str] = None
    status: UserStatus = UserStatus.OFFLINE
    email: Optional[str] = None
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    extra: dict[str, Any] = field(default_factory=dict)
    
    def is_online(self) -> bool:
        """Check if user is online."""
        return self.status == UserStatus.ONLINE
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "user_id": self.user_id,
            "nickname": self.nickname,
            "avatar": self.avatar,
            "status": self.status.value,
            "email": self.email,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            **self.extra,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "User":
        """Create from dictionary."""
        status = UserStatus(data.get("status", "offline"))
        
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        
        last_login = data.get("last_login")
        if isinstance(last_login, str):
            last_login = datetime.fromisoformat(last_login)
        
        return cls(
            user_id=data["user_id"],
            nickname=data["nickname"],
            avatar=data.get("avatar"),
            status=status,
            email=data.get("email"),
            created_at=created_at,
            last_login=last_login,
        )


@dataclass
class ChatMessage:
    """
    Chat message model.
    
    Attributes:
        message_id: Unique message identifier
        session_id: Session ID this message belongs to
        sender_id: Sender user ID
        content: Message content
        message_type: Type of message
        status: Sending status
        timestamp: Message timestamp
        updated_at: Updated timestamp
        is_self: Whether message is from current user
        is_ai: Whether message is from AI
        extra: Additional fields
    """
    
    message_id: str
    session_id: str
    sender_id: str
    content: str
    message_type: MessageType = MessageType.TEXT
    status: MessageStatus = MessageStatus.PENDING
    timestamp: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_self: bool = False
    is_ai: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        """Set default timestamps."""
        self.timestamp = _coerce_datetime(self.timestamp)
        self.updated_at = _coerce_datetime(self.updated_at)
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.updated_at is None:
            self.updated_at = self.timestamp
    
    def mark_sent(self) -> None:
        """Mark message as sent."""
        self.status = MessageStatus.SENT
        self.updated_at = datetime.now()
    
    def mark_delivered(self) -> None:
        """Mark message as delivered."""
        self.status = MessageStatus.DELIVERED
        self.updated_at = datetime.now()
    
    def mark_read(self) -> None:
        """Mark message as read."""
        self.status = MessageStatus.READ
        self.updated_at = datetime.now()
    
    def mark_failed(self) -> None:
        """Mark message as failed."""
        self.status = MessageStatus.FAILED
        self.updated_at = datetime.now()
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "sender_id": self.sender_id,
            "content": self.content,
            "message_type": self.message_type.value,
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_self": self.is_self,
            "is_ai": self.is_ai,
            **self.extra,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChatMessage":
        """Create from dictionary."""
        msg_type = MessageType(data.get("message_type", "text"))
        status = MessageStatus(data.get("status", "pending"))
        extra_keys = {
            "message_id", "session_id", "sender_id", "content", "message_type",
            "status", "timestamp", "updated_at", "is_self", "is_ai",
        }
        
        timestamp = data.get("timestamp")
        timestamp = _coerce_datetime(timestamp)
        
        updated_at = data.get("updated_at")
        updated_at = _coerce_datetime(updated_at)
        
        return cls(
            message_id=data["message_id"],
            session_id=data["session_id"],
            sender_id=data["sender_id"],
            content=data["content"],
            message_type=msg_type,
            status=status,
            timestamp=timestamp,
            updated_at=updated_at,
            is_self=data.get("is_self", False),
            is_ai=data.get("is_ai", False),
            extra={key: value for key, value in data.items() if key not in extra_keys},
        )


@dataclass
class Session:
    """
    Chat session model.
    
    Attributes:
        session_id: Unique session identifier
        name: Session name (or participant name for 1:1)
        session_type: "direct" or "group"
        participant_ids: List of participant user IDs
        last_message: Last message preview
        last_message_time: Last message timestamp
        unread_count: Number of unread messages
        avatar: Session avatar URL
        created_at: Session creation time
        updated_at: Session update time
        is_ai_session: Whether this is an AI assistant session
        extra: Additional fields
    """
    
    session_id: str
    name: str
    session_type: str = "direct"
    participant_ids: list[str] = field(default_factory=list)
    last_message: Optional[str] = None
    last_message_time: Optional[datetime] = None
    unread_count: int = 0
    avatar: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_ai_session: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        """Set default timestamps."""
        self.last_message_time = _coerce_datetime(self.last_message_time)
        self.created_at = _coerce_datetime(self.created_at)
        self.updated_at = _coerce_datetime(self.updated_at)
        now = datetime.now()
        if self.created_at is None:
            self.created_at = now
        if self.updated_at is None:
            self.updated_at = now
        if self.last_message_time is None:
            self.last_message_time = self.created_at
    
    def update_last_message(self, content: str, timestamp: Optional[datetime] = None) -> None:
        """Update last message."""
        timestamp = _coerce_datetime(timestamp)
        self.last_message = content
        self.last_message_time = timestamp or datetime.now()
        self.updated_at = self.last_message_time
    
    def increment_unread(self) -> None:
        """Increment unread count."""
        self.unread_count += 1
    
    def clear_unread(self) -> None:
        """Clear unread count."""
        self.unread_count = 0
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "name": self.name,
            "session_type": self.session_type,
            "participant_ids": self.participant_ids,
            "last_message": self.last_message,
            "last_message_time": self.last_message_time.isoformat() if self.last_message_time else None,
            "unread_count": self.unread_count,
            "avatar": self.avatar,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_ai_session": self.is_ai_session,
            **self.extra,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":
        """Create from dictionary."""
        last_message_time = data.get("last_message_time")
        last_message_time = _coerce_datetime(last_message_time)
        
        created_at = data.get("created_at")
        created_at = _coerce_datetime(created_at)
        
        updated_at = data.get("updated_at")
        updated_at = _coerce_datetime(updated_at)
        
        return cls(
            session_id=data["session_id"],
            name=data["name"],
            session_type=data.get("session_type", "direct"),
            participant_ids=data.get("participant_ids", []),
            last_message=data.get("last_message"),
            last_message_time=last_message_time,
            unread_count=data.get("unread_count", 0),
            avatar=data.get("avatar"),
            created_at=created_at,
            updated_at=updated_at,
            is_ai_session=data.get("is_ai_session", False),
        )


@dataclass
class AISession:
    """
    AI Chat session model.
    
    Extends Session with AI-specific fields.
    
    Attributes:
        session_id: Inherited from Session
        name: Inherited from Session
        provider: AI provider name (openai, ollama, etc.)
        model: AI model name
        system_prompt: System prompt for AI
        temperature: Sampling temperature
        max_tokens: Max tokens to generate
        context_messages: Number of messages to keep in context
    """
    
    session_id: str
    name: str
    provider: str = "openai"
    model: str = "gpt-3.5-turbo"
    system_prompt: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2048
    context_messages: int = 10
    is_ai_session: bool = True
    extra: dict[str, Any] = field(default_factory=dict)
    
    def to_session(self) -> Session:
        """Convert to generic Session."""
        return Session(
            session_id=self.session_id,
            name=self.name,
            session_type="ai",
            is_ai_session=True,
            extra=self.extra,
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "name": self.name,
            "provider": self.provider,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "context_messages": self.context_messages,
            "is_ai_session": self.is_ai_session,
            **self.extra,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AISession":
        """Create from dictionary."""
        return cls(
            session_id=data["session_id"],
            name=data["name"],
            provider=data.get("provider", "openai"),
            model=data.get("model", "gpt-3.5-turbo"),
            system_prompt=data.get("system_prompt"),
            temperature=data.get("temperature", 0.7),
            max_tokens=data.get("max_tokens", 2048),
            context_messages=data.get("context_messages", 10),
        )

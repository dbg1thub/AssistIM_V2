"""
Data Models Module

Core data models using dataclasses.
"""
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from client.core.datetime_utils import coerce_local_datetime


def _coerce_datetime(value: Any) -> Optional[datetime]:
    """Normalize timestamps from float/int/ISO string into datetime."""
    return coerce_local_datetime(value)


def _preview_token(key: str, default: str) -> str:
    """Resolve localized preview labels without hard-wiring model imports to UI startup."""
    try:
        from client.core.i18n import tr
    except Exception:
        return default
    return tr(key, default)


class MessageStatus(Enum):
    """Message sending status."""

    PENDING = "pending"
    AWAITING_SECURITY_CONFIRMATION = "awaiting_security_confirmation"
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


def _coerce_size_bytes(raw_value: Any, fallback_size: int = 0) -> int:
    try:
        return max(0, int(raw_value or fallback_size or 0))
    except (TypeError, ValueError):
        return max(0, int(fallback_size or 0))



def build_remote_attachment_extra(
    upload_payload: dict[str, Any],
    *,
    fallback_name: str,
    fallback_size: int = 0,
    duration: int | None = None,
) -> dict[str, Any]:
    """Build one shareable attachment payload that is safe to send to the server."""
    normalized = dict(upload_payload or {})
    file_url = str(normalized.get("url") or normalized.get("file_url") or "")
    original_name = str(
        normalized.get("original_name")
        or normalized.get("file_name")
        or normalized.get("name")
        or fallback_name
        or "upload.bin"
    )
    mime_type = str(normalized.get("mime_type") or normalized.get("file_type") or "")
    storage_provider = str(normalized.get("storage_provider") or "")
    storage_key = str(normalized.get("storage_key") or "")
    checksum_sha256 = str(normalized.get("checksum_sha256") or "")
    size_bytes = _coerce_size_bytes(normalized.get("size_bytes"), fallback_size)

    media = dict(normalized.get("media") or {})
    media.setdefault("url", file_url)
    media.setdefault("original_name", original_name)
    media.setdefault("mime_type", mime_type)
    media.setdefault("storage_provider", storage_provider)
    media.setdefault("storage_key", storage_key)
    media.setdefault("size_bytes", size_bytes)
    media.setdefault("checksum_sha256", checksum_sha256)

    extra = {
        "url": file_url,
        "name": original_name,
        "file_type": mime_type,
        "size": size_bytes,
        "media": media,
    }
    if duration is not None:
        extra["duration"] = duration
    return extra



def build_attachment_extra(
    upload_payload: dict[str, Any],
    *,
    local_path: str,
    fallback_name: str,
    fallback_size: int = 0,
    uploading: bool = False,
    duration: int | None = None,
) -> dict[str, Any]:
    """Build one normalized local attachment payload for chat messages."""
    extra = build_remote_attachment_extra(
        upload_payload,
        fallback_name=fallback_name or os.path.basename(local_path),
        fallback_size=fallback_size,
        duration=duration,
    )
    extra["local_path"] = local_path
    extra["uploading"] = uploading
    return extra



def sanitize_outbound_message_extra(extra: dict[str, Any] | None) -> dict[str, Any]:
    """Remove local-only attachment state before sending a payload to the server."""
    normalized = dict(extra or {})
    normalized.pop("local_path", None)
    normalized.pop("uploading", None)
    normalized.pop("security_pending", None)

    mentions = normalize_message_mentions(normalized.get("mentions"), content=str(normalized.get("content", "") or ""))
    if mentions:
        normalized["mentions"] = mentions
    else:
        normalized.pop("mentions", None)
    normalized.pop("content", None)

    media = dict(normalized.get("media") or {})
    if media:
        normalized["media"] = media

    encryption = dict(normalized.get("encryption") or {})
    if encryption:
        encryption.pop("local_plaintext", None)
        encryption.pop("decryption_error", None)
        encryption.pop("decryption_state", None)
        encryption.pop("recovery_action", None)
        encryption.pop("local_device_id", None)
        encryption.pop("target_device_id", None)
        encryption.pop("can_decrypt", None)
        if encryption:
            normalized["encryption"] = encryption
        else:
            normalized.pop("encryption", None)

    attachment_encryption = dict(normalized.get("attachment_encryption") or {})
    if attachment_encryption:
        attachment_encryption.pop("local_metadata", None)
        attachment_encryption.pop("decryption_error", None)
        attachment_encryption.pop("decryption_state", None)
        attachment_encryption.pop("recovery_action", None)
        attachment_encryption.pop("local_device_id", None)
        attachment_encryption.pop("target_device_id", None)
        attachment_encryption.pop("can_decrypt", None)
        if attachment_encryption.get("enabled"):
            normalized.pop("url", None)
            normalized.pop("name", None)
            normalized.pop("file_type", None)
            normalized.pop("size", None)
            normalized.pop("media", None)
        if attachment_encryption:
            normalized["attachment_encryption"] = attachment_encryption
        else:
            normalized.pop("attachment_encryption", None)
    return normalized


def normalize_message_mentions(raw_mentions: Any, *, content: str = "") -> list[dict[str, Any]]:
    """Normalize structured mention metadata attached to one text message."""
    if not isinstance(raw_mentions, list):
        return []

    normalized: list[dict[str, Any]] = []
    text = str(content or "")
    text_length = len(text)

    for raw_mention in raw_mentions:
        if not isinstance(raw_mention, dict):
            continue

        try:
            start = int(raw_mention.get("start", -1))
            end = int(raw_mention.get("end", -1))
        except (TypeError, ValueError):
            continue

        if start < 0 or end <= start:
            continue

        start = min(start, text_length) if text else start
        end = min(end, text_length) if text else end
        if end <= start:
            continue

        mention_type = str(raw_mention.get("mention_type", "") or "member").strip().lower()
        if mention_type not in {"member", "all"}:
            mention_type = "member"

        display_name = str(raw_mention.get("display_name", "") or "").strip()
        if not display_name:
            continue

        mention_text = text[start:end] if text else f"@{display_name}"
        if text and mention_text != f"@{display_name}":
            continue

        mention: dict[str, Any] = {
            "start": start,
            "end": end,
            "display_name": display_name,
            "mention_type": mention_type,
        }
        if mention_type == "member":
            member_id = str(raw_mention.get("member_id", "") or "").strip()
            if not member_id:
                continue
            mention["member_id"] = member_id

        normalized.append(mention)

    normalized.sort(key=lambda item: (int(item["start"]), int(item["end"])))
    return normalized


def merge_sender_profile_extra(extra: dict[str, Any] | None, sender_profile: dict[str, Any] | None) -> dict[str, Any]:
    """Merge one authoritative sender profile payload into message extra fields."""
    merged = dict(extra or {})
    if not isinstance(sender_profile, dict):
        return merged

    mapping = {
        "sender_avatar": sender_profile.get("avatar", ""),
        "sender_gender": sender_profile.get("gender", ""),
        "sender_username": sender_profile.get("username", ""),
        "sender_nickname": sender_profile.get("nickname", ""),
    }
    for key, raw_value in mapping.items():
        value = str(raw_value or "").strip()
        if merged.get(key) != value:
            merged[key] = value

    sender_name = (
        str(sender_profile.get("display_name", "") or "").strip()
        or str(sender_profile.get("nickname", "") or "").strip()
        or str(sender_profile.get("username", "") or "").strip()
        or str(sender_profile.get("id", "") or "").strip()
    )
    if sender_name and merged.get("sender_name") != sender_name:
        merged["sender_name"] = sender_name
    return merged


def format_message_preview(content: str, message_type: MessageType | str | None = None) -> str:
    """Format a short session preview for a message."""
    normalized_type = message_type
    if isinstance(normalized_type, str):
        try:
            normalized_type = MessageType(normalized_type)
        except ValueError:
            normalized_type = None

    if normalized_type == MessageType.IMAGE:
        return _preview_token("preview.image", "[Image]")
    if normalized_type == MessageType.VIDEO:
        return _preview_token("preview.video", "[Video]")
    if normalized_type == MessageType.FILE:
        return _preview_token("preview.file", "[File]")

    text = (content or "").strip()
    if not text:
        return ""

    inferred_type = infer_message_type_from_path(text) if text.startswith(("/", "http://", "https://")) or os.path.splitext(text)[1] else None
    if inferred_type == MessageType.IMAGE:
        return _preview_token("preview.image", "[Image]")
    if inferred_type == MessageType.VIDEO:
        return _preview_token("preview.video", "[Video]")
    if inferred_type == MessageType.FILE and (text.startswith("/uploads/") or text.startswith("http://") or text.startswith("https://")):
        return _preview_token("preview.file", "[File]")

    if text.count("|") >= 2:
        tail = text.split("|")[-1]
        inferred_tail_type = infer_message_type_from_path(tail)
        if inferred_tail_type == MessageType.IMAGE:
            return _preview_token("preview.image", "[Image]")
        if inferred_tail_type == MessageType.VIDEO:
            return _preview_token("preview.video", "[Video]")
        if inferred_tail_type == MessageType.FILE:
            return _preview_token("preview.file", "[File]")

    return text


def _quoted_recall_actor_name(name: str) -> str:
    """Wrap one recall actor name using the UI's quoted-member style."""
    normalized = str(name or "").strip()
    return f"“{normalized}”" if normalized else ""


def build_recall_notice(
    *,
    is_self: bool,
    session_type: str | None = None,
    sender_name: str = "",
    sender_id: str = "",
) -> str:
    """Build one localized recall notice from normalized message/session metadata."""
    if is_self:
        return _preview_token("message.recalled.self", "You recalled a message")

    normalized_session_type = str(session_type or "").strip().lower()
    actor_name = str(sender_name or "").strip() or str(sender_id or "").strip()
    if normalized_session_type == "group" and actor_name:
        try:
            from client.core.i18n import tr as _tr
        except Exception:
            return f"{_quoted_recall_actor_name(actor_name)} recalled a message"
        return _tr(
            "message.recalled.by",
            "{name} recalled a message",
            name=_quoted_recall_actor_name(actor_name),
        )

    return _preview_token("message.recalled.other", "The other side recalled a message")


def resolve_recall_notice(message: "ChatMessage") -> str:
    """Return the safe recall notice that should be shown to the user."""
    extra = getattr(message, "extra", {}) or {}
    explicit_notice = str(extra.get("recall_notice", "") or "").strip()
    if explicit_notice:
        return explicit_notice

    fallback_notice = build_recall_notice(
        is_self=bool(getattr(message, "is_self", False)),
        session_type=str(extra.get("session_type", "") or ""),
        sender_name=(
            str(extra.get("sender_name", "") or "").strip()
            or str(extra.get("sender_nickname", "") or "").strip()
            or str(extra.get("sender_username", "") or "").strip()
        ),
        sender_id=str(getattr(message, "sender_id", "") or ""),
    )

    message_type = getattr(message, "message_type", None)
    if message_type == MessageType.SYSTEM:
        text = (getattr(message, "content", "") or "").strip()
        return text or fallback_notice

    return fallback_notice

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
        setattr(self, "is_pinned", bool(self.extra.get("is_pinned", getattr(self, "is_pinned", False))))
    
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

    def display_avatar(self) -> Optional[str]:
        """Return the UI avatar source without mutating the stored session avatar semantics."""
        if self.session_type == "direct" and not self.is_ai_session:
            return str(self.extra.get("counterpart_avatar") or self.avatar or "") or None
        return self.avatar


    def encryption_mode(self) -> str:
        """Return the authoritative encryption mode for this session."""
        explicit_mode = str(self.extra.get("encryption_mode", "") or "").strip()
        if explicit_mode:
            return explicit_mode
        if self.is_ai_session or self.session_type == "ai":
            return "server_visible_ai"
        return "plain"

    def session_crypto_state(self) -> dict[str, Any]:
        """Return one normalized runtime crypto-state snapshot for this session."""
        return dict(self.extra.get("session_crypto_state") or {})

    def call_capabilities(self) -> dict[str, bool]:
        """Return the normalized runtime call capability map for this session."""
        raw = self.extra.get("call_capabilities")
        if isinstance(raw, dict):
            return {
                "voice": bool(raw.get("voice", False)),
                "video": bool(raw.get("video", False)),
            }
        supports_direct_call = self.session_type == "direct" and not self.is_ai_session
        return {
            "voice": supports_direct_call,
            "video": supports_direct_call,
        }

    def call_state(self) -> dict[str, Any]:
        """Return one normalized runtime call-state snapshot for this session."""
        return dict(self.extra.get("call_state") or {})

    def supports_call(self) -> bool:
        """Return whether this session currently supports any call modality."""
        capabilities = self.call_capabilities()
        return bool(capabilities.get("voice") or capabilities.get("video"))

    def uses_e2ee(self) -> bool:
        """Return whether this session should use end-to-end encryption."""
        return self.encryption_mode() in {"e2ee_private", "e2ee_group"}

    def security_summary(self) -> dict[str, Any]:
        """Return one high-level security summary for UI and diagnostics."""
        crypto_state = self.session_crypto_state()
        encryption_mode = self.encryption_mode()
        identity_status = str(crypto_state.get("identity_status") or "").strip()
        call_state = self.call_state()
        summary = {
            "session_id": str(self.session_id or ""),
            "encryption_mode": encryption_mode,
            "uses_e2ee": self.uses_e2ee(),
            "crypto_ready": bool(crypto_state.get("ready", False)),
            "device_registered": bool(crypto_state.get("device_registered", False)),
            "identity_status": identity_status,
            "identity_action_required": bool(crypto_state.get("identity_action_required", False)),
            "identity_review_action": str(crypto_state.get("identity_review_action") or ""),
            "identity_review_blocking": bool(crypto_state.get("identity_review_blocking", False)),
            "identity_alert_severity": str(crypto_state.get("identity_alert_severity") or ""),
            "identity_change_count": int(crypto_state.get("identity_change_count", 0) or 0),
            "identity_last_changed_at": str(crypto_state.get("identity_last_changed_at") or ""),
            "identity_last_trusted_at": str(crypto_state.get("identity_last_trusted_at") or ""),
            "identity_verification_available": bool(crypto_state.get("identity_verification_available", False)),
            "identity_primary_verification_device_id": str(
                crypto_state.get("identity_primary_verification_device_id") or ""
            ),
            "identity_primary_verification_fingerprint_short": str(
                crypto_state.get("identity_primary_verification_fingerprint_short") or ""
            ),
            "identity_primary_verification_code": str(
                crypto_state.get("identity_primary_verification_code") or ""
            ),
            "identity_primary_verification_code_short": str(
                crypto_state.get("identity_primary_verification_code_short") or ""
            ),
            "identity_local_fingerprint_short": str(crypto_state.get("identity_local_fingerprint_short") or ""),
            "decryption_state": str(crypto_state.get("decryption_state") or ""),
            "recovery_action": str(crypto_state.get("recovery_action") or ""),
            "supports_call": self.supports_call(),
            "call_active": bool(call_state.get("active", False)),
            "call_status": str(call_state.get("status") or ""),
            "actions": [],
        }
        if encryption_mode == "e2ee_private":
            if summary["identity_review_blocking"]:
                summary["headline"] = "identity_review_required"
                summary["recommended_action"] = str(summary["identity_review_action"] or "trust_peer_identity")
                summary["actions"] = [
                    self._security_action(
                        action_id="trust_peer_identity",
                        kind="identity_review",
                        label="Trust peer identity",
                        description="Confirm the peer device identity before sending more encrypted messages.",
                        blocking=True,
                        primary=True,
                    )
                ]
            elif summary["identity_action_required"]:
                summary["headline"] = "identity_unverified"
                summary["recommended_action"] = str(summary["identity_review_action"] or "trust_peer_identity")
                summary["actions"] = [
                    self._security_action(
                        action_id="trust_peer_identity",
                        kind="identity_review",
                        label="Trust peer identity",
                        description="Verify and trust the peer device identity for this encrypted session.",
                        blocking=False,
                        primary=True,
                    )
                ]
            elif summary["decryption_state"]:
                summary["headline"] = "decryption_recovery_required"
                summary["recommended_action"] = str(summary["recovery_action"] or "")
                if summary["recommended_action"]:
                    if summary["recommended_action"] == "switch_device":
                        summary["actions"] = [
                            self._security_action(
                                action_id="switch_device",
                                kind="crypto_recovery",
                                label="Switch device",
                                description="Open the device that owns this encrypted history to continue recovery.",
                                blocking=True,
                                primary=True,
                                available=False,
                                external_requirement={
                                    "kind": "switch_device",
                                    "target_device_id": str(crypto_state.get("target_device_id") or ""),
                                    "blocking": True,
                                },
                            )
                        ]
                    else:
                        summary["actions"] = [
                            self._security_action(
                                action_id=str(summary["recommended_action"]),
                                kind="crypto_recovery",
                                label=str(summary["recommended_action"]).replace("_", " "),
                                description="Run the recommended encrypted-session recovery flow on this device.",
                                blocking=False,
                                primary=True,
                            )
                        ]
            else:
                summary["headline"] = "secure"
                summary["recommended_action"] = ""
        elif encryption_mode == "e2ee_group":
            if summary["decryption_state"]:
                summary["headline"] = "group_recovery_required"
                summary["recommended_action"] = str(summary["recovery_action"] or "")
                if summary["recommended_action"]:
                    summary["actions"] = [
                        self._security_action(
                            action_id=str(summary["recommended_action"]),
                            kind="crypto_recovery",
                            label=str(summary["recommended_action"]).replace("_", " "),
                            description="Run the recommended group encryption recovery flow on this device.",
                            blocking=False,
                            primary=True,
                        )
                    ]
            else:
                summary["headline"] = "secure"
                summary["recommended_action"] = ""
        else:
            summary["headline"] = "not_e2ee"
            summary["recommended_action"] = ""
        return summary

    @staticmethod
    def _security_action(
        *,
        action_id: str,
        kind: str,
        label: str,
        description: str,
        blocking: bool,
        primary: bool,
        available: bool = True,
        external_requirement: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action = {
            "id": str(action_id or ""),
            "kind": str(kind or ""),
            "label": str(label or ""),
            "title": str(label or ""),
            "description": str(description or ""),
            "blocking": bool(blocking),
            "primary": bool(primary),
            "available": bool(available),
        }
        if external_requirement:
            action["external_requirement"] = dict(external_requirement)
        return action

    def display_gender(self) -> str:
        """Return the UI gender hint for avatar fallback rendering."""
        if self.session_type == "direct" and not self.is_ai_session:
            return str(self.extra.get("counterpart_gender") or self.extra.get("gender") or "")
        return str(self.extra.get("gender") or "")

    def display_avatar_seed(self) -> str:
        """Return the UI seed for deterministic avatar fallback rendering."""
        return str(self.extra.get("avatar_seed") or self.session_id or "")

    @staticmethod
    def _preferred_member_name(member: dict[str, Any]) -> str:
        """Resolve one stable member display name for group-derived presentation."""
        return (
            str(member.get("remark", "") or "").strip()
            or str(member.get("group_nickname", "") or "").strip()
            or str(member.get("nickname", "") or "").strip()
            or str(member.get("display_name", "") or "").strip()
            or str(member.get("username", "") or "").strip()
            or str(member.get("id", "") or "").strip()
        )

    def authoritative_group_id(self) -> str:
        """Return the authoritative backend group id bound to this group session."""
        if self.session_type != "group" or self.is_ai_session:
            return ""
        return str(self.extra.get("group_id", "") or "").strip()

    def authoritative_group_name(self) -> str:
        """Return the explicit backend group name without falling back to generated member labels."""
        if self.session_type != "group" or self.is_ai_session:
            return str(self.name or "").strip()
        return str(self.extra.get("server_name", "") or "").strip()

    def has_custom_group_name(self) -> bool:
        """Return whether this group uses an explicit server-side name instead of member-derived naming."""
        if self.session_type != "group" or self.is_ai_session:
            return True
        explicit_name = self.authoritative_group_name()
        if not explicit_name:
            return False

        names = self._group_display_names(limit=3)
        if not names:
            return True

        joined = "、".join(names)
        generated_names = {joined}
        if self.group_member_count() > 3:
            generated_names.add(joined + "...")
            generated_names.add(joined + "…")
        return explicit_name not in generated_names

    def group_member_count(self) -> int:
        """Return the best available member count for a group session."""
        raw_count = self.extra.get("member_count")
        try:
            normalized_count = int(raw_count or 0)
        except (TypeError, ValueError):
            normalized_count = 0
        if normalized_count > 0:
            return normalized_count
        members = list(self.extra.get("members") or [])
        if members:
            return len(members)
        return len([item for item in self.participant_ids if str(item or "").strip()])

    def _group_display_names(self, *, limit: int) -> list[str]:
        """Return group member display names for default naming, excluding the current user when possible."""
        members = list(self.extra.get("members") or [])
        if not members:
            return []

        current_user_id = str(self.extra.get("current_user_id", "") or "").strip()

        def collect(include_current_user: bool) -> list[str]:
            names: list[str] = []
            seen: set[str] = set()
            for member in members:
                member_id = str(member.get("id", "") or "").strip()
                if not include_current_user and current_user_id and member_id == current_user_id:
                    continue
                name = self._preferred_member_name(member)
                if not name or name in seen:
                    continue
                seen.add(name)
                names.append(name)
                if len(names) >= limit:
                    break
            return names

        names = collect(include_current_user=False)
        if names:
            return names
        return collect(include_current_user=True)

    def display_name(self) -> str:
        """Return the list/header display name without mutating the persisted session name."""
        explicit_name = self.authoritative_group_name()
        if self.session_type != "group" or self.is_ai_session or explicit_name:
            return explicit_name or str(self.name or "").strip()

        names = self._group_display_names(limit=3)
        if not names:
            return str(self.name or "").strip()

        joined = "、".join(names)
        return joined if self.group_member_count() <= 3 else joined + "..."

    def chat_title(self) -> str:
        """Return the chat-header title, including member count for default-named groups."""
        display_name = self.display_name()
        if self.session_type != "group" or self.is_ai_session or self.has_custom_group_name():
            return display_name

        names = self._group_display_names(limit=3)
        if not names:
            return display_name

        member_count = self.group_member_count()
        title = "、".join(names)
        return f"{title}({member_count})" if member_count > 0 else title

    def group_announcement_text(self) -> str:
        """Return the current group announcement body for this session."""
        if self.session_type != "group" or self.is_ai_session:
            return ""
        return str(self.extra.get("group_announcement", "") or "").strip()

    def group_announcement_message_id(self) -> str:
        """Return the announcement-version message id used for viewed-state tracking."""
        if self.session_type != "group" or self.is_ai_session:
            return ""
        return str(self.extra.get("announcement_message_id", "") or "").strip()

    def group_announcement_author_id(self) -> str:
        """Return the user id of the announcement publisher when available."""
        if self.session_type != "group" or self.is_ai_session:
            return ""
        return str(self.extra.get("announcement_author_id", "") or "").strip()

    def group_announcement_published_at(self) -> Optional[datetime]:
        """Return the local datetime for the latest group announcement publication."""
        if self.session_type != "group" or self.is_ai_session:
            return None
        return _coerce_datetime(self.extra.get("announcement_published_at"))

    def group_announcement_needs_view(self) -> bool:
        """Return whether the announcement card should remain visible for the current user."""
        announcement = self.group_announcement_text()
        if not announcement:
            return False
        announcement_message_id = self.group_announcement_message_id()
        if not announcement_message_id:
            return True
        last_viewed_message_id = str(self.extra.get("last_viewed_announcement_message_id", "") or "").strip()
        return last_viewed_message_id != announcement_message_id

    def preview_sender_name(self) -> str:
        """Return the sender name prefix for group-session preview rows."""
        if self.session_type != "group" or self.is_ai_session:
            return ""

        sender_id = str(self.extra.get("last_message_sender_id", "") or "").strip()
        if not sender_id:
            return ""
        current_user_id = str(self.extra.get("current_user_id", "") or "").strip()
        if current_user_id and sender_id == current_user_id:
            return ""

        for member in list(self.extra.get("members") or []):
            if str(member.get("id", "") or "").strip() != sender_id:
                continue
            return self._preferred_member_name(member) or sender_id
        return sender_id

    def preview_mentions_current_user(self) -> bool:
        """Return whether the latest group preview should show an @-mention attention prefix."""
        if self.session_type != "group" or self.is_ai_session:
            return False
        return bool(self.extra.get("last_message_mentions_current_user", False))

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

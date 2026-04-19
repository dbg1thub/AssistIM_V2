"""Local AI assistant thread and message models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from client.core.datetime_utils import coerce_local_datetime


class AIThreadStatus(Enum):
    """Thread visibility/lifecycle state."""

    ACTIVE = "active"
    DELETED = "deleted"


class AIMessageRole(Enum):
    """OpenAI-style message roles stored for the local assistant page."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AIMessageStatus(Enum):
    """Local assistant message lifecycle."""

    PENDING = "pending"
    STREAMING = "streaming"
    DONE = "done"
    CANCELLED = "cancelled"
    FAILED = "failed"


def _coerce_datetime(value: Any) -> datetime:
    coerced = coerce_local_datetime(value)
    return coerced or datetime.now()


@dataclass(slots=True)
class AIThread:
    """One local AI assistant chat thread."""

    thread_id: str
    title: str
    model: str = ""
    last_message: str = ""
    last_message_time: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    status: AIThreadStatus = AIThreadStatus.ACTIVE
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        now = datetime.now()
        self.created_at = _coerce_datetime(self.created_at) if self.created_at is not None else now
        self.updated_at = _coerce_datetime(self.updated_at) if self.updated_at is not None else self.created_at
        self.last_message_time = (
            _coerce_datetime(self.last_message_time)
            if self.last_message_time is not None
            else self.updated_at
        )
        if not isinstance(self.status, AIThreadStatus):
            self.status = AIThreadStatus(str(self.status or AIThreadStatus.ACTIVE.value))


@dataclass(slots=True)
class AIMessage:
    """One local AI assistant chat message."""

    message_id: str
    thread_id: str
    role: AIMessageRole | str
    content: str = ""
    status: AIMessageStatus | str = AIMessageStatus.DONE
    created_at: datetime | None = None
    updated_at: datetime | None = None
    task_id: str = ""
    model: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        now = datetime.now()
        self.created_at = _coerce_datetime(self.created_at) if self.created_at is not None else now
        self.updated_at = _coerce_datetime(self.updated_at) if self.updated_at is not None else self.created_at
        if not isinstance(self.role, AIMessageRole):
            self.role = AIMessageRole(str(self.role or AIMessageRole.USER.value))
        if not isinstance(self.status, AIMessageStatus):
            self.status = AIMessageStatus(str(self.status or AIMessageStatus.DONE.value))

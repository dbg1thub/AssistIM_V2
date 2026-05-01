"""Pydantic input and output contracts for atomic AI actions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ActionOutputModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ContactResolveInput(_StrictInputModel):
    queries: list[str] = Field(min_length=1, max_length=5)
    allow_multiple: bool = True


class ContactResolveOutput(_ActionOutputModel):
    contacts: list[dict[str, Any]]
    groups: list[dict[str, Any]] = Field(default_factory=list)
    ambiguous: list[dict[str, Any]] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class MemorySearchInput(_StrictInputModel):
    participants: list[Any] = Field(default_factory=list)
    participant_match: Literal["any", "all", "direct_only", "group_only"] = "any"
    time_scope: dict[str, Any] = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)
    question: str = ""
    limit: int = Field(default=8, ge=1, le=50)
    max_items: int | None = Field(default=None, ge=1, le=50)
    return_raw_content: bool = False


class MemorySearchOutput(_ActionOutputModel):
    results: list[dict[str, Any]] = Field(default_factory=list)
    preview: list[dict[str, Any]] = Field(default_factory=list)
    context_lines: list[str] = Field(default_factory=list)
    result_count: int = Field(ge=0)
    truncated: bool = False


class MemorySummarizeInput(_StrictInputModel):
    source: dict[str, Any]
    question: str = ""
    style: str = "summary"


class MemorySummarizeOutput(_ActionOutputModel):
    result_count: int = Field(ge=0)
    input_result_count: int = Field(ge=0)
    context_chars: int = Field(ge=0)
    chunked: bool = False
    chunk_count: int = Field(ge=0)
    status: str
    text: str = ""
    requires_responder: bool = False
    context_lines: list[str] = Field(default_factory=list)


class MessageDraftInput(_StrictInputModel):
    target: Any
    content: str = ""
    source: Any = None


class MessageDraftOutput(_ActionOutputModel):
    target: str
    target_entity: dict[str, Any]
    content: str
    preview: dict[str, Any]
    idempotency_key: str


class UserConfirmInput(_StrictInputModel):
    risk: Literal["low", "medium", "high"] = "high"
    preview: dict[str, Any]


class MessageSendInput(_StrictInputModel):
    target: dict[str, Any]
    content: str
    preview: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str


class MessageSendOutput(_ActionOutputModel):
    status: str
    text: str
    target: dict[str, Any] = Field(default_factory=dict)
    content_chars: int = Field(default=0, ge=0)
    error_code: str = ""

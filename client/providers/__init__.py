# Providers module - AI model providers

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from client.services.ai_service import (
        AIErrorCode,
        AIProvider,
        AIProviderType,
        AIService,
        AIRequest,
        AIResponse,
        AIServiceError,
        AIStreamEvent,
        AIStreamEventType,
        AITaskType,
        AIPrivacyScope,
        get_ai_service,
    )

__all__ = [
    "AIErrorCode",
    "AIProvider",
    "AIProviderType",
    "AIService",
    "AIRequest",
    "AIResponse",
    "AIServiceError",
    "AIStreamEvent",
    "AIStreamEventType",
    "AITaskType",
    "AIPrivacyScope",
    "get_ai_service",
]


def __getattr__(name: str):
    """Lazily expose provider helpers so package import stays lightweight."""
    if name in __all__:
        from client.services import ai_service

        return getattr(ai_service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

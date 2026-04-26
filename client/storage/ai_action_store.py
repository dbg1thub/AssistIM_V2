"""Persistence boundary for AI assistant action plans."""

from __future__ import annotations

from client.storage.ai_action_plan_store import AIActionPlanStore
from client.storage.database import get_database


class AIActionStore(AIActionPlanStore):
    """SQLite boundary for versioned AI action plans."""

    def __init__(self) -> None:
        super().__init__(db=get_database())


_ai_action_store: AIActionStore | None = None


def get_ai_action_store() -> AIActionStore:
    global _ai_action_store
    if _ai_action_store is None:
        _ai_action_store = AIActionStore()
    return _ai_action_store

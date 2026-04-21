"""Compatibility import for AI action temporary result persistence."""

from __future__ import annotations

from client.storage.ai_action_plan_store import AIActionPlanStore, AIActionTempResultRecord


class AIActionTempResultStore(AIActionPlanStore):
    """Store focused on large action payload references.

    The tables are created by the same schema initializer as action plans so
    callers can depend on either storage boundary without duplicating schema.
    """


__all__ = ["AIActionTempResultRecord", "AIActionTempResultStore"]

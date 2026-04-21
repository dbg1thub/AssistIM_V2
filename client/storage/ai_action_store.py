"""Persistence for AI assistant action workflow state."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from client.storage.ai_action_plan_store import AIActionPlanRecord, AIActionPlanStore
from client.storage.database import get_database


PENDING_ACTION_STATES = {"need_clarification", "need_confirmation"}


@dataclass(slots=True)
class AIActionStateRecord:
    """One resumable AI assistant action state."""

    id: str
    ai_thread_id: str
    action: str
    state: str
    kind: str
    risk_level: str
    slots: dict[str, Any] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    confirmation_text: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    expires_at: float = 0.0
    executed_at: float = 0.0
    result_status: str = ""
    result_summary: str = ""
    error_message: str = ""


class AIActionStore(AIActionPlanStore):
    """SQLite boundary for AI actions.

    The old ``ai_action_states`` table is kept for compatibility with existing
    tests and callers. New code should use the versioned plan methods inherited
    from ``AIActionPlanStore``.
    """

    DEFAULT_EXPIRES_IN_SECONDS = 600

    def __init__(self) -> None:
        super().__init__(db=get_database())
        self._schema_ready = False

    async def initialize(self) -> None:
        await super().initialize()
        if self._schema_ready:
            return
        connection = self._connection()
        await connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS ai_action_states (
                id TEXT PRIMARY KEY,
                ai_thread_id TEXT NOT NULL,
                action TEXT NOT NULL,
                state TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT '',
                risk_level TEXT NOT NULL DEFAULT '',
                slots_json TEXT NOT NULL DEFAULT '{}',
                missing_slots_json TEXT NOT NULL DEFAULT '[]',
                confirmation_text TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                expires_at REAL NOT NULL DEFAULT 0,
                executed_at REAL NOT NULL DEFAULT 0,
                result_status TEXT NOT NULL DEFAULT '',
                result_summary TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_ai_action_states_thread_state
                ON ai_action_states(ai_thread_id, state, updated_at DESC);
            """
        )
        await connection.commit()
        self._schema_ready = True

    async def create_state(
        self,
        *,
        ai_thread_id: str,
        action: str,
        state: str,
        kind: str,
        risk_level: str,
        slots: dict[str, Any] | None = None,
        missing_slots: list[str] | None = None,
        confirmation_text: str = "",
        expires_in_seconds: int | None = None,
    ) -> AIActionStateRecord:
        await self.initialize()
        now = time.time()
        expires_in = (
            self.DEFAULT_EXPIRES_IN_SECONDS
            if expires_in_seconds is None
            else max(1, int(expires_in_seconds or 1))
        )
        record = AIActionStateRecord(
            id=str(uuid.uuid4()),
            ai_thread_id=str(ai_thread_id or "").strip(),
            action=str(action or "").strip(),
            state=str(state or "").strip(),
            kind=str(kind or "").strip(),
            risk_level=str(risk_level or "").strip(),
            slots=dict(slots or {}),
            missing_slots=list(missing_slots or []),
            confirmation_text=str(confirmation_text or ""),
            created_at=now,
            updated_at=now,
            expires_at=now + expires_in,
        )
        await self._connection().execute(
            """
            INSERT INTO ai_action_states (
                id, ai_thread_id, action, state, kind, risk_level,
                slots_json, missing_slots_json, confirmation_text,
                created_at, updated_at, expires_at,
                executed_at, result_status, result_summary, error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._params(record),
        )
        await self._connection().commit()
        return record

    async def update_state(
        self,
        action_id: str,
        *,
        state: str | None = None,
        slots: dict[str, Any] | None = None,
        missing_slots: list[str] | None = None,
        confirmation_text: str | None = None,
        executed_at: float | None = None,
        result_status: str | None = None,
        result_summary: str | None = None,
        error_message: str | None = None,
    ) -> AIActionStateRecord | None:
        await self.initialize()
        record = await self.get_state(action_id)
        if record is None:
            return None
        if state is not None:
            record.state = str(state or "").strip()
        if slots is not None:
            record.slots = dict(slots or {})
        if missing_slots is not None:
            record.missing_slots = list(missing_slots or [])
        if confirmation_text is not None:
            record.confirmation_text = str(confirmation_text or "")
        if executed_at is not None:
            record.executed_at = float(executed_at or 0)
        if result_status is not None:
            record.result_status = str(result_status or "")
        if result_summary is not None:
            record.result_summary = str(result_summary or "")
        if error_message is not None:
            record.error_message = str(error_message or "")
        record.updated_at = time.time()
        await self._connection().execute(
            """
            INSERT OR REPLACE INTO ai_action_states (
                id, ai_thread_id, action, state, kind, risk_level,
                slots_json, missing_slots_json, confirmation_text,
                created_at, updated_at, expires_at,
                executed_at, result_status, result_summary, error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._params(record),
        )
        await self._connection().commit()
        return record

    async def get_state(self, action_id: str) -> AIActionStateRecord | None:
        await self.initialize()
        cursor = await self._connection().execute(
            "SELECT * FROM ai_action_states WHERE id = ?",
            (str(action_id or "").strip(),),
        )
        row = await cursor.fetchone()
        if row is not None:
            return self._row_to_record(row)
        plan = await self.get_plan(action_id)
        return self._plan_to_legacy_record(plan) if plan is not None else None

    async def latest_pending_state(self, ai_thread_id: str) -> AIActionStateRecord | None:
        await self.initialize()
        await self.expire_stale_states(ai_thread_id)
        cursor = await self._connection().execute(
            """
            SELECT * FROM ai_action_states
            WHERE ai_thread_id = ?
              AND state IN (?, ?)
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """,
            (str(ai_thread_id or "").strip(), "need_clarification", "need_confirmation"),
        )
        row = await cursor.fetchone()
        if row is not None:
            return self._row_to_record(row)
        plan = await self.latest_pending_plan(ai_thread_id)
        return self._plan_to_legacy_record(plan) if plan is not None else None

    async def expire_stale_states(self, ai_thread_id: str = "") -> None:
        await self.initialize()
        now = time.time()
        params: list[Any] = [now, now, "expired", "need_clarification", "need_confirmation"]
        thread_clause = ""
        if str(ai_thread_id or "").strip():
            thread_clause = "AND ai_thread_id = ?"
            params.append(str(ai_thread_id or "").strip())
        await self._connection().execute(
            f"""
            UPDATE ai_action_states
            SET state = ?, updated_at = ?
            WHERE expires_at > 0
              AND expires_at < ?
              AND state IN (?, ?)
              {thread_clause}
            """,
            (params[2], params[1], params[0], params[3], params[4], *params[5:]),
        )
        await self._connection().commit()

    def _connection(self):
        connection = getattr(self._db, "_db", None)
        if connection is None:
            raise RuntimeError("database is not connected")
        return connection

    @staticmethod
    def _params(record: AIActionStateRecord) -> tuple[Any, ...]:
        return (
            record.id,
            record.ai_thread_id,
            record.action,
            record.state,
            record.kind,
            record.risk_level,
            json.dumps(record.slots, ensure_ascii=False),
            json.dumps(record.missing_slots, ensure_ascii=False),
            record.confirmation_text,
            float(record.created_at or 0),
            float(record.updated_at or 0),
            float(record.expires_at or 0),
            float(record.executed_at or 0),
            record.result_status,
            record.result_summary,
            record.error_message,
        )

    @staticmethod
    def _json_dict(value: object) -> dict[str, Any]:
        try:
            data = json.loads(str(value or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            data = {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _json_list(value: object) -> list[str]:
        try:
            data = json.loads(str(value or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            data = []
        if not isinstance(data, list):
            return []
        return [str(item or "").strip() for item in data if str(item or "").strip()]

    @classmethod
    def _row_to_record(cls, row) -> AIActionStateRecord:
        return AIActionStateRecord(
            id=str(row["id"] or ""),
            ai_thread_id=str(row["ai_thread_id"] or ""),
            action=str(row["action"] or ""),
            state=str(row["state"] or ""),
            kind=str(row["kind"] or ""),
            risk_level=str(row["risk_level"] or ""),
            slots=cls._json_dict(row["slots_json"]),
            missing_slots=cls._json_list(row["missing_slots_json"]),
            confirmation_text=str(row["confirmation_text"] or ""),
            created_at=float(row["created_at"] or 0),
            updated_at=float(row["updated_at"] or 0),
            expires_at=float(row["expires_at"] or 0),
            executed_at=float(row["executed_at"] or 0),
            result_status=str(row["result_status"] or ""),
            result_summary=str(row["result_summary"] or ""),
            error_message=str(row["error_message"] or ""),
        )

    @staticmethod
    def _plan_to_legacy_record(plan: AIActionPlanRecord | None) -> AIActionStateRecord | None:
        if plan is None:
            return None
        plan_json = dict(plan.plan_json or {})
        compat_action = str(plan_json.get("compat_action") or _first_plan_action(plan_json) or "").strip()
        compat_slots = dict(plan_json.get("compat_slots") or {})
        state = {
            "waiting_clarification": "need_clarification",
            "waiting_confirmation": "need_confirmation",
            "running": "executing",
        }.get(plan.state, plan.state)
        missing_slots = []
        waiting_type = str((plan.waiting_payload or {}).get("type") or "")
        if waiting_type == "contact_ambiguity":
            missing_slots = ["participant_identity"]
        elif waiting_type == "clarification":
            missing_slots = [
                str(item or "").strip()
                for item in list((plan.waiting_payload or {}).get("missing") or [])
                if str(item or "").strip()
            ]
        return AIActionStateRecord(
            id=plan.id,
            ai_thread_id=plan.thread_id,
            action=compat_action,
            state=state,
            kind="write" if _plan_has_write_action(plan_json) else "read",
            risk_level=str(plan_json.get("risk") or "low"),
            slots=compat_slots,
            missing_slots=missing_slots,
            confirmation_text=str((plan.waiting_payload or {}).get("response_text") or ""),
            created_at=plan.created_at,
            updated_at=plan.updated_at,
            executed_at=plan.completed_at,
            result_status=plan.state,
            result_summary=str(plan.step_outputs.get("final", {}).get("text") or ""),
            error_message=plan.error_text,
        )


def _first_plan_action(plan_json: dict[str, object]) -> str:
    for step in list(plan_json.get("steps") or []):
        if isinstance(step, dict):
            return str(step.get("action") or "")
    return ""


def _plan_has_write_action(plan_json: dict[str, object]) -> bool:
    for step in list(plan_json.get("steps") or []):
        if not isinstance(step, dict):
            continue
        if str(step.get("action") or "").strip() in {"message.send", "friend.add", "moment.publish"}:
            return True
    return False


_ai_action_store: AIActionStore | None = None


def get_ai_action_store() -> AIActionStore:
    """Return the global AI action-state store."""
    global _ai_action_store
    if _ai_action_store is None:
        _ai_action_store = AIActionStore()
    return _ai_action_store

"""Persistence for resumable AI assistant action plans."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from client.storage.database import Database, get_database


PENDING_PLAN_STATES = {"running", "waiting_clarification", "waiting_confirmation"}


@dataclass(slots=True)
class AIActionPlanRecord:
    """One stored AI action plan and its execution state."""

    id: str
    thread_id: str
    state: str
    goal: str = ""
    plan_json: dict[str, Any] = field(default_factory=dict)
    plan_version: int = 1
    parent_plan_id: str = ""
    plan_history: list[dict[str, Any]] = field(default_factory=list)
    step_outputs: dict[str, Any] = field(default_factory=dict)
    waiting_payload: dict[str, Any] = field(default_factory=dict)
    current_step_id: str = ""
    error_text: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    completed_at: float = 0.0


@dataclass(slots=True)
class AIActionTempResultRecord:
    """One large intermediate result saved outside plan JSON."""

    id: str
    plan_id: str
    step_id: str
    result_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    payload_meta: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    expires_at: float = 0.0


class AIActionPlanStore:
    """SQLite boundary for versioned action plans and temporary payloads."""

    TEMP_RESULT_EXPIRES_IN_SECONDS = 24 * 60 * 60

    def __init__(self, db: Database | None = None) -> None:
        self._db = db or get_database()
        self._plan_schema_ready = False

    async def initialize(self) -> None:
        if not self._db.is_connected:
            await self._db.connect()
        if self._plan_schema_ready:
            return
        connection = self._connection()
        await connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS ai_action_plans (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                state TEXT NOT NULL,
                goal TEXT NOT NULL DEFAULT '',
                plan_json TEXT NOT NULL DEFAULT '{}',
                plan_version INTEGER NOT NULL DEFAULT 1,
                parent_plan_id TEXT NOT NULL DEFAULT '',
                plan_history_json TEXT NOT NULL DEFAULT '[]',
                step_outputs_json TEXT NOT NULL DEFAULT '{}',
                waiting_payload_json TEXT NOT NULL DEFAULT '{}',
                current_step_id TEXT NOT NULL DEFAULT '',
                error_text TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_ai_action_plans_thread_state
                ON ai_action_plans(thread_id, state, updated_at DESC);

            CREATE TABLE IF NOT EXISTS ai_action_temp_results (
                id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                result_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                payload_meta_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ai_action_temp_results_plan_step
                ON ai_action_temp_results(plan_id, step_id);

            CREATE INDEX IF NOT EXISTS idx_ai_action_temp_results_expires
                ON ai_action_temp_results(expires_at);
            """
        )
        await connection.commit()
        self._plan_schema_ready = True

    async def create_plan(
        self,
        *,
        thread_id: str,
        goal: str,
        plan_json: dict[str, Any],
        state: str = "running",
        parent_plan_id: str = "",
        reason: str = "initial",
    ) -> AIActionPlanRecord:
        await self.initialize()
        now = time.time()
        normalized_plan = dict(plan_json or {})
        history = [
            {
                "version": 1,
                "plan": normalized_plan,
                "reason": str(reason or "initial"),
                "created_at": now,
            }
        ]
        record = AIActionPlanRecord(
            id=str(uuid.uuid4()),
            thread_id=str(thread_id or "").strip(),
            state=str(state or "running").strip(),
            goal=str(goal or "").strip(),
            plan_json=normalized_plan,
            plan_version=1,
            parent_plan_id=str(parent_plan_id or "").strip(),
            plan_history=history,
            created_at=now,
            updated_at=now,
        )
        await self._connection().execute(
            """
            INSERT INTO ai_action_plans (
                id, thread_id, state, goal, plan_json, plan_version,
                parent_plan_id, plan_history_json, step_outputs_json,
                waiting_payload_json, current_step_id, error_text,
                created_at, updated_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            AIActionPlanStore._params(record),
        )
        await self._connection().commit()
        return record

    async def update_plan(
        self,
        plan_id: str,
        *,
        state: str | None = None,
        goal: str | None = None,
        plan_json: dict[str, Any] | None = None,
        reason: str = "",
        bump_version: bool = True,
        step_outputs: dict[str, Any] | None = None,
        waiting_payload: dict[str, Any] | None = None,
        current_step_id: str | None = None,
        error_text: str | None = None,
        completed_at: float | None = None,
    ) -> AIActionPlanRecord | None:
        await self.initialize()
        record = await self.get_plan(plan_id)
        if record is None:
            return None
        now = time.time()
        if state is not None:
            record.state = str(state or "").strip()
            if record.state in {"done", "failed", "cancelled"} and not record.completed_at:
                record.completed_at = now
        if goal is not None:
            record.goal = str(goal or "").strip()
        if plan_json is not None:
            record.plan_json = dict(plan_json or {})
            if bump_version:
                record.plan_version += 1
                record.plan_history.append(
                    {
                        "version": record.plan_version,
                        "plan": record.plan_json,
                        "reason": str(reason or "updated"),
                        "created_at": now,
                    }
                )
        if step_outputs is not None:
            record.step_outputs = dict(step_outputs or {})
        if waiting_payload is not None:
            record.waiting_payload = dict(waiting_payload or {})
        if current_step_id is not None:
            record.current_step_id = str(current_step_id or "").strip()
        if error_text is not None:
            record.error_text = str(error_text or "")
        if completed_at is not None:
            record.completed_at = float(completed_at or 0)
        record.updated_at = now
        await self._connection().execute(
            """
            INSERT OR REPLACE INTO ai_action_plans (
                id, thread_id, state, goal, plan_json, plan_version,
                parent_plan_id, plan_history_json, step_outputs_json,
                waiting_payload_json, current_step_id, error_text,
                created_at, updated_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            AIActionPlanStore._params(record),
        )
        await self._connection().commit()
        return record

    async def get_plan(self, plan_id: str) -> AIActionPlanRecord | None:
        await self.initialize()
        cursor = await self._connection().execute(
            "SELECT * FROM ai_action_plans WHERE id = ?",
            (str(plan_id or "").strip(),),
        )
        row = await cursor.fetchone()
        return self._row_to_plan_record(row) if row is not None else None

    async def latest_pending_plan(self, thread_id: str) -> AIActionPlanRecord | None:
        await self.initialize()
        cursor = await self._connection().execute(
            """
            SELECT * FROM ai_action_plans
            WHERE thread_id = ?
              AND state IN (?, ?, ?)
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """,
            (str(thread_id or "").strip(), "running", "waiting_clarification", "waiting_confirmation"),
        )
        row = await cursor.fetchone()
        return self._row_to_plan_record(row) if row is not None else None

    async def create_temp_result(
        self,
        *,
        plan_id: str,
        step_id: str,
        result_type: str,
        payload: dict[str, Any],
        payload_meta: dict[str, Any] | None = None,
        expires_in_seconds: int | None = None,
    ) -> AIActionTempResultRecord:
        await self.initialize()
        now = time.time()
        expires_in = (
            self.TEMP_RESULT_EXPIRES_IN_SECONDS
            if expires_in_seconds is None
            else max(1, int(expires_in_seconds or 1))
        )
        record = AIActionTempResultRecord(
            id=str(uuid.uuid4()),
            plan_id=str(plan_id or "").strip(),
            step_id=str(step_id or "").strip(),
            result_type=str(result_type or "").strip(),
            payload=dict(payload or {}),
            payload_meta=dict(payload_meta or {}),
            created_at=now,
            expires_at=now + expires_in,
        )
        await self._connection().execute(
            """
            INSERT INTO ai_action_temp_results (
                id, plan_id, step_id, result_type, payload_json,
                payload_meta_json, created_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.plan_id,
                record.step_id,
                record.result_type,
                json.dumps(record.payload, ensure_ascii=False),
                json.dumps(record.payload_meta, ensure_ascii=False),
                record.created_at,
                record.expires_at,
            ),
        )
        await self._connection().commit()
        return record

    async def get_temp_result(self, result_id: str) -> AIActionTempResultRecord | None:
        await self.initialize()
        cursor = await self._connection().execute(
            "SELECT * FROM ai_action_temp_results WHERE id = ?",
            (str(result_id or "").strip(),),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        record = self._row_to_temp_result_record(row)
        if record.expires_at and record.expires_at < time.time():
            return None
        return record

    async def delete_expired_temp_results(self) -> None:
        await self.initialize()
        await self._connection().execute(
            "DELETE FROM ai_action_temp_results WHERE expires_at > 0 AND expires_at < ?",
            (time.time(),),
        )
        await self._connection().commit()

    def _connection(self):
        connection = getattr(self._db, "_db", None)
        if connection is None:
            raise RuntimeError("database is not connected")
        return connection

    @staticmethod
    def _params(record: AIActionPlanRecord) -> tuple[Any, ...]:
        return (
            record.id,
            record.thread_id,
            record.state,
            record.goal,
            json.dumps(record.plan_json, ensure_ascii=False),
            int(record.plan_version or 1),
            record.parent_plan_id,
            json.dumps(record.plan_history, ensure_ascii=False),
            json.dumps(record.step_outputs, ensure_ascii=False),
            json.dumps(record.waiting_payload, ensure_ascii=False),
            record.current_step_id,
            record.error_text,
            float(record.created_at or 0),
            float(record.updated_at or 0),
            float(record.completed_at or 0),
        )

    @staticmethod
    def _json_dict(value: object) -> dict[str, Any]:
        try:
            data = json.loads(str(value or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _json_list(value: object) -> list[dict[str, Any]]:
        try:
            data = json.loads(str(value or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return [dict(item) for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    @classmethod
    def _row_to_plan_record(cls, row) -> AIActionPlanRecord:
        return AIActionPlanRecord(
            id=str(row["id"] or ""),
            thread_id=str(row["thread_id"] or ""),
            state=str(row["state"] or ""),
            goal=str(row["goal"] or ""),
            plan_json=AIActionPlanStore._json_dict(row["plan_json"]),
            plan_version=int(row["plan_version"] or 1),
            parent_plan_id=str(row["parent_plan_id"] or ""),
            plan_history=AIActionPlanStore._json_list(row["plan_history_json"]),
            step_outputs=AIActionPlanStore._json_dict(row["step_outputs_json"]),
            waiting_payload=AIActionPlanStore._json_dict(row["waiting_payload_json"]),
            current_step_id=str(row["current_step_id"] or ""),
            error_text=str(row["error_text"] or ""),
            created_at=float(row["created_at"] or 0),
            updated_at=float(row["updated_at"] or 0),
            completed_at=float(row["completed_at"] or 0),
        )

    @classmethod
    def _row_to_temp_result_record(cls, row) -> AIActionTempResultRecord:
        return AIActionTempResultRecord(
            id=str(row["id"] or ""),
            plan_id=str(row["plan_id"] or ""),
            step_id=str(row["step_id"] or ""),
            result_type=str(row["result_type"] or ""),
            payload=AIActionPlanStore._json_dict(row["payload_json"]),
            payload_meta=AIActionPlanStore._json_dict(row["payload_meta_json"]),
            created_at=float(row["created_at"] or 0),
            expires_at=float(row["expires_at"] or 0),
        )


_ai_action_plan_store: AIActionPlanStore | None = None


def get_ai_action_plan_store() -> AIActionPlanStore:
    """Return the global AI action plan store."""
    global _ai_action_plan_store
    if _ai_action_plan_store is None:
        _ai_action_plan_store = AIActionPlanStore()
    return _ai_action_plan_store

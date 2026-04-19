"""Local SQLite persistence for the standalone AI assistant page."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any

from client.core import logging
from client.core.i18n import tr
from client.models.ai_assistant import AIMessage, AIMessageRole, AIMessageStatus, AIThread, AIThreadStatus
from client.storage.database import get_database

logger = logging.get_logger(__name__)


def _ts(value: datetime | None) -> float:
    if value is None:
        return time.time()
    return float(value.timestamp())


def _dt(value: object) -> datetime:
    try:
        return datetime.fromtimestamp(float(value or time.time()))
    except (TypeError, ValueError, OSError):
        return datetime.now()


def _json_loads(value: object) -> dict[str, Any]:
    try:
        data = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def _preview_text(value: str, *, max_chars: int = 72) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _is_default_thread_title(value: str) -> bool:
    title = str(value or "").strip()
    if not title:
        return True
    default_titles = {
        "New Chat",
        "新聊天",
        "새 채팅",
        tr("ai_assistant.thread.new", "New Chat"),
    }
    return title in default_titles


class AIAssistantStore:
    """Small persistence boundary for local AI assistant threads/messages."""

    def __init__(self) -> None:
        self._db = get_database()
        self._schema_ready = False

    async def initialize(self) -> None:
        """Ensure the shared local database and AI assistant tables exist."""
        if not self._db.is_connected:
            await self._db.connect()
        if self._schema_ready:
            return
        connection = self._connection()
        await connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS ai_threads (
                thread_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                last_message TEXT NOT NULL DEFAULT '',
                last_message_time INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                extra TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ai_messages (
                message_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'done',
                task_id TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                extra TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY (thread_id) REFERENCES ai_threads(thread_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_ai_threads_updated_at
                ON ai_threads(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_ai_messages_thread_created
                ON ai_messages(thread_id, created_at ASC);
            """
        )
        await connection.commit()
        self._schema_ready = True

    async def list_threads(self) -> list[AIThread]:
        """Return active assistant threads ordered by recent activity."""
        await self.initialize()
        cursor = await self._connection().execute(
            """
            SELECT * FROM ai_threads
            WHERE status != ?
            ORDER BY updated_at DESC, created_at DESC
            """,
            (AIThreadStatus.DELETED.value,),
        )
        return [self._row_to_thread(row) for row in await cursor.fetchall()]

    async def get_thread(self, thread_id: str) -> AIThread | None:
        """Return one active thread by id."""
        await self.initialize()
        cursor = await self._connection().execute(
            "SELECT * FROM ai_threads WHERE thread_id = ? AND status != ?",
            (thread_id, AIThreadStatus.DELETED.value),
        )
        row = await cursor.fetchone()
        return self._row_to_thread(row) if row else None

    async def create_thread(self, *, title: str = "", model: str = "") -> AIThread:
        """Create one local assistant thread."""
        await self.initialize()
        now = datetime.now()
        thread = AIThread(
            thread_id=str(uuid.uuid4()),
            title=(title or tr("ai_assistant.thread.new", "New Chat")).strip(),
            model=str(model or ""),
            created_at=now,
            updated_at=now,
            last_message_time=now,
        )
        await self._connection().execute(
            """
            INSERT INTO ai_threads
            (thread_id, title, model, last_message, last_message_time, status, extra, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thread.thread_id,
                thread.title,
                thread.model,
                thread.last_message,
                _ts(thread.last_message_time),
                thread.status.value,
                json.dumps(thread.extra, ensure_ascii=False),
                _ts(thread.created_at),
                _ts(thread.updated_at),
            ),
        )
        await self._connection().commit()
        return thread

    async def update_thread_title(self, thread_id: str, title: str) -> AIThread | None:
        """Update one thread title."""
        await self.initialize()
        normalized = str(title or "").strip() or tr("ai_assistant.thread.new", "New Chat")
        await self._connection().execute(
            "UPDATE ai_threads SET title = ?, updated_at = ? WHERE thread_id = ?",
            (normalized, time.time(), thread_id),
        )
        await self._connection().commit()
        return await self.get_thread(thread_id)

    async def delete_thread(self, thread_id: str) -> None:
        """Soft-delete a thread and remove its messages."""
        await self.initialize()
        connection = self._connection()
        await connection.execute("DELETE FROM ai_messages WHERE thread_id = ?", (thread_id,))
        await connection.execute(
            "UPDATE ai_threads SET status = ?, updated_at = ? WHERE thread_id = ?",
            (AIThreadStatus.DELETED.value, time.time(), thread_id),
        )
        await connection.commit()

    async def clear_thread_messages(self, thread_id: str) -> None:
        """Remove all messages from one thread while keeping the thread."""
        await self.initialize()
        now = time.time()
        connection = self._connection()
        await connection.execute("DELETE FROM ai_messages WHERE thread_id = ?", (thread_id,))
        await connection.execute(
            """
            UPDATE ai_threads
            SET last_message = '', last_message_time = ?, updated_at = ?
            WHERE thread_id = ?
            """,
            (now, now, thread_id),
        )
        await connection.commit()

    async def delete_message(self, message_id: str) -> None:
        """Delete one assistant-page message and refresh its thread preview."""
        await self.initialize()
        connection = self._connection()
        cursor = await connection.execute(
            "SELECT thread_id FROM ai_messages WHERE message_id = ?",
            (message_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return
        thread_id = str(row["thread_id"] or "")
        await connection.execute("DELETE FROM ai_messages WHERE message_id = ?", (message_id,))
        await self._refresh_thread_preview(thread_id)
        await connection.commit()

    async def list_messages(self, thread_id: str, *, limit: int = 200) -> list[AIMessage]:
        """Return messages for one thread in display order."""
        await self.initialize()
        normalized_limit = max(1, int(limit or 1))
        cursor = await self._connection().execute(
            """
            SELECT * FROM (
                SELECT * FROM ai_messages
                WHERE thread_id = ?
                ORDER BY created_at DESC, message_id DESC
                LIMIT ?
            )
            ORDER BY created_at ASC, message_id ASC
            """,
            (thread_id, normalized_limit),
        )
        return [self._row_to_message(row) for row in await cursor.fetchall()]

    async def create_message(
        self,
        *,
        thread_id: str,
        role: AIMessageRole | str,
        content: str = "",
        status: AIMessageStatus | str = AIMessageStatus.DONE,
        task_id: str = "",
        model: str = "",
        extra: dict[str, Any] | None = None,
    ) -> AIMessage:
        """Create one message and update the owning thread preview."""
        await self.initialize()
        message = AIMessage(
            message_id=str(uuid.uuid4()),
            thread_id=thread_id,
            role=role,
            content=content,
            status=status,
            task_id=task_id,
            model=model,
            extra=dict(extra or {}),
        )
        await self._insert_or_replace_message(message)
        await self._touch_thread_from_message(message)
        return message

    async def update_message(
        self,
        message: AIMessage,
        *,
        content: str | None = None,
        status: AIMessageStatus | str | None = None,
        task_id: str | None = None,
        model: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> AIMessage:
        """Persist changes to one message and refresh thread preview."""
        await self.initialize()
        if content is not None:
            message.content = str(content or "")
        if status is not None:
            message.status = status if isinstance(status, AIMessageStatus) else AIMessageStatus(str(status))
        if task_id is not None:
            message.task_id = str(task_id or "")
        if model is not None:
            message.model = str(model or "")
        if extra is not None:
            message.extra = dict(extra or {})
        message.updated_at = datetime.now()
        await self._insert_or_replace_message(message)
        await self._touch_thread_from_message(message)
        return message

    async def maybe_title_from_first_user_message(self, thread_id: str, text: str) -> AIThread | None:
        """Set a concise title from the first user prompt if the thread still has its default name."""
        thread = await self.get_thread(thread_id)
        if thread is None:
            return None
        default_title = tr("ai_assistant.thread.new", "New Chat")
        if not _is_default_thread_title(thread.title):
            return thread
        title = _preview_text(text, max_chars=24) or default_title
        return await self.update_thread_title(thread_id, title)

    def _connection(self):
        connection = getattr(self._db, "_db", None)
        if connection is None:
            raise RuntimeError("database is not connected")
        return connection

    async def _insert_or_replace_message(self, message: AIMessage) -> None:
        await self._connection().execute(
            """
            INSERT OR REPLACE INTO ai_messages
            (message_id, thread_id, role, content, status, task_id, model, extra, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.message_id,
                message.thread_id,
                message.role.value if isinstance(message.role, AIMessageRole) else str(message.role),
                message.content,
                message.status.value if isinstance(message.status, AIMessageStatus) else str(message.status),
                message.task_id,
                message.model,
                json.dumps(message.extra, ensure_ascii=False),
                _ts(message.created_at),
                _ts(message.updated_at),
            ),
        )
        await self._connection().commit()

    async def _touch_thread_from_message(self, message: AIMessage) -> None:
        preview = _preview_text(message.content)
        timestamp = _ts(message.updated_at)
        await self._connection().execute(
            """
            UPDATE ai_threads
            SET last_message = ?, last_message_time = ?, updated_at = ?
            WHERE thread_id = ?
            """,
            (preview, timestamp, timestamp, message.thread_id),
        )
        await self._connection().commit()

    async def _refresh_thread_preview(self, thread_id: str) -> None:
        cursor = await self._connection().execute(
            """
            SELECT content, updated_at FROM ai_messages
            WHERE thread_id = ?
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """,
            (thread_id,),
        )
        row = await cursor.fetchone()
        now = time.time()
        if row is None:
            await self._connection().execute(
                """
                UPDATE ai_threads
                SET last_message = '', last_message_time = ?, updated_at = ?
                WHERE thread_id = ?
                """,
                (now, now, thread_id),
            )
            return
        updated_at = float(row["updated_at"] or now)
        await self._connection().execute(
            """
            UPDATE ai_threads
            SET last_message = ?, last_message_time = ?, updated_at = ?
            WHERE thread_id = ?
            """,
            (_preview_text(str(row["content"] or "")), updated_at, updated_at, thread_id),
        )

    @staticmethod
    def _row_to_thread(row) -> AIThread:
        return AIThread(
            thread_id=str(row["thread_id"]),
            title=str(row["title"] or ""),
            model=str(row["model"] or ""),
            last_message=str(row["last_message"] or ""),
            last_message_time=_dt(row["last_message_time"]),
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
            status=AIThreadStatus(str(row["status"] or AIThreadStatus.ACTIVE.value)),
            extra=_json_loads(row["extra"]),
        )

    @staticmethod
    def _row_to_message(row) -> AIMessage:
        return AIMessage(
            message_id=str(row["message_id"]),
            thread_id=str(row["thread_id"]),
            role=AIMessageRole(str(row["role"] or AIMessageRole.USER.value)),
            content=str(row["content"] or ""),
            status=AIMessageStatus(str(row["status"] or AIMessageStatus.DONE.value)),
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
            task_id=str(row["task_id"] or ""),
            model=str(row["model"] or ""),
            extra=_json_loads(row["extra"]),
        )


_ai_assistant_store: AIAssistantStore | None = None


def get_ai_assistant_store() -> AIAssistantStore:
    """Return the global AI assistant store."""
    global _ai_assistant_store
    if _ai_assistant_store is None:
        _ai_assistant_store = AIAssistantStore()
    return _ai_assistant_store

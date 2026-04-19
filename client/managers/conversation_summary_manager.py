from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional

from client.core import logging
from client.core.chat_time_buckets import is_chat_time_break
from client.core.datetime_utils import to_epoch_seconds
from client.core.logging import setup_logging
from client.core.secure_storage import SecureStorage
from client.events.event_bus import EventBus, get_event_bus
from client.managers.ai_task_manager import AITaskManager, AITaskSnapshot, AITaskState, get_ai_task_manager
from client.managers.conversation_summary_prompt_builder import (
    ConversationSummaryPromptBuilder,
    ConversationSummaryRequest,
)
from client.managers.message_manager import MessageEvent
from client.managers.session_manager import SessionEvent
from client.models.message import ChatMessage, MessageType, Session
from client.storage.database import Database, get_database


setup_logging()
logger = logging.get_logger(__name__)


class ConversationSummaryEvent:
    """EventBus names emitted by the local conversation-summary manager."""

    READY = "conversation_summary_ready"


class ConversationSummaryManager:
    """Maintain local per-session chat-bucket summaries in the background."""

    DEBOUNCE_SECONDS = 20.0
    CLOSE_BUCKET_REFRESH_DELAY = 0.0

    def __init__(
        self,
        *,
        db: Database | None = None,
        event_bus: EventBus | None = None,
        task_manager: AITaskManager | None = None,
        prompt_builder: ConversationSummaryPromptBuilder | None = None,
    ) -> None:
        self._db = db or get_database()
        self._event_bus = event_bus or get_event_bus()
        self._task_manager = task_manager or get_ai_task_manager()
        self._prompt_builder = prompt_builder or ConversationSummaryPromptBuilder()
        self._event_subscriptions: list[tuple[str, Any]] = []
        self._scheduled_refresh_tasks: dict[tuple[str, int], asyncio.Task] = {}
        self._refresh_task_running_keys: set[tuple[str, int]] = set()
        self._pending_refresh_delays: dict[tuple[str, int], float] = {}
        self._deleted_session_ids: set[str] = set()
        self._closing = False
        self._initialized = False

    async def initialize(self) -> None:
        """Subscribe to message/session events exactly once."""
        if self._initialized:
            return
        self._closing = False

        await self._subscribe(MessageEvent.RECEIVED, self._on_message_event)
        await self._subscribe(MessageEvent.SENT, self._on_message_event)
        await self._subscribe(MessageEvent.ACK, self._on_message_event)
        await self._subscribe(MessageEvent.EDITED, self._on_message_event)
        await self._subscribe(MessageEvent.RECALLED, self._on_message_event)
        await self._subscribe(MessageEvent.DELETED, self._on_message_event)
        await self._subscribe(SessionEvent.DELETED, self._on_session_deleted)
        self._initialized = True

    async def close(self) -> None:
        """Cancel background tasks and remove event subscriptions."""
        self._closing = True
        while self._event_subscriptions:
            event_type, handler = self._event_subscriptions.pop()
            await self._event_bus.unsubscribe(event_type, handler)

        for key, task in list(self._scheduled_refresh_tasks.items()):
            if task.done():
                continue
            if key not in self._refresh_task_running_keys:
                task.cancel()
        self._pending_refresh_delays.clear()
        self._refresh_task_running_keys.clear()
        self._scheduled_refresh_tasks.clear()
        self._initialized = False

    async def _subscribe(self, event_type: str, handler: Any) -> None:
        self._event_subscriptions.append((event_type, handler))
        await self._event_bus.subscribe(event_type, handler)

    async def _on_message_event(self, payload: dict[str, Any] | None) -> None:
        """Route message lifecycle events into the open-bucket summary state machine."""
        data = dict(payload or {})
        message = data.get("message")
        session_id = str(data.get("session_id") or getattr(message, "session_id", "") or "").strip()
        if not session_id or not self._db.is_connected:
            return

        if isinstance(message, ChatMessage):
            await self._process_message(session_id, message)
            return

        await self._schedule_current_open_bucket_refresh(session_id, delay=self.DEBOUNCE_SECONDS)

    async def _on_session_deleted(self, payload: dict[str, Any] | None) -> None:
        """Cancel any queued summary work for a deleted session."""
        session_id = str(dict(payload or {}).get("session_id") or "").strip()
        if not session_id:
            return
        self._deleted_session_ids.add(session_id)
        self._cancel_session_tasks(session_id)

    async def _process_message(self, session_id: str, message: ChatMessage) -> None:
        if message.message_type != MessageType.TEXT:
            return

        session = await self._db.get_session(session_id)
        if session is None or session.is_ai_session or session.session_type == "ai":
            return

        message_ts = int(to_epoch_seconds(message.timestamp) or 0)
        if message_ts <= 0:
            return

        open_bucket = await self._db.get_open_conversation_summary_bucket(session_id)
        if open_bucket is None:
            await self._db.upsert_conversation_summary_bucket(
                self._new_bucket_payload(session_id, message, message_ts, is_open=True)
            )
            self._schedule_refresh(session_id, message_ts, delay=self.DEBOUNCE_SECONDS)
            return

        bucket_start_ts = int(open_bucket.get("bucket_start_ts") or 0)
        last_message_ts = int(open_bucket.get("last_message_ts") or open_bucket.get("bucket_end_ts") or bucket_start_ts)

        if message_ts < bucket_start_ts:
            return

        if message_ts > last_message_ts and is_chat_time_break(last_message_ts, message_ts):
            await self._db.close_conversation_summary_bucket(
                session_id,
                bucket_start_ts,
                bucket_end_ts=last_message_ts,
            )
            self._schedule_refresh(
                session_id,
                bucket_start_ts,
                delay=self.CLOSE_BUCKET_REFRESH_DELAY,
            )
            await self._db.upsert_conversation_summary_bucket(
                self._new_bucket_payload(session_id, message, message_ts, is_open=True)
            )
            self._schedule_refresh(session_id, message_ts, delay=self.DEBOUNCE_SECONDS)
            return

        updated = dict(open_bucket)
        if message_ts >= last_message_ts:
            updated["bucket_end_ts"] = message_ts
            updated["last_message_ts"] = message_ts
            updated["last_message_id"] = message.message_id
        updated["summary_status"] = "stale"
        updated["updated_at"] = int(time.time())
        await self._db.upsert_conversation_summary_bucket(updated)
        self._schedule_refresh(session_id, bucket_start_ts, delay=self.DEBOUNCE_SECONDS)

    async def _schedule_current_open_bucket_refresh(self, session_id: str, *, delay: float) -> None:
        open_bucket = await self._db.get_open_conversation_summary_bucket(session_id)
        if open_bucket is None:
            return
        bucket_start_ts = int(open_bucket.get("bucket_start_ts") or 0)
        if bucket_start_ts <= 0:
            return
        updated = dict(open_bucket)
        updated["summary_status"] = "stale"
        updated["updated_at"] = int(time.time())
        await self._db.upsert_conversation_summary_bucket(updated)
        self._schedule_refresh(session_id, bucket_start_ts, delay=delay)

    def _schedule_refresh(self, session_id: str, bucket_start_ts: int, *, delay: float) -> None:
        key = (str(session_id or "").strip(), int(bucket_start_ts or 0))
        if not key[0] or key[1] <= 0:
            return
        existing = self._scheduled_refresh_tasks.get(key)
        if existing is not None and not existing.done():
            if key in self._refresh_task_running_keys:
                self._merge_pending_refresh_delay(key, delay)
                return
            existing.cancel()

        async def runner() -> None:
            rerun_delay: float | None = None
            try:
                if delay > 0:
                    await asyncio.sleep(delay)
                self._refresh_task_running_keys.add(key)
                await self._refresh_bucket_summary(key[0], key[1])
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Failed to refresh conversation summary session_id=%s bucket_start_ts=%s",
                    key[0],
                    key[1],
                )
            finally:
                self._refresh_task_running_keys.discard(key)
                rerun_delay = self._pending_refresh_delays.pop(key, None)
                current = self._scheduled_refresh_tasks.get(key)
                if current is asyncio.current_task():
                    self._scheduled_refresh_tasks.pop(key, None)
                if (
                    rerun_delay is not None
                    and not self._closing
                    and key[0] not in self._deleted_session_ids
                ):
                    self._schedule_refresh(key[0], key[1], delay=rerun_delay)

        self._scheduled_refresh_tasks[key] = asyncio.create_task(runner())

    async def _refresh_bucket_summary(self, session_id: str, bucket_start_ts: int) -> None:
        if session_id in self._deleted_session_ids:
            return
        bucket = await self._db.get_conversation_summary_bucket(session_id, bucket_start_ts)
        if bucket is None:
            return

        session = await self._db.get_session(session_id)
        if session is None or session.is_ai_session or session.session_type == "ai":
            return
        if self._closing or self._is_task_manager_closed():
            return

        bucket_end_ts = int(bucket.get("bucket_end_ts") or bucket.get("last_message_ts") or bucket_start_ts)
        working = dict(bucket)
        working["summary_status"] = "processing"
        working["updated_at"] = int(time.time())
        await self._db.upsert_conversation_summary_bucket(working)

        messages = await self._db.list_conversation_summary_bucket_messages(
            session_id,
            bucket_start_ts,
            bucket_end_ts,
            limit=self._prompt_builder.MAX_BUCKET_MESSAGES,
        )
        built = self._prompt_builder.build_bucket_summary_request(
            session,
            messages,
            task_id=self._task_id("conversation-summary"),
            bucket_start_ts=bucket_start_ts,
            bucket_end_ts=bucket_end_ts,
            is_open=bool(bucket.get("is_open", True)),
        )

        if built is None:
            if session_id in self._deleted_session_ids:
                return
            await self._db.upsert_conversation_summary_bucket(
                {
                    **working,
                    "summary_status": "ready",
                    "summary_text_ciphertext": "",
                    "summary_json_ciphertext": "",
                    "message_count": 0,
                    "error_code": "",
                    "updated_at": int(time.time()),
                }
            )
            return

        if self._closing or self._is_task_manager_closed():
            return
        try:
            snapshot = await self._task_manager.run_once(built.request)
        except RuntimeError as exc:
            if self._closing or self._is_task_manager_closed() or "closed" in str(exc).lower():
                logger.info(
                    "[ai-diag] conversation_summary_refresh_skipped session_id=%s bucket_start_ts=%s reason=%s",
                    session_id,
                    bucket_start_ts,
                    "task_manager_closed",
                )
                return
            raise
        await self._persist_summary_result(
            session_id=session_id,
            bucket_start_ts=bucket_start_ts,
            bucket_end_ts=bucket_end_ts,
            snapshot=snapshot,
            built=built,
            existing=working,
            messages=messages,
        )

    async def _persist_summary_result(
        self,
        *,
        session_id: str,
        bucket_start_ts: int,
        bucket_end_ts: int,
        snapshot: AITaskSnapshot,
        built: ConversationSummaryRequest,
        existing: dict[str, Any],
        messages: list[ChatMessage],
    ) -> None:
        if session_id in self._deleted_session_ids:
            return
        last_message = messages[-1] if messages else None
        payload = {
            **existing,
            "session_id": session_id,
            "bucket_start_ts": bucket_start_ts,
            "bucket_end_ts": bucket_end_ts,
            "message_count": int(built.message_count),
            "last_message_id": str(getattr(last_message, "message_id", "") or existing.get("last_message_id") or ""),
            "last_message_ts": int(
                to_epoch_seconds(getattr(last_message, "timestamp", None))
                or existing.get("last_message_ts")
                or bucket_end_ts
            ),
            "updated_at": int(time.time()),
        }

        if snapshot.state != AITaskState.DONE:
            if snapshot.state == AITaskState.CANCELLED:
                payload["summary_status"] = "stale"
                payload["error_code"] = ""
                await self._db.upsert_conversation_summary_bucket(payload)
                if not self._closing and session_id not in self._deleted_session_ids:
                    self._schedule_refresh(session_id, bucket_start_ts, delay=self.DEBOUNCE_SECONDS)
                return
            payload["summary_status"] = "failed"
            payload["error_code"] = str(
                getattr(snapshot.error_code, "value", snapshot.error_code) or snapshot.finish_reason or "summary_failed"
            )
            await self._db.upsert_conversation_summary_bucket(payload)
            return

        summary_text = self._prompt_builder.normalize_summary_output(snapshot.content)
        try:
            summary_ciphertext = SecureStorage.encrypt_text(summary_text) if summary_text else ""
        except Exception:
            logger.exception(
                "Failed to encrypt conversation summary session_id=%s bucket_start_ts=%s",
                session_id,
                bucket_start_ts,
            )
            payload["summary_status"] = "failed"
            payload["error_code"] = "summary_encrypt_failed"
            await self._db.upsert_conversation_summary_bucket(payload)
            return

        payload["summary_status"] = "ready"
        payload["summary_text_ciphertext"] = summary_ciphertext
        payload["error_code"] = ""
        await self._db.upsert_conversation_summary_bucket(payload)
        await self._event_bus.emit(
            ConversationSummaryEvent.READY,
            {
                "session_id": session_id,
                "bucket_start_ts": bucket_start_ts,
                "bucket_end_ts": bucket_end_ts,
                "is_open": bool(existing.get("is_open", True)),
                "message_count": int(payload.get("message_count") or 0),
                "summary_status": "ready",
            },
        )

    def _cancel_session_tasks(self, session_id: str) -> None:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return
        keys_to_clear: list[tuple[str, int]] = []
        for key, task in list(self._scheduled_refresh_tasks.items()):
            if key[0] != normalized_session_id:
                continue
            keys_to_clear.append(key)
            if not task.done() and key not in self._refresh_task_running_keys:
                task.cancel()
        for key in keys_to_clear:
            self._pending_refresh_delays.pop(key, None)

    def _merge_pending_refresh_delay(self, key: tuple[str, int], delay: float) -> None:
        normalized_delay = max(0.0, float(delay or 0.0))
        current_delay = self._pending_refresh_delays.get(key)
        if current_delay is None:
            self._pending_refresh_delays[key] = normalized_delay
            return
        self._pending_refresh_delays[key] = min(current_delay, normalized_delay)

    def _is_task_manager_closed(self) -> bool:
        return bool(getattr(self._task_manager, "_closed", False))

    @staticmethod
    def _new_bucket_payload(session_id: str, message: ChatMessage, message_ts: int, *, is_open: bool) -> dict[str, Any]:
        now_ts = int(time.time())
        return {
            "session_id": session_id,
            "bucket_start_ts": int(message_ts),
            "bucket_end_ts": int(message_ts),
            "bucket_rule_version": 1,
            "is_open": bool(is_open),
            "anchor_message_id": str(message.message_id or ""),
            "last_message_id": str(message.message_id or ""),
            "last_message_ts": int(message_ts),
            "message_count": 0,
            "summary_status": "pending",
            "summary_text_ciphertext": "",
            "summary_json_ciphertext": "",
            "summary_version": 1,
            "media_item_count": 0,
            "error_code": "",
            "notified_at": None,
            "created_at": now_ts,
            "updated_at": now_ts,
        }

    @staticmethod
    def _task_id(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4()}"


_conversation_summary_manager: Optional[ConversationSummaryManager] = None


def peek_conversation_summary_manager() -> Optional[ConversationSummaryManager]:
    """Return the existing conversation summary manager singleton when present."""
    return _conversation_summary_manager


def get_conversation_summary_manager() -> ConversationSummaryManager:
    """Return the global conversation summary manager singleton."""
    global _conversation_summary_manager
    if _conversation_summary_manager is None:
        _conversation_summary_manager = ConversationSummaryManager()
    return _conversation_summary_manager

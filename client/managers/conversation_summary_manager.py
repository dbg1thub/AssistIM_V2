from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from client.core import logging
from client.core.chat_time_buckets import is_chat_time_break
from client.core.datetime_utils import to_epoch_seconds
from client.core.file_text_extraction import FILE_TEXT_EXTRACT_EXTRA_KEY, FileTextExtractionError
from client.core.logging import setup_logging
from client.core.secure_storage import SecureStorage
from client.core.voice_transcription import VOICE_TRANSCRIPT_EXTRA_KEY, VOICE_TRANSCRIPT_MAX_SECONDS
from client.events.event_bus import EventBus, get_event_bus
from client.managers.ai_task_manager import AITaskManager, AITaskSnapshot, AITaskState, get_ai_task_manager
from client.managers.conversation_ann_index import ConversationAnnIndex
from client.managers.conversation_vector_index import ConversationVectorIndex
from client.managers.conversation_summary_prompt_builder import (
    ConversationSummaryPromptBuilder,
    ConversationSummaryRequest,
    StructuredConversationSummary,
)
from client.managers.message_manager import MessageEvent
from client.managers.session_manager import SessionEvent
from client.models.message import ChatMessage, MessageType, Session
from client.services.local_ai_memory_store import AIMemoryItem, get_local_ai_memory_store
from client.services.local_voice_transcription_service import LocalVoiceTranscriptionRuntimeError
from client.storage.database import Database, get_database


setup_logging()
logger = logging.get_logger(__name__)


class ConversationSummaryEvent:
    """EventBus names emitted by the local conversation-summary manager."""

    READY = "conversation_summary_ready"


class ConversationSummaryManager:
    """Maintain local per-session chat-bucket summaries in the background."""

    # Debounce prevents every incoming message from immediately scheduling model work.
    DEBOUNCE_SECONDS = 20.0
    CLOSE_BUCKET_REFRESH_DELAY = 0.0
    IDLE_REFRESH_THROTTLE_SECONDS = 5.0
    MEMORY_SOURCE_TYPE_SUMMARY = "summary"
    AI_MEMORY_SOURCE_TYPE_SUMMARY = "conversation_summary"
    MEMORY_INDEX_VERSION = 3
    SUMMARY_SCHEMA_VERSION = 2

    def __init__(
        self,
        *,
        db: Database | None = None,
        event_bus: EventBus | None = None,
        task_manager: AITaskManager | None = None,
        prompt_builder: ConversationSummaryPromptBuilder | None = None,
        vector_index: ConversationVectorIndex | None = None,
        ann_index: ConversationAnnIndex | None = None,
        message_manager: Any | None = None,
        voice_transcription_runtime: Any | None = None,
        file_text_extractor: Any | None = None,
        ai_memory_store: Any | None = None,
    ) -> None:
        self._db = db or get_database()
        self._event_bus = event_bus or get_event_bus()
        self._task_manager = task_manager or get_ai_task_manager()
        self._prompt_builder = prompt_builder or ConversationSummaryPromptBuilder()
        self._vector_index = vector_index or ConversationVectorIndex()
        self._ann_index = ann_index or ConversationAnnIndex(model_id=self._vector_index.model_id)
        self._message_manager = message_manager
        self._voice_transcription_runtime = voice_transcription_runtime
        self._file_text_extractor = file_text_extractor
        self._ai_memory_store = ai_memory_store
        self._voice_transcription_semaphore = asyncio.Semaphore(1)
        self._file_text_extract_semaphore = asyncio.Semaphore(1)
        self._event_subscriptions: list[tuple[str, Any]] = []
        self._scheduled_refresh_tasks: dict[tuple[str, int], asyncio.Task] = {}
        self._refresh_task_running_keys: set[tuple[str, int]] = set()
        self._pending_refresh_delays: dict[tuple[str, int], float] = {}
        self._last_idle_refresh_requested_at: dict[tuple[str, int], float] = {}
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
        await self._subscribe(MessageEvent.HISTORY_CLEARING, self._on_session_history_clearing)
        await self._subscribe(MessageEvent.HISTORY_CLEARED, self._on_session_history_cleared)
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

    async def _on_session_history_clearing(self, payload: dict[str, Any] | None) -> None:
        """Drop local AI memory for a session before its summary rows are removed."""
        session_id = str(dict(payload or {}).get("session_id") or "").strip()
        if not session_id:
            return
        self._cancel_session_tasks(session_id)
        if not self._db.is_connected:
            return

        list_bucket_keys = getattr(self._db, "list_conversation_summary_bucket_keys", None)
        if not callable(list_bucket_keys):
            return
        try:
            bucket_start_values = await list_bucket_keys(session_id)
        except Exception:
            logger.exception(
                "Failed to list conversation summary buckets before clearing local history session_id=%s",
                session_id,
            )
            return

        for bucket_start_ts in bucket_start_values:
            try:
                normalized_bucket_start_ts = int(bucket_start_ts or 0)
            except (TypeError, ValueError):
                continue
            if normalized_bucket_start_ts <= 0:
                continue
            await self._delete_memory_item_for_bucket(session_id, normalized_bucket_start_ts)

    async def _on_session_history_cleared(self, payload: dict[str, Any] | None) -> None:
        """Cancel queued summary work after local history is cleared."""
        session_id = str(dict(payload or {}).get("session_id") or "").strip()
        if not session_id:
            return
        self._cancel_session_tasks(session_id)

    async def _process_message(self, session_id: str, message: ChatMessage) -> None:
        if message.message_type not in {MessageType.TEXT, MessageType.VOICE, MessageType.FILE}:
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
        await self._delete_memory_item_for_bucket(session_id, bucket_start_ts)
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
        await self._delete_memory_item_for_bucket(session_id, bucket_start_ts)
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

        working = dict(bucket)
        working["session_name"] = session.display_name() or session.name or session.session_id
        working["summary_status"] = "processing"
        working["updated_at"] = int(time.time())
        await self._db.upsert_conversation_summary_bucket(working)

        bucket_end_ts = int(bucket.get("bucket_end_ts") or bucket.get("last_message_ts") or bucket_start_ts)
        messages = await self._db.list_conversation_summary_bucket_messages(
            session_id,
            bucket_start_ts,
            bucket_end_ts,
            limit=self._prompt_builder.MAX_BUCKET_MESSAGES,
        )
        messages = await self._prepare_voice_transcripts_for_summary(messages)
        messages = await self._prepare_file_text_extracts_for_summary(messages)
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
                    "display_summary_ciphertext": "",
                    "retrieval_summary_ciphertext": "",
                    "summary_structured_json_ciphertext": "",
                    "summary_schema_version": self.SUMMARY_SCHEMA_VERSION,
                    "summary_version": max(int(working.get("summary_version") or 1), self.SUMMARY_SCHEMA_VERSION),
                    "message_count": 0,
                    "error_code": "",
                    "updated_at": int(time.time()),
                }
            )
            await self._delete_memory_item_for_bucket(session_id, bucket_start_ts)
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
            session=session,
        )

    async def _prepare_voice_transcripts_for_summary(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        """Add local voice transcripts to summary input without blocking summary on ASR failures."""
        prepared: list[ChatMessage] = []
        for message in list(messages or []):
            if message.message_type != MessageType.VOICE:
                prepared.append(message)
                continue
            prepared.append(await self._prepare_voice_transcript_for_summary(message))
        return prepared

    async def _prepare_voice_transcript_for_summary(self, message: ChatMessage) -> ChatMessage:
        transcript = dict((message.extra or {}).get(VOICE_TRANSCRIPT_EXTRA_KEY) or {})
        status = str(transcript.get("status") or "").strip()
        if status == "ready" and str(transcript.get("text") or "").strip():
            return message
        if status in {"pending", "failed", "skipped"}:
            return message

        duration_seconds = self._voice_message_duration_seconds(message)
        if duration_seconds > VOICE_TRANSCRIPT_MAX_SECONDS:
            return await self._persist_summary_voice_transcript(
                message,
                self._voice_transcript_payload(
                    status="skipped",
                    reason="audio_too_long",
                    duration_seconds=duration_seconds,
                ),
            )

        try:
            local_path = await self._require_message_manager().download_attachment(message.message_id)
            async with self._voice_transcription_semaphore:
                result = await self._require_voice_transcription_runtime().transcribe(
                    local_path,
                    duration_seconds=duration_seconds or None,
                )
        except LocalVoiceTranscriptionRuntimeError as exc:
            if exc.code == "VOICE_TRANSCRIPT_AUDIO_TOO_LONG":
                payload = self._voice_transcript_payload(
                    status="skipped",
                    reason="audio_too_long",
                    duration_seconds=duration_seconds,
                    error_code=exc.code,
                    error_message=str(exc),
                )
            else:
                reason = "model_missing" if exc.code == "VOICE_TRANSCRIPT_MODEL_NOT_FOUND" else "runtime_error"
                payload = self._voice_transcript_payload(
                    status="failed",
                    reason=reason,
                    duration_seconds=duration_seconds,
                    error_code=exc.code,
                    error_message=str(exc),
                )
            logger.info(
                "[voice-asr] summary_voice_transcript_skipped message_id=%s session_id=%s reason=%s error_code=%s",
                message.message_id,
                message.session_id,
                str(payload.get("reason") or ""),
                exc.code,
            )
            return await self._persist_summary_voice_transcript(message, payload)
        except Exception as exc:
            logger.warning(
                "[voice-asr] summary_voice_transcript_unavailable message_id=%s session_id=%s error=%s",
                message.message_id,
                message.session_id,
                exc,
            )
            return await self._persist_summary_voice_transcript(
                message,
                self._voice_transcript_payload(
                    status="failed",
                    reason="audio_unavailable",
                    duration_seconds=duration_seconds,
                    error_code=exc.__class__.__name__,
                    error_message=str(exc),
                ),
            )

        text = " ".join(str(result.text or "").strip().split())
        if not text:
            payload = self._voice_transcript_payload(
                status="skipped",
                reason="no_speech",
                duration_seconds=duration_seconds,
            )
        else:
            payload = self._voice_transcript_payload(
                status="ready",
                text=text,
                duration_seconds=duration_seconds,
                language=str(result.language or ""),
                language_probability=float(result.language_probability or 0.0),
                metadata=dict(result.metadata or {}),
            )
        return await self._persist_summary_voice_transcript(message, payload)

    async def _persist_summary_voice_transcript(self, message: ChatMessage, payload: dict[str, Any]) -> ChatMessage:
        message.extra = dict(message.extra or {})
        message.extra[VOICE_TRANSCRIPT_EXTRA_KEY] = dict(payload or {})
        updated = await self._require_message_manager().update_message_voice_transcript(message.message_id, payload)
        return updated or message

    async def _prepare_file_text_extracts_for_summary(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        """Add local file text extracts to summary input without showing a visible file summary."""
        prepared: list[ChatMessage] = []
        for message in list(messages or []):
            if message.message_type != MessageType.FILE:
                prepared.append(message)
                continue
            prepared.append(await self._prepare_file_text_extract_for_summary(message))
        return prepared

    async def _prepare_file_text_extract_for_summary(self, message: ChatMessage) -> ChatMessage:
        extraction = dict((message.extra or {}).get(FILE_TEXT_EXTRACT_EXTRA_KEY) or {})
        status = str(extraction.get("status") or "").strip()
        if status == "ready" and str(extraction.get("text") or "").strip():
            return message
        if status in {"pending", "failed", "skipped"}:
            return message

        try:
            local_path = await self._require_message_manager().download_attachment(message.message_id)
            async with self._file_text_extract_semaphore:
                result = await self._require_file_text_extractor().extract(
                    local_path,
                    display_name=self._file_display_name(message),
                    mime_type=self._file_mime_type(message),
                )
        except FileTextExtractionError as exc:
            payload = self._file_text_extract_error_payload(exc)
            logger.info(
                "[file-summary] summary_file_text_extract_skipped message_id=%s session_id=%s reason=%s error_code=%s",
                message.message_id,
                message.session_id,
                str(payload.get("reason") or ""),
                exc.code,
            )
            return await self._persist_summary_file_text_extract(message, payload)
        except Exception as exc:
            logger.warning(
                "[file-summary] summary_file_text_extract_unavailable message_id=%s session_id=%s error=%s",
                message.message_id,
                message.session_id,
                exc,
            )
            return await self._persist_summary_file_text_extract(
                message,
                self._file_text_extract_payload(
                    status="failed",
                    reason="file_unavailable",
                    error_code=exc.__class__.__name__,
                    error_message=str(exc),
                ),
            )

        return await self._persist_summary_file_text_extract(
            message,
            self._file_text_extract_payload(
                status="ready",
                text=str(getattr(result, "text", "") or "").strip(),
                file_name=str(getattr(result, "file_name", "") or self._file_display_name(message)),
                file_ext=str(getattr(result, "file_ext", "") or ""),
                size_bytes=int(getattr(result, "size_bytes", 0) or 0),
                truncated=bool(getattr(result, "truncated", False)),
                page_count=int(getattr(result, "page_count", 0) or 0),
                metadata=dict(getattr(result, "metadata", {}) or {}),
            ),
        )

    async def _persist_summary_file_text_extract(self, message: ChatMessage, payload: dict[str, Any]) -> ChatMessage:
        message.extra = dict(message.extra or {})
        message.extra[FILE_TEXT_EXTRACT_EXTRA_KEY] = dict(payload or {})
        updated = await self._require_message_manager().update_message_file_analysis(
            message.message_id,
            text_extract=payload,
        )
        return updated or message

    def _require_message_manager(self) -> Any:
        if self._message_manager is None:
            from client.managers.message_manager import get_message_manager

            self._message_manager = get_message_manager()
        return self._message_manager

    def _require_voice_transcription_runtime(self) -> Any:
        if self._voice_transcription_runtime is None:
            from client.services.local_voice_transcription_service import get_local_voice_transcription_runtime

            self._voice_transcription_runtime = get_local_voice_transcription_runtime()
        return self._voice_transcription_runtime

    def _require_file_text_extractor(self) -> Any:
        if self._file_text_extractor is None:
            from client.core.file_text_extraction import get_local_file_text_extractor

            self._file_text_extractor = get_local_file_text_extractor()
        return self._file_text_extractor

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
        session: Session,
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

        structured = self._prompt_builder.parse_summary_output(snapshot.content)
        if structured is None:
            payload["summary_status"] = "failed"
            payload["error_code"] = "summary_parse_invalid"
            await self._db.upsert_conversation_summary_bucket(payload)
            return

        participants = self._summary_participants(
            built.request.session_id,
            messages,
            existing=existing,
            session=session,
            structured=structured,
        )
        structured = StructuredConversationSummary(
            display_summary=structured.display_summary,
            topics=structured.topics,
            facts=structured.facts,
            decisions=structured.decisions,
            pending_items=structured.pending_items,
            tone=structured.tone,
            participants=tuple(participants),
            keywords=self._summary_keywords(structured),
        )
        retrieval_summary = self._prompt_builder.build_retrieval_summary(
            structured,
            bucket_start_ts=bucket_start_ts,
            bucket_end_ts=bucket_end_ts,
        )
        message_ids = [str(message.message_id or "") for message in messages if str(message.message_id or "")]
        summary_json = {
            "source_type": self.MEMORY_SOURCE_TYPE_SUMMARY,
            "bucket_start_ts": int(bucket_start_ts),
            "bucket_end_ts": int(bucket_end_ts),
            "message_ids": message_ids,
            "display_summary": structured.display_summary,
            "topics": list(structured.topics),
            "facts": list(structured.facts),
            "decisions": list(structured.decisions),
            "pending_items": list(structured.pending_items),
            "tone": structured.tone,
            "participants": list(structured.participants),
            "keywords": list(structured.keywords),
            "message_count": int(built.message_count),
        }
        try:
            display_summary_ciphertext = SecureStorage.encrypt_text(structured.display_summary) if structured.display_summary else ""
            retrieval_summary_ciphertext = SecureStorage.encrypt_text(retrieval_summary) if retrieval_summary else ""
            summary_structured_json_ciphertext = SecureStorage.encrypt_text(
                json.dumps(summary_json, ensure_ascii=False)
            ) if summary_json else ""
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
        payload["summary_version"] = max(int(existing.get("summary_version") or 1), self.SUMMARY_SCHEMA_VERSION)
        payload["display_summary_ciphertext"] = display_summary_ciphertext
        payload["retrieval_summary_ciphertext"] = retrieval_summary_ciphertext
        payload["summary_structured_json_ciphertext"] = summary_structured_json_ciphertext
        payload["summary_schema_version"] = self.SUMMARY_SCHEMA_VERSION
        payload["error_code"] = ""
        await self._db.upsert_conversation_summary_bucket(payload)
        await self._upsert_memory_item_for_summary(
            session_id=session_id,
            bucket_start_ts=bucket_start_ts,
            bucket_end_ts=bucket_end_ts,
            retrieval_summary=retrieval_summary,
            participants=list(structured.participants),
            keywords=list(structured.keywords),
            existing=existing,
        )
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
            self._last_idle_refresh_requested_at.pop(key, None)

    async def schedule_idle_refresh(self, session_id: str, *, reason: str = "") -> bool:
        """Schedule an immediate low-priority summary refresh when the user leaves a chat context."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id or self._closing or self._is_task_manager_closed():
            return False
        if normalized_session_id in self._deleted_session_ids or not self._db.is_connected:
            return False

        session = await self._db.get_session(normalized_session_id)
        if session is None or session.is_ai_session or session.session_type == "ai":
            return False

        bucket = await self._db.get_open_conversation_summary_bucket(normalized_session_id)
        if bucket is None:
            return False
        bucket_start_ts = int(bucket.get("bucket_start_ts") or 0)
        if bucket_start_ts <= 0:
            return False

        stats = await self._bucket_message_stats(normalized_session_id, bucket)
        if not self._open_bucket_needs_refresh(bucket, stats):
            if self._summary_bucket_needs_regeneration(bucket):
                updated = dict(bucket)
                updated["summary_status"] = "stale"
                updated["updated_at"] = int(time.time())
                await self._db.upsert_conversation_summary_bucket(updated)
                await self._delete_memory_item_for_bucket(normalized_session_id, bucket_start_ts)
                self._schedule_refresh(normalized_session_id, bucket_start_ts, delay=0.0)
                logger.info(
                    "[ai-perf] conversation_summary_schema_rebuild_scheduled session_id=%s bucket_start_ts=%s reason=%s",
                    normalized_session_id,
                    bucket_start_ts,
                    "schema_upgrade",
                )
                return True
            if await self._memory_index_needs_rebuild(normalized_session_id, bucket):
                return await self._rebuild_memory_item_for_ready_bucket(session, bucket, stats=stats)
            return False

        key = (normalized_session_id, bucket_start_ts)
        now_monotonic = time.monotonic()
        last_requested_at = float(self._last_idle_refresh_requested_at.get(key, 0.0) or 0.0)
        if now_monotonic - last_requested_at < self.IDLE_REFRESH_THROTTLE_SECONDS:
            return False
        self._last_idle_refresh_requested_at[key] = now_monotonic

        updated = dict(bucket)
        updated["summary_status"] = "stale"
        updated["updated_at"] = int(time.time())
        updated["message_count"] = int(stats.get("message_count") or 0)
        last_message_id = str(stats.get("last_message_id") or "").strip()
        last_message_ts = int(stats.get("last_message_ts") or 0)
        if last_message_id:
            updated["last_message_id"] = last_message_id
        if last_message_ts > 0:
            updated["last_message_ts"] = last_message_ts
            updated["bucket_end_ts"] = max(int(updated.get("bucket_end_ts") or bucket_start_ts), last_message_ts)
        await self._db.upsert_conversation_summary_bucket(updated)
        await self._delete_memory_item_for_bucket(normalized_session_id, bucket_start_ts)
        self._schedule_refresh(normalized_session_id, bucket_start_ts, delay=0.0)
        logger.info(
            "[ai-perf] conversation_summary_idle_refresh_scheduled session_id=%s bucket_start_ts=%s reason=%s status=%s message_count=%s",
            normalized_session_id,
            bucket_start_ts,
            str(reason or "idle"),
            str(bucket.get("summary_status") or ""),
            int(stats.get("message_count") or 0),
        )
        return True

    async def _bucket_message_stats(self, session_id: str, bucket: dict[str, Any]) -> dict[str, Any]:
        stats_loader = getattr(self._db, "get_conversation_summary_bucket_message_stats", None)
        bucket_start_ts = int(bucket.get("bucket_start_ts") or 0)
        if stats_loader is not None:
            return dict(await stats_loader(session_id, bucket_start_ts, None))

        bucket_end_ts = int(bucket.get("bucket_end_ts") or bucket.get("last_message_ts") or bucket_start_ts)
        messages = await self._db.list_conversation_summary_bucket_messages(
            session_id,
            bucket_start_ts,
            bucket_end_ts,
            limit=max(1, int(self._prompt_builder.MAX_BUCKET_MESSAGES or 1)),
        )
        summary_messages = [
            message
            for message in messages
            if message.message_type in {MessageType.TEXT, MessageType.VOICE, MessageType.FILE}
        ]
        latest = summary_messages[-1] if summary_messages else None
        return {
            "message_count": len(summary_messages),
            "last_message_id": str(getattr(latest, "message_id", "") or "") if latest is not None else "",
            "last_message_ts": int(to_epoch_seconds(getattr(latest, "timestamp", None)) or 0) if latest is not None else 0,
        }

    @staticmethod
    def _open_bucket_needs_refresh(bucket: dict[str, Any], stats: dict[str, Any]) -> bool:
        message_count = int(stats.get("message_count") or 0)
        if message_count <= 0:
            return False

        status = str(bucket.get("summary_status") or "").strip().lower()
        if status in {"pending", "stale", "failed"}:
            return True

        last_message_id = str(stats.get("last_message_id") or "").strip()
        last_message_ts = int(stats.get("last_message_ts") or 0)
        if str(bucket.get("last_message_id") or "").strip() != last_message_id:
            return True
        if int(bucket.get("last_message_ts") or 0) != last_message_ts:
            return True
        if int(bucket.get("message_count") or 0) != message_count:
            return True
        if status != "ready":
            return True
        return False

    def _merge_pending_refresh_delay(self, key: tuple[str, int], delay: float) -> None:
        normalized_delay = max(0.0, float(delay or 0.0))
        current_delay = self._pending_refresh_delays.get(key)
        if current_delay is None:
            self._pending_refresh_delays[key] = normalized_delay
            return
        self._pending_refresh_delays[key] = min(current_delay, normalized_delay)

    def _is_task_manager_closed(self) -> bool:
        return bool(getattr(self._task_manager, "_closed", False))

    def _summary_bucket_needs_regeneration(self, bucket: dict[str, Any]) -> bool:
        if str(bucket.get("summary_status") or "").strip().lower() != "ready":
            return False
        if int(bucket.get("summary_schema_version") or 0) < self.SUMMARY_SCHEMA_VERSION:
            return True
        if not str(bucket.get("display_summary_ciphertext") or "").strip():
            return True
        if not str(bucket.get("retrieval_summary_ciphertext") or "").strip():
            return True
        if not str(bucket.get("summary_structured_json_ciphertext") or "").strip():
            return True
        return False

    async def _memory_index_needs_rebuild(self, session_id: str, bucket: dict[str, Any]) -> bool:
        if str(bucket.get("summary_status") or "").strip().lower() != "ready":
            return False
        if self._summary_bucket_needs_regeneration(bucket):
            return False
        if not str(bucket.get("retrieval_summary_ciphertext") or "").strip():
            return False
        list_items = getattr(self._db, "list_conversation_memory_items", None)
        if list_items is None:
            return False

        bucket_start_ts = int(bucket.get("bucket_start_ts") or 0)
        if bucket_start_ts <= 0:
            return False
        source_id = self._memory_source_id(bucket_start_ts)
        try:
            items = await list_items(
                session_id=session_id,
                source_type=self.MEMORY_SOURCE_TYPE_SUMMARY,
                start_ts=bucket_start_ts,
                end_ts=bucket_start_ts,
                limit=50,
            )
        except Exception:
            logger.exception(
                "Failed to inspect conversation memory index session_id=%s bucket_start_ts=%s",
                session_id,
                bucket_start_ts,
            )
            return False

        item = next((candidate for candidate in list(items or []) if str(candidate.get("source_id") or "") == source_id), None)
        if item is None:
            return True
        return int(item.get("source_version") or 0) < self.MEMORY_INDEX_VERSION

    async def _rebuild_memory_item_for_ready_bucket(
        self,
        session: Session,
        bucket: dict[str, Any],
        *,
        stats: dict[str, Any],
    ) -> bool:
        session_id = str(session.session_id or bucket.get("session_id") or "").strip()
        bucket_start_ts = int(bucket.get("bucket_start_ts") or 0)
        if not session_id or bucket_start_ts <= 0:
            return False

        retrieval_summary_ciphertext = str(bucket.get("retrieval_summary_ciphertext") or "").strip()
        structured_ciphertext = str(bucket.get("summary_structured_json_ciphertext") or "").strip()
        if not retrieval_summary_ciphertext or not structured_ciphertext:
            await self._delete_memory_item_for_bucket(session_id, bucket_start_ts)
            return True
        try:
            retrieval_summary = SecureStorage.decrypt_text(retrieval_summary_ciphertext)
            structured_data = json.loads(SecureStorage.decrypt_text(structured_ciphertext))
        except Exception:
            logger.exception(
                "Failed to decrypt ready conversation summary for memory reindex session_id=%s bucket_start_ts=%s",
                session_id,
                bucket_start_ts,
            )
            return False
        structured = StructuredConversationSummary(
            display_summary=str(structured_data.get("display_summary") or "").strip(),
            topics=tuple(str(item or "").strip() for item in list(structured_data.get("topics") or []) if str(item or "").strip()),
            facts=tuple(str(item or "").strip() for item in list(structured_data.get("facts") or []) if str(item or "").strip()),
            decisions=tuple(str(item or "").strip() for item in list(structured_data.get("decisions") or []) if str(item or "").strip()),
            pending_items=tuple(str(item or "").strip() for item in list(structured_data.get("pending_items") or []) if str(item or "").strip()),
            tone=str(structured_data.get("tone") or "").strip(),
            participants=tuple(
                str(item or "").strip() for item in list(structured_data.get("participants") or []) if str(item or "").strip()
            ),
            keywords=tuple(str(item or "").strip() for item in list(structured_data.get("keywords") or []) if str(item or "").strip()),
        )
        keywords = [
            str(item or "").strip()
            for item in list(structured_data.get("keywords") or [])
            if str(item or "").strip()
        ]

        last_message_ts = int(stats.get("last_message_ts") or 0)
        bucket_end_ts = max(
            int(bucket.get("bucket_end_ts") or bucket.get("last_message_ts") or bucket_start_ts),
            last_message_ts,
        )
        messages = await self._db.list_conversation_summary_bucket_messages(
            session_id,
            bucket_start_ts,
            bucket_end_ts,
            limit=self._prompt_builder.MAX_BUCKET_MESSAGES,
        )
        existing = {
            **bucket,
            "session_name": session.display_name() or session.name or session.session_id,
        }
        participants = self._summary_participants(
            session_id,
            messages,
            existing=existing,
            session=session,
            structured=structured,
        )
        await self._upsert_memory_item_for_summary(
            session_id=session_id,
            bucket_start_ts=bucket_start_ts,
            bucket_end_ts=bucket_end_ts,
            retrieval_summary=retrieval_summary,
            participants=participants,
            keywords=keywords,
            existing=existing,
        )
        logger.info(
            "[ai-perf] conversation_summary_memory_reindexed session_id=%s bucket_start_ts=%s source_version=%s",
            session_id,
            bucket_start_ts,
            self.MEMORY_INDEX_VERSION,
        )
        return True

    async def _delete_memory_item_for_bucket(self, session_id: str, bucket_start_ts: int) -> None:
        delete_source = getattr(self._db, "delete_conversation_memory_items_for_source", None)
        if callable(delete_source):
            await delete_source(
                session_id,
                self.MEMORY_SOURCE_TYPE_SUMMARY,
                self._memory_source_id(bucket_start_ts),
            )
        await self._delete_ai_memory_item_for_bucket(session_id, bucket_start_ts)

    async def _upsert_memory_item_for_summary(
        self,
        *,
        session_id: str,
        bucket_start_ts: int,
        bucket_end_ts: int,
        retrieval_summary: str,
        participants: list[str],
        keywords: list[str],
        existing: dict[str, Any],
    ) -> None:
        if not str(retrieval_summary or "").strip():
            await self._delete_memory_item_for_bucket(session_id, bucket_start_ts)
            return
        upsert = getattr(self._db, "upsert_conversation_memory_item", None)
        if upsert is None:
            return
        title = self._memory_title(
            session_name=str(existing.get("session_name") or session_id),
            bucket_start_ts=bucket_start_ts,
            bucket_end_ts=bucket_end_ts,
        )
        embedding_id = ""
        embedding_model = ""
        vector = None
        upsert_embedding = getattr(self._db, "upsert_conversation_memory_embedding", None)
        replace_ann_buckets = getattr(self._db, "replace_conversation_memory_ann_buckets", None)
        if callable(upsert_embedding) or self._ai_memory_store is not None:
            try:
                vector = await self._vector_index.encode_item(
                    title=title,
                    text=retrieval_summary,
                    keywords=keywords,
                    participants=participants,
                )
                embedding_model = self._vector_index.model_id
                if callable(upsert_embedding):
                    embedding_id = await upsert_embedding(
                        {
                            "session_id": session_id,
                            "source_type": self.MEMORY_SOURCE_TYPE_SUMMARY,
                            "source_id": self._memory_source_id(bucket_start_ts),
                            "source_version": max(self.MEMORY_INDEX_VERSION, int(existing.get("summary_version") or 1)),
                            "embedding_model": embedding_model,
                            "content_hash": self._vector_index.item_content_hash(
                                title=title,
                                text=retrieval_summary,
                                keywords=keywords,
                                participants=participants,
                            ),
                            "embedding_vector": list(vector.values),
                            "updated_at": int(time.time()),
                        }
                    )
                if callable(upsert_embedding) and callable(replace_ann_buckets):
                    await replace_ann_buckets(
                        embedding_id=embedding_id,
                        session_id=session_id,
                        source_type=self.MEMORY_SOURCE_TYPE_SUMMARY,
                        source_id=self._memory_source_id(bucket_start_ts),
                        ann_namespace=self._ann_index.namespace,
                        buckets=[
                            (bucket.band_index, bucket.bucket_key)
                            for bucket in self._ann_index.buckets_for_vector(vector)
                        ],
                        updated_at=int(time.time()),
                    )
                await self._upsert_ai_memory_item_for_summary(
                    session_id=session_id,
                    bucket_start_ts=bucket_start_ts,
                    bucket_end_ts=bucket_end_ts,
                    title=title,
                    retrieval_summary=retrieval_summary,
                    participants=participants,
                    keywords=keywords,
                    existing=existing,
                    vector=vector,
                    embedding_model=embedding_model,
                    embedding_id=embedding_id,
                )
            except Exception:
                logger.exception(
                    "Failed to upsert conversation memory embedding session_id=%s bucket_start_ts=%s",
                    session_id,
                    bucket_start_ts,
                )
                delete_embedding = getattr(self._db, "delete_conversation_memory_embeddings_for_source", None)
                if callable(delete_embedding):
                    await delete_embedding(
                        session_id,
                        self.MEMORY_SOURCE_TYPE_SUMMARY,
                        self._memory_source_id(bucket_start_ts),
                    )
                embedding_id = ""
                embedding_model = ""
        await upsert(
            {
                "session_id": session_id,
                "source_type": self.MEMORY_SOURCE_TYPE_SUMMARY,
                "source_id": self._memory_source_id(bucket_start_ts),
                "source_version": max(self.MEMORY_INDEX_VERSION, int(existing.get("summary_version") or 1)),
                "start_ts": int(bucket_start_ts),
                "end_ts": int(bucket_end_ts),
                "title": title,
                "text": retrieval_summary,
                "keywords": keywords,
                "participants": participants,
                "embedding_id": embedding_id,
                "embedding_model": embedding_model,
                "updated_at": int(time.time()),
            }
        )

    async def _upsert_ai_memory_item_for_summary(
        self,
        *,
        session_id: str,
        bucket_start_ts: int,
        bucket_end_ts: int,
        title: str,
        retrieval_summary: str,
        participants: list[str],
        keywords: list[str],
        existing: dict[str, Any],
        vector: Any,
        embedding_model: str,
        embedding_id: str,
    ) -> None:
        if self._ai_memory_store is None:
            return
        vector_values = tuple(getattr(vector, "values", ()) or ())
        if not vector_values:
            return
        owner_scope = await self._ai_memory_owner_scope()
        if not owner_scope:
            return
        source_id = self._ai_memory_source_id(session_id, bucket_start_ts)
        try:
            await self._ai_memory_store.upsert_item(
                AIMemoryItem(
                    owner_scope=owner_scope,
                    source_type=self.AI_MEMORY_SOURCE_TYPE_SUMMARY,
                    source_id=source_id,
                    title=title,
                    text=retrieval_summary,
                    vector=vector_values,
                    embedding_model_id=embedding_model,
                    metadata={
                        "session_id": str(session_id or "").strip(),
                        "legacy_source_type": self.MEMORY_SOURCE_TYPE_SUMMARY,
                        "legacy_source_id": self._memory_source_id(bucket_start_ts),
                        "bucket_start_ts": int(bucket_start_ts),
                        "bucket_end_ts": int(bucket_end_ts),
                        "source_version": max(self.MEMORY_INDEX_VERSION, int(existing.get("summary_version") or 1)),
                        "embedding_id": str(embedding_id or ""),
                        "keywords": list(keywords or []),
                        "participants": list(participants or []),
                    },
                    updated_at=int(time.time()),
                )
            )
        except Exception:
            logger.exception(
                "Failed to upsert conversation summary into local AI memory store session_id=%s bucket_start_ts=%s",
                session_id,
                bucket_start_ts,
            )

    async def _delete_ai_memory_item_for_bucket(self, session_id: str, bucket_start_ts: int) -> None:
        if self._ai_memory_store is None:
            return
        owner_scope = await self._ai_memory_owner_scope()
        if not owner_scope:
            return
        try:
            await self._ai_memory_store.delete_source(
                owner_scope=owner_scope,
                source_type=self.AI_MEMORY_SOURCE_TYPE_SUMMARY,
                source_id=self._ai_memory_source_id(session_id, bucket_start_ts),
            )
        except Exception:
            logger.exception(
                "Failed to delete conversation summary from local AI memory store session_id=%s bucket_start_ts=%s",
                session_id,
                bucket_start_ts,
            )

    async def _ai_memory_owner_scope(self) -> str:
        get_app_state = getattr(self._db, "get_app_state", None)
        if not callable(get_app_state):
            return ""
        try:
            user_id = str(await get_app_state(Database.AUTH_USER_ID_STATE_KEY) or "").strip()
        except Exception:
            logger.exception("Failed to resolve current account for local AI memory store")
            return ""
        if not user_id:
            return ""
        return f"account:{user_id}"

    @staticmethod
    def _ai_memory_source_id(session_id: str, bucket_start_ts: int) -> str:
        return f"conversation:{str(session_id or '').strip()}:summary:{int(bucket_start_ts or 0)}"

    @staticmethod
    def _summary_participants(
        session_id: str,
        messages: list[ChatMessage],
        *,
        existing: dict[str, Any],
        session: Session | None = None,
        structured: StructuredConversationSummary | None = None,
    ) -> list[str]:
        del session_id
        participants: list[str] = []

        def add(raw_value: Any) -> None:
            value = str(raw_value or "").strip()
            if value and value not in participants:
                participants.append(value)

        if structured is not None:
            for value in list(structured.participants or []):
                add(value)

        add(existing.get("session_name"))

        if session is not None:
            add(session.display_name())
            add(session.name)
            extra = session.extra if isinstance(session.extra, dict) else {}
            if str(session.session_type or "").strip() == "direct":
                for key in (
                    "counterpart_name",
                    "counterpart_nickname",
                    "counterpart_username",
                    "counterpart_id",
                    "last_message_sender_name",
                    "last_message_sender_id",
                ):
                    add(extra.get(key))
            elif str(session.session_type or "").strip() == "group":
                for member in list(extra.get("members") or []):
                    if not isinstance(member, dict):
                        continue
                    for key in ("remark", "group_nickname", "nickname", "display_name", "username", "id"):
                        add(member.get(key))
            for participant_id in list(getattr(session, "participant_ids", []) or []):
                add(participant_id)

        for message in messages:
            if message.is_self:
                add("我")
                continue
            extra = message.extra if isinstance(message.extra, dict) else {}
            for key in ("sender_name", "sender_nickname", "sender_username", "sender_display_name"):
                add(extra.get(key))
            add(message.sender_id)
            if not str(message.sender_id or "").strip():
                add("对方")
        return participants

    @staticmethod
    def _summary_keywords(structured: StructuredConversationSummary) -> tuple[str, ...]:
        keywords: list[str] = []

        def add(raw_value: Any) -> None:
            value = str(raw_value or "").strip()
            if not value or value in keywords:
                return
            keywords.append(value)

        for value in list(structured.keywords or []):
            add(value)
        for value in list(structured.topics or []):
            add(value)
        for value in list(structured.decisions or []):
            add(value)
        return tuple(keywords[:12])

    @staticmethod
    def _voice_message_duration_seconds(message: ChatMessage) -> int:
        try:
            return max(0, int(float((message.extra or {}).get("duration") or 0)))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _voice_transcript_payload(
        *,
        status: str,
        text: str = "",
        reason: str = "",
        duration_seconds: int = 0,
        language: str = "",
        language_probability: float = 0.0,
        metadata: dict | None = None,
        error_code: str = "",
        error_message: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": str(status or "").strip(),
            "engine": "faster-whisper",
            "duration_seconds": max(0, int(duration_seconds or 0)),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        if text:
            payload["text"] = text
        if reason:
            payload["reason"] = reason
        if language:
            payload["language"] = language
        if language_probability:
            payload["language_probability"] = float(language_probability)
        if metadata:
            payload.update({key: value for key, value in dict(metadata).items() if value not in (None, "")})
        if error_code:
            payload["error_code"] = error_code
        if error_message:
            payload["error_message"] = error_message
        return payload

    @staticmethod
    def _file_text_extract_payload(
        *,
        status: str,
        text: str = "",
        reason: str = "",
        file_name: str = "",
        file_ext: str = "",
        size_bytes: int = 0,
        truncated: bool = False,
        page_count: int = 0,
        metadata: dict | None = None,
        error_code: str = "",
        error_message: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": str(status or "").strip(),
            "engine": "local_file_text",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        if text:
            payload["text"] = text
        if reason:
            payload["reason"] = reason
        if file_name:
            payload["file_name"] = file_name
        if file_ext:
            payload["file_ext"] = file_ext
        if size_bytes:
            payload["size_bytes"] = max(0, int(size_bytes or 0))
        if truncated:
            payload["truncated"] = True
        if page_count:
            payload["page_count"] = max(0, int(page_count or 0))
        if metadata:
            payload.update({key: value for key, value in dict(metadata).items() if value not in (None, "")})
        if error_code:
            payload["error_code"] = error_code
        if error_message:
            payload["error_message"] = error_message
        return payload

    @classmethod
    def _file_text_extract_error_payload(cls, exc: FileTextExtractionError) -> dict[str, Any]:
        status, reason = cls._file_text_error_status_reason(exc.code)
        return cls._file_text_extract_payload(
            status=status,
            reason=reason,
            error_code=exc.code,
            error_message=str(exc),
        )

    @staticmethod
    def _file_text_error_status_reason(code: str) -> tuple[str, str]:
        normalized = str(code or "").strip()
        if normalized == "FILE_TEXT_UNSUPPORTED_TYPE":
            return "skipped", "unsupported_type"
        if normalized == "FILE_TEXT_FILE_TOO_LARGE":
            return "skipped", "file_too_large"
        if normalized == "FILE_TEXT_TOO_MANY_PAGES":
            return "skipped", "too_many_pages"
        if normalized == "FILE_TEXT_EMPTY":
            return "skipped", "empty"
        if normalized == "FILE_TEXT_DEPENDENCY_MISSING":
            return "failed", "dependency_missing"
        if normalized == "FILE_TEXT_NOT_FOUND":
            return "failed", "file_not_found"
        return "failed", "runtime_error"

    @staticmethod
    def _file_display_name(message: ChatMessage) -> str:
        extra = message.extra if isinstance(message.extra, dict) else {}
        media = extra.get("media") if isinstance(extra.get("media"), dict) else {}
        for key in ("name", "original_name", "file_name"):
            value = str(extra.get(key) or media.get(key) or "").strip()
            if value:
                return value
        content = str(message.content or "").replace("\\", "/").rstrip("/")
        return content.rsplit("/", 1)[-1].strip()

    @staticmethod
    def _file_mime_type(message: ChatMessage) -> str:
        extra = message.extra if isinstance(message.extra, dict) else {}
        media = extra.get("media") if isinstance(extra.get("media"), dict) else {}
        for key in ("mime_type", "mime", "content_type", "file_type"):
            value = str(extra.get(key) or media.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _memory_source_id(bucket_start_ts: int) -> str:
        return f"summary:{int(bucket_start_ts or 0)}"

    @staticmethod
    def _memory_title(*, session_name: str, bucket_start_ts: int, bucket_end_ts: int) -> str:
        name = str(session_name or "").strip() or "聊天"
        try:
            start_label = datetime.fromtimestamp(int(bucket_start_ts or 0)).strftime("%Y-%m-%d %H:%M")
            end_label = datetime.fromtimestamp(int(bucket_end_ts or bucket_start_ts or 0)).strftime("%H:%M")
        except (OSError, ValueError):
            start_label = str(int(bucket_start_ts or 0))
            end_label = str(int(bucket_end_ts or bucket_start_ts or 0))
        return f"{name} {start_label}-{end_label}"

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
            "display_summary_ciphertext": "",
            "retrieval_summary_ciphertext": "",
            "summary_structured_json_ciphertext": "",
            "summary_schema_version": ConversationSummaryManager.SUMMARY_SCHEMA_VERSION,
            "summary_version": ConversationSummaryManager.SUMMARY_SCHEMA_VERSION,
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
        _conversation_summary_manager = ConversationSummaryManager(ai_memory_store=get_local_ai_memory_store())
    return _conversation_summary_manager

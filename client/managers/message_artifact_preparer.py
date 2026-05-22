"""Prepare local AI artifacts for media messages."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Awaitable, Callable

from client.core import logging
from client.core.image_summary import IMAGE_SUMMARY_EXTRA_KEY
from client.core.voice_transcription import VOICE_TRANSCRIPT_EXTRA_KEY, VOICE_TRANSCRIPT_MAX_SECONDS
from client.events.event_bus import EventBus, get_event_bus
from client.models.message import ChatMessage, MessageType, Session
from client.services.local_voice_transcription_service import LocalVoiceTranscriptionRuntimeError


logger = logging.get_logger(__name__)
MESSAGE_RECEIVED_EVENT = "message_received"
MESSAGE_SENT_EVENT = "message_sent"


class MessageArtifactPreparer:
    """Create local voice/image text artifacts that downstream AI prompts can consume."""

    def __init__(
        self,
        *,
        message_manager: Any | None = None,
        voice_transcription_runtime: Any | None = None,
        task_manager: Any | None = None,
        prompt_builder: Any | None = None,
    ) -> None:
        self._message_manager = message_manager
        self._voice_transcription_runtime = voice_transcription_runtime
        if task_manager is None:
            from client.managers.ai_task_manager import get_ai_task_manager

            task_manager = get_ai_task_manager()
        self._task_manager = task_manager
        if prompt_builder is None:
            from client.managers.ai_prompt_builder import AIPromptBuilder

            prompt_builder = AIPromptBuilder()
        self._prompt_builder = prompt_builder
        self._voice_transcription_semaphore = asyncio.Semaphore(1)
        self._image_summary_semaphore = asyncio.Semaphore(1)

    def needs_preparation(self, message: ChatMessage) -> bool:
        if message.message_type == MessageType.VOICE:
            transcript = dict((message.extra or {}).get(VOICE_TRANSCRIPT_EXTRA_KEY) or {})
            status = str(transcript.get("status") or "").strip()
            summary_status = str(transcript.get("summary_status") or "").strip()
            transcript_text = str(transcript.get("text") or "").strip()
            if (
                status == "ready"
                and transcript_text
                and len(transcript_text) > self._prompt_builder.VOICE_SUMMARY_TRIGGER_CHARS
                and not (summary_status == "ready" and str(transcript.get("summary_text") or "").strip())
                and summary_status not in {"pending", "failed", "skipped"}
            ):
                return True
            return not (status == "ready" and str(transcript.get("text") or "").strip()) and status not in {
                "pending",
                "failed",
                "skipped",
            }
        if message.message_type == MessageType.IMAGE:
            summary = dict((message.extra or {}).get(IMAGE_SUMMARY_EXTRA_KEY) or {})
            status = str(summary.get("status") or "").strip()
            return not (status == "ready" and str(summary.get("text") or "").strip()) and status not in {
                "pending",
                "failed",
                "skipped",
            }
        return False

    async def prepare_message(self, message: ChatMessage, *, session: Session | None = None) -> ChatMessage:
        if message.message_type == MessageType.VOICE:
            return await self.prepare_voice_transcript(message, session=session)
        if message.message_type == MessageType.IMAGE:
            return await self.prepare_image_summary(message, session=session)
        return message

    async def prepare_voice_transcript(self, message: ChatMessage, *, session: Session | None = None) -> ChatMessage:
        transcript = dict((message.extra or {}).get(VOICE_TRANSCRIPT_EXTRA_KEY) or {})
        status = str(transcript.get("status") or "").strip()
        if status == "ready" and str(transcript.get("text") or "").strip():
            return await self._ensure_voice_summary(message, transcript, session=session)
        if status in {"pending", "failed", "skipped"}:
            return message

        duration_seconds = self._voice_message_duration_seconds(message)
        if duration_seconds > VOICE_TRANSCRIPT_MAX_SECONDS:
            return await self._persist_voice_transcript(
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
                "[voice-asr] message_voice_transcript_skipped message_id=%s session_id=%s reason=%s error_code=%s",
                message.message_id,
                message.session_id,
                str(payload.get("reason") or ""),
                exc.code,
            )
            return await self._persist_voice_transcript(message, payload)
        except Exception as exc:
            logger.warning(
                "[voice-asr] message_voice_transcript_unavailable message_id=%s session_id=%s error=%s",
                message.message_id,
                message.session_id,
                exc,
            )
            return await self._persist_voice_transcript(
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
        persisted = await self._persist_voice_transcript(message, payload)
        return await self._ensure_voice_summary(persisted, payload, session=session)

    async def _ensure_voice_summary(
        self,
        message: ChatMessage,
        transcript: dict[str, Any],
        *,
        session: Session | None = None,
    ) -> ChatMessage:
        """Generate a short local summary for long voice transcripts."""
        text = " ".join(str(transcript.get("text") or "").strip().split())
        if not text:
            return message
        if len(text) <= self._prompt_builder.VOICE_SUMMARY_TRIGGER_CHARS:
            return message
        summary_status = str(transcript.get("summary_status") or "").strip()
        if summary_status in {"ready", "pending", "failed", "skipped"}:
            return message

        payload = dict(transcript)
        try:
            request = self._prompt_builder.build_voice_summary_request(
                text,
                session=session,
                message_id=message.message_id,
                task_id=self._task_id("voice-summary"),
            )
            async with self._voice_transcription_semaphore:
                snapshot = await self._task_manager.run_once(request)
        except Exception as exc:
            logger.warning(
                "[voice-summary] message_voice_summary_unavailable message_id=%s session_id=%s error=%s",
                message.message_id,
                message.session_id,
                exc,
            )
            payload.update(
                {
                    "summary_status": "failed",
                    "summary_reason": "runtime_error",
                    "summary_error_code": exc.__class__.__name__,
                    "summary_error_message": str(exc),
                }
            )
            return await self._persist_voice_transcript(message, payload)

        if not self._snapshot_is_done(snapshot):
            error_code = str(getattr(snapshot.error_code, "value", snapshot.error_code) or snapshot.finish_reason or "voice_summary_failed")
            payload.update(
                {
                    "summary_status": "failed",
                    "summary_reason": self._voice_summary_failure_reason(error_code),
                    "summary_error_code": error_code,
                    "summary_error_message": str(snapshot.error_message or ""),
                }
            )
            return await self._persist_voice_transcript(message, payload)

        summary_text = " ".join(str(snapshot.content or "").strip().split())
        if not summary_text:
            payload.update({"summary_status": "skipped", "summary_reason": "empty"})
        else:
            payload.update(
                {
                    "summary_status": "ready",
                    "summary_text": summary_text[: self._prompt_builder.VOICE_SUMMARY_OUTPUT_CHARS].rstrip(),
                    "summary_engine": "local_llm",
                }
            )
            snapshot_metadata = dict(getattr(snapshot, "metadata", {}) or {})
            summary_model = str(
                snapshot_metadata.get("model_name")
                or snapshot_metadata.get("model_id")
                or snapshot_metadata.get("model")
                or ""
            ).strip()
            if summary_model:
                payload["summary_model"] = summary_model
        return await self._persist_voice_transcript(message, payload)

    async def prepare_image_summary(self, message: ChatMessage, *, session: Session | None = None) -> ChatMessage:
        summary = dict((message.extra or {}).get(IMAGE_SUMMARY_EXTRA_KEY) or {})
        status = str(summary.get("status") or "").strip()
        if status == "ready" and str(summary.get("text") or "").strip():
            return message
        if status in {"pending", "failed", "skipped"}:
            return message

        try:
            local_path = await self._require_message_manager().download_attachment(message.message_id)
            request = self._prompt_builder.build_image_summary_request(
                local_path,
                session=session,
                message_id=message.message_id,
                task_id=self._task_id("image-summary"),
                mime_type=self._file_mime_type(message),
                display_name=self._file_display_name(message),
            )
            async with self._image_summary_semaphore:
                snapshot = await self._task_manager.run_once(request)
        except Exception as exc:
            logger.warning(
                "[image-summary] message_image_unavailable message_id=%s session_id=%s error=%s",
                message.message_id,
                message.session_id,
                exc,
            )
            return await self._persist_image_summary(
                message,
                self._image_summary_payload(
                    status="failed",
                    reason="image_unavailable",
                    error_code=exc.__class__.__name__,
                    error_message=str(exc),
                ),
            )

        if not self._snapshot_is_done(snapshot):
            error_code = str(getattr(snapshot.error_code, "value", snapshot.error_code) or snapshot.finish_reason or "image_summary_failed")
            payload = self._image_summary_payload(
                status="failed",
                reason=self._image_summary_failure_reason(error_code),
                error_code=error_code,
                error_message=str(snapshot.error_message or ""),
            )
            logger.info(
                "[image-summary] message_image_skipped message_id=%s session_id=%s reason=%s error_code=%s",
                message.message_id,
                message.session_id,
                str(payload.get("reason") or ""),
                error_code,
            )
            return await self._persist_image_summary(message, payload)

        text = " ".join(str(snapshot.content or "").strip().split())
        if not text:
            payload = self._image_summary_payload(status="skipped", reason="empty")
        else:
            payload = self._image_summary_payload(
                status="ready",
                text=text[: self._prompt_builder.IMAGE_SUMMARY_OUTPUT_CHARS].rstrip(),
                metadata=dict(getattr(snapshot, "metadata", {}) or {}),
            )
        return await self._persist_image_summary(message, payload)

    async def _persist_voice_transcript(self, message: ChatMessage, payload: dict[str, Any]) -> ChatMessage:
        message.extra = dict(message.extra or {})
        message.extra[VOICE_TRANSCRIPT_EXTRA_KEY] = dict(payload or {})
        updated = await self._require_message_manager().update_message_voice_transcript(message.message_id, payload)
        return updated or message

    async def _persist_image_summary(self, message: ChatMessage, payload: dict[str, Any]) -> ChatMessage:
        message.extra = dict(message.extra or {})
        message.extra[IMAGE_SUMMARY_EXTRA_KEY] = dict(payload or {})
        updated = await self._require_message_manager().update_message_image_summary(message.message_id, payload)
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
    def _image_summary_payload(
        *,
        status: str,
        text: str = "",
        reason: str = "",
        metadata: dict | None = None,
        error_code: str = "",
        error_message: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": str(status or "").strip(),
            "engine": "local_vision",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        if text:
            payload["text"] = text
        if reason:
            payload["reason"] = reason
        if metadata:
            payload.update({key: value for key, value in dict(metadata).items() if value not in (None, "")})
        if error_code:
            payload["error_code"] = error_code
        if error_message:
            payload["error_message"] = error_message
        return payload

    @staticmethod
    def _image_summary_failure_reason(error_code: str) -> str:
        normalized = str(error_code or "").strip()
        if normalized in {
            "AI_MODEL_VISION_UNSUPPORTED",
            "AI_VISION_PROJECTOR_NOT_FOUND",
            "AI_VISION_RUNTIME_UNAVAILABLE",
            "AI_LOCAL_REQUIRED_UNAVAILABLE",
        }:
            return "vision_unavailable"
        if normalized == "AI_CONTEXT_TOO_LONG":
            return "image_too_large"
        if normalized == "AI_USER_CANCELLED":
            return "cancelled"
        return "runtime_error"

    @staticmethod
    def _voice_summary_failure_reason(error_code: str) -> str:
        normalized = str(error_code or "").strip()
        if normalized in {"AI_LOCAL_REQUIRED_UNAVAILABLE", "AI_MODEL_NOT_FOUND", "AI_RUNTIME_UNAVAILABLE"}:
            return "model_missing"
        if normalized == "AI_CONTEXT_TOO_LONG":
            return "transcript_too_long"
        if normalized == "AI_USER_CANCELLED":
            return "cancelled"
        return "runtime_error"

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
    def _task_id(prefix: str) -> str:
        import uuid

        return f"{prefix}-{uuid.uuid4()}"

    @staticmethod
    def _snapshot_is_done(snapshot: Any) -> bool:
        state = getattr(snapshot, "state", "")
        return str(getattr(state, "value", state) or "").strip().lower() == "done"


SessionLoader = Callable[[str], Session | None | Awaitable[Session | None]]


class MessageArtifactPreparationManager:
    """Background event bridge that prepares media artifacts after chat messages arrive."""

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        preparer: MessageArtifactPreparer | None = None,
        session_loader: SessionLoader | None = None,
    ) -> None:
        self._event_bus = event_bus or get_event_bus()
        self._preparer = preparer
        self._session_loader = session_loader
        self._event_subscriptions: list[tuple[str, Any]] = []
        self._tasks: set[asyncio.Task] = set()
        self._running_message_ids: set[str] = set()
        self._initialized = False
        self._closing = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._closing = False
        await self._subscribe(MESSAGE_RECEIVED_EVENT, self._on_message_event)
        await self._subscribe(MESSAGE_SENT_EVENT, self._on_message_event)
        self._initialized = True

    async def close(self) -> None:
        self._closing = True
        while self._event_subscriptions:
            event_type, handler = self._event_subscriptions.pop()
            await self._event_bus.unsubscribe(event_type, handler)
        tasks = list(self._tasks)
        self._tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._running_message_ids.clear()
        self._initialized = False

    async def drain(self) -> None:
        while self._tasks:
            tasks = list(self._tasks)
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0)

    async def _subscribe(self, event_type: str, handler: Any) -> None:
        self._event_subscriptions.append((event_type, handler))
        await self._event_bus.subscribe(event_type, handler)

    async def _on_message_event(self, payload: dict[str, Any] | None) -> None:
        if self._closing:
            return
        message = dict(payload or {}).get("message")
        if not isinstance(message, ChatMessage):
            return
        if not self._require_preparer().needs_preparation(message):
            return
        message_id = str(message.message_id or "").strip()
        if not message_id or message_id in self._running_message_ids:
            return
        self._running_message_ids.add(message_id)
        task = asyncio.create_task(self._prepare_message(message))
        self._tasks.add(task)
        task.add_done_callback(lambda completed: self._finalize_task(message_id, completed))

    async def _prepare_message(self, message: ChatMessage) -> None:
        session = await self._load_session(str(message.session_id or "").strip())
        await self._require_preparer().prepare_message(message, session=session)

    async def _load_session(self, session_id: str) -> Session | None:
        if not session_id:
            return None
        if self._session_loader is None:
            try:
                from client.storage.database import get_database

                return await get_database().get_session(session_id)
            except Exception:
                logger.exception("Failed to load session for message artifact preparation session_id=%s", session_id)
                return None
        result = self._session_loader(session_id)
        if asyncio.iscoroutine(result):
            return await result
        return result

    def _finalize_task(self, message_id: str, task: asyncio.Task) -> None:
        self._running_message_ids.discard(message_id)
        self._tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Failed to prepare message artifact message_id=%s", message_id)

    def _require_preparer(self) -> MessageArtifactPreparer:
        if self._preparer is None:
            self._preparer = MessageArtifactPreparer()
        return self._preparer


_message_artifact_preparation_manager: MessageArtifactPreparationManager | None = None


def get_message_artifact_preparation_manager() -> MessageArtifactPreparationManager:
    global _message_artifact_preparation_manager
    if _message_artifact_preparation_manager is None:
        _message_artifact_preparation_manager = MessageArtifactPreparationManager()
    return _message_artifact_preparation_manager


def peek_message_artifact_preparation_manager() -> MessageArtifactPreparationManager | None:
    return _message_artifact_preparation_manager

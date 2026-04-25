"""Index local AI-derived message artifacts into the unified vector memory store."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from client.core import logging
from client.core.file_text_extraction import (
    FILE_SUMMARY_EXTRA_KEY,
    FILE_TEXT_EXTRACT_EXTRA_KEY,
    extracted_file_context_text,
)
from client.core.voice_transcription import VOICE_TRANSCRIPT_EXTRA_KEY
from client.managers.conversation_vector_index import ConversationVectorIndex
from client.models.message import ChatMessage, MessageType
from client.services.local_ai_memory_store import AIMemoryItem, get_local_ai_memory_store
from client.storage.database import Database, get_database


logger = logging.get_logger(__name__)


class AIMemoryIndexingService:
    """Small coordinator that turns saved local AI artifacts into vector memory."""

    FILE_SUMMARY_SOURCE_TYPE = "file_summary"
    VOICE_TRANSCRIPT_SOURCE_TYPE = "voice_transcript"
    FILE_TEXT_SNIPPET_CHARS = 2400

    def __init__(
        self,
        *,
        db: Any | None = None,
        vector_index: ConversationVectorIndex | None = None,
        ai_memory_store: Any | None = None,
    ) -> None:
        self._db = db or get_database()
        self._vector_index = vector_index or ConversationVectorIndex()
        self._ai_memory_store = ai_memory_store or get_local_ai_memory_store()

    async def sync_file_analysis_message(self, message: ChatMessage) -> None:
        """Upsert or delete one file-summary memory item after message extra is persisted."""

        if message.message_type != MessageType.FILE:
            return
        owner_scope = await self._owner_scope()
        if not owner_scope:
            return
        source_id = self.file_summary_source_id(message)
        summary = dict((message.extra or {}).get(FILE_SUMMARY_EXTRA_KEY) or {})
        summary_text = _normalize_text(summary.get("text"))
        if str(summary.get("status") or "").strip() != "ready" or not summary_text:
            await self._ai_memory_store.delete_source(
                owner_scope=owner_scope,
                source_type=self.FILE_SUMMARY_SOURCE_TYPE,
                source_id=source_id,
            )
            return

        file_name = self._file_name(message)
        memory_text = self._file_memory_text(message, summary_text=summary_text)
        keywords = self._file_keywords(message, file_name=file_name)
        participants = self._file_participants(message)
        vector = await self._vector_index.encode_item(
            title=file_name,
            text=memory_text,
            keywords=keywords,
            participants=participants,
        )
        await self._ai_memory_store.upsert_item(
            AIMemoryItem(
                owner_scope=owner_scope,
                source_type=self.FILE_SUMMARY_SOURCE_TYPE,
                source_id=source_id,
                title=file_name,
                text=memory_text,
                vector=vector.values,
                embedding_model_id=self._vector_index.model_id,
                metadata={
                    "session_id": str(message.session_id or "").strip(),
                    "message_id": str(message.message_id or "").strip(),
                    "sender_id": str(message.sender_id or "").strip(),
                    "is_self": bool(message.is_self),
                    "file_name": file_name,
                    "mime_type": str((message.extra or {}).get("mime_type") or "").strip(),
                    "summary_status": "ready",
                    "file_text_status": str(dict((message.extra or {}).get(FILE_TEXT_EXTRACT_EXTRA_KEY) or {}).get("status") or "").strip(),
                    "bucket_start_ts": int(message.timestamp.timestamp()) if message.timestamp else 0,
                    "bucket_end_ts": int(message.timestamp.timestamp()) if message.timestamp else 0,
                    "source_version": 1,
                },
                updated_at=int(time.time()),
            )
        )

    async def sync_voice_transcript_message(self, message: ChatMessage) -> None:
        """Upsert or delete one voice-transcript memory item after message extra is persisted."""

        if message.message_type != MessageType.VOICE:
            return
        owner_scope = await self._owner_scope()
        if not owner_scope:
            return
        source_id = self.voice_transcript_source_id(message)
        transcript = dict((message.extra or {}).get(VOICE_TRANSCRIPT_EXTRA_KEY) or {})
        transcript_text = _normalize_text(transcript.get("text"))
        if str(transcript.get("status") or "").strip() != "ready" or not transcript_text:
            await self._ai_memory_store.delete_source(
                owner_scope=owner_scope,
                source_type=self.VOICE_TRANSCRIPT_SOURCE_TYPE,
                source_id=source_id,
            )
            return

        title = "语音消息"
        memory_text = f"语音转写：{transcript_text}"
        keywords = self._voice_keywords(message, transcript=transcript)
        participants = self._voice_participants(message)
        timestamp = int(message.timestamp.timestamp()) if message.timestamp else 0
        vector = await self._vector_index.encode_item(
            title=title,
            text=memory_text,
            keywords=keywords,
            participants=participants,
        )
        await self._ai_memory_store.upsert_item(
            AIMemoryItem(
                owner_scope=owner_scope,
                source_type=self.VOICE_TRANSCRIPT_SOURCE_TYPE,
                source_id=source_id,
                title=title,
                text=memory_text,
                vector=vector.values,
                embedding_model_id=self._vector_index.model_id,
                metadata={
                    "session_id": str(message.session_id or "").strip(),
                    "message_id": str(message.message_id or "").strip(),
                    "sender_id": str(message.sender_id or "").strip(),
                    "is_self": bool(message.is_self),
                    "duration_seconds": self._voice_duration_seconds(message, transcript=transcript),
                    "language": self._voice_language(transcript),
                    "transcript_status": "ready",
                    "engine": str(transcript.get("engine") or "").strip(),
                    "model": str(transcript.get("model") or "").strip(),
                    "mime_type": str((message.extra or {}).get("mime_type") or "").strip(),
                    "keywords": keywords,
                    "participants": participants,
                    "bucket_start_ts": timestamp,
                    "bucket_end_ts": timestamp,
                    "source_version": 1,
                },
                updated_at=int(time.time()),
            )
        )

    async def _owner_scope(self) -> str:
        get_app_state = getattr(self._db, "get_app_state", None)
        if not callable(get_app_state):
            return ""
        try:
            user_id = str(await get_app_state(Database.AUTH_USER_ID_STATE_KEY) or "").strip()
        except Exception:
            logger.exception("Failed to resolve current account for AI memory indexing")
            return ""
        if not user_id:
            return ""
        return f"account:{user_id}"

    def _file_memory_text(self, message: ChatMessage, *, summary_text: str) -> str:
        parts = [f"文件总结：{summary_text}"]
        file_text = extracted_file_context_text(message.extra, max_chars=self.FILE_TEXT_SNIPPET_CHARS)
        if file_text:
            parts.append(f"文件内容：{file_text}")
        return "\n".join(parts)

    @staticmethod
    def _file_name(message: ChatMessage) -> str:
        extra = dict(message.extra or {})
        for key in ("name", "file_name", "filename", "original_name"):
            value = _normalize_text(extra.get(key))
            if value:
                return value
        content_name = Path(str(message.content or "")).name
        return _normalize_text(content_name) or str(message.message_id or "").strip() or "file"

    @staticmethod
    def _file_keywords(message: ChatMessage, *, file_name: str) -> list[str]:
        keywords: list[str] = []

        def add(value: Any) -> None:
            normalized = _normalize_text(value)
            if normalized and normalized not in keywords:
                keywords.append(normalized)

        add(file_name)
        suffix = Path(file_name).suffix.lower()
        add(suffix)
        add(dict(message.extra or {}).get("mime_type"))
        return keywords

    @staticmethod
    def _file_participants(message: ChatMessage) -> list[str]:
        participants: list[str] = []
        sender_id = _normalize_text(message.sender_id)
        if sender_id:
            participants.append(sender_id)
        if message.is_self:
            participants.append("我")
        return participants

    @classmethod
    def file_summary_source_id(cls, message: ChatMessage) -> str:
        return f"file:{str(message.session_id or '').strip()}:{str(message.message_id or '').strip()}"

    @staticmethod
    def _voice_keywords(message: ChatMessage, *, transcript: dict[str, Any]) -> list[str]:
        keywords: list[str] = []

        def add(value: Any) -> None:
            normalized = _normalize_text(value)
            if normalized and normalized not in keywords:
                keywords.append(normalized)

        add("语音消息")
        add(transcript.get("engine"))
        add(transcript.get("model"))
        add(transcript.get("language"))
        add(transcript.get("detected_language"))
        add(dict(message.extra or {}).get("mime_type"))
        return keywords

    @staticmethod
    def _voice_participants(message: ChatMessage) -> list[str]:
        participants: list[str] = []
        sender_id = _normalize_text(message.sender_id)
        if sender_id:
            participants.append(sender_id)
        if message.is_self:
            participants.append("我")
        return participants

    @staticmethod
    def _voice_duration_seconds(message: ChatMessage, *, transcript: dict[str, Any]) -> int:
        extra = dict(message.extra or {})
        for value in (
            transcript.get("duration_seconds"),
            transcript.get("duration"),
            extra.get("duration_seconds"),
            extra.get("duration"),
        ):
            try:
                return max(0, int(round(float(value))))
            except (TypeError, ValueError):
                continue
        return 0

    @staticmethod
    def _voice_language(transcript: dict[str, Any]) -> str:
        return _normalize_text(transcript.get("language") or transcript.get("detected_language"))

    @classmethod
    def voice_transcript_source_id(cls, message: ChatMessage) -> str:
        return f"voice:{str(message.session_id or '').strip()}:{str(message.message_id or '').strip()}"


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


_ai_memory_indexing_service: AIMemoryIndexingService | None = None


def get_ai_memory_indexing_service() -> AIMemoryIndexingService:
    global _ai_memory_indexing_service
    if _ai_memory_indexing_service is None:
        _ai_memory_indexing_service = AIMemoryIndexingService()
    return _ai_memory_indexing_service

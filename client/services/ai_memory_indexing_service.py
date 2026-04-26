"""Index local AI-derived message artifacts into the unified vector memory store."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from client.core import logging
from client.core.file_text_extraction import (
    FILE_SUMMARY_EXTRA_KEY,
    FILE_TEXT_EXTRACT_EXTRA_KEY,
    FILE_TEXT_EXTRACT_MAX_CHARS,
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
    FILE_TEXT_CHUNK_SOURCE_TYPE = "file_text_chunk"
    VOICE_TRANSCRIPT_SOURCE_TYPE = "voice_transcript"
    FILE_TEXT_SNIPPET_CHARS = 2400
    FILE_TEXT_INDEX_MAX_CHARS = FILE_TEXT_EXTRACT_MAX_CHARS
    FILE_TEXT_CHUNK_CHARS = 1200
    FILE_TEXT_CHUNK_OVERLAP_CHARS = 160

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
        """Upsert or delete file-analysis memory items after message extra is persisted."""

        if message.message_type != MessageType.FILE:
            return
        owner_scope = await self._owner_scope()
        if not owner_scope:
            return
        participants = await self._message_participants(message)
        await self._sync_file_summary_message(owner_scope=owner_scope, message=message, participants=participants)
        await self._sync_file_text_chunks(owner_scope=owner_scope, message=message, participants=participants)

    async def _sync_file_summary_message(
        self,
        *,
        owner_scope: str,
        message: ChatMessage,
        participants: list[str],
    ) -> None:
        """Upsert or delete one file-summary memory item."""

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
                    "keywords": keywords,
                    "participants": participants,
                },
                updated_at=int(time.time()),
            )
        )

    async def _sync_file_text_chunks(
        self,
        *,
        owner_scope: str,
        message: ChatMessage,
        participants: list[str],
    ) -> None:
        """Replace extracted file-text chunks for one file message."""

        source_id = self.file_text_source_id(message)
        extraction = dict((message.extra or {}).get(FILE_TEXT_EXTRACT_EXTRA_KEY) or {})
        file_text = extracted_file_context_text(message.extra, max_chars=self.FILE_TEXT_INDEX_MAX_CHARS)
        if str(extraction.get("status") or "").strip() != "ready" or not file_text:
            await self._ai_memory_store.delete_source(
                owner_scope=owner_scope,
                source_type=self.FILE_TEXT_CHUNK_SOURCE_TYPE,
                source_id=source_id,
            )
            return

        chunks = self._split_file_text_chunks(file_text)
        if not chunks:
            await self._ai_memory_store.delete_source(
                owner_scope=owner_scope,
                source_type=self.FILE_TEXT_CHUNK_SOURCE_TYPE,
                source_id=source_id,
            )
            return

        file_name = self._file_name(message)
        keywords = self._file_keywords(message, file_name=file_name)
        timestamp = int(message.timestamp.timestamp()) if message.timestamp else 0
        items: list[AIMemoryItem] = []
        for index, chunk_text in enumerate(chunks):
            chunk_id = f"chunk-{index:04d}"
            title = f"{file_name} #{index + 1}"
            memory_text = f"文件内容片段：{chunk_text}"
            vector = await self._vector_index.encode_item(
                title=title,
                text=memory_text,
                keywords=keywords,
                participants=participants,
            )
            items.append(
                AIMemoryItem(
                    owner_scope=owner_scope,
                    source_type=self.FILE_TEXT_CHUNK_SOURCE_TYPE,
                    source_id=source_id,
                    chunk_id=chunk_id,
                    title=title,
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
                        "file_text_status": "ready",
                        "chunk_index": index,
                        "chunk_count": len(chunks),
                        "keywords": keywords,
                        "participants": participants,
                        "bucket_start_ts": timestamp,
                        "bucket_end_ts": timestamp,
                        "source_version": 1,
                    },
                    updated_at=int(time.time()),
                )
            )

        await self._ai_memory_store.delete_source(
            owner_scope=owner_scope,
            source_type=self.FILE_TEXT_CHUNK_SOURCE_TYPE,
            source_id=source_id,
        )
        await self._ai_memory_store.upsert_items(items)

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
        participants = await self._message_participants(message)
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

    async def sync_ready_local_artifact_messages(self, *, limit: int = 500) -> dict[str, int]:
        """Backfill ready local file/voice AI artifacts into the unified vector memory store."""

        list_messages = getattr(self._db, "list_local_ai_artifact_messages", None)
        if not callable(list_messages):
            return {"processed": 0, "files": 0, "voices": 0, "failed": 0}

        normalized_limit = max(1, min(5000, int(limit or 500)))
        messages = list(await list_messages(limit=normalized_limit))
        stats = {"processed": 0, "files": 0, "voices": 0, "failed": 0}
        for message in messages:
            try:
                if message.message_type == MessageType.FILE:
                    await self.sync_file_analysis_message(message)
                    stats["files"] += 1
                elif message.message_type == MessageType.VOICE:
                    await self.sync_voice_transcript_message(message)
                    stats["voices"] += 1
                else:
                    continue
                stats["processed"] += 1
            except Exception:
                stats["failed"] += 1
                logger.exception(
                    "Failed to backfill local AI memory artifact message_id=%s session_id=%s message_type=%s",
                    getattr(message, "message_id", ""),
                    getattr(message, "session_id", ""),
                    getattr(getattr(message, "message_type", ""), "value", getattr(message, "message_type", "")),
                )
        return stats

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

    async def _message_participants(self, message: ChatMessage) -> list[str]:
        participants: list[str] = []

        def add(value: Any) -> None:
            normalized = _normalize_text(value)
            if normalized and normalized not in participants:
                participants.append(normalized)

        add(message.sender_id)
        if message.is_self:
            add("我")
        extra = dict(message.extra or {})
        for key in (
            "sender_id",
            "sender_name",
            "sender_username",
            "sender_nickname",
            "sender_display_name",
        ):
            add(extra.get(key))

        get_session = getattr(self._db, "get_session", None)
        if callable(get_session) and str(message.session_id or "").strip():
            try:
                session = await get_session(str(message.session_id or "").strip())
            except Exception:
                logger.exception("Failed to resolve session participants for local AI memory message_id=%s", message.message_id)
                session = None
            if session is not None:
                add(getattr(session, "session_id", ""))
                add(getattr(session, "name", ""))
                display_name = getattr(session, "display_name", None)
                if callable(display_name):
                    try:
                        add(display_name())
                    except Exception:
                        pass
                for participant_id in list(getattr(session, "participant_ids", []) or []):
                    add(participant_id)
                session_extra = dict(getattr(session, "extra", {}) or {})
                for key in (
                    "current_user_id",
                    "counterpart_id",
                    "counterpart_name",
                    "counterpart_username",
                    "counterpart_nickname",
                    "counterpart_display_name",
                    "server_name",
                ):
                    add(session_extra.get(key))
                for member in list(session_extra.get("members") or []):
                    if not isinstance(member, dict):
                        continue
                    for key in (
                        "id",
                        "user_id",
                        "contact_id",
                        "username",
                        "nickname",
                        "remark",
                        "display_name",
                        "group_nickname",
                    ):
                        add(member.get(key))
        return participants

    @classmethod
    def file_summary_source_id(cls, message: ChatMessage) -> str:
        return f"file:{str(message.session_id or '').strip()}:{str(message.message_id or '').strip()}"

    @classmethod
    def file_text_source_id(cls, message: ChatMessage) -> str:
        return f"file_text:{str(message.session_id or '').strip()}:{str(message.message_id or '').strip()}"

    @classmethod
    def _split_file_text_chunks(cls, text: str) -> list[str]:
        normalized = str(text or "").strip()
        if not normalized:
            return []
        chunk_size = max(1, int(cls.FILE_TEXT_CHUNK_CHARS or 1))
        overlap = max(0, min(int(cls.FILE_TEXT_CHUNK_OVERLAP_CHARS or 0), chunk_size - 1))
        chunks: list[str] = []
        start = 0
        text_length = len(normalized)
        while start < text_length:
            end = min(text_length, start + chunk_size)
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= text_length:
                break
            next_start = end - overlap
            start = next_start if next_start > start else end
        return chunks

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

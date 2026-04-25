import asyncio
from datetime import datetime

from client.core.file_text_extraction import FILE_SUMMARY_EXTRA_KEY, FILE_TEXT_EXTRACT_EXTRA_KEY
from client.core.voice_transcription import VOICE_TRANSCRIPT_EXTRA_KEY
from client.managers.conversation_vector_index import DenseVector
from client.models.message import ChatMessage, MessageStatus, MessageType
from client.services.ai_memory_indexing_service import AIMemoryIndexingService
from client.storage.database import Database


class _FakeDatabase:
    def __init__(self, user_id: str = "test1") -> None:
        self.app_state = {Database.AUTH_USER_ID_STATE_KEY: user_id}

    async def get_app_state(self, key: str):
        return self.app_state.get(str(key or ""))


class _FakeVectorIndex:
    model_id = "fake-embedding-model"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def encode_item(self, *, title: str, text: str, keywords=(), participants=()):
        self.calls.append(
            {
                "title": title,
                "text": text,
                "keywords": list(keywords or []),
                "participants": list(participants or []),
            }
        )
        return DenseVector(values=(1.0, 0.0, 0.0))


class _FakeAIMemoryStore:
    def __init__(self) -> None:
        self.upserted_items = []
        self.deleted_sources: list[tuple[str, str, str]] = []

    async def upsert_item(self, item) -> None:
        self.upserted_items.append(item)

    async def delete_source(self, *, owner_scope: str, source_type: str, source_id: str) -> None:
        self.deleted_sources.append((owner_scope, source_type, source_id))


def _file_message(*, summary_status: str = "ready", summary_text: str = "文件确认了合同金额。") -> ChatMessage:
    now = datetime(2026, 4, 24, 10, 0, 0)
    return ChatMessage(
        message_id="m-file",
        session_id="session-1",
        sender_id="alice",
        content="/uploads/report.pdf",
        message_type=MessageType.FILE,
        status=MessageStatus.RECEIVED,
        timestamp=now,
        updated_at=now,
        is_self=False,
        extra={
            "name": "report.pdf",
            "mime_type": "application/pdf",
            FILE_TEXT_EXTRACT_EXTRA_KEY: {
                "status": "ready",
                "text": "合同金额为 100 元，付款期限为周五。",
                "file_name": "report.pdf",
                "file_ext": ".pdf",
            },
            FILE_SUMMARY_EXTRA_KEY: {
                "status": summary_status,
                "text": summary_text,
            },
        },
    )


def _voice_message(*, transcript_status: str = "ready", transcript_text: str = "今晚八点开会。") -> ChatMessage:
    now = datetime(2026, 4, 24, 10, 5, 0)
    return ChatMessage(
        message_id="m-voice",
        session_id="session-1",
        sender_id="test1",
        content="file:///voice.m4a",
        message_type=MessageType.VOICE,
        status=MessageStatus.RECEIVED,
        timestamp=now,
        updated_at=now,
        is_self=True,
        extra={
            "duration": 8,
            "mime_type": "audio/mp4",
            VOICE_TRANSCRIPT_EXTRA_KEY: {
                "status": transcript_status,
                "text": transcript_text,
                "language": "zh",
                "engine": "faster-whisper",
                "model": "small",
            },
        },
    )


def test_ai_memory_indexing_service_indexes_ready_file_summary() -> None:
    async def scenario() -> None:
        store = _FakeAIMemoryStore()
        vector_index = _FakeVectorIndex()
        service = AIMemoryIndexingService(
            db=_FakeDatabase(),
            vector_index=vector_index,
            ai_memory_store=store,
        )

        await service.sync_file_analysis_message(_file_message())

        assert len(store.upserted_items) == 1
        item = store.upserted_items[0]
        assert item.owner_scope == "account:test1"
        assert item.source_type == "file_summary"
        assert item.source_id == "file:session-1:m-file"
        assert item.title == "report.pdf"
        assert "文件确认了合同金额" in item.text
        assert "合同金额为 100 元" in item.text
        assert item.embedding_model_id == "fake-embedding-model"
        assert item.metadata["session_id"] == "session-1"
        assert item.metadata["message_id"] == "m-file"
        assert item.metadata["file_name"] == "report.pdf"
        assert vector_index.calls[0]["title"] == "report.pdf"
        assert "report.pdf" in vector_index.calls[0]["keywords"]
        assert "alice" in vector_index.calls[0]["participants"]

    asyncio.run(scenario())


def test_ai_memory_indexing_service_indexes_ready_voice_transcript() -> None:
    async def scenario() -> None:
        store = _FakeAIMemoryStore()
        vector_index = _FakeVectorIndex()
        service = AIMemoryIndexingService(
            db=_FakeDatabase(),
            vector_index=vector_index,
            ai_memory_store=store,
        )

        await service.sync_voice_transcript_message(_voice_message())

        assert len(store.upserted_items) == 1
        item = store.upserted_items[0]
        assert item.owner_scope == "account:test1"
        assert item.source_type == "voice_transcript"
        assert item.source_id == "voice:session-1:m-voice"
        assert item.title == "语音消息"
        assert "今晚八点开会" in item.text
        assert item.embedding_model_id == "fake-embedding-model"
        assert item.metadata["session_id"] == "session-1"
        assert item.metadata["message_id"] == "m-voice"
        assert item.metadata["duration_seconds"] == 8
        assert item.metadata["language"] == "zh"
        assert item.metadata["transcript_status"] == "ready"
        assert vector_index.calls[0]["title"] == "语音消息"
        assert "faster-whisper" in vector_index.calls[0]["keywords"]
        assert "test1" in vector_index.calls[0]["participants"]
        assert "我" in vector_index.calls[0]["participants"]

    asyncio.run(scenario())


def test_ai_memory_indexing_service_deletes_non_ready_voice_transcript() -> None:
    async def scenario() -> None:
        store = _FakeAIMemoryStore()
        service = AIMemoryIndexingService(
            db=_FakeDatabase(),
            vector_index=_FakeVectorIndex(),
            ai_memory_store=store,
        )

        await service.sync_voice_transcript_message(_voice_message(transcript_status="failed", transcript_text=""))

        assert store.upserted_items == []
        assert store.deleted_sources == [("account:test1", "voice_transcript", "voice:session-1:m-voice")]

    asyncio.run(scenario())


def test_ai_memory_indexing_service_deletes_non_ready_file_summary() -> None:
    async def scenario() -> None:
        store = _FakeAIMemoryStore()
        service = AIMemoryIndexingService(
            db=_FakeDatabase(),
            vector_index=_FakeVectorIndex(),
            ai_memory_store=store,
        )

        await service.sync_file_analysis_message(_file_message(summary_status="failed", summary_text=""))

        assert store.upserted_items == []
        assert store.deleted_sources == [("account:test1", "file_summary", "file:session-1:m-file")]

    asyncio.run(scenario())

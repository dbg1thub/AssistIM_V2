import asyncio
from datetime import datetime

from client.core.file_text_extraction import FILE_SUMMARY_EXTRA_KEY, FILE_TEXT_EXTRACT_EXTRA_KEY
from client.core.voice_transcription import VOICE_TRANSCRIPT_EXTRA_KEY
from client.managers.conversation_vector_index import DenseVector
from client.models.message import ChatMessage, MessageStatus, MessageType
from client.services.ai_memory_indexing_service import AIMemoryIndexingService
from client.storage.database import Database


class _FakeDatabase:
    def __init__(
        self,
        user_id: str = "test1",
        *,
        sessions: dict[str, object] | None = None,
        ready_artifact_messages: list[ChatMessage] | None = None,
    ) -> None:
        self.app_state = {Database.AUTH_USER_ID_STATE_KEY: user_id}
        self.sessions = dict(sessions or {})
        self.ready_artifact_messages = list(ready_artifact_messages or [])
        self.ready_artifact_calls: list[dict] = []

    async def get_app_state(self, key: str):
        return self.app_state.get(str(key or ""))

    async def get_session(self, session_id: str):
        return self.sessions.get(str(session_id or ""))

    async def list_local_ai_artifact_messages(self, *, limit: int = 500):
        self.ready_artifact_calls.append({"limit": limit})
        return list(self.ready_artifact_messages)[: int(limit or 500)]


class _FakeSession:
    def __init__(
        self,
        *,
        session_id: str = "session-1",
        name: str = "test3",
        session_type: str = "direct",
        participant_ids: list[str] | None = None,
        extra: dict | None = None,
    ) -> None:
        self.session_id = session_id
        self.name = name
        self.session_type = session_type
        self.participant_ids = list(participant_ids or [])
        self.extra = dict(extra or {})

    def display_name(self) -> str:
        return self.name


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

    async def upsert_items(self, items) -> None:
        self.upserted_items.extend(list(items or []))

    async def delete_source(self, *, owner_scope: str, source_type: str, source_id: str) -> None:
        self.deleted_sources.append((owner_scope, source_type, source_id))


def _file_message(
    *,
    session_id: str = "session-1",
    sender_id: str = "alice",
    is_self: bool = False,
    summary_status: str = "ready",
    summary_text: str = "文件确认了合同金额。",
    text_status: str = "ready",
    text: str = "合同金额为 100 元，付款期限为周五。",
) -> ChatMessage:
    now = datetime(2026, 4, 24, 10, 0, 0)
    return ChatMessage(
        message_id="m-file",
        session_id=session_id,
        sender_id=sender_id,
        content="/uploads/report.pdf",
        message_type=MessageType.FILE,
        status=MessageStatus.RECEIVED,
        timestamp=now,
        updated_at=now,
        is_self=is_self,
        extra={
            "name": "report.pdf",
            "mime_type": "application/pdf",
            FILE_TEXT_EXTRACT_EXTRA_KEY: {
                "status": text_status,
                "text": text,
                "file_name": "report.pdf",
                "file_ext": ".pdf",
            },
            FILE_SUMMARY_EXTRA_KEY: {
                "status": summary_status,
                "text": summary_text,
            },
        },
    )


def _voice_message(
    *,
    session_id: str = "session-1",
    sender_id: str = "test1",
    is_self: bool = True,
    transcript_status: str = "ready",
    transcript_text: str = "今晚八点开会。",
) -> ChatMessage:
    now = datetime(2026, 4, 24, 10, 5, 0)
    return ChatMessage(
        message_id="m-voice",
        session_id=session_id,
        sender_id=sender_id,
        content="file:///voice.m4a",
        message_type=MessageType.VOICE,
        status=MessageStatus.RECEIVED,
        timestamp=now,
        updated_at=now,
        is_self=is_self,
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

        item = next(item for item in store.upserted_items if item.source_type == "file_summary")
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


def test_ai_memory_indexing_service_adds_session_participants_to_file_memory() -> None:
    async def scenario() -> None:
        store = _FakeAIMemoryStore()
        vector_index = _FakeVectorIndex()
        session = _FakeSession(
            participant_ids=["user-test1", "user-test3"],
            extra={
                "current_user_id": "user-test1",
                "counterpart_id": "user-test3",
                "counterpart_name": "test3",
                "counterpart_username": "test3",
            },
        )
        service = AIMemoryIndexingService(
            db=_FakeDatabase(sessions={"session-1": session}),
            vector_index=vector_index,
            ai_memory_store=store,
        )

        await service.sync_file_analysis_message(_file_message(sender_id="user-test1", is_self=True))

        item = next(item for item in store.upserted_items if item.source_type == "file_summary")
        assert "user-test1" in item.metadata["participants"]
        assert "user-test3" in item.metadata["participants"]
        assert "test3" in item.metadata["participants"]
        assert "我" in item.metadata["participants"]
        assert "test3" in vector_index.calls[0]["participants"]

    asyncio.run(scenario())


def test_ai_memory_indexing_service_indexes_ready_file_text_chunks() -> None:
    async def scenario() -> None:
        store = _FakeAIMemoryStore()
        vector_index = _FakeVectorIndex()
        service = AIMemoryIndexingService(
            db=_FakeDatabase(),
            vector_index=vector_index,
            ai_memory_store=store,
        )
        text = (
            "第一段 付款期限为周五。"
            + "甲" * 1500
            + "第二段 违约金按每日千分之一计算。"
            + "乙" * 1500
            + "第三段 发票需要在验收后七日内开具。"
        )

        await service.sync_file_analysis_message(_file_message(text=text))

        chunks = [item for item in store.upserted_items if item.source_type == "file_text_chunk"]
        assert len(chunks) >= 2
        assert store.deleted_sources[0] == ("account:test1", "file_text_chunk", "file_text:session-1:m-file")
        assert all(item.owner_scope == "account:test1" for item in chunks)
        assert all(item.source_id == "file_text:session-1:m-file" for item in chunks)
        assert [item.chunk_id for item in chunks] == [f"chunk-{index:04d}" for index in range(len(chunks))]
        assert chunks[0].title == "report.pdf #1"
        assert "第一段 付款期限为周五" in chunks[0].text
        assert any("违约金按每日千分之一计算" in item.text for item in chunks)
        assert chunks[0].metadata["session_id"] == "session-1"
        assert chunks[0].metadata["message_id"] == "m-file"
        assert chunks[0].metadata["file_name"] == "report.pdf"
        assert chunks[0].metadata["chunk_index"] == 0
        assert chunks[0].metadata["chunk_count"] == len(chunks)
        assert chunks[0].metadata["file_text_status"] == "ready"
        assert "report.pdf" in vector_index.calls[-1]["keywords"]
        assert "alice" in vector_index.calls[-1]["participants"]

    asyncio.run(scenario())


def test_ai_memory_indexing_service_deletes_non_ready_file_text_chunks() -> None:
    async def scenario() -> None:
        store = _FakeAIMemoryStore()
        service = AIMemoryIndexingService(
            db=_FakeDatabase(),
            vector_index=_FakeVectorIndex(),
            ai_memory_store=store,
        )

        await service.sync_file_analysis_message(_file_message(text_status="failed", text=""))

        assert ("account:test1", "file_text_chunk", "file_text:session-1:m-file") in store.deleted_sources
        assert not [item for item in store.upserted_items if item.source_type == "file_text_chunk"]

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


def test_ai_memory_indexing_service_adds_session_participants_to_voice_memory() -> None:
    async def scenario() -> None:
        store = _FakeAIMemoryStore()
        vector_index = _FakeVectorIndex()
        session = _FakeSession(
            participant_ids=["user-test1", "user-test3"],
            extra={
                "current_user_id": "user-test1",
                "counterpart_id": "user-test3",
                "counterpart_name": "test3",
                "counterpart_username": "test3",
            },
        )
        service = AIMemoryIndexingService(
            db=_FakeDatabase(sessions={"session-1": session}),
            vector_index=vector_index,
            ai_memory_store=store,
        )

        await service.sync_voice_transcript_message(_voice_message(sender_id="user-test3", is_self=False))

        item = store.upserted_items[0]
        assert item.source_type == "voice_transcript"
        assert "user-test3" in item.metadata["participants"]
        assert "test3" in item.metadata["participants"]
        assert "user-test1" in item.metadata["participants"]
        assert "test3" in vector_index.calls[0]["participants"]

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


def test_ai_memory_indexing_service_backfills_ready_local_artifacts() -> None:
    async def scenario() -> None:
        store = _FakeAIMemoryStore()
        db = _FakeDatabase(
            ready_artifact_messages=[
                _file_message(),
                _voice_message(),
            ],
        )
        service = AIMemoryIndexingService(
            db=db,
            vector_index=_FakeVectorIndex(),
            ai_memory_store=store,
        )

        result = await service.sync_ready_local_artifact_messages(limit=20)

        assert db.ready_artifact_calls == [{"limit": 20}]
        assert result["processed"] == 2
        assert result["files"] == 1
        assert result["voices"] == 1
        source_types = [item.source_type for item in store.upserted_items]
        assert "file_summary" in source_types
        assert "file_text_chunk" in source_types
        assert "voice_transcript" in source_types

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

        assert ("account:test1", "file_summary", "file:session-1:m-file") in store.deleted_sources
        assert [item.source_type for item in store.upserted_items] == ["file_text_chunk"]

    asyncio.run(scenario())

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from client.core.file_text_extraction import (
    FILE_TEXT_EXTRACT_EXTRA_KEY,
    FileTextExtractionError,
    FileTextExtractionResult,
)
from client.core.voice_transcription import VOICE_TRANSCRIPT_EXTRA_KEY
from client.core.secure_storage import SecureStorage
from client.events.event_bus import EventBus
from client.managers.ai_task_manager import AITaskSnapshot, AITaskState
from client.managers.conversation_summary_manager import ConversationSummaryEvent, ConversationSummaryManager
from client.managers.message_manager import MessageEvent
from client.models.message import ChatMessage, MessageStatus, MessageType, Session
from client.services.ai_service import AIErrorCode
from client.storage.database import Database
from client.services.local_voice_transcription_service import (
    LocalVoiceTranscriptionResult,
    LocalVoiceTranscriptionRuntimeError,
)


@dataclass
class _FakeTaskManager:
    content: str = (
        "DISPLAY_SUMMARY: 本段聊天主要在确认见面安排，语气自然。\n"
        "TOPICS: 见面安排\n"
        "FACTS: 双方在确认见面时间\n"
        "DECISIONS: 暂定继续确认\n"
        "PENDING_ITEMS: 具体地点待确认\n"
        "TONE: 自然，推进中\n"
        "PARTICIPANTS: 我 | Bob\n"
        "KEYWORDS: 见面 | 时间 | 地点"
    )
    state: AITaskState = AITaskState.DONE
    error_code: AIErrorCode | None = None

    def __post_init__(self) -> None:
        self.requests = []

    async def run_once(self, request):
        self.requests.append(request)
        return AITaskSnapshot(
            task_id=request.task_id,
            session_id=request.session_id,
            task_type=getattr(request.task_type, "value", request.task_type),
            state=self.state,
            content=self.content if self.state == AITaskState.DONE else "",
            error_code=self.error_code,
            error_message=self.error_code.value if self.error_code is not None else "",
        )


def _structured_output(
    *,
    display_summary: str,
    topics: str = "见面安排",
    facts: str = "双方在确认见面时间",
    decisions: str = "暂定继续确认",
    pending_items: str = "具体地点待确认",
    tone: str = "自然，推进中",
    participants: str = "我 | Bob",
    keywords: str = "见面 | 时间 | 地点",
) -> str:
    return "\n".join(
        [
            f"DISPLAY_SUMMARY: {display_summary}",
            f"TOPICS: {topics}",
            f"FACTS: {facts}",
            f"DECISIONS: {decisions}",
            f"PENDING_ITEMS: {pending_items}",
            f"TONE: {tone}",
            f"PARTICIPANTS: {participants}",
            f"KEYWORDS: {keywords}",
        ]
    )


class _FakeDatabase:
    def __init__(self, session: Session) -> None:
        self.is_connected = True
        self._session = session
        self.messages_by_session: dict[str, list[ChatMessage]] = {session.session_id: []}
        self.buckets: dict[tuple[str, int], dict] = {}
        self.memory_items: dict[tuple[str, str, str], dict] = {}
        self.memory_embeddings: dict[tuple[str, str, str], dict] = {}
        self.memory_ann_buckets: dict[tuple[str, str, str], dict] = {}
        self.deleted_memory_sources: list[tuple[str, str, str]] = []
        self.app_state: dict[str, str] = {Database.AUTH_USER_ID_STATE_KEY: "test1"}

    async def get_session(self, session_id: str) -> Session | None:
        if session_id == self._session.session_id:
            return self._session
        return None

    async def get_open_conversation_summary_bucket(self, session_id: str) -> dict | None:
        candidates = [
            dict(bucket)
            for (bucket_session_id, _bucket_start_ts), bucket in self.buckets.items()
            if bucket_session_id == session_id and bool(bucket.get("is_open", False))
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: int(item.get("bucket_start_ts") or 0))

    async def get_conversation_summary_bucket(self, session_id: str, bucket_start_ts: int, *, bucket_rule_version: int = 1):
        bucket = self.buckets.get((session_id, int(bucket_start_ts)))
        if bucket is None or int(bucket.get("bucket_rule_version") or 1) != int(bucket_rule_version or 1):
            return None
        return dict(bucket)

    async def upsert_conversation_summary_bucket(self, payload: dict) -> None:
        key = (str(payload.get("session_id") or ""), int(payload.get("bucket_start_ts") or 0))
        self.buckets[key] = dict(payload)

    async def close_conversation_summary_bucket(self, session_id: str, bucket_start_ts: int, *, bucket_end_ts: float | None = None) -> None:
        key = (session_id, int(bucket_start_ts or 0))
        bucket = dict(self.buckets.get(key) or {})
        if not bucket:
            return
        bucket["is_open"] = False
        if bucket_end_ts is not None:
            bucket["bucket_end_ts"] = int(bucket_end_ts)
        self.buckets[key] = bucket

    async def list_conversation_summary_bucket_messages(
        self,
        session_id: str,
        bucket_start_ts: int,
        bucket_end_ts: int,
        *,
        limit: int = 24,
    ) -> list[ChatMessage]:
        messages = [
            message
            for message in self.messages_by_session.get(session_id, [])
            if bucket_start_ts <= int(message.timestamp.timestamp()) <= bucket_end_ts
        ]
        messages.sort(key=lambda item: item.timestamp)
        return messages[-max(1, int(limit or 1)) :]

    async def get_conversation_summary_bucket_message_stats(
        self,
        session_id: str,
        bucket_start_ts: int,
        bucket_end_ts: int | None = None,
    ) -> dict:
        messages = [
            message
            for message in self.messages_by_session.get(session_id, [])
            if message.message_type in {MessageType.TEXT, MessageType.VOICE, MessageType.FILE}
            and int(message.timestamp.timestamp()) >= int(bucket_start_ts or 0)
            and (bucket_end_ts is None or int(message.timestamp.timestamp()) <= int(bucket_end_ts or 0))
        ]
        messages.sort(key=lambda item: item.timestamp)
        latest = messages[-1] if messages else None
        return {
            "message_count": len(messages),
            "last_message_id": latest.message_id if latest is not None else "",
            "last_message_ts": int(latest.timestamp.timestamp()) if latest is not None else 0,
        }

    async def upsert_conversation_memory_item(self, payload: dict) -> None:
        key = (
            str(payload.get("session_id") or ""),
            str(payload.get("source_type") or ""),
            str(payload.get("source_id") or ""),
        )
        self.memory_items[key] = dict(payload)

    async def upsert_conversation_memory_embedding(self, payload: dict) -> str:
        key = (
            str(payload.get("session_id") or ""),
            str(payload.get("source_type") or ""),
            str(payload.get("source_id") or ""),
        )
        stored = dict(payload)
        stored["embedding_id"] = stored.get("embedding_id") or "|".join(key)
        self.memory_embeddings[key] = stored
        return str(stored["embedding_id"])

    async def delete_conversation_memory_embeddings_for_source(
        self,
        session_id: str,
        source_type: str,
        source_id: str = "",
    ) -> None:
        key = (str(session_id or ""), str(source_type or ""), str(source_id or ""))
        if source_id:
            self.memory_embeddings.pop(key, None)
            self.memory_ann_buckets.pop(key, None)
            return
        for existing_key in list(self.memory_embeddings):
            if existing_key[0] == key[0] and existing_key[1] == key[1]:
                self.memory_embeddings.pop(existing_key, None)
        for existing_key in list(self.memory_ann_buckets):
            if existing_key[0] == key[0] and existing_key[1] == key[1]:
                self.memory_ann_buckets.pop(existing_key, None)

    async def replace_conversation_memory_ann_buckets(
        self,
        *,
        embedding_id: str,
        session_id: str,
        source_type: str,
        source_id: str,
        ann_namespace: str,
        buckets,
        created_at: int | None = None,
        updated_at: int | None = None,
    ) -> None:
        del created_at
        key = (str(session_id or ""), str(source_type or ""), str(source_id or ""))
        self.memory_ann_buckets[key] = {
            "embedding_id": embedding_id,
            "ann_namespace": ann_namespace,
            "buckets": list(buckets),
            "updated_at": int(updated_at or 0),
        }

    async def delete_conversation_memory_items_for_source(self, session_id: str, source_type: str, source_id: str = "") -> None:
        key = (str(session_id or ""), str(source_type or ""), str(source_id or ""))
        self.deleted_memory_sources.append(key)
        if source_id:
            self.memory_items.pop(key, None)
            self.memory_embeddings.pop(key, None)
            self.memory_ann_buckets.pop(key, None)
            return
        for existing_key in list(self.memory_items):
            if existing_key[0] == key[0] and existing_key[1] == key[1]:
                self.memory_items.pop(existing_key, None)
        for existing_key in list(self.memory_embeddings):
            if existing_key[0] == key[0] and existing_key[1] == key[1]:
                self.memory_embeddings.pop(existing_key, None)
        for existing_key in list(self.memory_ann_buckets):
            if existing_key[0] == key[0] and existing_key[1] == key[1]:
                self.memory_ann_buckets.pop(existing_key, None)

    async def list_conversation_memory_items(
        self,
        *,
        session_id: str = "",
        source_type: str = "",
        start_ts: int | None = None,
        end_ts: int | None = None,
        limit: int = 12,
    ) -> list[dict]:
        items = []
        for item in self.memory_items.values():
            if session_id and str(item.get("session_id") or "") != session_id:
                continue
            if source_type and str(item.get("source_type") or "") != source_type:
                continue
            if start_ts is not None and int(item.get("end_ts") or 0) < int(start_ts or 0):
                continue
            if end_ts is not None and int(item.get("start_ts") or 0) > int(end_ts or 0):
                continue
            items.append(dict(item))
        items.sort(key=lambda item: (int(item.get("end_ts") or 0), int(item.get("start_ts") or 0)), reverse=True)
        return items[: max(1, int(limit or 1))]

    async def get_app_state(self, key: str):
        return self.app_state.get(str(key or ""))


class _FakeDenseVector:
    def __init__(self, values: list[float]) -> None:
        self.values = tuple(values)


class _FakeVectorIndex:
    model_id = "fake-embedding-model"

    async def encode_item(self, *, title: str, text: str, keywords=(), participants=()):
        tokens = self._tokens([title, text, *list(keywords or []), *list(participants or [])])
        return _FakeDenseVector(self._vector(tokens))

    @classmethod
    def item_content_hash(cls, *, title: str, text: str, keywords=(), participants=()) -> str:
        tokens = cls._tokens([title, text, *list(keywords or []), *list(participants or [])])
        return "|".join(sorted(tokens))

    @staticmethod
    def _tokens(values: list[str]) -> set[str]:
        joined = " ".join(str(value or "").strip().casefold() for value in values if str(value or "").strip())
        return {token for token in joined.replace("，", " ").replace("。", " ").replace("：", " ").split() if token}

    @staticmethod
    def _vector(tokens: set[str], dim: int = 16) -> list[float]:
        vector = [0.0] * dim
        for token in tokens:
            vector[sum(ord(ch) for ch in token) % dim] += 1.0
        return vector


class _FakeAnnIndex:
    namespace = "fake-ann:8x8"

    def buckets_for_vector(self, vector: _FakeDenseVector):
        bucket_value = int(sum(vector.values)) % 256
        return [type("Bucket", (), {"band_index": 0, "bucket_key": f"{bucket_value:02x}"})()]


class _FakeMessageManager:
    def __init__(self, fake_db: _FakeDatabase, *, local_paths: dict[str, str] | None = None, download_error: Exception | None = None) -> None:
        self._fake_db = fake_db
        self._local_paths = dict(local_paths or {})
        self._download_error = download_error
        self.download_attachment_calls: list[str] = []
        self.update_voice_transcript_calls: list[tuple[str, dict]] = []
        self.update_file_analysis_calls: list[tuple[str, dict | None, dict | None]] = []

    async def download_attachment(self, message_id: str) -> str:
        self.download_attachment_calls.append(message_id)
        if self._download_error is not None:
            raise self._download_error
        return self._local_paths.get(message_id, f"D:/voice/{message_id}.m4a")

    async def update_message_voice_transcript(self, message_id: str, transcript: dict) -> ChatMessage | None:
        payload = dict(transcript or {})
        self.update_voice_transcript_calls.append((message_id, payload))
        for messages in self._fake_db.messages_by_session.values():
            for message in messages:
                if message.message_id != message_id:
                    continue
                updated_extra = dict(message.extra or {})
                updated_extra[VOICE_TRANSCRIPT_EXTRA_KEY] = payload
                message.extra = updated_extra
                return message
        return None

    async def update_message_file_analysis(
        self,
        message_id: str,
        *,
        text_extract: dict | None = None,
        summary: dict | None = None,
    ) -> ChatMessage | None:
        text_payload = dict(text_extract or {}) if text_extract is not None else None
        summary_payload = dict(summary or {}) if summary is not None else None
        self.update_file_analysis_calls.append((message_id, text_payload, summary_payload))
        for messages in self._fake_db.messages_by_session.values():
            for message in messages:
                if message.message_id != message_id:
                    continue
                updated_extra = dict(message.extra or {})
                if text_payload is not None:
                    updated_extra[FILE_TEXT_EXTRACT_EXTRA_KEY] = text_payload
                if summary_payload is not None:
                    updated_extra["file_summary"] = summary_payload
                message.extra = updated_extra
                return message
        return None


class _FakeVoiceTranscriptionRuntime:
    def __init__(
        self,
        *,
        result: LocalVoiceTranscriptionResult | None = None,
        error: LocalVoiceTranscriptionRuntimeError | None = None,
    ) -> None:
        self._result = result or LocalVoiceTranscriptionResult(
            text="语音里说周日下午三点见。",
            language="zh",
            language_probability=0.92,
            duration_seconds=5,
            metadata={"engine": "faster-whisper", "model_id": "small"},
        )
        self._error = error
        self.calls: list[tuple[str, int | None]] = []

    async def transcribe(self, local_path: str, *, duration_seconds: int | None = None) -> LocalVoiceTranscriptionResult:
        self.calls.append((local_path, duration_seconds))
        if self._error is not None:
            raise self._error
        return self._result


class _FakeFileTextExtractor:
    def __init__(
        self,
        *,
        result: FileTextExtractionResult | None = None,
        error: FileTextExtractionError | None = None,
    ) -> None:
        self._result = result or FileTextExtractionResult(
            text="合同金额为 100 元，付款期限为周五。",
            file_name="report.pdf",
            file_ext=".pdf",
            size_bytes=123,
            truncated=False,
            metadata={"engine": "local_file_text"},
        )
        self._error = error
        self.calls: list[tuple[str, str]] = []

    async def extract(self, file_path: str, *, display_name: str = "", mime_type: str = "") -> FileTextExtractionResult:
        del mime_type
        self.calls.append((file_path, display_name))
        if self._error is not None:
            raise self._error
        return self._result


class _FakeAIMemoryStore:
    def __init__(self) -> None:
        self.upserted_items = []
        self.deleted_sources: list[tuple[str, str, str]] = []

    async def upsert_item(self, item) -> None:
        self.upserted_items.append(item)

    async def delete_source(self, *, owner_scope: str, source_type: str, source_id: str) -> None:
        self.deleted_sources.append((owner_scope, source_type, source_id))


def _make_manager(
    fake_db: _FakeDatabase,
    event_bus: EventBus,
    fake_task_manager: _FakeTaskManager,
    *,
    message_manager=None,
    voice_transcription_runtime=None,
    file_text_extractor=None,
    ai_memory_store=None,
) -> ConversationSummaryManager:
    return ConversationSummaryManager(
        db=fake_db,
        event_bus=event_bus,
        task_manager=fake_task_manager,
        vector_index=_FakeVectorIndex(),
        ann_index=_FakeAnnIndex(),
        message_manager=message_manager,
        voice_transcription_runtime=voice_transcription_runtime,
        file_text_extractor=file_text_extractor,
        ai_memory_store=ai_memory_store,
    )


def _message(
    message_id: str,
    when: datetime,
    *,
    content: str,
    is_self: bool = False,
    message_type: MessageType = MessageType.TEXT,
    extra: dict | None = None,
):
    return ChatMessage(
        message_id=message_id,
        session_id="session-1",
        sender_id="alice" if is_self else "bob",
        content=content,
        message_type=message_type,
        status=MessageStatus.SENT if is_self else MessageStatus.RECEIVED,
        timestamp=when,
        updated_at=when,
        is_self=is_self,
        extra=dict(extra or {}),
    )


async def _drain_summary_tasks(manager: ConversationSummaryManager) -> None:
    while manager._scheduled_refresh_tasks:
        tasks = list(manager._scheduled_refresh_tasks.values())
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)


def test_conversation_summary_manager_creates_ready_open_bucket(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()

    async def scenario() -> None:
        manager = _make_manager(fake_db, event_bus, fake_task_manager)
        manager.DEBOUNCE_SECONDS = 0.0
        await manager.initialize()
        try:
            incoming = _message("m-1", datetime(2026, 4, 19, 10, 0, 0), content="周日下午可以见面。")
            fake_db.messages_by_session["session-1"].append(incoming)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": incoming})
            await _drain_summary_tasks(manager)

            bucket = await fake_db.get_open_conversation_summary_bucket("session-1")
            assert bucket is not None
            assert bucket["summary_status"] == "ready"
            assert bucket["display_summary_ciphertext"].startswith("enc:")
            assert bucket["retrieval_summary_ciphertext"].startswith("enc:")
            assert bucket["summary_structured_json_ciphertext"].startswith("enc:")
            assert bucket["summary_schema_version"] == ConversationSummaryManager.SUMMARY_SCHEMA_VERSION
            assert bucket["message_count"] == 1
            assert fake_task_manager.requests
            assert "周日下午可以见面" in fake_task_manager.requests[0].messages[0]["content"]
            memory_key = ("session-1", "summary", f"summary:{int(incoming.timestamp.timestamp())}")
            assert memory_key in fake_db.memory_items
            assert "会话对象：" in fake_db.memory_items[memory_key]["text"]
            assert memory_key in fake_db.memory_embeddings
            assert fake_db.memory_embeddings[memory_key]["embedding_model"] == "fake-embedding-model"
            assert memory_key in fake_db.memory_ann_buckets
            assert fake_db.memory_ann_buckets[memory_key]["ann_namespace"] == "fake-ann:8x8"
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_dual_writes_summary_to_ai_memory_store(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()
    fake_ai_memory_store = _FakeAIMemoryStore()

    async def scenario() -> None:
        manager = _make_manager(
            fake_db,
            event_bus,
            fake_task_manager,
            ai_memory_store=fake_ai_memory_store,
        )
        manager.DEBOUNCE_SECONDS = 0.0
        await manager.initialize()
        try:
            incoming = _message("m-1", datetime(2026, 4, 19, 10, 0, 0), content="周日下午可以见面。")
            fake_db.messages_by_session["session-1"].append(incoming)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": incoming})
            await _drain_summary_tasks(manager)

            assert len(fake_ai_memory_store.upserted_items) == 1
            item = fake_ai_memory_store.upserted_items[0]
            assert item.owner_scope == "account:test1"
            assert item.source_type == ConversationSummaryManager.AI_MEMORY_SOURCE_TYPE_SUMMARY
            assert item.source_id == f"conversation:session-1:summary:{int(incoming.timestamp.timestamp())}"
            assert item.title.startswith("Bob")
            assert "会话对象：" in item.text
            assert "Bob" in item.text
            assert item.embedding_model_id == "fake-embedding-model"
            assert item.vector
            assert item.metadata["session_id"] == "session-1"
            assert item.metadata["bucket_start_ts"] == int(incoming.timestamp.timestamp())
            assert {"见面", "时间", "地点"}.issubset(set(item.metadata["keywords"]))
            assert item.metadata["participants"]
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_deletes_summary_from_ai_memory_store() -> None:
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()
    fake_ai_memory_store = _FakeAIMemoryStore()

    async def scenario() -> None:
        manager = _make_manager(
            fake_db,
            event_bus,
            fake_task_manager,
            ai_memory_store=fake_ai_memory_store,
        )

        await manager._delete_memory_item_for_bucket("session-1", 1776583200)

        assert ("session-1", "summary", "summary:1776583200") in fake_db.deleted_memory_sources
        assert fake_ai_memory_store.deleted_sources == [
            (
                "account:test1",
                ConversationSummaryManager.AI_MEMORY_SOURCE_TYPE_SUMMARY,
                "conversation:session-1:summary:1776583200",
            )
        ]

    asyncio.run(scenario())


def test_conversation_summary_manager_transcribes_voice_before_summary(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()
    fake_message_manager = _FakeMessageManager(fake_db, local_paths={"m-voice": "D:/voice/m-voice.m4a"})
    fake_voice_runtime = _FakeVoiceTranscriptionRuntime()

    async def scenario() -> None:
        manager = _make_manager(
            fake_db,
            event_bus,
            fake_task_manager,
            message_manager=fake_message_manager,
            voice_transcription_runtime=fake_voice_runtime,
        )
        manager.DEBOUNCE_SECONDS = 0.0
        await manager.initialize()
        try:
            incoming = _message(
                "m-voice",
                datetime(2026, 4, 19, 10, 0, 0),
                content="voice.m4a",
                message_type=MessageType.VOICE,
                extra={"duration": 5},
            )
            fake_db.messages_by_session["session-1"].append(incoming)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": incoming})
            await _drain_summary_tasks(manager)

            assert fake_message_manager.download_attachment_calls == ["m-voice"]
            assert fake_voice_runtime.calls == [("D:/voice/m-voice.m4a", 5)]
            assert fake_message_manager.update_voice_transcript_calls[0][0] == "m-voice"
            transcript_payload = fake_message_manager.update_voice_transcript_calls[0][1]
            assert transcript_payload["status"] == "ready"
            assert transcript_payload["text"] == "语音里说周日下午三点见。"
            assert incoming.extra[VOICE_TRANSCRIPT_EXTRA_KEY]["status"] == "ready"
            assert fake_task_manager.requests
            assert "语音里说周日下午三点见" in fake_task_manager.requests[0].messages[0]["content"]
            bucket = await fake_db.get_open_conversation_summary_bucket("session-1")
            assert bucket is not None
            assert bucket["summary_status"] == "ready"
            assert bucket["message_count"] == 1
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_reuses_existing_voice_transcript_without_asr(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()
    fake_message_manager = _FakeMessageManager(fake_db)
    fake_voice_runtime = _FakeVoiceTranscriptionRuntime()

    async def scenario() -> None:
        manager = _make_manager(
            fake_db,
            event_bus,
            fake_task_manager,
            message_manager=fake_message_manager,
            voice_transcription_runtime=fake_voice_runtime,
        )
        manager.DEBOUNCE_SECONDS = 0.0
        await manager.initialize()
        try:
            incoming = _message(
                "m-voice",
                datetime(2026, 4, 19, 10, 0, 0),
                content="voice.m4a",
                message_type=MessageType.VOICE,
                extra={
                    "duration": 5,
                    VOICE_TRANSCRIPT_EXTRA_KEY: {"status": "ready", "text": "已有转写内容。"},
                },
            )
            fake_db.messages_by_session["session-1"].append(incoming)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": incoming})
            await _drain_summary_tasks(manager)

            assert fake_message_manager.download_attachment_calls == []
            assert fake_message_manager.update_voice_transcript_calls == []
            assert fake_voice_runtime.calls == []
            assert fake_task_manager.requests
            assert "已有转写内容" in fake_task_manager.requests[0].messages[0]["content"]
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_marks_overlong_voice_without_asr(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()
    fake_message_manager = _FakeMessageManager(fake_db)
    fake_voice_runtime = _FakeVoiceTranscriptionRuntime()

    async def scenario() -> None:
        manager = _make_manager(
            fake_db,
            event_bus,
            fake_task_manager,
            message_manager=fake_message_manager,
            voice_transcription_runtime=fake_voice_runtime,
        )
        manager.DEBOUNCE_SECONDS = 0.0
        await manager.initialize()
        try:
            incoming = _message(
                "m-voice",
                datetime(2026, 4, 19, 10, 0, 0),
                content="voice.m4a",
                message_type=MessageType.VOICE,
                extra={"duration": 31},
            )
            fake_db.messages_by_session["session-1"].append(incoming)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": incoming})
            await _drain_summary_tasks(manager)

            assert fake_message_manager.download_attachment_calls == []
            assert fake_voice_runtime.calls == []
            assert fake_message_manager.update_voice_transcript_calls[0][0] == "m-voice"
            transcript_payload = fake_message_manager.update_voice_transcript_calls[0][1]
            assert transcript_payload["status"] == "skipped"
            assert transcript_payload["reason"] == "audio_too_long"
            assert fake_task_manager.requests
            prompt = fake_task_manager.requests[0].messages[0]["content"]
            assert "对方: [语音]" in prompt
            assert "语音转文字" not in prompt
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_continues_when_voice_model_missing(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()
    fake_message_manager = _FakeMessageManager(fake_db, local_paths={"m-voice": "D:/voice/m-voice.m4a"})
    fake_voice_runtime = _FakeVoiceTranscriptionRuntime(
        error=LocalVoiceTranscriptionRuntimeError("VOICE_TRANSCRIPT_MODEL_NOT_FOUND", "missing")
    )

    async def scenario() -> None:
        manager = _make_manager(
            fake_db,
            event_bus,
            fake_task_manager,
            message_manager=fake_message_manager,
            voice_transcription_runtime=fake_voice_runtime,
        )
        manager.DEBOUNCE_SECONDS = 0.0
        await manager.initialize()
        try:
            incoming = _message(
                "m-voice",
                datetime(2026, 4, 19, 10, 0, 0),
                content="voice.m4a",
                message_type=MessageType.VOICE,
                extra={"duration": 5},
            )
            fake_db.messages_by_session["session-1"].append(incoming)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": incoming})
            await _drain_summary_tasks(manager)

            assert fake_message_manager.download_attachment_calls == ["m-voice"]
            assert fake_voice_runtime.calls == [("D:/voice/m-voice.m4a", 5)]
            assert fake_message_manager.update_voice_transcript_calls[0][0] == "m-voice"
            transcript_payload = fake_message_manager.update_voice_transcript_calls[0][1]
            assert transcript_payload["status"] == "failed"
            assert transcript_payload["reason"] == "model_missing"
            assert fake_task_manager.requests
            prompt = fake_task_manager.requests[0].messages[0]["content"]
            assert "对方: [语音]" in prompt
            bucket = await fake_db.get_open_conversation_summary_bucket("session-1")
            assert bucket is not None
            assert bucket["summary_status"] == "ready"
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_extracts_file_text_before_summary(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()
    fake_message_manager = _FakeMessageManager(fake_db, local_paths={"m-file": "D:/files/report.pdf"})
    fake_file_extractor = _FakeFileTextExtractor()

    async def scenario() -> None:
        manager = _make_manager(
            fake_db,
            event_bus,
            fake_task_manager,
            message_manager=fake_message_manager,
            file_text_extractor=fake_file_extractor,
        )
        manager.DEBOUNCE_SECONDS = 0.0
        await manager.initialize()
        try:
            incoming = _message(
                "m-file",
                datetime(2026, 4, 19, 10, 0, 0),
                content="/uploads/report.pdf",
                message_type=MessageType.FILE,
                extra={"name": "report.pdf", "size": 123},
            )
            fake_db.messages_by_session["session-1"].append(incoming)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": incoming})
            await _drain_summary_tasks(manager)

            assert fake_message_manager.download_attachment_calls == ["m-file"]
            assert fake_file_extractor.calls == [("D:/files/report.pdf", "report.pdf")]
            assert fake_message_manager.update_file_analysis_calls[0][0] == "m-file"
            text_payload = fake_message_manager.update_file_analysis_calls[0][1]
            assert text_payload is not None
            assert text_payload["status"] == "ready"
            assert text_payload["text"] == "合同金额为 100 元，付款期限为周五。"
            assert fake_task_manager.requests
            assert "合同金额为 100 元" in fake_task_manager.requests[0].messages[0]["content"]
            bucket = await fake_db.get_open_conversation_summary_bucket("session-1")
            assert bucket is not None
            assert bucket["summary_status"] == "ready"
            assert bucket["message_count"] == 1
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_reuses_existing_file_text_extract_without_extracting(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()
    fake_message_manager = _FakeMessageManager(fake_db)
    fake_file_extractor = _FakeFileTextExtractor()

    async def scenario() -> None:
        manager = _make_manager(
            fake_db,
            event_bus,
            fake_task_manager,
            message_manager=fake_message_manager,
            file_text_extractor=fake_file_extractor,
        )
        manager.DEBOUNCE_SECONDS = 0.0
        await manager.initialize()
        try:
            incoming = _message(
                "m-file",
                datetime(2026, 4, 19, 10, 0, 0),
                content="/uploads/report.pdf",
                message_type=MessageType.FILE,
                extra={
                    "name": "report.pdf",
                    FILE_TEXT_EXTRACT_EXTRA_KEY: {"status": "ready", "text": "已有文件文字。"},
                },
            )
            fake_db.messages_by_session["session-1"].append(incoming)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": incoming})
            await _drain_summary_tasks(manager)

            assert fake_message_manager.download_attachment_calls == []
            assert fake_file_extractor.calls == []
            assert fake_message_manager.update_file_analysis_calls == []
            assert "已有文件文字" in fake_task_manager.requests[0].messages[0]["content"]
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_continues_when_file_extract_unsupported(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()
    fake_message_manager = _FakeMessageManager(fake_db, local_paths={"m-file": "D:/files/archive.zip"})
    fake_file_extractor = _FakeFileTextExtractor(
        error=FileTextExtractionError("FILE_TEXT_UNSUPPORTED_TYPE", "unsupported")
    )

    async def scenario() -> None:
        manager = _make_manager(
            fake_db,
            event_bus,
            fake_task_manager,
            message_manager=fake_message_manager,
            file_text_extractor=fake_file_extractor,
        )
        manager.DEBOUNCE_SECONDS = 0.0
        await manager.initialize()
        try:
            incoming = _message(
                "m-file",
                datetime(2026, 4, 19, 10, 0, 0),
                content="/uploads/archive.zip",
                message_type=MessageType.FILE,
                extra={"name": "archive.zip"},
            )
            fake_db.messages_by_session["session-1"].append(incoming)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": incoming})
            await _drain_summary_tasks(manager)

            text_payload = fake_message_manager.update_file_analysis_calls[0][1]
            assert text_payload is not None
            assert text_payload["status"] == "skipped"
            assert text_payload["reason"] == "unsupported_type"
            prompt = fake_task_manager.requests[0].messages[0]["content"]
            assert "对方: [文件: archive.zip]" in prompt
            bucket = await fake_db.get_open_conversation_summary_bucket("session-1")
            assert bucket is not None
            assert bucket["summary_status"] == "ready"
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_defers_refresh_by_debounce(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()

    async def scenario() -> None:
        manager = _make_manager(fake_db, event_bus, fake_task_manager)
        manager.DEBOUNCE_SECONDS = 0.05
        await manager.initialize()
        try:
            incoming = _message("m-1", datetime(2026, 4, 19, 10, 0, 0), content="刚刚发出的消息。")
            fake_db.messages_by_session["session-1"].append(incoming)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": incoming})
            await asyncio.sleep(0)

            bucket = await fake_db.get_open_conversation_summary_bucket("session-1")
            assert bucket is not None
            assert bucket["summary_status"] == "pending"
            assert fake_task_manager.requests == []
            assert fake_db.memory_items == {}

            await _drain_summary_tasks(manager)

            bucket = await fake_db.get_open_conversation_summary_bucket("session-1")
            assert bucket is not None
            assert bucket["summary_status"] == "ready"
            assert len(fake_task_manager.requests) == 1
            memory_key = ("session-1", "summary", f"summary:{int(incoming.timestamp.timestamp())}")
            assert memory_key in fake_db.memory_items
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_indexes_sender_username_for_memory_lookup(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="user-bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()

    async def scenario() -> None:
        manager = _make_manager(fake_db, event_bus, fake_task_manager)
        manager.DEBOUNCE_SECONDS = 0.0
        await manager.initialize()
        try:
            incoming = _message(
                "m-1",
                datetime(2026, 4, 19, 10, 0, 0),
                content="昨天那家店可以去。",
                extra={"sender_username": "test3"},
            )
            fake_db.messages_by_session["session-1"].append(incoming)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": incoming})
            await _drain_summary_tasks(manager)

            memory_key = ("session-1", "summary", f"summary:{int(incoming.timestamp.timestamp())}")
            participants = fake_db.memory_items[memory_key]["participants"]

            assert "test3" in participants
            assert "bob" in participants
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_reindexes_ready_bucket_without_model_when_memory_index_is_old(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    monkeypatch.setattr(SecureStorage, "decrypt_text", classmethod(lambda cls, value: str(value).removeprefix("enc:")))
    session = Session(session_id="session-1", name="user-bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()
    incoming = _message(
        "m-1",
        datetime(2026, 4, 19, 10, 0, 0),
        content="昨天那家店可以去。",
        extra={"sender_username": "test3"},
    )
    incoming_ts = int(incoming.timestamp.timestamp())
    fake_db.messages_by_session["session-1"].append(incoming)
    fake_db.buckets[("session-1", incoming_ts)] = {
        "session_id": "session-1",
        "bucket_start_ts": incoming_ts,
        "bucket_end_ts": incoming_ts,
        "bucket_rule_version": 1,
        "is_open": True,
        "last_message_id": "m-1",
        "last_message_ts": incoming_ts,
        "message_count": 1,
        "summary_status": "ready",
        "display_summary_ciphertext": "enc:旧摘要",
        "retrieval_summary_ciphertext": "enc:会话对象：我；Bob\n时间范围：2026-04-19 10:00-10:00\n主题：旧主题\n已确认：旧事实\n已决定：旧决定\n待跟进：旧待办\n整体语气：平稳",
        "summary_structured_json_ciphertext": 'enc:{"display_summary":"旧摘要","topics":["旧主题"],"facts":["旧事实"],"decisions":["旧决定"],"pending_items":["旧待办"],"tone":"平稳","participants":["user-bob","bob"],"keywords":["旧主题"]}',
        "summary_schema_version": ConversationSummaryManager.SUMMARY_SCHEMA_VERSION,
        "summary_version": 1,
    }
    memory_key = ("session-1", "summary", f"summary:{incoming_ts}")
    fake_db.memory_items[memory_key] = {
        "session_id": "session-1",
        "source_type": "summary",
        "source_id": f"summary:{incoming_ts}",
        "source_version": 1,
        "start_ts": incoming_ts,
        "end_ts": incoming_ts,
        "title": "旧标题",
        "text": "旧摘要",
        "keywords": [],
        "participants": ["user-bob", "bob"],
    }

    async def scenario() -> None:
        manager = _make_manager(fake_db, event_bus, fake_task_manager)

        scheduled = await manager.schedule_idle_refresh("session-1", reason="test")

        assert scheduled is True
        assert fake_task_manager.requests == []
        assert fake_db.memory_items[memory_key]["source_version"] == ConversationSummaryManager.MEMORY_INDEX_VERSION
        assert "test3" in fake_db.memory_items[memory_key]["participants"]

    asyncio.run(scenario())


def test_conversation_summary_manager_idle_refresh_skips_ready_bucket_without_changes(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()

    async def scenario() -> None:
        manager = _make_manager(fake_db, event_bus, fake_task_manager)
        incoming = _message("m-1", datetime(2026, 4, 19, 10, 0, 0), content="刚才确认了地点。")
        incoming_ts = int(incoming.timestamp.timestamp())
        fake_db.messages_by_session["session-1"].append(incoming)
        fake_db.buckets[("session-1", incoming_ts)] = {
            "session_id": "session-1",
            "bucket_start_ts": incoming_ts,
            "bucket_end_ts": incoming_ts,
            "bucket_rule_version": 1,
            "is_open": True,
            "last_message_id": "m-1",
            "last_message_ts": incoming_ts,
            "message_count": 1,
            "summary_status": "ready",
            "display_summary_ciphertext": "enc:已有摘要",
            "retrieval_summary_ciphertext": "enc:会话对象：Bob；bob\n时间范围：2026-04-19 10:00-10:00\n主题：已有摘要\n已确认：已有摘要\n已决定：无\n待跟进：无\n整体语气：平稳",
            "summary_structured_json_ciphertext": 'enc:{"display_summary":"已有摘要","topics":["已有摘要"],"facts":["已有摘要"],"decisions":[],"pending_items":[],"tone":"平稳","participants":["Bob","bob"],"keywords":["已有摘要"]}',
            "summary_schema_version": ConversationSummaryManager.SUMMARY_SCHEMA_VERSION,
            "summary_version": 1,
        }
        fake_db.memory_items[("session-1", "summary", f"summary:{incoming_ts}")] = {
            "session_id": "session-1",
            "source_type": "summary",
            "source_id": f"summary:{incoming_ts}",
            "source_version": ConversationSummaryManager.MEMORY_INDEX_VERSION,
            "start_ts": incoming_ts,
            "end_ts": incoming_ts,
            "title": "已有摘要",
            "text": "已有摘要",
            "keywords": [],
            "participants": ["Bob", "bob"],
        }

        scheduled = await manager.schedule_idle_refresh("session-1", reason="test")

        assert scheduled is False
        assert fake_task_manager.requests == []

    asyncio.run(scenario())


def test_conversation_summary_manager_idle_refresh_updates_ready_bucket_when_messages_changed(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()

    async def scenario() -> None:
        manager = _make_manager(fake_db, event_bus, fake_task_manager)
        first = _message("m-1", datetime(2026, 4, 19, 10, 0, 0), content="先确认地点。")
        second = _message("m-2", datetime(2026, 4, 19, 10, 1, 0), content="再确认时间。")
        first_ts = int(first.timestamp.timestamp())
        second_ts = int(second.timestamp.timestamp())
        fake_db.messages_by_session["session-1"].extend([first, second])
        fake_db.buckets[("session-1", first_ts)] = {
            "session_id": "session-1",
            "bucket_start_ts": first_ts,
            "bucket_end_ts": first_ts,
            "bucket_rule_version": 1,
            "is_open": True,
            "last_message_id": "m-1",
            "last_message_ts": first_ts,
            "message_count": 1,
            "summary_status": "ready",
            "display_summary_ciphertext": "enc:旧摘要",
            "retrieval_summary_ciphertext": "enc:会话对象：Bob\n时间范围：2026-04-19 10:00-10:00\n主题：旧主题\n已确认：旧事实\n已决定：旧决定\n待跟进：旧待办\n整体语气：平稳",
            "summary_structured_json_ciphertext": 'enc:{"display_summary":"旧摘要","topics":["旧主题"],"facts":["旧事实"],"decisions":["旧决定"],"pending_items":["旧待办"],"tone":"平稳","participants":["Bob"],"keywords":["旧主题"]}',
            "summary_schema_version": ConversationSummaryManager.SUMMARY_SCHEMA_VERSION,
            "summary_version": 1,
        }

        scheduled = await manager.schedule_idle_refresh("session-1", reason="test")
        await _drain_summary_tasks(manager)

        assert scheduled is True
        assert len(fake_task_manager.requests) == 1
        assert "再确认时间" in fake_task_manager.requests[0].messages[0]["content"]
        bucket = fake_db.buckets[("session-1", first_ts)]
        assert bucket["summary_status"] == "ready"
        assert bucket["last_message_id"] == "m-2"
        assert bucket["last_message_ts"] == second_ts
        assert bucket["message_count"] == 2
        memory_key = ("session-1", "summary", f"summary:{first_ts}")
        assert memory_key in fake_db.memory_items

    asyncio.run(scenario())


def test_conversation_summary_manager_emits_ready_event(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()
    ready_events: list[dict] = []

    async def _capture_ready(payload: dict) -> None:
        ready_events.append(dict(payload or {}))

    async def scenario() -> None:
        manager = _make_manager(fake_db, event_bus, fake_task_manager)
        manager.DEBOUNCE_SECONDS = 0.0
        await event_bus.subscribe(ConversationSummaryEvent.READY, _capture_ready)
        await manager.initialize()
        try:
            incoming = _message("m-1", datetime(2026, 4, 19, 10, 0, 0), content="周日下午可以见面。")
            fake_db.messages_by_session["session-1"].append(incoming)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": incoming})
            await _drain_summary_tasks(manager)

            assert ready_events == [
                {
                    "session_id": "session-1",
                    "bucket_start_ts": int(incoming.timestamp.timestamp()),
                    "bucket_end_ts": int(incoming.timestamp.timestamp()),
                    "is_open": True,
                    "message_count": 1,
                    "summary_status": "ready",
                }
            ]
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_closes_previous_bucket_on_time_break(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager()
    event_bus = EventBus()

    async def scenario() -> None:
        manager = _make_manager(fake_db, event_bus, fake_task_manager)
        manager.DEBOUNCE_SECONDS = 0.0
        await manager.initialize()
        try:
            first = _message("m-1", datetime(2026, 4, 19, 10, 0, 0), content="先约一下周末。")
            second = _message("m-2", datetime(2026, 4, 19, 10, 6, 0), content="我 14:30 以后有空。")
            fake_db.messages_by_session["session-1"].extend([first, second])

            await event_bus.emit(MessageEvent.RECEIVED, {"message": first})
            await _drain_summary_tasks(manager)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": second})
            await _drain_summary_tasks(manager)

            assert len(fake_db.buckets) == 2
            first_bucket = fake_db.buckets[("session-1", int(first.timestamp.timestamp()))]
            second_bucket = fake_db.buckets[("session-1", int(second.timestamp.timestamp()))]
            assert first_bucket["is_open"] is False
            assert second_bucket["is_open"] is True
            assert second_bucket["summary_status"] == "ready"
            assert len(fake_task_manager.requests) == 3
            assert fake_task_manager.requests[0].metadata["is_open_bucket"] is True
            assert "当前仍在继续的聊天时间段" in fake_task_manager.requests[0].messages[0]["content"]
            assert fake_task_manager.requests[1].metadata["is_open_bucket"] is False
            assert "稳定的最终总结" in fake_task_manager.requests[1].messages[0]["content"]
            assert "不要使用“当前”“正在”“还在继续”等进行时措辞" in fake_task_manager.requests[1].messages[0]["content"]
            assert fake_task_manager.requests[2].metadata["is_open_bucket"] is True
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_marks_bucket_failed_when_ai_fails(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    fake_task_manager = _FakeTaskManager(state=AITaskState.FAILED, error_code=AIErrorCode.AI_MODEL_UNAVAILABLE)
    event_bus = EventBus()

    async def scenario() -> None:
        manager = _make_manager(fake_db, event_bus, fake_task_manager)
        manager.DEBOUNCE_SECONDS = 0.0
        await manager.initialize()
        try:
            incoming = _message("m-1", datetime(2026, 4, 19, 10, 0, 0), content="你几点方便？")
            fake_db.messages_by_session["session-1"].append(incoming)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": incoming})
            await _drain_summary_tasks(manager)

            bucket = await fake_db.get_open_conversation_summary_bucket("session-1")
            assert bucket is not None
            assert bucket["summary_status"] == "failed"
            assert bucket["error_code"] == AIErrorCode.AI_MODEL_UNAVAILABLE.value
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_reschedules_cancelled_summary(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    event_bus = EventBus()

    class _CancelThenSucceedTaskManager:
        def __init__(self) -> None:
            self.requests = []

        async def run_once(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                return AITaskSnapshot(
                    task_id=request.task_id,
                    session_id=request.session_id,
                    task_type=getattr(request.task_type, "value", request.task_type),
                    state=AITaskState.CANCELLED,
                    finish_reason=AIErrorCode.AI_USER_CANCELLED.value,
                )
            return AITaskSnapshot(
                task_id=request.task_id,
                session_id=request.session_id,
                task_type=getattr(request.task_type, "value", request.task_type),
                state=AITaskState.DONE,
                content=_structured_output(display_summary="本段聊天主要在确认晚饭细节。"),
            )

    fake_task_manager = _CancelThenSucceedTaskManager()

    async def scenario() -> None:
        manager = _make_manager(fake_db, event_bus, fake_task_manager)
        manager.DEBOUNCE_SECONDS = 0.0
        await manager.initialize()
        try:
            incoming = _message("m-1", datetime(2026, 4, 19, 10, 0, 0), content="晚饭吃什么？")
            fake_db.messages_by_session["session-1"].append(incoming)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": incoming})
            await _drain_summary_tasks(manager)

            bucket = await fake_db.get_open_conversation_summary_bucket("session-1")
            assert bucket is not None
            assert bucket["summary_status"] == "ready"
            assert bucket["display_summary_ciphertext"] == "enc:本段聊天主要在确认晚饭细节。"
            assert len(fake_task_manager.requests) == 2
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_reschedules_running_bucket_without_cancelling_it(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    event_bus = EventBus()

    class _BlockingTaskManager:
        def __init__(self) -> None:
            self.requests = []
            self.started = asyncio.Event()
            self.allow_finish = asyncio.Event()
            self.cancelled_runs = 0

        async def run_once(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                self.started.set()
                try:
                    await self.allow_finish.wait()
                except asyncio.CancelledError:
                    self.cancelled_runs += 1
                    raise
            return AITaskSnapshot(
                task_id=request.task_id,
                session_id=request.session_id,
                task_type=getattr(request.task_type, "value", request.task_type),
                state=AITaskState.DONE,
                content=_structured_output(display_summary="本段聊天主要在确认细节安排。"),
            )

    fake_task_manager = _BlockingTaskManager()

    async def scenario() -> None:
        manager = _make_manager(fake_db, event_bus, fake_task_manager)
        manager.DEBOUNCE_SECONDS = 0.0
        await manager.initialize()
        try:
            first = _message("m-1", datetime(2026, 4, 19, 10, 0, 0), content="明天去饭店吃饭吧。")
            second = _message("m-2", datetime(2026, 4, 19, 10, 1, 0), content="那吃什么菜？")
            fake_db.messages_by_session["session-1"].append(first)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": first})
            await asyncio.wait_for(fake_task_manager.started.wait(), timeout=1)

            fake_db.messages_by_session["session-1"].append(second)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": second})
            await asyncio.sleep(0)

            assert fake_task_manager.cancelled_runs == 0
            assert len(fake_task_manager.requests) == 1

            fake_task_manager.allow_finish.set()
            await _drain_summary_tasks(manager)

            assert fake_task_manager.cancelled_runs == 0
            assert len(fake_task_manager.requests) == 2
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_conversation_summary_manager_skips_closed_task_manager(monkeypatch) -> None:
    monkeypatch.setattr(SecureStorage, "encrypt_text", classmethod(lambda cls, value: f"enc:{value}"))
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    fake_db = _FakeDatabase(session)
    event_bus = EventBus()

    class _ClosedTaskManager:
        def __init__(self) -> None:
            self._closed = True
            self.requests = []

        async def run_once(self, request):
            self.requests.append(request)
            raise RuntimeError("AI task manager is closed")

    fake_task_manager = _ClosedTaskManager()

    async def scenario() -> None:
        manager = _make_manager(fake_db, event_bus, fake_task_manager)
        manager.DEBOUNCE_SECONDS = 0.0
        await manager.initialize()
        try:
            incoming = _message("m-1", datetime(2026, 4, 19, 10, 0, 0), content="晚点再确认地点。")
            fake_db.messages_by_session["session-1"].append(incoming)
            await event_bus.emit(MessageEvent.RECEIVED, {"message": incoming})
            await _drain_summary_tasks(manager)

            bucket = await fake_db.get_open_conversation_summary_bucket("session-1")
            assert bucket is not None
            assert bucket["summary_status"] == "pending"
            assert bucket["display_summary_ciphertext"] == ""
            assert fake_task_manager.requests == []
        finally:
            await manager.close()

    asyncio.run(scenario())

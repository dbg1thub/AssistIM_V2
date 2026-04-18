import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from client.core.secure_storage import SecureStorage
from client.events.event_bus import EventBus
from client.managers.ai_task_manager import AITaskSnapshot, AITaskState
from client.managers.conversation_summary_manager import ConversationSummaryEvent, ConversationSummaryManager
from client.managers.message_manager import MessageEvent
from client.models.message import ChatMessage, MessageStatus, MessageType, Session
from client.services.ai_service import AIErrorCode


@dataclass
class _FakeTaskManager:
    content: str = "本段聊天主要在确认见面安排，语气自然。"
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


class _FakeDatabase:
    def __init__(self, session: Session) -> None:
        self.is_connected = True
        self._session = session
        self.messages_by_session: dict[str, list[ChatMessage]] = {session.session_id: []}
        self.buckets: dict[tuple[str, int], dict] = {}

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


def _message(message_id: str, when: datetime, *, content: str, is_self: bool = False, message_type: MessageType = MessageType.TEXT):
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
        manager = ConversationSummaryManager(
            db=fake_db,
            event_bus=event_bus,
            task_manager=fake_task_manager,
        )
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
            assert bucket["summary_text_ciphertext"].startswith("enc:")
            assert bucket["message_count"] == 1
            assert fake_task_manager.requests
            assert "周日下午可以见面" in fake_task_manager.requests[0].messages[0]["content"]
        finally:
            await manager.close()

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
        manager = ConversationSummaryManager(
            db=fake_db,
            event_bus=event_bus,
            task_manager=fake_task_manager,
        )
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
        manager = ConversationSummaryManager(
            db=fake_db,
            event_bus=event_bus,
            task_manager=fake_task_manager,
        )
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
            assert "不要使用“当前”“正在”“还在继续”等时间敏感措辞" in fake_task_manager.requests[1].messages[0]["content"]
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
        manager = ConversationSummaryManager(
            db=fake_db,
            event_bus=event_bus,
            task_manager=fake_task_manager,
        )
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

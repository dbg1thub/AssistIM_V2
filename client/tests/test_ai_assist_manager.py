from __future__ import annotations

import asyncio
import sys
import types

if "aiohttp" not in sys.modules:
    aiohttp = types.ModuleType("aiohttp")

    class _DummyClientError(Exception):
        pass

    class _DummyClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class _DummyFormData:
        def __init__(self):
            self.fields = []

        def add_field(self, name, value, **kwargs):
            self.fields.append({"name": name, "value": value, **kwargs})

    class _DummyClientSession:
        def __init__(self, *args, **kwargs):
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class _DummyClientResponse:
        status = 200

    aiohttp.ClientError = _DummyClientError
    aiohttp.FormData = _DummyFormData
    aiohttp.ClientTimeout = _DummyClientTimeout
    aiohttp.ClientSession = _DummyClientSession
    aiohttp.ClientResponse = _DummyClientResponse
    sys.modules["aiohttp"] = aiohttp

from client.managers.ai_assist_manager import AIAssistManager, AIReplySuggestionStatus
from client.managers.ai_prompt_builder import AIAssistAction
from client.managers.ai_task_manager import AITaskSnapshot, AITaskState
from client.core.secure_storage import SecureStorage
from client.models.message import ChatMessage, MessageStatus, MessageType, Session
from client.services.ai_service import AIErrorCode, AIPrivacyScope, AITaskType


class FakeTaskManager:
    def __init__(self, content: str = "好的，我来推进。\n可以，我现在处理。\n这边先不方便。\n我晚些再回复。") -> None:
        self.content = content
        self.requests = []
        self.state = AITaskState.DONE
        self.error_code = None

    async def run_once(self, request):
        self.requests.append(request)
        return AITaskSnapshot(
            task_id=request.task_id,
            session_id=request.session_id,
            task_type=request.task_type.value,
            state=self.state,
            content=self.content if self.state == AITaskState.DONE else "",
            error_code=self.error_code,
            finish_reason="stop",
        )


class FakeSummaryDatabase:
    def __init__(self, *, open_bucket: dict | None = None, closed_buckets: list[dict] | None = None) -> None:
        self.is_connected = True
        self.open_bucket = dict(open_bucket or {}) if open_bucket is not None else None
        self.closed_buckets = [dict(item) for item in list(closed_buckets or [])]

    async def get_open_conversation_summary_bucket(self, session_id: str):
        return dict(self.open_bucket) if self.open_bucket is not None else None

    async def list_recent_conversation_summary_buckets(
        self,
        session_id: str,
        *,
        limit: int = 3,
        is_open: bool | None = None,
        ready_only: bool = False,
    ):
        buckets = list(self.closed_buckets)
        if is_open is True:
            buckets = [dict(self.open_bucket)] if self.open_bucket is not None else []
        elif is_open is False:
            buckets = list(self.closed_buckets)
        if ready_only:
            buckets = [item for item in buckets if str(item.get("summary_status") or "") == "ready"]
        return [dict(item) for item in buckets[:limit]]


def _session(**kwargs) -> Session:
    data = {
        "session_id": "s1",
        "name": "Alice",
        "session_type": "direct",
    }
    data.update(kwargs)
    return Session(**data)


def _peer_message(message_id: str = "m1", content: str = "你看下这个？") -> ChatMessage:
    return ChatMessage(
        message_id=message_id,
        session_id="s1",
        sender_id="peer",
        content=content,
        status=MessageStatus.RECEIVED,
    )


def test_assist_draft_uses_task_manager_and_returns_text() -> None:
    async def scenario() -> None:
        fake = FakeTaskManager(content="润色后的文本")
        manager = AIAssistManager(task_manager=fake)

        result = await manager.assist_draft(AIAssistAction.POLISH, "帮我看下", session=_session())

        assert result.state == AITaskState.DONE
        assert result.text == "润色后的文本"
        assert fake.requests[0].task_type == AITaskType.INPUT_POLISH
        assert fake.requests[0].privacy_scope == AIPrivacyScope.DIRECT_CONTEXT

    asyncio.run(scenario())


def test_suggest_replies_generates_ready_state_without_persistence() -> None:
    async def scenario() -> None:
        fake = FakeTaskManager(
            content="1. 好的，我看一下。\n2. 明白，我现在处理。\n3. 这边先不方便。\n4. 我晚点再回复。"
        )
        manager = AIAssistManager(task_manager=fake)
        session = _session()

        state = await manager.suggest_replies(session, [_peer_message()], current_user_id="me")

        assert state.status == AIReplySuggestionStatus.READY
        assert [item.text for item in state.items] == [
            "好的，我看一下。",
            "明白，我现在处理。",
            "这边先不方便。",
            "我晚点再回复。",
        ]
        assert state.anchor_message_id == "m1"
        assert manager.get_suggestions("s1") is not state
        assert fake.requests[0].task_type == AITaskType.REPLY_SUGGESTION

    asyncio.run(scenario())


def test_suggest_replies_includes_local_bucket_summaries_when_available(monkeypatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(
            SecureStorage,
            "decrypt_text",
            classmethod(lambda cls, value: {"enc:open": "当前主要在确认周日下午见面。", "enc:closed": "之前已经确认了见面地点。"}[value]),
        )
        fake = FakeTaskManager(
            content="好的，我看一下。\n明白，我现在处理。\n这边先不方便。\n我晚点再回复。"
        )
        db = FakeSummaryDatabase(
            open_bucket={
                "session_id": "s1",
                "bucket_start_ts": 1,
                "summary_status": "ready",
                "summary_text_ciphertext": "enc:open",
            },
            closed_buckets=[
                {
                    "session_id": "s1",
                    "bucket_start_ts": 0,
                    "summary_status": "ready",
                    "summary_text_ciphertext": "enc:closed",
                }
            ],
        )
        manager = AIAssistManager(task_manager=fake, db=db)

        state = await manager.suggest_replies(_session(), [_peer_message()], current_user_id="me")

        assert state.status == AIReplySuggestionStatus.READY
        prompt = fake.requests[0].messages[0]["content"]
        assert "当前时间段摘要：" in prompt
        assert "最近历史摘要：" in prompt
        assert "当前主要在确认周日下午见面。" in prompt
        assert "之前已经确认了见面地点。" in prompt
    asyncio.run(scenario())


def test_suggest_replies_skips_bucket_summary_when_decrypt_fails(monkeypatch) -> None:
    async def scenario() -> None:
        def _decrypt(_cls, value: str) -> str:
            if value == "enc:bad":
                raise RuntimeError("bad ciphertext")
            return "之前已经确认了见面地点。"

        monkeypatch.setattr(SecureStorage, "decrypt_text", classmethod(_decrypt))
        fake = FakeTaskManager(
            content="好的，我看一下。\n明白，我现在处理。\n这边先不方便。\n我晚点再回复。"
        )
        db = FakeSummaryDatabase(
            open_bucket={
                "session_id": "s1",
                "bucket_start_ts": 1,
                "summary_status": "ready",
                "summary_text_ciphertext": "enc:bad",
            },
            closed_buckets=[
                {
                    "session_id": "s1",
                    "bucket_start_ts": 0,
                    "summary_status": "ready",
                    "summary_text_ciphertext": "enc:closed",
                }
            ],
        )
        manager = AIAssistManager(task_manager=fake, db=db)

        state = await manager.suggest_replies(_session(), [_peer_message()], current_user_id="me")

        assert state.status == AIReplySuggestionStatus.READY
        prompt = fake.requests[0].messages[0]["content"]
        assert "当前时间段摘要：" not in prompt
        assert "最近历史摘要：" in prompt
        assert "之前已经确认了见面地点。" in prompt

    asyncio.run(scenario())


def test_suggest_replies_for_e2ee_requires_local_provider() -> None:
    async def scenario() -> None:
        fake = FakeTaskManager()
        manager = AIAssistManager(task_manager=fake)
        session = _session(extra={"encryption_mode": "e2ee_private"})

        state = await manager.suggest_replies(session, [_peer_message()])

        assert state.status == AIReplySuggestionStatus.READY
        assert fake.requests[0].must_be_local is True
        assert fake.requests[0].privacy_scope == AIPrivacyScope.E2EE_PLAINTEXT

    asyncio.run(scenario())


def test_suggest_replies_skips_group_ai_and_self_latest_contexts() -> None:
    manager = AIAssistManager(task_manager=FakeTaskManager())
    group = _session(session_type="group")
    ai_session = _session(session_type="ai", is_ai_session=True)
    self_message = ChatMessage("m-self", "s1", "me", "我来处理", is_self=True)

    assert manager.can_suggest_replies(group, [_peer_message()]) == (False, "unsupported_session_type")
    assert manager.can_suggest_replies(ai_session, [_peer_message()]) == (False, "ai_session")
    assert manager.can_suggest_replies(_session(), [self_message], current_user_id="me") == (
        False,
        "no_peer_text_message",
    )


def test_suggest_replies_ignores_non_text_and_invalid_peer_messages() -> None:
    manager = AIAssistManager(task_manager=FakeTaskManager())
    failed = _peer_message("m-failed")
    failed.status = MessageStatus.FAILED
    image = ChatMessage(
        "m-image",
        "s1",
        "peer",
        "image",
        message_type=MessageType.IMAGE,
        status=MessageStatus.RECEIVED,
    )

    assert manager.can_suggest_replies(_session(), [image, failed]) == (
        False,
        "no_peer_text_message",
    )


def test_suggest_replies_reuses_same_anchor_until_invalidated() -> None:
    async def scenario() -> None:
        fake = FakeTaskManager()
        manager = AIAssistManager(task_manager=fake)
        session = _session()
        anchor = _peer_message("m-anchor")

        first = await manager.suggest_replies(session, [anchor])
        second = await manager.suggest_replies(session, [anchor])

        assert first.status == AIReplySuggestionStatus.READY
        assert second.anchor_message_id == "m-anchor"
        assert len(fake.requests) == 1

        manager.invalidate_for_sent_message("s1")
        assert manager.get_suggestions("s1") is None

    asyncio.run(scenario())


def test_invalidate_for_new_message_clears_stale_candidates() -> None:
    async def scenario() -> None:
        fake = FakeTaskManager()
        manager = AIAssistManager(task_manager=fake)
        session = _session()

        await manager.suggest_replies(session, [_peer_message("m1")])
        manager.invalidate_for_new_message("s1", _peer_message("m2"))

        assert manager.get_suggestions("s1") is None

    asyncio.run(scenario())


def test_invalid_reply_output_marks_failed() -> None:
    async def scenario() -> None:
        fake = FakeTaskManager(content="")
        manager = AIAssistManager(task_manager=fake)

        state = await manager.suggest_replies(_session(), [_peer_message()])

        assert state.status == AIReplySuggestionStatus.FAILED
        assert state.error_code == AIErrorCode.AI_OUTPUT_INVALID

    asyncio.run(scenario())

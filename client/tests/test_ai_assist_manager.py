from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime

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
from client.managers.conversation_memory_manager import ConversationMemoryContext
from client.core.file_text_extraction import FILE_TEXT_EXTRACT_EXTRA_KEY
from client.core.image_summary import IMAGE_SUMMARY_EXTRA_KEY
from client.core.voice_transcription import VOICE_TRANSCRIPT_EXTRA_KEY
from client.core.secure_storage import SecureStorage
from client.models.message import ChatMessage, MessageStatus, MessageType, Session
from client.services.ai_service import AIErrorCode, AIPrivacyScope, AITaskType


class FakeTaskManager:
    def __init__(
        self,
        content: str | list[str] = "好的，我来推进。\n可以，我现在处理。\n这边先不方便。\n我晚些再回复。",
    ) -> None:
        if isinstance(content, list):
            self.contents = list(content)
        else:
            self.contents = [content]
        self.requests = []
        self.state = AITaskState.DONE
        self.error_code = None

    async def run_once(self, request):
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.contents) - 1)
        return AITaskSnapshot(
            task_id=request.task_id,
            session_id=request.session_id,
            task_type=request.task_type.value,
            state=self.state,
            content=self.contents[index] if self.state == AITaskState.DONE else "",
            error_code=self.error_code,
            finish_reason="stop",
        )


class FakeSummaryDatabase:
    def __init__(
        self,
        *,
        open_bucket: dict | None = None,
        closed_buckets: list[dict] | None = None,
        historical_messages: list[ChatMessage] | None = None,
    ) -> None:
        self.is_connected = True
        self.open_bucket = dict(open_bucket or {}) if open_bucket is not None else None
        self.closed_buckets = [dict(item) for item in list(closed_buckets or [])]
        self.historical_messages = list(historical_messages or [])
        self.get_messages_calls: list[dict] = []

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

    async def get_messages(self, session_id: str, limit: int = 50, before_timestamp: float | None = None):
        self.get_messages_calls.append(
            {
                "session_id": session_id,
                "limit": limit,
                "before_timestamp": before_timestamp,
            }
        )
        messages = list(self.historical_messages)
        if before_timestamp is not None:
            messages = [
                message
                for message in messages
                if message.timestamp is not None and message.timestamp.timestamp() < before_timestamp
            ]
        return messages[-limit:]


class FakeReplyMemoryManager:
    def __init__(self, lines: tuple[str, ...]) -> None:
        self.lines = tuple(lines)
        self.calls: list[dict] = []

    async def build_reply_suggestion_rag_context(
        self,
        session_id: str,
        query_text: str,
        *,
        max_end_ts: int | None = None,
        min_start_ts: int | None = None,
        result_limit: int = 3,
        candidate_limit: int = 80,
    ) -> ConversationMemoryContext:
        self.calls.append(
            {
                "session_id": session_id,
                "query_text": query_text,
                "max_end_ts": max_end_ts,
                "min_start_ts": min_start_ts,
                "result_limit": result_limit,
                "candidate_limit": candidate_limit,
            }
        )
        return ConversationMemoryContext(lines=self.lines, query_kind="reply_suggestion_rag")


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


def _peer_voice_message(
    message_id: str = "voice-1",
    *,
    transcript_text: str = "你帮我看一下这个时间行不行？",
    transcript_status: str = "ready",
) -> ChatMessage:
    return ChatMessage(
        message_id=message_id,
        session_id="s1",
        sender_id="peer",
        content="[voice]",
        message_type=MessageType.VOICE,
        status=MessageStatus.RECEIVED,
        extra={
            VOICE_TRANSCRIPT_EXTRA_KEY: {
                "status": transcript_status,
                "text": transcript_text,
            }
        },
    )


def _peer_file_message(
    message_id: str = "file-1",
    *,
    extract_text: str = "合同金额为 100 元，付款期限为周五。",
    extract_status: str = "ready",
) -> ChatMessage:
    return ChatMessage(
        message_id=message_id,
        session_id="s1",
        sender_id="peer",
        content="/uploads/report.pdf",
        message_type=MessageType.FILE,
        status=MessageStatus.RECEIVED,
        extra={
            "name": "report.pdf",
            FILE_TEXT_EXTRACT_EXTRA_KEY: {
                "status": extract_status,
                "text": extract_text,
            },
        },
    )


def _peer_image_message(
    message_id: str = "image-1",
    *,
    summary_text: str = "图片里是一张会议白板，写着周五前确认预算。",
    summary_status: str = "ready",
) -> ChatMessage:
    return ChatMessage(
        message_id=message_id,
        session_id="s1",
        sender_id="peer",
        content="/uploads/whiteboard.png",
        message_type=MessageType.IMAGE,
        status=MessageStatus.RECEIVED,
        extra={
            IMAGE_SUMMARY_EXTRA_KEY: {
                "status": summary_status,
                "text": summary_text,
            },
        },
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


def test_translate_message_runs_local_translation_request() -> None:
    async def scenario() -> None:
        fake = FakeTaskManager(content="明天一起吃饭吗？")
        manager = AIAssistManager(task_manager=fake)

        result = await manager.translate_message(
            "Would you like dinner tomorrow?",
            session=_session(),
            message_id="m1",
            target_language_code="zh-CN",
            mode="manual",
        )

        assert result.state == AITaskState.DONE
        assert result.action == AIAssistAction.TRANSLATE
        assert result.text == "明天一起吃饭吗？"
        assert fake.requests[0].task_type == AITaskType.TRANSLATE
        assert fake.requests[0].must_be_local is True
        assert fake.requests[0].metadata["mode"] == "manual"
        assert fake.requests[0].metadata["message_id"] == "m1"

    asyncio.run(scenario())


def test_suggest_replies_generates_ready_state_without_persistence() -> None:
    async def scenario() -> None:
        fake = FakeTaskManager(
            content="好的，我看一下。\n明白，我现在处理。\n这边先不方便。\n我晚点再回复。"
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
        assert len(fake.requests) == 1
        assert fake.requests[0].task_type == AITaskType.REPLY_SUGGESTION
        assert fake.requests[0].metadata["reply_prompt_mode"] == "standard"
        assert fake.requests[0].seed is None
        assert fake.requests[0].response_format is None
        assert fake.requests[0].system_prompt is not None

    asyncio.run(scenario())


def test_suggest_replies_includes_local_bucket_summaries_when_available(monkeypatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr("client.managers.ai_assist_manager.time.time", lambda: 1000)
        monkeypatch.setattr(
            SecureStorage,
            "decrypt_text",
            classmethod(lambda cls, value: {"enc:closed": "之前已经确认了见面地点。"}[value]),
        )
        fake = FakeTaskManager(
            content="好的，我看一下。\n明白，我现在处理。\n这边先不方便。\n我晚点再回复。"
        )
        db = FakeSummaryDatabase(
            open_bucket={
                "session_id": "s1",
                "bucket_start_ts": 1,
                "bucket_end_ts": 1000,
                "summary_status": "ready",
                "display_summary_ciphertext": "enc:closed",
            },
            closed_buckets=[
                {
                    "session_id": "s1",
                    "bucket_start_ts": 0,
                    "bucket_end_ts": 600,
                    "summary_status": "ready",
                    "display_summary_ciphertext": "enc:closed",
                }
            ],
        )
        manager = AIAssistManager(task_manager=fake, db=db)

        state = await manager.suggest_replies(_session(), [_peer_message()], current_user_id="me")

        assert state.status == AIReplySuggestionStatus.READY
        prompt = fake.requests[0].messages[0]["content"]
        assert "当前待回复消息组：" in prompt
        assert "背景摘要（仅供参考，用来避免前后矛盾；不要优先复述已经确认过的话题）：" in prompt
        assert "当前时间段摘要：" in prompt
        assert "一周历史摘要：" in prompt
        assert "之前已经确认了见面地点。" in prompt
        assert fake.requests[0].metadata["has_open_bucket_summary"] is True
        assert fake.requests[0].metadata["has_weekly_history_summary"] is True
        assert "你是 AssistIM 的私聊回复建议助手。" in fake.requests[0].system_prompt
    asyncio.run(scenario())


def test_suggest_replies_skips_bucket_summary_when_decrypt_fails(monkeypatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr("client.managers.ai_assist_manager.time.time", lambda: 1000)
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
                "bucket_end_ts": 1000,
                "summary_status": "ready",
                "display_summary_ciphertext": "enc:bad",
            },
            closed_buckets=[
                {
                    "session_id": "s1",
                    "bucket_start_ts": 0,
                    "bucket_end_ts": 600,
                    "summary_status": "ready",
                    "display_summary_ciphertext": "enc:closed",
                }
            ],
        )
        manager = AIAssistManager(task_manager=fake, db=db)

        state = await manager.suggest_replies(_session(), [_peer_message()], current_user_id="me")

        assert state.status == AIReplySuggestionStatus.READY
        prompt = fake.requests[0].messages[0]["content"]
        assert "背景摘要（仅供参考，用来避免前后矛盾；不要优先复述已经确认过的话题）：" in prompt
        assert "一周历史摘要：" in prompt
        assert "之前已经确认了见面地点。" in prompt

    asyncio.run(scenario())


def test_suggest_replies_ignores_recent_closed_bucket_summaries(monkeypatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr("client.managers.ai_assist_manager.time.time", lambda: 1000)
        monkeypatch.setattr(
            SecureStorage,
            "decrypt_text",
            classmethod(lambda cls, value: {"enc:recent": "最近五分钟内的摘要。", "enc:old": "五分钟前的历史摘要。"}[value]),
        )
        fake = FakeTaskManager(
            content="好的，我看一下。\n明白，我现在处理。\n这边先不方便。\n我晚点再回复。"
        )
        db = FakeSummaryDatabase(
            closed_buckets=[
                {
                    "session_id": "s1",
                    "bucket_start_ts": 650,
                    "bucket_end_ts": 760,
                    "summary_status": "ready",
                    "display_summary_ciphertext": "enc:recent",
                },
                {
                    "session_id": "s1",
                    "bucket_start_ts": 0,
                    "bucket_end_ts": 600,
                    "summary_status": "ready",
                    "display_summary_ciphertext": "enc:old",
                },
            ]
        )
        manager = AIAssistManager(task_manager=fake, db=db)

        state = await manager.suggest_replies(_session(), [_peer_message()], current_user_id="me")

        assert state.status == AIReplySuggestionStatus.READY
        prompt = fake.requests[0].messages[0]["content"]
        assert "最近五分钟内的摘要。" not in prompt
        assert "五分钟前的历史摘要。" in prompt
        assert "一周历史摘要：" in prompt

    asyncio.run(scenario())


def test_suggest_replies_includes_related_summary_rag_context() -> None:
    async def scenario() -> None:
        fake = FakeTaskManager(
            content="那就周日下午去吧。\n可以，我到时候提前联系你。\n这周我可能不太方便。\n我再看看时间安排。"
        )
        db = FakeSummaryDatabase()
        memory = FakeReplyMemoryManager(
            lines=("2026-04-12 18:30-18:35；参与者：对方、我；摘要：之前确认那家店周日人会少一点。",)
        )
        manager = AIAssistManager(task_manager=fake, db=db, memory_manager=memory)
        messages = [
            ChatMessage(
                "m-now-1",
                "s1",
                "peer",
                "周日去那家店吗？",
                status=MessageStatus.RECEIVED,
                timestamp=datetime(2026, 4, 15, 19, 0, 0),
            )
        ]

        state = await manager.suggest_replies(_session(), messages, current_user_id="me")

        assert state.status == AIReplySuggestionStatus.READY
        prompt = fake.requests[0].messages[0]["content"]
        assert "相关历史摘要（仅在和当前话题明显相关时参考；用于承接背景，不要复述旧内容）：" in prompt
        assert "之前确认那家店周日人会少一点。" in prompt
        assert fake.requests[0].metadata["history_recall_count"] == 1
        assert fake.requests[0].metadata["has_rag_history_context"] is True
        assert fake.requests[0].metadata["rag_history_count"] == 1
        assert fake.requests[0].metadata["rag_history_prompt_chars"] > 0
        assert len(memory.calls) == 1
        assert memory.calls[0]["session_id"] == "s1"
        assert "周日去那家店吗？" in memory.calls[0]["query_text"]
        assert memory.calls[0]["max_end_ts"] is not None
        assert db.get_messages_calls == []

    asyncio.run(scenario())


def test_suggest_replies_skip_when_latest_text_is_self() -> None:
    async def scenario() -> None:
        fake = FakeTaskManager()
        manager = AIAssistManager(task_manager=fake)
        session = _session()
        messages = [
            _peer_message("m1", "周日去那家店吗？"),
            ChatMessage("m2", "s1", "me", "我晚点确认。", is_self=True, status=MessageStatus.SENT),
        ]

        state = await manager.suggest_replies(session, messages, current_user_id="me")

        assert state.status == AIReplySuggestionStatus.IDLE
        assert state.reason == "latest_text_from_self"
        assert fake.requests == []

    asyncio.run(scenario())


def test_suggest_replies_filters_old_topic_repeats_from_model_output() -> None:
    async def scenario() -> None:
        fake = FakeTaskManager(
            content="明天去不去饭店吃饭？\n可以，你想吃辣一点还是清淡一点？\n我都行，你有没有特别想点的菜？\n这边先不太确定，晚点定菜也行。"
        )
        manager = AIAssistManager(task_manager=fake)
        session = _session()
        messages = [
            _peer_message("m1", "明天去不去饭店吃饭？"),
            ChatMessage("m2", "s1", "me", "可以，去。", is_self=True, status=MessageStatus.SENT),
            _peer_message("m3", "那吃什么菜？"),
        ]

        state = await manager.suggest_replies(session, messages, current_user_id="me")

        assert state.status == AIReplySuggestionStatus.READY
        assert [item.text for item in state.items] == [
            "可以，你想吃辣一点还是清淡一点？",
            "我都行，你有没有特别想点的菜？",
            "这边先不太确定，晚点定菜也行。",
        ]

    asyncio.run(scenario())


def test_suggest_replies_retries_with_fallback_prompt_when_first_output_is_filtered() -> None:
    class SequenceTaskManager:
        def __init__(self) -> None:
            self.requests = []
            self.contents = [
                "那吃什么菜？",
                "你想吃辣一点还是清淡一点？\n我都行，你有没有特别想点的菜？\n这边先不太确定，晚点定菜也行。",
            ]

        async def run_once(self, request):
            self.requests.append(request)
            index = min(len(self.requests) - 1, len(self.contents) - 1)
            return AITaskSnapshot(
                task_id=request.task_id,
                session_id=request.session_id,
                task_type=request.task_type.value,
                state=AITaskState.DONE,
                content=self.contents[index],
                error_code=None,
                finish_reason="stop",
            )

    async def scenario() -> None:
        fake = SequenceTaskManager()
        manager = AIAssistManager(task_manager=fake)
        session = _session()
        messages = [
            _peer_message("m1", "明天去不去饭店吃饭？"),
            ChatMessage("m2", "s1", "me", "可以，去。", is_self=True, status=MessageStatus.SENT),
            _peer_message("m3", "那吃什么菜？"),
        ]

        state = await manager.suggest_replies(session, messages, current_user_id="me")

        assert state.status == AIReplySuggestionStatus.READY
        assert [item.text for item in state.items] == [
            "你想吃辣一点还是清淡一点？",
            "我都行，你有没有特别想点的菜？",
            "这边先不太确定，晚点定菜也行。",
        ]
        assert len(fake.requests) == 2
        assert fake.requests[0].metadata["reply_prompt_mode"] == "standard"
        assert fake.requests[1].metadata["reply_prompt_mode"] == "fallback"
        assert fake.requests[1].metadata["has_summary"] is False
        assert fake.requests[0].seed is None
        assert fake.requests[1].seed is None
        assert fake.requests[0].response_format is None
        assert fake.requests[1].response_format is None
        assert fake.requests[0].system_prompt is not None
        assert fake.requests[1].system_prompt is not None

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
        "latest_text_from_self",
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


def test_suggest_replies_uses_ready_voice_transcript_as_anchor() -> None:
    async def scenario() -> None:
        fake = FakeTaskManager(
            content="可以，这个时间我方便。\n我看可以，咱们就按这个来。\n这会儿我不太确定。\n我晚点确认后回复你。"
        )
        manager = AIAssistManager(task_manager=fake)

        state = await manager.suggest_replies(_session(), [_peer_voice_message()], current_user_id="me")

        assert state.status == AIReplySuggestionStatus.READY
        assert state.anchor_message_id == "voice-1"
        prompt = fake.requests[0].messages[0]["content"]
        assert "当前待回复消息组：" in prompt
        assert "[语音转文字: 你帮我看一下这个时间行不行？]" in prompt
        assert fake.requests[0].metadata["anchor_message_id"] == "voice-1"

    asyncio.run(scenario())


def test_suggest_replies_skips_voice_without_ready_transcript() -> None:
    manager = AIAssistManager(task_manager=FakeTaskManager())

    assert manager.can_suggest_replies(_session(), [_peer_voice_message(transcript_status="pending")]) == (
        False,
        "no_peer_text_message",
    )


def test_suggest_replies_uses_ready_file_extract_as_anchor() -> None:
    async def scenario() -> None:
        fake = FakeTaskManager(
            content="我看到了，合同金额和付款时间都清楚。\n可以，我按文件内容继续确认。\n我现在不方便确认文件细节。\n我晚点看完再回复你。"
        )
        manager = AIAssistManager(task_manager=fake)

        state = await manager.suggest_replies(_session(), [_peer_file_message()], current_user_id="me")

        assert state.status == AIReplySuggestionStatus.READY
        assert state.anchor_message_id == "file-1"
        prompt = fake.requests[0].messages[0]["content"]
        assert "[文件内容: report.pdf: 合同金额为 100 元，付款期限为周五。]" in prompt
        assert fake.requests[0].metadata["anchor_message_id"] == "file-1"

    asyncio.run(scenario())


def test_suggest_replies_skips_file_without_ready_extract() -> None:
    manager = AIAssistManager(task_manager=FakeTaskManager())

    assert manager.can_suggest_replies(_session(), [_peer_file_message(extract_status="pending")]) == (
        False,
        "no_peer_text_message",
    )


def test_suggest_replies_skips_image_even_with_ready_summary() -> None:
    manager = AIAssistManager(task_manager=FakeTaskManager())

    assert manager.can_suggest_replies(_session(), [_peer_image_message()]) == (
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

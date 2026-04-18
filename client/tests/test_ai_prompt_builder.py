from __future__ import annotations

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

from client.managers.ai_prompt_builder import AIAssistAction, AIPromptBuilder, ReplySummaryContext
from client.models.message import ChatMessage, MessageStatus, Session
from client.services.ai_service import AIPrivacyScope, AITaskType


def test_draft_prompt_marks_e2ee_requests_local() -> None:
    builder = AIPromptBuilder()
    session = Session(
        session_id="s-e2ee",
        name="Alice",
        session_type="direct",
        extra={"encryption_mode": "e2ee_private"},
    )

    request = builder.build_draft_request(AIAssistAction.POLISH, "  hello   there  ", session=session)

    assert request.task_type == AITaskType.INPUT_POLISH
    assert request.must_be_local is True
    assert request.privacy_scope == AIPrivacyScope.E2EE_PLAINTEXT
    assert "hello there" in request.messages[0]["content"]


def test_reply_suggestion_prompt_anchors_latest_peer_text() -> None:
    builder = AIPromptBuilder()
    session = Session(session_id="s1", name="Alice", session_type="direct")
    messages = [
        ChatMessage("m1", "s1", "me", "old", is_self=True, status=MessageStatus.SENT),
        ChatMessage("m2", "s1", "peer", "can you check this?", status=MessageStatus.RECEIVED),
    ]

    built = builder.build_reply_suggestion_request(session, messages, current_user_id="me")

    assert built.anchor_message.message_id == "m2"
    assert built.request.task_type == AITaskType.REPLY_SUGGESTION
    assert built.request.privacy_scope == AIPrivacyScope.DIRECT_CONTEXT
    assert built.request.must_be_local is False
    assert built.request.metadata["anchor_message_id"] == "m2"
    assert "生成 4 条我可以直接发送的简短回复" in built.request.messages[0]["content"]
    assert "前 2 条为积极推进型" in built.request.messages[0]["content"]
    assert "后 2 条为保守婉拒型" in built.request.messages[0]["content"]
    assert "对方: can you check this?" in built.request.messages[0]["content"]


def test_reply_suggestion_prompt_includes_local_summary_context_when_available() -> None:
    builder = AIPromptBuilder()
    session = Session(session_id="s1", name="Alice", session_type="direct")
    messages = [
        ChatMessage("m1", "s1", "peer", "周日下午可以见面。", status=MessageStatus.RECEIVED),
    ]

    built = builder.build_reply_suggestion_request(
        session,
        messages,
        summary_context=ReplySummaryContext(
            open_bucket_summary="当前主要在确认周日下午是否见面。",
            recent_bucket_summaries=("之前已经确认了见面地点。", "还没有最终敲定具体时间。"),
        ),
    )

    prompt = built.request.messages[0]["content"]
    assert "聊天上下文：" in prompt
    assert "当前时间段摘要：" in prompt
    assert "最近历史摘要：" in prompt
    assert "当前主要在确认周日下午是否见面。" in prompt
    assert "之前已经确认了见面地点。" in prompt
    assert built.request.metadata["has_open_bucket_summary"] is True
    assert built.request.metadata["history_summary_count"] == 2


def test_parse_reply_suggestions_cleans_markers_and_limits() -> None:
    builder = AIPromptBuilder()
    output = """
    1. 好的，我看一下。
    - 明白，我稍后回复。
    • 可以，发我细节。
    4. 这边先不方便，晚点再说。
    5. 多余的一条
    """

    assert builder.parse_reply_suggestions(output) == [
        "好的，我看一下。",
        "明白，我稍后回复。",
        "可以，发我细节。",
        "这边先不方便，晚点再说。",
    ]

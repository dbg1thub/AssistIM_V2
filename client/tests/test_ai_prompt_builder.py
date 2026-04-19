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

from client.managers.ai_prompt_builder import (
    AIAssistAction,
    AIPromptBuilder,
    ReplySummaryContext,
    latest_peer_text_message_group,
)
from client.core.message_translation import AI_TRANSLATION_NOOP_MARKER
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
        ChatMessage("m3", "s1", "peer", "the deadline is tomorrow", status=MessageStatus.RECEIVED),
    ]

    built = builder.build_reply_suggestion_request(session, messages, current_user_id="me")

    assert built.anchor_message.message_id == "m3"
    assert built.request.task_type == AITaskType.REPLY_SUGGESTION
    assert built.request.privacy_scope == AIPrivacyScope.DIRECT_CONTEXT
    assert built.request.must_be_local is False
    assert built.request.temperature == builder.REPLY_SUGGESTION_TEMPERATURE
    assert built.request.seed is None
    assert built.request.max_tokens == 160
    assert built.request.response_format is None
    assert built.request.system_prompt is not None
    assert built.request.metadata["anchor_message_id"] == "m3"
    assert built.request.metadata["anchor_group_size"] == 2
    assert built.request.metadata["recent_context_count"] == 3
    assert built.request.metadata["has_summary"] is False
    assert built.request.metadata["prompt_chars"] == len(built.request.messages[0]["content"])
    assert built.request.metadata["reply_template_family"] == "gemma4_standard_roles"
    assert "你是 AssistIM 的私聊回复建议助手。" in built.request.system_prompt
    assert "使用标准聊天角色" in built.request.system_prompt
    assert "请生成 4 条我可以直接发送的简短回复" in built.request.system_prompt
    assert "每行一条，不要编号" in built.request.system_prompt
    assert "请根据下面的私聊场景生成回复" in built.request.messages[0]["content"]
    assert "当前待回复消息组：" in built.request.messages[0]["content"]
    assert "最近直接上下文：" in built.request.messages[0]["content"]
    assert "1. can you check this?" in built.request.messages[0]["content"]
    assert "2. the deadline is tomorrow" in built.request.messages[0]["content"]
    assert "最新一句：the deadline is tomorrow" in built.request.messages[0]["content"]
    assert "对方: can you check this?" in built.request.messages[0]["content"]
    assert "对方: the deadline is tomorrow" in built.request.messages[0]["content"]


def test_message_translation_request_is_local_and_mode_aware() -> None:
    builder = AIPromptBuilder()
    session = Session(session_id="s1", name="Alice", session_type="direct")

    request = builder.build_message_translation_request(
        "Would you like dinner tomorrow?",
        session=session,
        message_id="m1",
        target_language_code="zh-CN",
        mode="auto",
        task_id="translate-test",
    )

    prompt = request.messages[0]["content"]
    assert request.task_id == "translate-test"
    assert request.session_id == "s1"
    assert request.task_type == AITaskType.TRANSLATE
    assert request.must_be_local is True
    assert request.stream is False
    assert request.privacy_scope == AIPrivacyScope.DIRECT_CONTEXT
    assert request.metadata["mode"] == "auto"
    assert request.metadata["message_id"] == "m1"
    assert request.metadata["target_language"] == "zh-CN"
    assert request.metadata["source_chars"] == len("Would you like dinner tomorrow?")
    assert request.metadata["prompt_chars"] == len(prompt)
    assert "翻译成中文" in prompt
    assert AI_TRANSLATION_NOOP_MARKER in prompt


def test_manual_message_translation_request_does_not_skip_same_language() -> None:
    builder = AIPromptBuilder()

    request = builder.build_message_translation_request(
        "你好",
        target_language_code="zh-CN",
        mode="manual",
    )

    assert AI_TRANSLATION_NOOP_MARKER not in request.messages[0]["content"]
    assert request.metadata["mode"] == "manual"


def test_parse_message_translation_strips_fences_and_auto_noop() -> None:
    builder = AIPromptBuilder()

    assert builder.parse_message_translation("```text\n明天一起吃饭吗？\n```") == "明天一起吃饭吗？"
    assert builder.parse_message_translation(AI_TRANSLATION_NOOP_MARKER, mode="auto") == ""


def test_latest_peer_text_message_group_collects_latest_consecutive_peer_texts() -> None:
    messages = [
        ChatMessage("m1", "s1", "peer", "周五去不去？", status=MessageStatus.RECEIVED),
        ChatMessage("m2", "s1", "peer", "我晚上有空", status=MessageStatus.RECEIVED),
        ChatMessage("m3", "s1", "me", "可以", is_self=True, status=MessageStatus.SENT),
        ChatMessage("m4", "s1", "peer", "那吃什么？", status=MessageStatus.RECEIVED),
        ChatMessage("m5", "s1", "peer", "想吃辣一点", status=MessageStatus.RECEIVED),
    ]

    grouped = latest_peer_text_message_group(messages, current_user_id="me")

    assert [message.message_id for message in grouped] == ["m4", "m5"]


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
    assert "最近直接上下文：" in prompt
    assert "背景摘要（仅供参考，用来避免前后矛盾；不要优先复述已经确认过的话题）：" in prompt
    assert "当前时间段摘要：" in prompt
    assert "最近历史摘要：" in prompt
    assert "当前主要在确认周日下午是否见面。" in prompt
    assert "之前已经确认了见面地点。" in prompt
    assert built.request.system_prompt is not None
    assert built.request.metadata["has_open_bucket_summary"] is True
    assert built.request.metadata["history_summary_count"] == 2


def test_single_reply_suggestion_prompt_includes_existing_candidates_and_style() -> None:
    builder = AIPromptBuilder()
    session = Session(session_id="s1", name="Alice", session_type="direct")
    messages = [
        ChatMessage("m1", "s1", "peer", "周日下午可以见面。", status=MessageStatus.RECEIVED),
    ]

    built = builder.build_single_reply_suggestion_request(
        session,
        messages,
        target_style="reserved",
        existing_candidates=("好的，那就周日下午见。", "我到时候提前联系你。"),
        round_index=2,
    )

    prompt = built.request.messages[0]["content"]
    assert built.request.task_type == AITaskType.REPLY_SUGGESTION
    assert built.request.temperature == builder.REPLY_SINGLE_TEMPERATURE
    assert built.request.seed is None
    assert built.request.response_format is None
    assert built.request.max_tokens == 96
    assert built.request.metadata["reply_prompt_mode"] == "single"
    assert built.request.metadata["reply_target_style"] == "reserved"
    assert built.request.metadata["reply_round"] == 2
    assert built.request.metadata["reply_existing_count"] == 2
    assert "只生成 1 条" in prompt
    assert "以下回复已经生成，禁止重复" in prompt
    assert "好的，那就周日下午见。" in prompt
    assert "我到时候提前联系你。" in prompt


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


def test_parse_reply_suggestions_supports_inline_numbered_output() -> None:
    builder = AIPromptBuilder()
    output = "1. 好的，我看一下。 2. 明白，我稍后回复。 3. 可以，发我细节。 4. 这边先不方便，晚点再说。"

    assert builder.parse_reply_suggestions(output) == [
        "好的，我看一下。",
        "明白，我稍后回复。",
        "可以，发我细节。",
        "这边先不方便，晚点再说。",
    ]


def test_parse_reply_suggestions_supports_json_output() -> None:
    builder = AIPromptBuilder()
    output = '{"replies":["好的，我看一下。","明白，我稍后回复。","可以，发我细节。","这边先不方便，晚点再说。"]}'

    assert builder.parse_reply_suggestions(output) == [
        "好的，我看一下。",
        "明白，我稍后回复。",
        "可以，发我细节。",
        "这边先不方便，晚点再说。",
    ]


def test_parse_reply_suggestions_skips_stale_topic_repeats() -> None:
    builder = AIPromptBuilder()
    recent_messages = [
        ChatMessage("m1", "s1", "peer", "明天去不去饭店吃饭？", status=MessageStatus.RECEIVED),
        ChatMessage("m2", "s1", "me", "可以，去。", is_self=True, status=MessageStatus.SENT),
        ChatMessage("m3", "s1", "peer", "那吃什么菜？", status=MessageStatus.RECEIVED),
    ]
    output = """
    1. 明天去不去饭店吃饭？
    2. 可以，你想吃辣一点还是清淡一点？
    3. 我都行，你有没有特别想点的菜？
    4. 这边先不太确定，晚点定菜也行。
    """

    assert builder.parse_reply_suggestions(
        output,
        anchor_message=recent_messages[-1],
        recent_messages=recent_messages,
    ) == [
        "可以，你想吃辣一点还是清淡一点？",
        "我都行，你有没有特别想点的菜？",
        "这边先不太确定，晚点定菜也行。",
    ]


def test_parse_reply_suggestions_keeps_short_valid_follow_up() -> None:
    builder = AIPromptBuilder()
    recent_messages = [
        ChatMessage("m1", "s1", "peer", "明天去不去饭店吃饭？", status=MessageStatus.RECEIVED),
        ChatMessage("m2", "s1", "me", "可以，去。", is_self=True, status=MessageStatus.SENT),
        ChatMessage("m3", "s1", "peer", "那吃什么菜？", status=MessageStatus.RECEIVED),
    ]

    assert builder.parse_reply_suggestions(
        "1. 你想吃辣一点还是清淡一点？",
        anchor_message=recent_messages[-1],
        recent_messages=recent_messages,
    ) == ["你想吃辣一点还是清淡一点？"]

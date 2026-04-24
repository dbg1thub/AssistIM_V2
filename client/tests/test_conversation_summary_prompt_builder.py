from datetime import datetime

from client.core.voice_transcription import VOICE_TRANSCRIPT_EXTRA_KEY
from client.managers.conversation_summary_prompt_builder import (
    ConversationSummaryPromptBuilder,
    StructuredConversationSummary,
)
from client.models.message import ChatMessage, MessageStatus, MessageType, Session


def _message(message_id: str, when: datetime, *, content: str, is_self: bool = False, message_type: MessageType = MessageType.TEXT, extra: dict | None = None) -> ChatMessage:
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


def test_open_bucket_prompt_requires_fixed_eight_line_output() -> None:
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    builder = ConversationSummaryPromptBuilder()
    built = builder.build_bucket_summary_request(
        session,
        [
            _message("m-1", datetime(2026, 4, 19, 10, 0, 0), content="周日下午可以见面。"),
            _message("m-2", datetime(2026, 4, 19, 10, 1, 0), content="那我再确认一下地点。", is_self=True),
        ],
        is_open=True,
    )

    assert built is not None
    prompt = built.request.messages[0]["content"]
    assert "只输出正好 8 行" in prompt
    assert "DISPLAY_SUMMARY:" in prompt
    assert "PENDING_ITEMS:" in prompt
    assert "允许保留未完成状态" in prompt


def test_closed_bucket_prompt_requires_stable_final_summary_language() -> None:
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    builder = ConversationSummaryPromptBuilder()
    built = builder.build_bucket_summary_request(
        session,
        [
            _message("m-1", datetime(2026, 4, 19, 10, 0, 0), content="周日下午可以见面。"),
            _message("m-2", datetime(2026, 4, 19, 10, 1, 0), content="那就定在咖啡店。", is_self=True),
        ],
        is_open=False,
    )

    assert built is not None
    prompt = built.request.messages[0]["content"]
    assert "已经结束的聊天时间段" in prompt
    assert "DECISIONS 强调已达成的决定" in prompt
    assert "不要使用“当前”“正在”“还在继续”等进行时措辞" in prompt
    assert "不要输出 JSON" in prompt


def test_parse_summary_output_returns_structured_summary() -> None:
    parsed = ConversationSummaryPromptBuilder.parse_summary_output(
        "\n".join(
            [
                "DISPLAY_SUMMARY: 双方正在确认周日下午见面，地点倾向南山咖啡店。",
                "TOPICS: 周日下午见面 | 南山咖啡店",
                "FACTS: 双方周日下午都有空 | 地点倾向南山咖啡店",
                "DECISIONS: 暂定周日下午见面",
                "PENDING_ITEMS: 具体到店时间待确认",
                "TONE: 轻松，推进中",
                "PARTICIPANTS: 我 | 张三",
                "KEYWORDS: 周日 | 咖啡店 | 见面 | 南山",
            ]
        )
    )

    assert parsed == StructuredConversationSummary(
        display_summary="双方正在确认周日下午见面，地点倾向南山咖啡店。",
        topics=("周日下午见面", "南山咖啡店"),
        facts=("双方周日下午都有空", "地点倾向南山咖啡店"),
        decisions=("暂定周日下午见面",),
        pending_items=("具体到店时间待确认",),
        tone="轻松，推进中",
        participants=("我", "张三"),
        keywords=("周日", "咖啡店", "见面", "南山"),
    )


def test_parse_summary_output_rejects_wrong_field_order() -> None:
    parsed = ConversationSummaryPromptBuilder.parse_summary_output(
        "\n".join(
            [
                "DISPLAY_SUMMARY: 双方正在确认周日下午见面。",
                "FACTS: 双方周日下午都有空",
                "TOPICS: 周日下午见面",
                "DECISIONS: 暂定周日下午见面",
                "PENDING_ITEMS: 具体到店时间待确认",
                "TONE: 轻松，推进中",
                "PARTICIPANTS: 我 | 张三",
                "KEYWORDS: 周日 | 见面",
            ]
        )
    )
    assert parsed is None


def test_build_retrieval_summary_uses_fixed_field_order() -> None:
    retrieval_summary = ConversationSummaryPromptBuilder.build_retrieval_summary(
        StructuredConversationSummary(
            display_summary="双方正在确认周日下午见面，地点倾向南山咖啡店。",
            topics=("周日下午见面", "南山咖啡店"),
            facts=("双方周日下午都有空", "地点倾向南山咖啡店"),
            decisions=("暂定周日下午见面",),
            pending_items=("具体到店时间待确认",),
            tone="轻松，推进中",
            participants=("我", "张三"),
            keywords=("周日", "咖啡店", "见面", "南山"),
        ),
        bucket_start_ts=int(datetime(2026, 4, 19, 10, 0, 0).timestamp()),
        bucket_end_ts=int(datetime(2026, 4, 19, 10, 5, 0).timestamp()),
    )

    assert retrieval_summary.splitlines() == [
        "会话对象：我；张三",
        "时间范围：2026-04-19 10:00-10:05",
        "主题：周日下午见面；南山咖啡店",
        "已确认：双方周日下午都有空；地点倾向南山咖啡店",
        "已决定：暂定周日下午见面",
        "待跟进：具体到店时间待确认",
        "整体语气：轻松，推进中",
    ]


def test_format_context_keeps_non_text_placeholders() -> None:
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    builder = ConversationSummaryPromptBuilder()
    built = builder.build_bucket_summary_request(
        session,
        [
            _message("m-1", datetime(2026, 4, 19, 10, 0, 0), content="看下这个图片", message_type=MessageType.IMAGE),
            _message(
                "m-2",
                datetime(2026, 4, 19, 10, 1, 0),
                content="",
                is_self=True,
                message_type=MessageType.FILE,
                extra={"name": "合同.pdf"},
            ),
        ],
        is_open=True,
    )

    assert built is not None
    prompt = built.request.messages[0]["content"]
    assert "对方: [图片]" in prompt
    assert "我: [文件: 合同.pdf]" in prompt


def test_format_context_uses_ready_voice_transcript_for_voice_messages() -> None:
    session = Session(session_id="session-1", name="Bob", session_type="direct")
    builder = ConversationSummaryPromptBuilder()
    built = builder.build_bucket_summary_request(
        session,
        [
            _message(
                "m-voice-1",
                datetime(2026, 4, 19, 10, 0, 0),
                content="voice-1.m4a",
                message_type=MessageType.VOICE,
                extra={VOICE_TRANSCRIPT_EXTRA_KEY: {"status": "ready", "text": "明天下午三点见。"}},
            ),
            _message(
                "m-voice-2",
                datetime(2026, 4, 19, 10, 1, 0),
                content="voice-2.m4a",
                is_self=True,
                message_type=MessageType.VOICE,
                extra={VOICE_TRANSCRIPT_EXTRA_KEY: {"status": "pending"}},
            ),
        ],
        is_open=True,
    )

    assert built is not None
    prompt = built.request.messages[0]["content"]
    assert "对方: [语音转文字: 明天下午三点见。]" in prompt
    assert "我: [语音]" in prompt
    assert "pending" not in prompt

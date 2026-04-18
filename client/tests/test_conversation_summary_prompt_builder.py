from datetime import datetime

from client.managers.conversation_summary_prompt_builder import ConversationSummaryPromptBuilder
from client.models.message import ChatMessage, MessageStatus, MessageType, Session


def _message(message_id: str, when: datetime, *, content: str, is_self: bool = False) -> ChatMessage:
    return ChatMessage(
        message_id=message_id,
        session_id="session-1",
        sender_id="alice" if is_self else "bob",
        content=content,
        message_type=MessageType.TEXT,
        status=MessageStatus.SENT if is_self else MessageStatus.RECEIVED,
        timestamp=when,
        updated_at=when,
        is_self=is_self,
    )


def test_open_bucket_prompt_keeps_rolling_summary_language() -> None:
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
    assert "当前仍在继续的聊天时间段" in prompt
    assert "突出当前在聊什么、已确认事实、待确认事项和整体语气" in prompt
    assert "允许保留未完成状态" in prompt
    assert "稳定的最终总结" not in prompt


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
    assert "稳定的最终总结" in prompt
    assert "最终讨论主题、已达成的结论或决定、仍待后续跟进的遗留点和整体语气" in prompt
    assert "不要使用“当前”“正在”“还在继续”等时间敏感措辞" in prompt
    assert "不要写推测性语句" in prompt
    assert "允许保留未完成状态" not in prompt

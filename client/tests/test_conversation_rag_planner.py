from client.managers.conversation_rag_planner import ConversationRagPlanner
from client.models.ai_assistant import AIMessage, AIMessageRole


def test_conversation_rag_planner_coerces_string_false_to_no_memory() -> None:
    plan = ConversationRagPlanner.coerce_plan(
        {
            "needs_memory": "false",
            "user_goal": "请你自我介绍下",
            "memory_query": "",
            "participants": [],
            "participant_relation": "separate",
            "time_range": {"type": "all_history", "start_ts": None, "end_ts": None, "label": "全部历史"},
            "answer_style": "answer",
            "query_kind": "rag",
        },
        fallback_query="请你自我介绍下",
    )

    assert plan is not None
    assert plan.use_rag is False


def test_conversation_rag_planner_coerces_string_true_to_memory() -> None:
    plan = ConversationRagPlanner.coerce_plan(
        {
            "needs_memory": "true",
            "user_goal": "张三昨天聊了什么",
            "memory_query": "张三昨天聊了什么",
            "participants": [{"mention": "张三", "role": "contact"}],
            "participant_relation": "separate",
            "time_range": {"type": "all_history", "start_ts": None, "end_ts": None, "label": "全部历史"},
            "answer_style": "summary",
            "query_kind": "rag",
        },
        fallback_query="张三昨天聊了什么",
    )

    assert plan is not None
    assert plan.use_rag is True


def test_conversation_rag_planner_history_lines_ignore_assistant_and_current_query() -> None:
    planner = ConversationRagPlanner()
    previous_messages = [
        AIMessage("u1", "thread-1", AIMessageRole.USER, "帮我查张三昨天聊了什么"),
        AIMessage("a1", "thread-1", AIMessageRole.ASSISTANT, "我先查一下本机聊天记录。"),
        AIMessage("u2", "thread-1", AIMessageRole.USER, "请你自我介绍下"),
    ]

    lines = planner._history_lines(previous_messages=previous_messages, current_query="请你自我介绍下")

    assert lines == ["user: 帮我查张三昨天聊了什么"]

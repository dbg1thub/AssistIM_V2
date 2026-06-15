from client.managers.ai_action_registry import AtomicActionRegistry
from client.managers.ai_action_validator import AIPlanValidator
from client.managers.ai_skill_compiler import AISkillCompiler
from client.managers.ai_skill_types import SkillIntent
import pytest


class _FakeContactResolver:
    async def resolve(self, queries, *, allow_multiple=False):
        del allow_multiple
        return {"contacts": [], "groups": [], "ambiguous": [], "unresolved": list(queries or [])}


def _compiler() -> AISkillCompiler:
    return AISkillCompiler()


def _validator() -> AIPlanValidator:
    registry = AtomicActionRegistry(contact_resolver=_FakeContactResolver())
    return AIPlanValidator(registry=registry)


def _actions(plan):
    return [step.action for step in plan.steps]


def _step(plan, action):
    for step in plan.steps:
        if step.action == action:
            return step
    raise AssertionError(f"missing step action: {action}")


def _compile(skill: str, slots: dict, *, goal: str = ""):
    return _compiler().compile(SkillIntent(type="skill", skill=skill, goal=goal or skill, slots=slots))


def test_send_message_skill_compiles_to_confirmed_message_plan() -> None:
    result = _compiler().compile(
        SkillIntent(
            type="skill",
            skill="SEND_MESSAGE",
            goal="给 dengbin 说我晚点联系他",
            slots={"target": "dengbin", "content": "我晚点联系他"},
        )
    )

    assert result.type == "plan"
    assert result.plan is not None
    assert _actions(result.plan) == [
        "contact.resolve",
        "message.draft",
        "user.confirm",
        "message.send",
    ]
    assert _step(result.plan, "contact.resolve").args == {
        "queries": ["dengbin"],
        "allow_multiple": False,
    }
    assert _step(result.plan, "message.draft").args["target"] == "$resolve_target.contacts[0]"
    assert _step(result.plan, "message.draft").args["content"] == "我晚点联系他"
    confirm_args = _step(result.plan, "user.confirm").args
    assert confirm_args["risk"] == "high"
    assert confirm_args["preview"] == {
        "operation": "发送消息",
        "target": "$draft_message.target",
        "content": "$draft_message.content",
    }
    assert _step(result.plan, "message.send").args == {
        "target": "$draft_message.target_entity",
        "content": "$draft_message.content",
        "preview": "$draft_message.preview",
        "idempotency_key": "$draft_message.idempotency_key",
    }
    assert _validator().validate(result.plan).allowed


@pytest.mark.parametrize(
    ("skill", "slots", "expected_action", "expected_args"),
    [
        ("LIST_FRIENDS", {}, "friend.list", {}),
        ("LIST_FRIEND_REQUESTS", {}, "friend.request.list", {}),
        ("LIST_GROUPS", {}, "group.list", {}),
        ("LIST_SESSIONS", {}, "session.list", {}),
        ("LIST_UPLOADED_FILES", {"limit": 30}, "file.list", {"limit": 30}),
        ("LIST_MOMENTS", {"page": 2, "size": 10}, "moment.list", {"page": 2, "size": 10}),
        (
            "LIST_MOMENTS",
            {"scope": "mine", "content_filter": "media", "page": 2, "size": 10},
            "moment.list",
            {"scope": "mine", "content_filter": "media", "page": 2, "size": 10},
        ),
    ],
)
def test_server_read_list_skills_compile_to_single_read_action(
    skill: str,
    slots: dict,
    expected_action: str,
    expected_args: dict,
) -> None:
    result = _compile(skill, slots)

    assert result.type == "plan"
    assert result.plan is not None
    assert _actions(result.plan) == [expected_action]
    assert result.plan.steps[0].args == expected_args
    assert _validator().validate(result.plan).allowed


@pytest.mark.parametrize(
    ("skill", "slots", "expected_action", "expected_args"),
    [
        ("VIEW_USER_PROFILE", {"target": "user-3", "source": "user_id"}, "user.get", {"user_id": "user-3"}),
        ("VIEW_GROUP", {"target": "group-1", "source": "group_id"}, "group.get", {"group_id": "group-1"}),
        ("VIEW_SESSION", {"session_id": "session-1"}, "session.get", {"session_id": "session-1"}),
        (
            "LIST_SESSION_MESSAGES",
            {"session_id": "session-1", "limit": 20},
            "message.list",
            {"session_id": "session-1", "limit": 20, "before_seq": None},
        ),
        ("VIEW_MOMENT", {"moment_id": "moment-1"}, "moment.get", {"moment_id": "moment-1"}),
    ],
)
def test_server_read_detail_skills_compile_direct_id_plans(
    skill: str,
    slots: dict,
    expected_action: str,
    expected_args: dict,
) -> None:
    result = _compile(skill, slots)

    assert result.type == "plan"
    assert result.plan is not None
    assert _actions(result.plan) == [expected_action]
    assert result.plan.steps[0].args == expected_args
    assert _validator().validate(result.plan).allowed


@pytest.mark.parametrize(
    ("skill", "slots", "expected_actions", "tail_action", "tail_args"),
    [
        (
            "VIEW_USER_PROFILE",
            {"target": "dengbin", "source": "search"},
            ["user.search", "user.get"],
            "user.get",
            {"user_id": "$search_user.items[0].id"},
        ),
        (
            "CHECK_FRIENDSHIP",
            {"target": "dengbin", "source": "search"},
            ["user.search", "friend.check"],
            "friend.check",
            {"user_id": "$search_user.items[0].id"},
        ),
        (
            "LIST_USER_MOMENTS",
            {"target": "dengbin", "source": "search", "page": 1, "size": 20},
            ["user.search", "moment.list"],
            "moment.list",
            {"user_id": "$search_user.items[0].id", "page": 1, "size": 20},
        ),
    ],
)
def test_search_based_read_skills_compile_lookup_then_read(
    skill: str,
    slots: dict,
    expected_actions: list[str],
    tail_action: str,
    tail_args: dict,
) -> None:
    result = _compile(skill, slots)

    assert result.type == "plan"
    assert result.plan is not None
    assert _actions(result.plan) == expected_actions
    assert _step(result.plan, "user.search").args == {"keyword": "dengbin", "page": 1, "size": 10}
    assert _step(result.plan, tail_action).args == tail_args
    assert _validator().validate(result.plan).allowed


def test_view_group_skill_can_resolve_named_group_before_detail_read() -> None:
    result = _compile("VIEW_GROUP", {"target": "项目群", "source": "contact"})

    assert result.type == "plan"
    assert result.plan is not None
    assert _actions(result.plan) == ["contact.resolve", "group.get"]
    assert _step(result.plan, "contact.resolve").args == {"queries": ["项目群"], "allow_multiple": False}
    assert _step(result.plan, "group.get").args == {"group_id": "$resolve_group.groups[0].id"}
    assert _validator().validate(result.plan).allowed


@pytest.mark.parametrize(
    ("skill", "action", "operation"),
    [
        ("ACCEPT_FRIEND_REQUEST", "friend.request.accept", "接受好友申请"),
        ("REJECT_FRIEND_REQUEST", "friend.request.reject", "拒绝好友申请"),
    ],
)
def test_friend_request_decision_skills_compile_to_confirmed_write(skill: str, action: str, operation: str) -> None:
    result = _compile(skill, {"request_id": "req-1"})

    assert result.type == "plan"
    assert result.plan is not None
    assert _actions(result.plan) == ["user.confirm", action]
    assert _step(result.plan, "user.confirm").args == {
        "risk": "high",
        "preview": {"operation": operation, "target": "req-1", "content": operation},
    }
    assert _step(result.plan, action).args == {
        "request_id": "req-1",
        "preview": "$confirm_request.preview",
        "idempotency_key": "$confirm_request.preview_fingerprint",
    }
    assert _validator().validate(result.plan).allowed


def test_send_friend_request_skill_uses_user_search_and_confirmation() -> None:
    result = _compiler().compile(
        SkillIntent(
            type="skill",
            skill="SEND_FRIEND_REQUEST",
            goal="加 dengbin 为好友，备注我是 test1",
            slots={"keyword": "dengbin", "message": "我是 test1"},
        )
    )

    assert result.type == "plan"
    assert result.plan is not None
    assert _actions(result.plan) == [
        "user.search",
        "user.confirm",
        "friend.request.send",
    ]
    assert _step(result.plan, "user.search").args == {"keyword": "dengbin", "page": 1, "size": 10}
    confirm_args = _step(result.plan, "user.confirm").args
    assert confirm_args["risk"] == "high"
    assert confirm_args["preview"] == {
        "operation": "发送好友申请",
        "target": "$search_user.items[0]",
        "content": "我是 test1",
    }
    assert _step(result.plan, "friend.request.send").args == {
        "target_user_id": "$search_user.items[0].id",
        "message": "我是 test1",
        "preview": "$confirm_request.preview",
        "idempotency_key": "$confirm_request.preview_fingerprint",
    }
    assert _validator().validate(result.plan).allowed


def test_memory_qa_skill_compiles_to_resolve_search_and_summarize() -> None:
    result = _compiler().compile(
        SkillIntent(
            type="skill",
            skill="MEMORY_QA",
            goal="我和 dengbin 之前聊过什么",
            slots={"participants": ["dengbin"], "question": "我和 dengbin 之前聊过什么"},
        )
    )

    assert result.type == "plan"
    assert result.plan is not None
    assert _actions(result.plan) == [
        "contact.resolve",
        "memory.search",
        "memory.summarize",
    ]
    assert _step(result.plan, "contact.resolve").args == {
        "queries": ["dengbin"],
        "allow_multiple": True,
    }
    assert _step(result.plan, "memory.search").args["participants"] == "$resolve_participants.contacts"
    assert _step(result.plan, "memory.search").args["keywords"] == []
    assert _step(result.plan, "memory.search").args["time_scope"] == {"type": "all_history"}
    assert _step(result.plan, "memory.summarize").args["source"] == "$search_memory"
    assert _validator().validate(result.plan).allowed


def test_memory_qa_skill_without_participants_skips_contact_resolve() -> None:
    result = _compiler().compile(
        SkillIntent(
            type="skill",
            skill="MEMORY_QA",
            goal="总结最近发过的合同文件内容",
            slots={"question": "总结最近发过的合同文件内容", "keywords": ["合同", "文件"]},
        )
    )

    assert result.type == "plan"
    assert result.plan is not None
    assert _actions(result.plan) == [
        "memory.search",
        "memory.summarize",
    ]
    assert _step(result.plan, "memory.search").args["participants"] == []
    assert _step(result.plan, "memory.search").args["keywords"] == ["合同", "文件"]
    assert _validator().validate(result.plan).allowed


def test_count_moments_skill_reads_one_page_with_requested_scope() -> None:
    result = _compile("COUNT_MOMENTS", {"scope": "mine", "content_filter": "all"})

    assert result.type == "plan"
    assert result.plan is not None
    assert _actions(result.plan) == ["moment.list"]
    assert _step(result.plan, "moment.list").args == {
        "scope": "mine",
        "content_filter": "all",
        "page": 1,
        "size": 1,
    }
    assert result.plan.final == {"source": "$count_moments"}
    assert _validator().validate(result.plan).allowed


def test_summarize_moments_skill_reads_moments_then_summarizes_items() -> None:
    result = _compile(
        "SUMMARIZE_MOMENTS",
        {"scope": "mine", "content_filter": "all", "question": "我发的朋友圈主要讲什么", "limit": 20},
    )

    assert result.type == "plan"
    assert result.plan is not None
    assert _actions(result.plan) == ["moment.list", "moment.summarize"]
    assert _step(result.plan, "moment.list").args == {
        "scope": "mine",
        "content_filter": "all",
        "page": 1,
        "size": 20,
    }
    assert _step(result.plan, "moment.summarize").args == {
        "source": "$list_moments",
        "question": "我发的朋友圈主要讲什么",
        "style": "summary",
    }
    assert result.plan.final == {"source": "$summarize_moments"}
    assert _validator().validate(result.plan).allowed


def test_file_content_qa_skill_filters_memory_search_to_file_sources() -> None:
    result = _compile(
        "FILE_CONTENT_QA",
        {
            "participants": ["联系人甲"],
            "question": "我给 联系人甲 发的 资料.txt 文件内容有什么",
            "keywords": ["资料.txt"],
            "time_scope": {"type": "all_history"},
            "limit": 8,
        },
    )

    assert result.type == "plan"
    assert result.plan is not None
    assert _actions(result.plan) == ["contact.resolve", "memory.search", "memory.summarize"]
    assert _step(result.plan, "contact.resolve").args == {
        "queries": ["联系人甲"],
        "allow_multiple": True,
    }
    search_args = _step(result.plan, "memory.search").args
    assert search_args["participants"] == "$resolve_participants.contacts"
    assert search_args["keywords"] == ["资料.txt"]
    assert search_args["source_types"] == ["file_summary", "file_text_chunk"]
    assert search_args["return_raw_content"] is False
    assert _step(result.plan, "memory.summarize").args["source"] == "$search_files"
    assert _validator().validate(result.plan).allowed


def test_unknown_skill_returns_unsupported_without_action_plan() -> None:
    result = _compiler().compile(
        SkillIntent(
            type="skill",
            skill="DELETE_FRIEND",
            goal="删除 dengbin 好友",
            slots={"target": "dengbin"},
        )
    )

    assert result.type == "unsupported"
    assert result.plan is None
    assert "DELETE_FRIEND" in result.reason


def test_missing_required_skill_slot_returns_clarification() -> None:
    result = _compiler().compile(
        SkillIntent(
            type="skill",
            skill="SEND_MESSAGE",
            goal="发消息",
            slots={"content": "我晚点联系他"},
        )
    )

    assert result.type == "clarification"
    assert result.plan is None
    assert result.missing_slots == ("target",)

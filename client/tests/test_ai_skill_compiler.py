from client.managers.ai_action_registry import AtomicActionRegistry
from client.managers.ai_action_validator import AIPlanValidator
from client.managers.ai_skill_compiler import AISkillCompiler
from client.managers.ai_skill_types import SkillIntent


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

from types import SimpleNamespace

from client.managers.ai_pending_control_parser import (
    AIPendingControlParser,
    AIPendingControlDecision,
    classify_obvious_pending_control,
    parse_pending_control_json,
)


def _pending(state: str, waiting_payload: dict) -> SimpleNamespace:
    return SimpleNamespace(state=state, waiting_payload=dict(waiting_payload))


def test_parse_pending_control_json_accepts_control_shapes() -> None:
    confirm = parse_pending_control_json('{"type": "confirm", "reason": "用户确认"}')
    selection = parse_pending_control_json('{"type": "select_contact_alias", "selection_index": 2}')
    fill = parse_pending_control_json('{"type": "fill_slots", "slots": {"target": "张三"}}')

    assert confirm == AIPendingControlDecision(type="confirm", reason="用户确认")
    assert selection == AIPendingControlDecision(type="select_contact_alias", selection_index=2)
    assert fill == AIPendingControlDecision(type="fill_slots", slots={"target": "张三"})


def test_parse_pending_control_json_rejects_atomic_plan_fields() -> None:
    assert parse_pending_control_json('{"type": "confirm", "steps": []}') is None
    assert parse_pending_control_json('{"type": "fill_slots", "action": "message.send"}') is None


def test_classify_obvious_pending_control_handles_safe_local_controls() -> None:
    confirmation = _pending("waiting_confirmation", {"type": "confirmation"})
    contact_ambiguity = _pending(
        "waiting_clarification",
        {"type": "contact_ambiguity", "candidates": [{"contact_id": "u1"}, {"contact_id": "u2"}]},
    )

    assert classify_obvious_pending_control("确认", confirmation) == AIPendingControlDecision(type="confirm")
    assert classify_obvious_pending_control("取消", confirmation) == AIPendingControlDecision(type="cancel")
    assert classify_obvious_pending_control("第2个", contact_ambiguity) == AIPendingControlDecision(
        type="select_contact_alias",
        selection_index=2,
        alias_text="2",
    )
    assert classify_obvious_pending_control("张三", contact_ambiguity) is None
    assert classify_obvious_pending_control("我想改成发给李四", confirmation) is None


def test_pending_control_parser_request_is_control_only() -> None:
    request = AIPendingControlParser().build_request(
        "发给张三",
        pending_state=_pending(
            "waiting_clarification",
            {
                "type": "clarification",
                "reason": "skill_clarification",
                "skill": "SEND_MESSAGE",
                "missing_slots": ["target"],
            },
        ),
    )

    system_prompt = request.system_prompt
    user_prompt = request.messages[0]["content"]

    assert request.metadata["source"] == "ai_pending_control_parser"
    assert request.response_format["type"] == "json_object"
    assert "只判断用户对当前 pending 操作的回复" in system_prompt
    assert "禁止生成执行步骤" in system_prompt
    assert "AIActionPlan" not in system_prompt
    assert '"state": "waiting_clarification"' in user_prompt
    assert "发给张三" in user_prompt

from client.managers.ai_skill_compiler import AISkillCompiler
from client.managers.ai_skill_parser import AISkillParser, parse_skill_intent_json


def _parser() -> AISkillParser:
    return AISkillParser(registry=AISkillCompiler().registry)


def test_parse_skill_intent_json_accepts_registered_skill_and_slots() -> None:
    intent = parse_skill_intent_json(
        """
        {
          "type": "skill",
          "skill": "SEND_MESSAGE",
          "goal": "给 dengbin 发送消息",
          "slots": {
            "target": "dengbin",
            "content": "我晚点联系他"
          },
          "confidence": "high"
        }
        """,
        registry=AISkillCompiler().registry,
    )

    assert intent is not None
    assert intent.type == "skill"
    assert intent.skill == "SEND_MESSAGE"
    assert intent.goal == "给 dengbin 发送消息"
    assert intent.slots == {"target": "dengbin", "content": "我晚点联系他"}
    assert intent.confidence == "high"


def test_parse_skill_intent_json_accepts_unsupported_without_steps() -> None:
    intent = parse_skill_intent_json(
        """
        {
          "type": "unsupported",
          "goal": "删除 dengbin 好友",
          "reason": "当前没有删除好友 Skill"
        }
        """,
        registry=AISkillCompiler().registry,
    )

    assert intent is not None
    assert intent.type == "unsupported"
    assert intent.skill == ""
    assert intent.reason == "当前没有删除好友 Skill"


def test_parse_skill_intent_json_accepts_clarification_control() -> None:
    intent = parse_skill_intent_json(
        """
        {
          "type": "clarification",
          "goal": "发送消息",
          "missing_slots": ["target"],
          "question": "你想发给谁？"
        }
        """,
        registry=AISkillCompiler().registry,
    )

    assert intent is not None
    assert intent.type == "clarification"
    assert intent.control == {"missing_slots": ["target"], "question": "你想发给谁？"}


def test_parse_skill_intent_json_rejects_atomic_action_fields() -> None:
    intent = parse_skill_intent_json(
        """
        {
          "type": "skill",
          "skill": "SEND_MESSAGE",
          "goal": "给 dengbin 发送消息",
          "slots": {
            "target": "dengbin",
            "content": "我晚点联系他"
          },
          "confidence": "high",
          "steps": [
            {"action": "message.send", "args": {}, "depends_on": []}
          ]
        }
        """,
        registry=AISkillCompiler().registry,
    )

    assert intent is None


def test_parse_skill_intent_json_rejects_unknown_skill() -> None:
    intent = parse_skill_intent_json(
        """
        {
          "type": "skill",
          "skill": "DELETE_FRIEND",
          "goal": "删除 dengbin 好友",
          "slots": {"target": "dengbin"},
          "confidence": "high"
        }
        """,
        registry=AISkillCompiler().registry,
    )

    assert intent is None


def test_parse_skill_intent_json_rejects_unknown_slot_fields() -> None:
    intent = parse_skill_intent_json(
        """
        {
          "type": "skill",
          "skill": "SEARCH_USER",
          "goal": "搜索用户 dengbin",
          "slots": {
            "keyword": "dengbin",
            "unexpected": true
          },
          "confidence": "high"
        }
        """,
        registry=AISkillCompiler().registry,
    )

    assert intent is None


def test_skill_parser_schema_does_not_allow_atomic_action_fields() -> None:
    schema = _parser().build_schema()
    properties = schema["properties"]

    assert "steps" not in properties
    assert "action" not in properties
    assert "depends_on" not in properties
    assert properties["skill"]["enum"] == [
        "MEMORY_QA",
        "SEARCH_USER",
        "SEND_FRIEND_REQUEST",
        "SEND_MESSAGE",
        "VIEW_USER_PROFILE",
    ]

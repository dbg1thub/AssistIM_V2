import asyncio
from types import SimpleNamespace

from client.managers.ai_skill_compiler import AISkillCompiler
from client.managers.ai_skill_parser import AISkillParser, parse_skill_intent_json


def _parser() -> AISkillParser:
    return AISkillParser(registry=AISkillCompiler().registry)


def _skill_names() -> list[str]:
    return list(AISkillCompiler().registry.names())


class _FakeTaskManager:
    def __init__(self, raw_output: str) -> None:
        self.raw_output = raw_output
        self.requests = []

    async def run_once(self, request):
        self.requests.append(request)
        return SimpleNamespace(content=self.raw_output, provider="fake", model="skill-parser-test")


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


def test_parse_skill_intent_json_rejects_missing_skill_for_skill_intent() -> None:
    intent = parse_skill_intent_json(
        """
        {
          "type": "skill",
          "goal": "搜索用户",
          "slots": {"keyword": "dengbin"}
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


def test_parse_skill_intent_json_rejects_null_for_non_nullable_slot() -> None:
    intent = parse_skill_intent_json(
        """
        {
          "type": "skill",
          "skill": "VIEW_USER_PROFILE",
          "goal": "查看用户资料",
          "slots": {
            "target": "user-3",
            "source": null
          }
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
    assert properties["skill"]["enum"] == _skill_names()
    assert "LIST_SESSION_MESSAGES" in properties["skill"]["enum"]
    assert "ACCEPT_FRIEND_REQUEST" in properties["skill"]["enum"]


def test_skill_parser_system_prompt_declares_strict_skill_output_rules() -> None:
    prompt = _parser().system_prompt()

    assert "type=skill" in prompt
    assert "skill 和 slots" in prompt
    assert "不要输出 null" in prompt
    assert "可选 slot" in prompt


def test_skill_parser_system_prompt_contains_generated_skill_catalog() -> None:
    prompt = _parser().system_prompt()

    assert "LIST_SESSION_MESSAGES" in prompt
    assert "ACCEPT_FRIEND_REQUEST" in prompt
    assert "session_id" in prompt
    assert "request_id" in prompt
    assert "source enum[contact|search|user_id]" in prompt
    assert "default=contact" in prompt
    assert "文件内容摘要" in prompt
    assert "语音转写" in prompt
    assert "steps" not in prompt
    assert "depends_on" not in prompt


def test_skill_parser_parse_with_model_builds_strict_local_request() -> None:
    task_manager = _FakeTaskManager(
        """
        {
          "type": "skill",
          "skill": "SEARCH_USER",
          "goal": "搜索用户 dengbin",
          "slots": {"keyword": "dengbin"},
          "confidence": "high"
        }
        """
    )

    intent = asyncio.run(_parser().parse_with_model("在 AssistIM 里搜索用户 dengbin", task_manager=task_manager))

    assert intent is not None
    assert intent.type == "skill"
    assert intent.skill == "SEARCH_USER"
    assert intent.slots == {"keyword": "dengbin"}
    assert len(task_manager.requests) == 1
    request = task_manager.requests[0]
    assert request.must_be_local is True
    assert request.stream is False
    assert request.temperature == 0.0
    assert request.response_format["schema"]["properties"]["skill"]["enum"] == _skill_names()
    assert request.metadata["source"] == "ai_skill_parser"
    assert request.metadata["skill_schema_version"] == AISkillParser.SCHEMA_VERSION
    assert "steps" not in request.system_prompt

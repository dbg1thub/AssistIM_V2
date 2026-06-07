from types import SimpleNamespace

from client.managers.ai_action_intent_gate import AIActionIntentGate, classify_obvious_action_intent, parse_action_intent_decision_json


def test_parse_action_intent_decision_json_accepts_strict_gate_output() -> None:
    decision = parse_action_intent_decision_json(
        """
        {
          "is_action": true,
          "confidence": 0.92,
          "reason": "需要读取 AssistIM 会话数据"
        }
        """
    )

    assert decision is not None
    assert decision.is_action is True
    assert decision.confidence == 0.92
    assert decision.reason == "需要读取 AssistIM 会话数据"


def test_parse_action_intent_decision_json_rejects_executable_fields() -> None:
    assert (
        parse_action_intent_decision_json(
            """
            {
              "is_action": true,
              "confidence": 0.9,
              "reason": "需要发送",
              "steps": []
            }
            """
        )
        is None
    )


def test_action_intent_gate_prompt_keeps_routing_separate_from_planning() -> None:
    request = AIActionIntentGate().build_request("给 dengbin 发消息", max_tokens=128)

    assert request.metadata["source"] == "ai_action_intent_gate"
    assert request.metadata["intent_schema_version"] == "assistim_intent_gate_v1"
    assert request.response_format["type"] == "json_object"
    assert "是否需要读取或操作 AssistIM" in request.system_prompt
    assert "不要因为用户没有写出 AssistIM 字样" in request.system_prompt
    assert "禁止输出 skill、slots、steps、actions、args" in request.system_prompt
    assert request.messages == [{"role": "user", "content": "用户输入：给 dengbin 发消息"}]


def test_classify_obvious_action_intent_routes_product_actions_without_model() -> None:
    assert classify_obvious_action_intent("帮我搜索用户 dengbin").is_action is True
    assert classify_obvious_action_intent("给 dengbin 说我晚点联系他").is_action is True
    assert classify_obvious_action_intent("帮我删除 dengbin 好友").is_action is True
    assert classify_obvious_action_intent("我和 dengbin 之前聊过什么？").is_action is True
    assert classify_obvious_action_intent("怎么删除 MySQL 数据库？").is_action is False


def test_action_intent_gate_skips_model_for_obvious_product_action() -> None:
    class _TaskManager:
        def __init__(self) -> None:
            self.requests = []

        async def run_once(self, request):
            self.requests.append(request)
            return SimpleNamespace(content='{"is_action": false, "confidence": 1, "reason": "should not run"}')

    async def scenario() -> None:
        task_manager = _TaskManager()
        decision = await AIActionIntentGate().classify("帮我搜索用户 dengbin", task_manager=task_manager)

        assert decision is not None
        assert decision.is_action is True
        assert task_manager.requests == []

    import asyncio

    asyncio.run(scenario())

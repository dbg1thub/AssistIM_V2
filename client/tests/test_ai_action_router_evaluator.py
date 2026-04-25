from __future__ import annotations

from tools.ai_action_prompt_benchmark import PromptBenchmarkCase, PromptCaseExpectation, load_golden_corpus
from tools.ai_action_router_evaluator import (
    ROUTE_ACTION_CANDIDATE,
    ROUTE_CHAT,
    ROUTE_UNKNOWN,
    evaluate_router_samples,
    expected_route_for_case,
    parse_router_output,
    summarize_router_results,
)


def test_parse_router_output_accepts_valid_classification_json() -> None:
    sample = parse_router_output(
        """
        ```json
        {
          "route": "action_candidate",
          "confidence": 0.86,
          "reason": "需要查询聊天记忆"
        }
        ```
        """
    )

    assert sample.valid_json is True
    assert sample.accepted_schema is True
    assert sample.unsafe_output is False
    assert sample.route == ROUTE_ACTION_CANDIDATE
    assert sample.effective_route == ROUTE_ACTION_CANDIDATE
    assert sample.confidence == 0.86
    assert sample.messages == []


def test_parse_router_output_rejects_executable_plan_fields() -> None:
    sample = parse_router_output(
        """
        {
          "route": "chat",
          "confidence": 0.91,
          "reason": "普通聊天",
          "steps": [
            {"action": "message.send", "args": {"content": "你好"}}
          ]
        }
        """
    )

    assert sample.valid_json is True
    assert sample.accepted_schema is False
    assert sample.unsafe_output is True
    assert sample.effective_route == ROUTE_UNKNOWN
    assert "forbidden router field: steps" in sample.messages


def test_parse_router_output_falls_back_to_unknown_when_confidence_is_low() -> None:
    sample = parse_router_output(
        '{"route": "action_candidate", "confidence": 0.42, "reason": "可能需要执行"}',
        min_confidence=0.6,
    )

    assert sample.accepted_schema is True
    assert sample.route == ROUTE_ACTION_CANDIDATE
    assert sample.effective_route == ROUTE_UNKNOWN
    assert "confidence below threshold" in sample.messages


def test_expected_route_for_case_uses_golden_action_expectation() -> None:
    assert (
        expected_route_for_case(
            PromptBenchmarkCase(
                name="history",
                user_input="我和 test3 聊过什么",
                expectation=PromptCaseExpectation(is_action=True),
            )
        )
        == ROUTE_ACTION_CANDIDATE
    )
    assert (
        expected_route_for_case(
            PromptBenchmarkCase(
                name="chat",
                user_input="你好",
                expectation=PromptCaseExpectation(is_action=False),
            )
        )
        == ROUTE_CHAT
    )
    assert expected_route_for_case(PromptBenchmarkCase(name="unknown", user_input="随便看看")) == ROUTE_UNKNOWN


def test_evaluate_router_samples_reports_accuracy_fallbacks_and_unsafe_outputs() -> None:
    cases = [
        PromptBenchmarkCase(
            name="chat_case",
            user_input="你好",
            expectation=PromptCaseExpectation(is_action=False),
        ),
        PromptBenchmarkCase(
            name="action_case",
            user_input="帮我总结和 test3 的聊天",
            expectation=PromptCaseExpectation(is_action=True),
        ),
        PromptBenchmarkCase(
            name="unsafe_case",
            user_input="帮我给张三发消息",
            expectation=PromptCaseExpectation(is_action=True),
        ),
    ]

    results = evaluate_router_samples(
        cases,
        {
            "chat_case": ['{"route": "chat", "confidence": 0.93, "reason": "普通聊天"}'],
            "action_case": ['{"route": "chat", "confidence": 0.88, "reason": "误判为聊天"}'],
            "unsafe_case": [
                '{"route": "action_candidate", "confidence": 0.95, "reason": "执行发送", "steps": []}'
            ],
        },
    )
    summary = summarize_router_results(results)

    assert summary["case_count"] == 3
    assert summary["sample_count"] == 3
    assert summary["accepted_schema_rate"] == 0.6667
    assert summary["route_accuracy"] == 0.3333
    assert summary["fallback_rate"] == 0.3333
    assert summary["unsafe_output_count"] == 1
    assert summary["failed_cases"] == [
        {
            "name": "action_case",
            "failed_sample_count": 1,
            "messages": ["route mismatch"],
        },
        {
            "name": "unsafe_case",
            "failed_sample_count": 1,
            "messages": ["forbidden router field: steps", "route mismatch"],
        },
    ]


def test_default_golden_corpus_can_seed_router_expectations() -> None:
    routes = {case.name: expected_route_for_case(case) for case in load_golden_corpus()}

    assert routes["chat_smalltalk"] == ROUTE_CHAT
    assert routes["history_direct_test3"] == ROUTE_ACTION_CANDIDATE
    assert routes["send_direct_message"] == ROUTE_ACTION_CANDIDATE

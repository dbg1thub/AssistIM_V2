from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tools.ai_action_prompt_benchmark import PromptBenchmarkCase, PromptCaseExpectation, load_golden_corpus
from tools.ai_action_router_evaluator import (
    ROUTE_ACTION_CANDIDATE,
    ROUTE_CHAT,
    ROUTE_UNKNOWN,
    RouterReplayRecord,
    build_router_request,
    evaluate_router_samples,
    evaluate_router_replay_file,
    expected_route_for_case,
    load_router_replay_records,
    parse_router_output,
    summarize_router_results,
    write_router_replay_records,
)
from tools.run_ai_action_router_corpus import run_router_corpus


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


def test_expected_route_for_case_prefers_router_expected_route() -> None:
    assert (
        expected_route_for_case(
            PromptBenchmarkCase(
                name="unsupported",
                user_input="帮我删除服务器数据库",
                expectation=PromptCaseExpectation(is_action=False),
                router_expected_route=ROUTE_ACTION_CANDIDATE,
            )
        )
        == ROUTE_ACTION_CANDIDATE
    )
    assert (
        expected_route_for_case(
            PromptBenchmarkCase(
                name="unclear",
                user_input="帮我处理一下",
                expectation=PromptCaseExpectation(is_action=False),
                router_expected_route=ROUTE_UNKNOWN,
            )
        )
        == ROUTE_UNKNOWN
    )


def test_expected_route_for_case_falls_back_to_action_expectation() -> None:
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
    assert routes["unsupported_delete_server_database"] == ROUTE_ACTION_CANDIDATE
    assert routes["group_ai_reply_not_enabled"] == ROUTE_ACTION_CANDIDATE


def test_build_router_request_uses_strict_classification_prompt() -> None:
    case = PromptBenchmarkCase(
        name="history",
        user_input="我和 test3 之前聊过什么？",
        expectation=PromptCaseExpectation(is_action=True),
    )

    request = build_router_request(case)

    assert request.stream is False
    assert request.must_be_local is True
    assert request.temperature == 0.0
    assert request.max_tokens <= 128
    assert request.max_output_chars <= 512
    assert request.metadata["source"] == "ai_action_router_corpus"
    assert "chat" in request.system_prompt
    assert "action_candidate" in request.system_prompt
    assert "unknown" in request.system_prompt
    assert "不要输出 steps" in request.system_prompt
    assert "message.send" in request.system_prompt
    assert "只输出一个 JSON 对象" in request.system_prompt
    assert request.messages == [{"role": "user", "content": "用户输入：我和 test3 之前聊过什么？"}]
    assert "history" not in request.messages[0]["content"]
    assert "action_candidate" not in request.messages[0]["content"]


def test_router_replay_jsonl_roundtrip_and_evaluation(tmp_path) -> None:
    output_path = tmp_path / "router-results.jsonl"
    records = [
        RouterReplayRecord(
            case_name="chat_case",
            user_input="你好",
            expected_route=ROUTE_CHAT,
            raw_output='{"route": "chat", "confidence": 0.92, "reason": "普通聊天"}',
            elapsed_ms=12,
            provider="fake",
            model="router-test",
        ),
        RouterReplayRecord(
            case_name="send_case",
            user_input="帮我给张三发消息",
            expected_route=ROUTE_ACTION_CANDIDATE,
            raw_output='{"route": "action_candidate", "confidence": 0.95, "reason": "需要进入 planner"}',
            elapsed_ms=15,
            provider="fake",
            model="router-test",
        ),
    ]

    write_router_replay_records(output_path, records)
    loaded = load_router_replay_records(output_path)
    results = evaluate_router_replay_file(
        [
            PromptBenchmarkCase(
                name="chat_case",
                user_input="你好",
                expectation=PromptCaseExpectation(is_action=False),
            ),
            PromptBenchmarkCase(
                name="send_case",
                user_input="帮我给张三发消息",
                expectation=PromptCaseExpectation(is_action=True),
            ),
        ],
        output_path,
    )
    summary = summarize_router_results(results)

    assert loaded == records
    assert output_path.read_text(encoding="utf-8").count("\n") == 2
    assert summary["sample_count"] == 2
    assert summary["route_accuracy"] == 1.0
    assert summary["unsafe_output_count"] == 0


def test_run_router_corpus_calls_task_manager_and_writes_jsonl(tmp_path) -> None:
    class FakeTaskManager:
        def __init__(self) -> None:
            self.requests = []

        async def run_once(self, request):
            self.requests.append(request)
            return SimpleNamespace(
                content='{"route": "chat", "confidence": 0.91, "reason": "普通聊天"}',
                provider="fake",
                model="router-test",
                error_code=None,
                error_message="",
            )

    output_path = tmp_path / "router-run.jsonl"
    task_manager = FakeTaskManager()
    cases = [
        PromptBenchmarkCase(
            name="chat_case",
            user_input="你好",
            expectation=PromptCaseExpectation(is_action=False),
        )
    ]

    records = asyncio.run(run_router_corpus(cases, task_manager=task_manager, output_path=output_path))

    assert len(task_manager.requests) == 1
    assert task_manager.requests[0].metadata["router_case_name"] == "chat_case"
    assert records == load_router_replay_records(output_path)
    assert records[0].case_name == "chat_case"
    assert records[0].expected_route == ROUTE_CHAT
    assert records[0].raw_output.startswith('{"route": "chat"')

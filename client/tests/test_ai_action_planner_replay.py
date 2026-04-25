from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tools.ai_action_planner_replay import (
    PlannerReplayRecord,
    build_planner_request,
    evaluate_planner_replay_file,
    load_planner_replay_records,
    write_planner_replay_records,
)
from tools.ai_action_prompt_benchmark import PromptBenchmarkCase, PromptCaseExpectation, summarize_results
from tools.run_ai_action_planner_corpus import run_planner_corpus


def test_build_planner_request_reuses_atomic_planner_prompt_and_schema() -> None:
    case = PromptBenchmarkCase(
        name="history",
        user_input="我和 test3 之前聊过什么？",
        expectation=PromptCaseExpectation(is_action=True),
    )

    request = build_planner_request(case)

    assert request.stream is False
    assert request.must_be_local is True
    assert request.temperature == 0.0
    assert request.max_tokens == 1024
    assert request.priority == 4
    assert request.response_format["type"] == "json_object"
    assert request.response_format["schema"]["required"] == ["is_action", "goal", "risk", "steps", "final"]
    assert request.metadata["source"] == "ai_action_planner_corpus"
    assert request.metadata["planner_schema"] == "atomic_steps_v1"
    assert "contact.resolve, memory.search, memory.summarize" in request.system_prompt
    assert "用户输入：我和 test3 之前聊过什么？" in request.messages[0]["content"]
    assert "router_expected_route" not in request.messages[0]["content"]


def test_planner_replay_jsonl_roundtrip_and_evaluation(tmp_path) -> None:
    output_path = tmp_path / "planner-results.jsonl"
    records = [
        PlannerReplayRecord(
            case_name="chat_case",
            user_input="你好",
            raw_output='{"is_action": false, "goal": "闲聊", "risk": "low", "steps": [], "final": {"type": "chat"}}',
            elapsed_ms=11,
            provider="fake",
            model="planner-test",
        ),
        PlannerReplayRecord(
            case_name="history_case",
            user_input="我和 test3 聊过什么",
            raw_output=(
                '{"is_action": true, "goal": "查询历史", "risk": "low", '
                '"steps": ['
                '{"id": "resolve_1", "action": "contact.resolve", "depends_on": [], "args": {"queries": ["test3"]}},'
                '{"id": "search_1", "action": "memory.search", "depends_on": ["resolve_1"], "args": {"time_scope": {"type": "all_history"}}},'
                '{"id": "sum_1", "action": "memory.summarize", "depends_on": ["search_1"], "args": {"source": "$search_1"}}'
                '], "final": {}}'
            ),
            elapsed_ms=17,
            provider="fake",
            model="planner-test",
        ),
    ]

    write_planner_replay_records(output_path, records)
    loaded = load_planner_replay_records(output_path)
    results = evaluate_planner_replay_file(
        [
            PromptBenchmarkCase(
                name="chat_case",
                user_input="你好",
                expectation=PromptCaseExpectation(is_action=False),
            ),
            PromptBenchmarkCase(
                name="history_case",
                user_input="我和 test3 聊过什么",
                expectation=PromptCaseExpectation(
                    is_action=True,
                    required_actions=("contact.resolve", "memory.search", "memory.summarize"),
                    contact_queries=("test3",),
                    require_all_history=True,
                ),
            ),
        ],
        output_path,
    )
    summary = summarize_results(results)

    assert loaded == records
    assert output_path.read_text(encoding="utf-8").count("\n") == 2
    assert summary["sample_count"] == 2
    assert summary["valid_json_rate"] == 1.0
    assert summary["expectation_pass_rate"] == 1.0
    assert summary["failed_cases"] == []


def test_planner_replay_evaluation_reports_failed_cases(tmp_path) -> None:
    output_path = tmp_path / "planner-failed.jsonl"
    write_planner_replay_records(
        output_path,
        [
            PlannerReplayRecord(
                case_name="send_case",
                user_input="帮我给张三发我晚点到",
                raw_output='{"is_action": false, "goal": "闲聊", "risk": "low", "steps": [], "final": {}}',
            )
        ],
    )

    results = evaluate_planner_replay_file(
        [
            PromptBenchmarkCase(
                name="send_case",
                user_input="帮我给张三发我晚点到",
                expectation=PromptCaseExpectation(
                    is_action=True,
                    required_actions=("contact.resolve", "message.draft", "user.confirm", "message.send"),
                ),
            )
        ],
        output_path,
    )
    summary = summarize_results(results)

    assert summary["expectation_pass_rate"] == 0.0
    assert summary["failed_cases"] == [
        {
            "name": "send_case",
            "failed_sample_count": 1,
            "messages": ["is_action mismatch", "missing required actions"],
        }
    ]


def test_run_planner_corpus_calls_task_manager_and_writes_jsonl(tmp_path) -> None:
    class FakeTaskManager:
        def __init__(self) -> None:
            self.requests = []

        async def run_once(self, request):
            self.requests.append(request)
            return SimpleNamespace(
                content='{"is_action": false, "goal": "闲聊", "risk": "low", "steps": [], "final": {}}',
                provider="fake",
                model="planner-test",
                error_code=None,
                error_message="",
            )

    output_path = tmp_path / "planner-run.jsonl"
    task_manager = FakeTaskManager()
    cases = [
        PromptBenchmarkCase(
            name="chat_case",
            user_input="你好",
            expectation=PromptCaseExpectation(is_action=False),
        )
    ]

    records = asyncio.run(run_planner_corpus(cases, task_manager=task_manager, output_path=output_path))

    assert len(task_manager.requests) == 1
    assert task_manager.requests[0].metadata["planner_case_name"] == "chat_case"
    assert records == load_planner_replay_records(output_path)
    assert records[0].case_name == "chat_case"
    assert records[0].raw_output.startswith('{"is_action": false')

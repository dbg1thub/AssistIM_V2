from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from client.managers.ai_action_workflow import AIActionPlanner
from tools.ai_action_planner_replay import (
    PlannerReplayRecord,
    annotate_planner_replay_records_with_workflow_repair,
    annotate_planner_replay_records,
    build_planner_request,
    evaluate_planner_replay_file,
    load_planner_replay_records,
    write_planner_replay_records,
)
from tools.ai_action_prompt_benchmark import (
    PromptBenchmarkCase,
    PromptCaseExpectation,
    PromptStepArgExpectation,
    summarize_results,
)
from tools.run_ai_action_planner_corpus import (
    evaluate_quality_gate,
    quality_gate_exit_code,
    run_planner_corpus,
    validate_planner_replay,
)


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
    action_enum = request.response_format["schema"]["properties"]["steps"]["items"]["properties"]["action"]["enum"]
    assert "contact.resolve" in action_enum
    assert "message.send" in action_enum
    assert "delete_server_database" not in action_enum
    assert request.metadata["source"] == "ai_action_planner_corpus"
    assert request.metadata["planner_schema_version"] == AIActionPlanner.PLANNER_SCHEMA_VERSION
    assert request.metadata["planner_prompt_version"] == AIActionPlanner.PLANNER_PROMPT_VERSION
    assert request.metadata["planner_prompt_kind"] == AIActionPlanner.PROMPT_NEW_ACTION
    assert "已注册 action 能力：" in request.system_prompt
    assert "contact.resolve" in request.system_prompt
    assert "memory.search" in request.system_prompt
    assert "memory.summarize" in request.system_prompt
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

    cases = [
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
    ]
    expected_records = annotate_planner_replay_records(cases, records)

    write_planner_replay_records(output_path, records, cases=cases)
    loaded = load_planner_replay_records(output_path)
    results = evaluate_planner_replay_file(cases, output_path)
    summary = summarize_results(results)
    payloads = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]

    assert loaded == expected_records
    assert output_path.read_text(encoding="utf-8").count("\n") == 2
    assert payloads[0]["planner_prompt_version"] == AIActionPlanner.PLANNER_PROMPT_VERSION
    assert payloads[0]["planner_schema_version"] == AIActionPlanner.PLANNER_SCHEMA_VERSION
    assert payloads[0]["plan_version"] == AIActionPlanner.PLAN_OUTPUT_VERSION
    assert payloads[0]["actions"] == []
    assert payloads[0]["validation_result"] == "passed"
    assert payloads[0]["diff_from_expected"] == []
    assert payloads[1]["actions"] == ["contact.resolve", "memory.search", "memory.summarize"]
    assert payloads[1]["validation_result"] == "passed"
    assert payloads[1]["diff_from_expected"] == []
    assert summary["sample_count"] == 2
    assert summary["valid_json_rate"] == 1.0
    assert summary["expectation_pass_rate"] == 1.0
    assert summary["failed_cases"] == []


def test_planner_replay_evaluation_reports_failed_cases(tmp_path) -> None:
    output_path = tmp_path / "planner-failed.jsonl"
    records = [
        PlannerReplayRecord(
            case_name="send_case",
            user_input="帮我给张三发我晚点到",
            raw_output='{"is_action": false, "goal": "闲聊", "risk": "low", "steps": [], "final": {}}',
        )
    ]
    cases = [
        PromptBenchmarkCase(
            name="send_case",
            user_input="帮我给张三发我晚点到",
            expectation=PromptCaseExpectation(
                is_action=True,
                required_actions=("contact.resolve", "message.draft", "user.confirm", "message.send"),
            ),
        )
    ]
    write_planner_replay_records(
        output_path,
        records,
        cases=cases,
    )

    loaded = load_planner_replay_records(output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8").strip())
    results = evaluate_planner_replay_file(cases, output_path)
    summary = summarize_results(results)

    assert loaded[0].validation_result == "failed"
    assert loaded[0].diff_from_expected == ("is_action mismatch", "missing required actions")
    assert payload["validation_result"] == "failed"
    assert payload["diff_from_expected"] == ["is_action mismatch", "missing required actions"]
    assert summary["expectation_pass_rate"] == 0.0
    assert summary["failed_cases"] == [
        {
            "name": "send_case",
            "failed_sample_count": 1,
            "messages": ["is_action mismatch", "missing required actions"],
        }
    ]
    assert summary["failure_analysis"]["raw"]["category_counts"] == {
        "wrong_is_action": 1,
        "missing_action": 1,
    }
    assert summary["failure_analysis"]["raw"]["cases"] == [
        {
            "name": "send_case",
            "failed_sample_count": 1,
            "category_counts": {
                "wrong_is_action": 1,
                "missing_action": 1,
            },
            "messages": ["is_action mismatch", "missing required actions"],
        }
    ]


def test_planner_replay_runtime_evaluation_normalizes_send_plan(tmp_path) -> None:
    output_path = tmp_path / "planner-runtime-send.jsonl"
    raw_output = (
        '{"is_action": true, "goal": "发送消息", "risk": "medium", "steps": ['
        '{"id": "resolve_target", "action": "contact.resolve", "depends_on": [], '
        '"args": {"queries": ["张三"], "allow_multiple": false}},'
        '{"id": "draft_message", "action": "message.draft", "depends_on": ["resolve_target"], '
        '"args": {"target": "$resolve_target.contacts[0]", "content": "我晚点到"}},'
        '{"id": "confirm_send", "action": "user.confirm", "depends_on": ["draft_message"], '
        '"args": {"risk": "medium", "preview": {"operation": "发送消息", '
        '"target": "$draft_message.target", "content": "$draft_message.content"}}},'
        '{"id": "send_message", "action": "message.send", "depends_on": ["confirm_send"], '
        '"args": {"target": "$draft_message.target_entity", "content": "$draft_message.content", '
        '"preview": "$draft_message.preview", "idempotency_key": "$draft_message.idempotency_key"}},'
        '{"id": "resolve_target", "action": "contact.resolve", "depends_on": [], '
        '"args": {"queries": ["张三"], "allow_multiple": false}}'
        '], "final": {}}'
    )
    cases = [
        PromptBenchmarkCase(
            name="send_case",
            user_input="帮我给张三发我晚点到",
            expectation=PromptCaseExpectation(
                is_action=True,
                risk="high",
                required_actions=("contact.resolve", "message.draft", "user.confirm", "message.send"),
                required_action_sequence=("contact.resolve", "message.draft", "user.confirm", "message.send"),
                contact_queries=("张三",),
                requires_confirmation=True,
                expected_content="我晚点到",
            ),
        )
    ]
    write_planner_replay_records(
        output_path,
        [PlannerReplayRecord(case_name="send_case", user_input="帮我给张三发我晚点到", raw_output=raw_output)],
        cases=cases,
    )

    loaded = load_planner_replay_records(output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8").strip())
    summary = summarize_results(evaluate_planner_replay_file(cases, output_path))

    assert loaded[0].validation_result == "failed"
    assert loaded[0].runtime_validation_result == "passed"
    assert loaded[0].runtime_safe is True
    assert loaded[0].runtime_actions == ("contact.resolve", "message.draft", "user.confirm", "message.send")
    assert payload["validation_result"] == "failed"
    assert payload["runtime_validation_result"] == "passed"
    assert payload["runtime_safe"] is True
    assert payload["runtime_actions"] == ["contact.resolve", "message.draft", "user.confirm", "message.send"]
    assert summary["raw_expectation_pass_rate"] == 0.0
    assert summary["runtime_expectation_pass_rate"] == 1.0
    assert summary["runtime_safe_rate"] == 1.0


def test_planner_replay_runtime_evaluation_uses_registered_write_contracts(tmp_path) -> None:
    output_path = tmp_path / "planner-runtime-friend-accept.jsonl"
    raw_output = (
        '{"is_action": true, "goal": "接受好友申请", "risk": "high", "steps": ['
        '{"id": "confirm_req_1", "action": "user.confirm", "depends_on": [], '
        '"args": {"risk": "high", "preview": {"operation": "接受好友申请", '
        '"target": {"request_id": "req-1"}, "content": "接受好友申请 req-1"}}},'
        '{"id": "accept_req_1", "action": "friend.request.accept", "depends_on": ["confirm_req_1"], '
        '"args": {"request_id": "req-1", "preview": {"operation": "接受好友申请", '
        '"target": {"request_id": "req-1"}, "idempotency_key": "..."}}}'
        '], "final": {"status": {"action": "accept_req_1"}}}'
    )
    cases = [
        PromptBenchmarkCase(
            name="accept_case",
            user_input="接受 req-1 这个好友申请",
            expectation=PromptCaseExpectation(
                is_action=True,
                risk="high",
                required_actions=("user.confirm", "friend.request.accept"),
                required_action_sequence=("user.confirm", "friend.request.accept"),
                requires_confirmation=True,
                expected_content="req-1",
                required_step_args=(
                    PromptStepArgExpectation(action="friend.request.accept", path="preview", ref_action="user.confirm"),
                    PromptStepArgExpectation(action="friend.request.accept", path="idempotency_key", ref_action="user.confirm"),
                ),
            ),
        )
    ]
    write_planner_replay_records(
        output_path,
        [PlannerReplayRecord(case_name="accept_case", user_input="接受 req-1 这个好友申请", raw_output=raw_output)],
        cases=cases,
    )

    loaded = load_planner_replay_records(output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8").strip())
    summary = summarize_results(evaluate_planner_replay_file(cases, output_path))

    assert loaded[0].validation_result == "failed"
    assert loaded[0].runtime_validation_result == "passed"
    assert loaded[0].runtime_safe is True
    assert loaded[0].runtime_actions == ("user.confirm", "friend.request.accept")
    assert payload["runtime_validation_result"] == "passed"
    assert payload["runtime_actions"] == ["user.confirm", "friend.request.accept"]
    assert summary["runtime_expectation_pass_rate"] == 1.0


def test_planner_replay_evaluation_rejects_send_refs_that_do_not_point_to_draft(tmp_path) -> None:
    output_path = tmp_path / "planner-send-ref-action.jsonl"
    raw_output = (
        '{"is_action": true, "goal": "发送消息", "risk": "high", "steps": ['
        '{"id": "resolve", "action": "contact.resolve", "depends_on": [], '
        '"args": {"queries": ["张三"], "allow_multiple": false}},'
        '{"id": "draft", "action": "message.draft", "depends_on": ["resolve"], '
        '"args": {"target": "$resolve.contacts[0]", "content": "我晚点到"}},'
        '{"id": "confirm", "action": "user.confirm", "depends_on": ["draft"], '
        '"args": {"risk": "high", "preview": {"operation": "发送", '
        '"target": "$draft.target", "content": "$draft.content"}}},'
        '{"id": "send", "action": "message.send", "depends_on": ["confirm"], '
        '"args": {"target": "$confirm.target_entity", "content": "$confirm.content", '
        '"preview": "$confirm.preview", "idempotency_key": "$confirm.idempotency_key"}}'
        '], "final": {}}'
    )
    cases = [
        PromptBenchmarkCase(
            name="send_case",
            user_input="帮我给张三发我晚点到",
            expectation=PromptCaseExpectation(
                is_action=True,
                required_actions=("contact.resolve", "message.draft", "user.confirm", "message.send"),
                required_step_args=(
                    PromptStepArgExpectation(action="message.send", path="target", ref_action="message.draft"),
                    PromptStepArgExpectation(action="message.send", path="content", ref_action="message.draft"),
                    PromptStepArgExpectation(action="message.send", path="idempotency_key", ref_action="message.draft"),
                ),
            ),
        )
    ]
    write_planner_replay_records(
        output_path,
        [PlannerReplayRecord(case_name="send_case", user_input="帮我给张三发我晚点到", raw_output=raw_output)],
        cases=cases,
    )

    loaded = load_planner_replay_records(output_path)
    results = evaluate_planner_replay_file(cases, output_path)

    assert loaded[0].validation_result == "failed"
    assert "required step args mismatch" in loaded[0].diff_from_expected
    assert results[0].samples[0].expectation_passed is False
    summary = summarize_results(results)
    assert summary["failure_analysis"]["raw"]["category_counts"] == {"wrong_args": 1}


def test_planner_replay_runtime_evaluation_marks_unsafe_plan_blocked(tmp_path) -> None:
    output_path = tmp_path / "planner-runtime-blocked.jsonl"
    raw_output = (
        '{"is_action": true, "goal": "删除服务器数据库", "risk": "high", "steps": ['
        '{"id": "resolve_target", "action": "contact.resolve", "depends_on": [], '
        '"args": {"queries": ["服务器数据库"]}},'
        '{"id": "draft_message", "action": "message.draft", "depends_on": ["resolve_target"], '
        '"args": {"target": "$resolve_target.contacts[0]", "content": "请确认删除服务器数据库。"}},'
        '{"id": "confirm_send", "action": "user.confirm", "depends_on": ["draft_message"], '
        '"args": {"risk": "high", "preview": {"operation": "发送消息", '
        '"target": "$draft_message.target", "content": "$draft_message.content"}}},'
        '{"id": "send_message", "action": "message.send", "depends_on": ["confirm_send"], '
        '"args": {"target": "$draft_message.target_entity", "content": "$draft_message.content", '
        '"preview": "$draft_message.preview", "idempotency_key": "$draft_message.idempotency_key"}},'
        '{"id": "delete_db", "action": "system_action", "depends_on": ["send_message"], '
        '"args": {"database_name": "服务器数据库"}}'
        '], "final": {}}'
    )
    cases = [
        PromptBenchmarkCase(
            name="delete_case",
            user_input="帮我删除服务器数据库",
            expectation=PromptCaseExpectation(
                is_action=False,
                forbidden_actions=("contact.resolve", "memory.search", "memory.summarize", "user.confirm", "message.send"),
            ),
        )
    ]
    write_planner_replay_records(
        output_path,
        [PlannerReplayRecord(case_name="delete_case", user_input="帮我删除服务器数据库", raw_output=raw_output)],
        cases=cases,
    )

    loaded = load_planner_replay_records(output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8").strip())
    summary = summarize_results(evaluate_planner_replay_file(cases, output_path))

    assert loaded[0].validation_result == "failed"
    assert loaded[0].runtime_validation_result == "blocked"
    assert loaded[0].runtime_safe is True
    assert "runtime blocked: unknown_action" in loaded[0].runtime_diff_from_expected
    assert payload["runtime_validation_result"] == "blocked"
    assert payload["runtime_safe"] is True
    assert "runtime blocked: unknown_action" in payload["runtime_diff_from_expected"]
    assert summary["raw_expectation_pass_rate"] == 0.0
    assert summary["runtime_expectation_pass_rate"] == 0.0
    assert summary["runtime_safe_rate"] == 1.0
    assert summary["runtime_blocked_cases"] == [
        {
            "name": "delete_case",
            "blocked_sample_count": 1,
            "messages": ["runtime blocked: unknown_action"],
        }
    ]
    assert summary["failure_analysis"]["runtime"]["category_counts"] == {
        "unsafe_or_blocked": 1,
    }


def test_planner_replay_workflow_repair_skips_model_when_normalizer_fixes_send_plan(tmp_path) -> None:
    class FakeRepairTaskManager:
        def __init__(self) -> None:
            self.requests = []

        async def run_once(self, request):
            self.requests.append(request)
            return SimpleNamespace(
                content=(
                    '{"is_action": true, "goal": "发送消息", "risk": "high", "steps": ['
                    '{"id": "resolve_target", "action": "contact.resolve", "depends_on": [], '
                    '"args": {"queries": ["张三"], "allow_multiple": false}},'
                    '{"id": "draft_message", "action": "message.draft", "depends_on": ["resolve_target"], '
                    '"args": {"target": "$resolve_target.contacts[0]", "content": "我晚点到"}},'
                    '{"id": "confirm_send", "action": "user.confirm", "depends_on": ["draft_message"], '
                    '"args": {"risk": "high", "preview": {"operation": "发送消息", '
                    '"target": "$draft_message.target", "content": "$draft_message.content"}}},'
                    '{"id": "send_message", "action": "message.send", "depends_on": ["draft_message", "confirm_send"], '
                    '"args": {"target": "$draft_message.target_entity", "content": "$draft_message.content", '
                    '"preview": "$confirm_send.preview", "idempotency_key": "$draft_message.idempotency_key"}}'
                    '], "final": {}}'
                ),
                provider="fake",
                model="repair-test",
                error_code=None,
                error_message="",
            )

    output_path = tmp_path / "planner-workflow-repair-send.jsonl"
    raw_output = (
        '{"is_action": true, "goal": "发送消息", "risk": "high", "steps": ['
        '{"id": "resolve_target", "action": "contact.resolve", "depends_on": [], '
        '"args": {"queries": ["张三"], "allow_multiple": false}},'
        '{"id": "draft_message", "action": "message.draft", "depends_on": ["resolve_target"], '
        '"args": {"target": "$resolve_target.contacts[0]", "content": "我晚点到"}},'
        '{"id": "confirm_send", "action": "user.confirm", "depends_on": ["draft_message"], '
        '"args": {"risk": "high", "preview": {"operation": "发送消息", '
        '"target": "$draft_message.target", "content": "$draft_message.content"}}},'
        '{"id": "send_message", "action": "message.send", "depends_on": ["draft_message", "confirm_send"], '
        '"args": {"target": "$draft_message.target_entity", "content": "$draft_message.content", '
        '"preview": {"operation": "发送消息", "target": "$draft_message.target", "content": "$draft_message.content"}, '
        '"idempotency_key": "$draft_message.idempotency_key"}}'
        '], "final": {}}'
    )
    cases = [
        PromptBenchmarkCase(
            name="send_case",
            user_input="帮我给张三发我晚点到",
            expectation=PromptCaseExpectation(
                is_action=True,
                risk="high",
                required_actions=("contact.resolve", "message.draft", "user.confirm", "message.send"),
                required_action_sequence=("contact.resolve", "message.draft", "user.confirm", "message.send"),
                contact_queries=("张三",),
                requires_confirmation=True,
                expected_content="我晚点到",
                required_step_args=(
                    PromptStepArgExpectation(action="message.send", path="preview", starts_with="$"),
                ),
            ),
        )
    ]
    repair_task_manager = FakeRepairTaskManager()

    records = asyncio.run(
        annotate_planner_replay_records_with_workflow_repair(
            cases,
            [PlannerReplayRecord(case_name="send_case", user_input="帮我给张三发我晚点到", raw_output=raw_output)],
            task_manager=repair_task_manager,
        )
    )
    write_planner_replay_records(output_path, records)

    loaded = load_planner_replay_records(output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8").strip())
    summary = summarize_results(evaluate_planner_replay_file(cases, output_path))

    assert repair_task_manager.requests == []
    assert loaded[0].runtime_validation_result == "passed"
    assert loaded[0].workflow_repair_attempted is False
    assert loaded[0].workflow_repair_result == "passed"
    assert loaded[0].workflow_repair_safe is True
    assert loaded[0].workflow_repair_actions == ("contact.resolve", "message.draft", "user.confirm", "message.send")
    assert payload["workflow_repair_attempted"] is False
    assert payload["workflow_repair_result"] == "passed"
    assert payload["workflow_repair_safe"] is True
    assert summary["workflow_repair_expectation_pass_rate"] == 1.0
    assert summary["workflow_repair_safe_rate"] == 1.0
    assert summary["workflow_repair_attempt_rate"] == 0.0


def test_planner_replay_workflow_repair_blocks_unknown_action_without_model_call(tmp_path) -> None:
    class FakeRepairTaskManager:
        def __init__(self) -> None:
            self.requests = []

        async def run_once(self, request):
            self.requests.append(request)
            return SimpleNamespace(content="{}")

    output_path = tmp_path / "planner-workflow-repair-blocked.jsonl"
    raw_output = (
        '{"is_action": true, "goal": "删除服务器数据库", "risk": "high", "steps": ['
        '{"id": "delete_db", "action": "system_action", "depends_on": [], '
        '"args": {"database_name": "服务器数据库"}}'
        '], "final": {}}'
    )
    cases = [
        PromptBenchmarkCase(
            name="delete_case",
            user_input="帮我删除服务器数据库",
            expectation=PromptCaseExpectation(is_action=False, forbidden_actions=("message.send",)),
        )
    ]
    repair_task_manager = FakeRepairTaskManager()

    records = asyncio.run(
        annotate_planner_replay_records_with_workflow_repair(
            cases,
            [PlannerReplayRecord(case_name="delete_case", user_input="帮我删除服务器数据库", raw_output=raw_output)],
            task_manager=repair_task_manager,
        )
    )
    write_planner_replay_records(output_path, records)

    loaded = load_planner_replay_records(output_path)
    summary = summarize_results(evaluate_planner_replay_file(cases, output_path))

    assert repair_task_manager.requests == []
    assert loaded[0].workflow_repair_attempted is False
    assert loaded[0].workflow_repair_result == "blocked"
    assert loaded[0].workflow_repair_safe is True
    assert "workflow repair blocked: unknown_action" in loaded[0].workflow_repair_diff_from_expected
    assert summary["workflow_repair_safe_rate"] == 1.0
    assert summary["workflow_repair_blocked_cases"] == [
        {
            "name": "delete_case",
            "blocked_sample_count": 1,
            "messages": ["workflow repair blocked: unknown_action"],
        }
    ]


def test_planner_replay_workflow_repair_blocks_non_contract_side_effect_without_model_call(tmp_path) -> None:
    class FakeRepairTaskManager:
        def __init__(self) -> None:
            self.requests = []

        async def run_once(self, request):
            self.requests.append(request)
            return SimpleNamespace(content="{}")

    output_path = tmp_path / "planner-workflow-repair-side-effect.jsonl"
    raw_output = (
        '{"is_action": true, "goal": "发送消息", "risk": "high", "steps": ['
        '{"id": "resolve_target", "action": "contact.resolve", "depends_on": [], '
        '"args": {"queries": ["张三"], "allow_multiple": false}},'
        '{"id": "draft_message", "action": "message.draft", "depends_on": ["resolve_target"], '
        '"args": {"target": "$resolve_target.contacts[0]", "content": "我晚点到"}},'
        '{"id": "confirm_send", "action": "user.confirm", "depends_on": ["draft_message"], '
        '"args": {"risk": "high", "preview": {"operation": "发送消息", '
        '"target": "$draft_message.target", "content": "$draft_message.content"}}},'
        '{"id": "send_message", "action": "message.send", "depends_on": ["draft_message", "confirm_send"], '
        '"args": {"target": "$draft_message.target_entity", "content": "$draft_message.content", '
        '"preview": "$confirm_send.preview", "idempotency_key": "$draft_message.idempotency_key"}},'
        '{"id": "bad_tail", "action": "memory.search", "depends_on": ["send_message"], '
        '"args": {"participant_match": "张三", "question": "不应执行"}}'
        '], "final": {}}'
    )
    cases = [
        PromptBenchmarkCase(
            name="send_case",
            user_input="帮我给张三发我晚点到",
            expectation=PromptCaseExpectation(
                is_action=True,
                required_actions=("contact.resolve", "message.draft", "user.confirm", "message.send"),
            ),
        )
    ]
    repair_task_manager = FakeRepairTaskManager()

    records = asyncio.run(
        annotate_planner_replay_records_with_workflow_repair(
            cases,
            [PlannerReplayRecord(case_name="send_case", user_input="帮我给张三发我晚点到", raw_output=raw_output)],
            task_manager=repair_task_manager,
        )
    )
    write_planner_replay_records(output_path, records)

    loaded = load_planner_replay_records(output_path)

    assert repair_task_manager.requests == []
    assert loaded[0].workflow_repair_attempted is False
    assert loaded[0].workflow_repair_result == "blocked"
    assert loaded[0].workflow_repair_safe is True
    assert "workflow repair blocked: side_effect_plan" in loaded[0].workflow_repair_diff_from_expected


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
    assert task_manager.requests[0].metadata["planner_prompt_version"] == AIActionPlanner.PLANNER_PROMPT_VERSION
    assert task_manager.requests[0].metadata["planner_schema_version"] == AIActionPlanner.PLANNER_SCHEMA_VERSION
    assert records == load_planner_replay_records(output_path)
    assert records[0].case_name == "chat_case"
    assert records[0].raw_output.startswith('{"is_action": false')
    assert records[0].actions == ()
    assert records[0].validation_result == "passed"


def test_run_planner_corpus_filters_cases_and_repeats_samples(tmp_path) -> None:
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

    output_path = tmp_path / "planner-repeat.jsonl"
    task_manager = FakeTaskManager()
    cases = [
        PromptBenchmarkCase(
            name="chat_case",
            user_input="你好",
            expectation=PromptCaseExpectation(is_action=False),
        ),
        PromptBenchmarkCase(
            name="send_case",
            user_input="帮我给张三发我晚点到",
            expectation=PromptCaseExpectation(is_action=True),
        ),
    ]

    records = asyncio.run(
        run_planner_corpus(
            cases,
            task_manager=task_manager,
            output_path=output_path,
            case_names=("chat_case",),
            repeat=3,
        )
    )

    assert len(task_manager.requests) == 3
    assert [request.metadata["planner_case_name"] for request in task_manager.requests] == [
        "chat_case",
        "chat_case",
        "chat_case",
    ]
    assert [request.metadata["planner_case_iteration"] for request in task_manager.requests] == [1, 2, 3]
    assert [request.metadata["planner_case_repeat"] for request in task_manager.requests] == [3, 3, 3]
    assert [record.case_name for record in records] == ["chat_case", "chat_case", "chat_case"]
    assert [record.metadata["planner_case_iteration"] for record in records] == [1, 2, 3]
    assert [record.metadata["planner_case_repeat"] for record in records] == [3, 3, 3]
    assert records == load_planner_replay_records(output_path)


def test_run_planner_corpus_rejects_unknown_case_name(tmp_path) -> None:
    class FakeTaskManager:
        async def run_once(self, request):
            del request
            return SimpleNamespace(content="{}", provider="fake", model="planner-test")

    cases = [
        PromptBenchmarkCase(
            name="chat_case",
            user_input="你好",
            expectation=PromptCaseExpectation(is_action=False),
        )
    ]

    with pytest.raises(ValueError, match="unknown golden case name: missing_case"):
        asyncio.run(
            run_planner_corpus(
                cases,
                task_manager=FakeTaskManager(),
                output_path=tmp_path / "unused.jsonl",
                case_names=("missing_case",),
            )
        )


def test_validate_planner_replay_evaluates_existing_jsonl_without_model(tmp_path) -> None:
    output_path = tmp_path / "planner-existing.jsonl"
    summary_path = tmp_path / "planner-summary.json"
    cases = [
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
                required_action_sequence=("contact.resolve", "memory.search", "memory.summarize"),
                contact_queries=("test3",),
                require_all_history=True,
            ),
        ),
    ]
    write_planner_replay_records(
        output_path,
        [
            PlannerReplayRecord(
                case_name="chat_case",
                user_input="你好",
                raw_output='{"is_action": false, "goal": "闲聊", "risk": "low", "steps": [], "final": {"type": "chat"}}',
                provider="fake",
                model="planner-test",
            ),
            PlannerReplayRecord(
                case_name="history_case",
                user_input="我和 test3 聊过什么",
                raw_output=(
                    '{"is_action": true, "goal": "查询历史", "risk": "low", '
                    '"steps": ['
                    '{"id": "resolve", "action": "contact.resolve", "depends_on": [], "args": {"queries": ["test3"]}},'
                    '{"id": "search", "action": "memory.search", "depends_on": ["resolve"], '
                    '"args": {"participants": "$resolve.contacts", "time_scope": {"type": "all_history"}}},'
                    '{"id": "summarize", "action": "memory.summarize", "depends_on": ["search"], '
                    '"args": {"source": "$search"}}'
                    '], "final": {"source": "$summarize"}}'
                ),
                provider="fake",
                model="planner-test",
            ),
        ],
        cases=cases,
    )

    summary = validate_planner_replay(cases, output_path, summary_path=summary_path)
    written_summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["mode"] == "validate_only"
    assert summary["output_path"] == str(output_path)
    assert summary["replay_record_count"] == 2
    assert summary["sample_count"] == 2
    assert summary["valid_json_rate"] == 1.0
    assert summary["expectation_pass_rate"] == 1.0
    assert written_summary == summary
    assert summary["failure_analysis"]["raw"]["failed_sample_count"] == 0


def test_ai_action_quality_gate_passes_with_runtime_and_workflow_baseline() -> None:
    summary = {
        "runtime_expectation_pass_rate": 1.0,
        "runtime_safe_rate": 1.0,
        "workflow_repair_expectation_pass_rate": 1.0,
        "workflow_repair_safe_rate": 1.0,
    }

    gate = evaluate_quality_gate(summary)

    assert gate["enabled"] is True
    assert gate["passed"] is True
    assert gate["failures"] == []
    assert [item["metric"] for item in gate["checked_metrics"]] == [
        "runtime_expectation_pass_rate",
        "runtime_safe_rate",
        "workflow_repair_expectation_pass_rate",
        "workflow_repair_safe_rate",
    ]
    assert quality_gate_exit_code({"quality_gate": gate}) == 0


def test_ai_action_quality_gate_fails_for_missing_or_below_baseline_metrics() -> None:
    summary = {
        "runtime_expectation_pass_rate": 1.0,
        "runtime_safe_rate": 0.999,
        "workflow_repair_expectation_pass_rate": 1.0,
    }

    gate = evaluate_quality_gate(summary)

    assert gate["passed"] is False
    assert gate["failures"] == [
        {
            "metric": "runtime_safe_rate",
            "actual": 0.999,
            "expected_min": 1.0,
            "reason": "below_threshold",
        },
        {
            "metric": "workflow_repair_safe_rate",
            "actual": None,
            "expected_min": 1.0,
            "reason": "missing_metric",
        },
    ]
    assert quality_gate_exit_code({"quality_gate": gate}) == 1


def test_ai_action_quality_gate_fails_when_selected_case_has_no_sample() -> None:
    summary = {
        "runtime_expectation_pass_rate": 1.0,
        "runtime_safe_rate": 1.0,
        "workflow_repair_expectation_pass_rate": 1.0,
        "workflow_repair_safe_rate": 1.0,
        "cases": [
            {"name": "covered_case", "sample_count": 1},
            {"name": "missing_case", "sample_count": 0},
        ],
    }

    gate = evaluate_quality_gate(summary)

    assert gate["passed"] is False
    assert gate["missing_case_samples"] == ["missing_case"]
    assert gate["failures"] == []
    assert quality_gate_exit_code({"quality_gate": gate}) == 1


def test_validate_planner_replay_can_attach_quality_gate_result(tmp_path) -> None:
    output_path = tmp_path / "planner-quality-gate.jsonl"
    cases = [
        PromptBenchmarkCase(
            name="chat_case",
            user_input="你好",
            expectation=PromptCaseExpectation(is_action=False),
        )
    ]
    write_planner_replay_records(
        output_path,
        [
            PlannerReplayRecord(
                case_name="chat_case",
                user_input="你好",
                raw_output='{"is_action": false, "goal": "闲聊", "risk": "low", "steps": [], "final": {}}',
                workflow_repair_actions=(),
                workflow_repair_result="passed",
                workflow_repair_attempted=False,
                workflow_repair_safe=True,
                workflow_repair_diff_from_expected=(),
            )
        ],
        cases=cases,
    )

    summary = validate_planner_replay(cases, output_path, quality_gate=True)

    assert summary["quality_gate"]["passed"] is True
    assert quality_gate_exit_code(summary) == 0

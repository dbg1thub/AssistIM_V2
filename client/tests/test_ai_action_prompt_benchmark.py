from __future__ import annotations

from tools.ai_action_prompt_benchmark import (
    CaseBenchmarkResult,
    PromptBenchmarkCase,
    PromptCaseExpectation,
    PromptStepArgExpectation,
    SampleResult,
    canonical_structural_signature,
    evaluate_case,
    parse_plan_json,
    summarize_results,
)


def test_parse_plan_json_extracts_fenced_object() -> None:
    parsed, valid = parse_plan_json(
        """
        ```json
        {
          "goal": "查询历史",
          "risk": "low",
          "steps": [],
          "final": {}
        }
        ```
        """
    )

    assert valid is True
    assert parsed is not None
    assert parsed["risk"] == "low"


def test_canonical_structural_signature_rewrites_ids_and_ignores_display_text() -> None:
    first = {
        "goal": "send",
        "risk": "high",
        "steps": [
            {
                "id": "draft_a",
                "action": "message.draft",
                "depends_on": [],
                "args": {"content": "hello"},
                "display_text": "first",
            },
            {
                "id": "confirm_a",
                "action": "user.confirm",
                "depends_on": ["draft_a"],
                "args": {"title": "确认发送"},
            },
            {
                "id": "send_a",
                "action": "message.send",
                "depends_on": ["confirm_a"],
                "args": {"draft_ref": "$draft_a.content"},
            },
        ],
        "final": {"source": "$send_a.result"},
    }
    second = {
        "goal": "send",
        "risk": "high",
        "steps": [
            {
                "id": "x1",
                "action": "message.draft",
                "depends_on": [],
                "args": {"content": "hello"},
                "display_text": "second",
                "explanation": "ignored",
            },
            {
                "id": "x2",
                "action": "user.confirm",
                "depends_on": ["x1"],
                "args": {"title": "确认发送"},
            },
            {
                "id": "x3",
                "action": "message.send",
                "depends_on": ["x2"],
                "args": {"draft_ref": "$x1.content"},
            },
        ],
        "final": {"source": "$x3.result"},
    }

    assert canonical_structural_signature(first) == canonical_structural_signature(second)


def test_evaluate_case_accepts_extra_contact_aliases_and_transitive_confirmation() -> None:
    plan = {
        "goal": "send",
        "risk": "high",
        "steps": [
            {
                "id": "resolve_1",
                "action": "contact.resolve",
                "depends_on": [],
                "args": {"queries": ["张三", "zhangsan"]},
            },
            {
                "id": "confirm_1",
                "action": "user.confirm",
                "depends_on": ["resolve_1"],
                "args": {"title": "确认"},
            },
            {
                "id": "draft_1",
                "action": "message.draft",
                "depends_on": ["confirm_1"],
                "args": {"content": "我晚点到"},
            },
            {
                "id": "send_1",
                "action": "message.send",
                "depends_on": ["draft_1"],
                "args": {"content": "我晚点到"},
            },
        ],
        "final": {},
    }
    expect = PromptCaseExpectation(
        required_actions=("contact.resolve", "message.draft", "user.confirm", "message.send"),
        risk="high",
        contact_queries=("张三",),
        requires_confirmation=True,
        expected_content="我晚点到",
    )

    checks, messages = evaluate_case(plan, expect)

    assert all(checks.values()) is True
    assert messages == []


def test_evaluate_case_checks_all_history() -> None:
    plan = {
        "goal": "history",
        "risk": "low",
        "steps": [
            {
                "id": "resolve_1",
                "action": "contact.resolve",
                "depends_on": [],
                "args": {"queries": ["test3"]},
            },
            {
                "id": "search_1",
                "action": "memory.search",
                "depends_on": ["resolve_1"],
                "args": {"time_scope": {"type": "all_history"}},
            },
            {
                "id": "sum_1",
                "action": "memory.summarize",
                "depends_on": ["search_1"],
                "args": {"source": "$search_1"},
            },
        ],
        "final": {},
    }

    checks, messages = evaluate_case(
        plan,
        PromptCaseExpectation(
            required_actions=("contact.resolve", "memory.search", "memory.summarize"),
            risk="low",
            contact_queries=("test3",),
            require_all_history=True,
        ),
    )

    assert all(checks.values()) is True
    assert messages == []


def test_evaluate_case_checks_required_step_args() -> None:
    plan = {
        "goal": "send",
        "risk": "high",
        "steps": [
            {
                "id": "resolve_1",
                "action": "contact.resolve",
                "depends_on": [],
                "args": {"queries": ["张三"], "allow_multiple": False},
            },
            {
                "id": "draft_1",
                "action": "message.draft",
                "depends_on": ["resolve_1"],
                "args": {"target": "$resolve_1.contacts[0]", "content": "我晚点到"},
            },
            {
                "id": "confirm_1",
                "action": "user.confirm",
                "depends_on": ["draft_1"],
                "args": {"risk": "high", "preview": {"operation": "发送消息"}},
            },
            {
                "id": "send_1",
                "action": "message.send",
                "depends_on": ["confirm_1"],
                "args": {
                    "target": "$draft_1.target_entity",
                    "content": "$draft_1.content",
                    "preview": "$draft_1.preview",
                    "idempotency_key": "$draft_1.idempotency_key",
                },
            },
        ],
        "final": {},
    }
    expect = PromptCaseExpectation(
        required_step_args=(
            PromptStepArgExpectation(action="contact.resolve", path="allow_multiple", equals="False"),
            PromptStepArgExpectation(action="message.send", path="idempotency_key", starts_with="$draft_1."),
            PromptStepArgExpectation(action="message.send", path="preview", starts_with="$draft_1."),
        )
    )

    checks, messages = evaluate_case(plan, expect)

    assert checks["required_step_args"] is True
    assert messages == []


def test_summarize_results_reports_structural_stability_by_case() -> None:
    case = PromptBenchmarkCase(name="history", user_input="我和test3聊过什么？")
    stable_signature = '{"risk":"low"}'
    result = CaseBenchmarkResult(
        case=case,
        samples=[
            SampleResult(
                iteration=1,
                elapsed_ms=100,
                duration_ms=90,
                queue_wait_ms=0,
                prompt_chars=200,
                raw_output="{}",
                parsed_plan={"goal": "a"},
                valid_json=True,
                expectation_passed=True,
                checks={"valid_json": True},
                check_messages=[],
                structural_signature=stable_signature,
                raw_signature='{"goal":"a"}',
            ),
            SampleResult(
                iteration=2,
                elapsed_ms=120,
                duration_ms=110,
                queue_wait_ms=0,
                prompt_chars=200,
                raw_output="{}",
                parsed_plan={"goal": "b"},
                valid_json=True,
                expectation_passed=False,
                checks={"valid_json": True, "required_actions": False},
                check_messages=["missing required actions"],
                structural_signature=stable_signature,
                raw_signature='{"goal":"b"}',
                error_code="AI_MODEL_UNAVAILABLE",
                error_message="runtime missing",
            ),
        ],
    )

    summary = summarize_results([result])

    assert summary["case_count"] == 1
    assert summary["sample_count"] == 2
    assert summary["valid_json_rate"] == 1.0
    assert summary["expectation_pass_rate"] == 0.5
    assert summary["error_codes"] == {"AI_MODEL_UNAVAILABLE": 1}
    assert summary["cases"][0]["structural_stability"] == 1.0
    assert summary["cases"][0]["error_codes"] == {"AI_MODEL_UNAVAILABLE": 1}

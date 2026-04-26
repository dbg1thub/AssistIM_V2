from __future__ import annotations

import json

from tools.ai_action_prompt_benchmark import (
    CaseBenchmarkResult,
    LEGACY_PLAN_TOP_LEVEL_FIELDS,
    PromptBenchmarkCase,
    PromptCaseExpectation,
    PromptStepArgExpectation,
    SampleResult,
    canonical_structural_signature,
    evaluate_case,
    load_golden_corpus,
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


def test_evaluate_case_rejects_unresolved_step_references() -> None:
    plan = {
        "goal": "history",
        "risk": "low",
        "steps": [
            {
                "id": "%step_0",
                "action": "contact.resolve",
                "depends_on": [],
                "args": {"queries": ["test3"], "allow_multiple": False},
            },
            {
                "id": "%step_1",
                "action": "memory.search",
                "depends_on": ["%step_0"],
                "args": {
                    "participants": "$resolve_contacts.contacts",
                    "participant_match": "test3",
                    "time_scope": {"type": "all_history"},
                    "keywords": [],
                    "question": "我和 test3 之前聊过什么？",
                },
            },
            {
                "id": "%step_2",
                "action": "memory.summarize",
                "depends_on": ["%step_1"],
                "args": {"source": "$search_memory", "question": "我和 test3 之前聊过什么？"},
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

    assert checks["step_references"] is False
    assert "unresolved step reference" in messages


def test_evaluate_case_checks_non_action_and_forbidden_actions() -> None:
    plan = {
        "is_action": False,
        "goal": "普通聊天",
        "risk": "low",
        "steps": [],
        "final": {"type": "chat"},
    }
    checks, messages = evaluate_case(
        plan,
        PromptCaseExpectation(
            is_action=False,
            forbidden_actions=("contact.resolve", "memory.search", "user.confirm", "message.send"),
        ),
    )

    assert all(checks.values()) is True
    assert messages == []

    bad_plan = {
        "is_action": False,
        "goal": "普通聊天",
        "risk": "low",
        "steps": [{"id": "confirm", "action": "user.confirm", "depends_on": [], "args": {}}],
        "final": {},
    }
    bad_checks, bad_messages = evaluate_case(
        bad_plan,
        PromptCaseExpectation(is_action=False, forbidden_actions=("user.confirm",)),
    )

    assert bad_checks["no_steps_for_non_action"] is False
    assert bad_checks["forbidden_actions"] is False
    assert "non-action plan contains steps" in bad_messages
    assert "forbidden action present" in bad_messages


def test_evaluate_case_rejects_legacy_top_level_plan_fields_by_default() -> None:
    plan = {
        "is_action": True,
        "goal": "查询历史",
        "risk": "low",
        "action": "memory.search",
        "slots": {"query": "test3"},
        "missing_slots": [],
        "steps": [],
        "final": {},
    }

    checks, messages = evaluate_case(plan, PromptCaseExpectation(is_action=True))

    assert checks["forbidden_top_level_fields"] is False
    assert "forbidden top-level fields present: action, missing_slots, slots" in messages


def test_evaluate_case_checks_required_action_sequence() -> None:
    expectation = PromptCaseExpectation(
        required_actions=("contact.resolve", "memory.search", "memory.summarize"),
        required_action_sequence=("contact.resolve", "memory.search", "memory.summarize"),
    )
    plan = {
        "is_action": True,
        "goal": "查询历史",
        "risk": "low",
        "steps": [
            {"id": "resolve_1", "action": "contact.resolve", "depends_on": [], "args": {}},
            {"id": "sum_1", "action": "memory.summarize", "depends_on": ["resolve_1"], "args": {}},
            {"id": "search_1", "action": "memory.search", "depends_on": ["sum_1"], "args": {}},
        ],
        "final": {},
    }

    checks, messages = evaluate_case(plan, expectation)

    assert checks["required_actions"] is True
    assert checks["required_action_sequence"] is False
    assert "required action sequence mismatch" in messages

    plan["steps"] = [
        {"id": "resolve_1", "action": "contact.resolve", "depends_on": [], "args": {}},
        {"id": "search_1", "action": "memory.search", "depends_on": ["resolve_1"], "args": {}},
        {"id": "sum_1", "action": "memory.summarize", "depends_on": ["search_1"], "args": {}},
    ]
    ok_checks, ok_messages = evaluate_case(plan, expectation)

    assert ok_checks["required_action_sequence"] is True
    assert ok_messages == []


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
    assert summary["failed_cases"] == [
        {
            "name": "history",
            "failed_sample_count": 1,
            "messages": ["missing required actions"],
        }
    ]


def test_load_golden_corpus_from_json(tmp_path) -> None:
    corpus_path = tmp_path / "golden.json"
    corpus_path.write_text(
        json.dumps(
            {
                "version": 1,
                "cases": [
                    {
                        "name": "chat_smalltalk",
                        "user_input": "你好",
                        "tags": ["chat"],
                        "router_expected_route": "chat",
                        "expectation": {
                            "is_action": False,
                            "forbidden_actions": ["contact.resolve", "user.confirm"],
                        },
                    },
                    {
                        "name": "send_message",
                        "user_input": "帮我给张三发我晚点到",
                        "router_expected_route": "action_candidate",
                        "expectation": {
                            "is_action": True,
                            "risk": "high",
                            "required_actions": ["contact.resolve", "message.draft", "user.confirm", "message.send"],
                            "required_action_sequence": [
                                "contact.resolve",
                                "message.draft",
                                "user.confirm",
                                "message.send"
                            ],
                            "contact_queries": ["张三"],
                            "requires_confirmation": True,
                            "expected_content": "我晚点到",
                            "required_step_args": [
                                {"action": "contact.resolve", "path": "allow_multiple", "equals": "False"}
                            ],
                        },
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cases = load_golden_corpus(corpus_path)

    assert [case.name for case in cases] == ["chat_smalltalk", "send_message"]
    assert cases[0].tags == ("chat",)
    assert cases[0].router_expected_route == "chat"
    assert cases[0].expectation.is_action is False
    assert cases[0].expectation.forbidden_actions == ("contact.resolve", "user.confirm")
    assert cases[1].router_expected_route == "action_candidate"
    assert cases[1].expectation.required_actions == (
        "contact.resolve",
        "message.draft",
        "user.confirm",
        "message.send",
    )
    assert cases[1].expectation.required_action_sequence == (
        "contact.resolve",
        "message.draft",
        "user.confirm",
        "message.send",
    )
    assert cases[1].expectation.forbidden_top_level_fields == LEGACY_PLAN_TOP_LEVEL_FIELDS
    assert cases[1].expectation.required_step_args[0].path == "allow_multiple"


def test_load_default_golden_corpus_has_core_action_and_chat_cases() -> None:
    cases = load_golden_corpus()
    names = [case.name for case in cases]

    assert len(cases) >= 8
    assert len(names) == len(set(names))
    assert any(case.expectation.is_action is False for case in cases)
    assert any("memory.search" in case.expectation.required_actions for case in cases)
    assert any("message.send" in case.expectation.required_actions for case in cases)
    assert any(
        case.expectation.required_action_sequence == ("contact.resolve", "memory.search", "memory.summarize")
        for case in cases
    )
    assert all(case.expectation.forbidden_top_level_fields == LEGACY_PLAN_TOP_LEVEL_FIELDS for case in cases)
    assert {case.router_expected_route for case in cases} >= {"chat", "action_candidate"}


def test_load_golden_corpus_rejects_duplicate_names(tmp_path) -> None:
    corpus_path = tmp_path / "duplicate.json"
    corpus_path.write_text(
        json.dumps(
            {
                "version": 1,
                "cases": [
                    {"name": "same", "user_input": "你好", "expectation": {"is_action": False}},
                    {"name": "same", "user_input": "再见", "expectation": {"is_action": False}},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    try:
        load_golden_corpus(corpus_path)
    except ValueError as exc:
        assert "duplicate case name" in str(exc)
    else:
        raise AssertionError("duplicate corpus names should be rejected")

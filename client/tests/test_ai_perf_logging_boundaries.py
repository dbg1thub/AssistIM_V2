from pathlib import Path


def test_ai_task_and_runtime_perf_logs_are_registered() -> None:
    task_manager = Path("client/managers/ai_task_manager.py").read_text(encoding="utf-8")
    runtime = Path("client/services/local_gguf_runtime.py").read_text(encoding="utf-8")
    ai_service = Path("client/services/ai_service.py").read_text(encoding="utf-8")

    assert "[ai-perf] task_queued" in task_manager
    assert "[ai-perf] task_started" in task_manager
    assert "[ai-perf] task_finished" in task_manager
    assert "[ai-perf] task_failed" in task_manager
    assert "[ai-perf] task_cancelled" in task_manager
    assert "queue_wait_ms" in task_manager
    assert "prompt_chars" in task_manager

    assert "[ai-perf] local_model_load_start" in runtime
    assert "[ai-perf] local_model_load_done" in runtime
    assert "[ai-perf] local_model_load_failed" in runtime
    assert "[ai-perf] local_model_gpu_fallback" in runtime
    assert "[ai-perf] local_generation_start" in runtime
    assert "[ai-perf] local_generation_first_chunk" in runtime
    assert "[ai-perf] local_generation_done" in runtime
    assert "[ai-perf] local_generation_failed" in runtime
    assert "acceleration_profile=%s" in runtime
    assert "task_type=getattr(request.task_type" in ai_service


def test_ai_perf_logs_do_not_print_prompt_or_message_content() -> None:
    paths = [
        Path("client/managers/ai_task_manager.py"),
        Path("client/services/local_gguf_runtime.py"),
        Path("client/managers/ai_assist_manager.py"),
        Path("client/ui/windows/chat_interface.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    forbidden_fragments = [
        " message_content=%s",
        " prompt_content=%s",
        "prompt=%s",
        "messages=%s",
        "message_content",
        "prompt_text",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in combined


def test_business_perf_metadata_is_count_only() -> None:
    prompt_builder = Path("client/managers/ai_prompt_builder.py").read_text(encoding="utf-8")
    assist_manager = Path("client/managers/ai_assist_manager.py").read_text(encoding="utf-8")

    assert '"source_chars": len(source)' in prompt_builder
    assert '"prompt_chars": len(prompt)' in prompt_builder
    assert '"anchor_group_size": len(anchor_group)' in prompt_builder
    assert '"recent_context_count": recent_context_count' in prompt_builder
    assert '"has_summary": bool(background_lines or related_history_lines)' in prompt_builder
    assert "[ai-perf] translation_request" in assist_manager
    assert "[ai-perf] reply_suggestion_request" in assist_manager


def test_ai_action_perf_logs_are_registered() -> None:
    workflow = Path("client/managers/ai_action_workflow.py").read_text(encoding="utf-8")
    executor = Path("client/managers/ai_action_executor.py").read_text(encoding="utf-8")

    assert "[ai-perf] ai_action_workflow_finished" in workflow
    assert "planner_ms=%s" in workflow
    assert "normalizer_ms=%s" in workflow
    assert "optimizer_ms=%s" in workflow
    assert "resource_check_ms=%s" in workflow
    assert "executor_ms=%s" in workflow
    assert "total_ms=%s" in workflow
    assert "step_count=%s" in workflow

    assert "[ai-perf] ai_action_step_finished" in executor
    assert "duration_ms=%s" in executor
    assert "result_count=%s" in executor
    assert "result_ref=%s" in executor
    assert "output_bytes=%s" in executor


def test_ai_action_perf_logs_do_not_print_prompt_or_result_content() -> None:
    paths = [
        Path("client/managers/ai_action_workflow.py"),
        Path("client/managers/ai_action_executor.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    forbidden_fragments = [
        "user_text=%s",
        "normalized_text=%s",
        "prompt=%s",
        "prompt_text=%s",
        "raw_output=%s",
        "context_lines=%s",
        "memory_context_lines=%s",
        "step_output=%s",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in combined

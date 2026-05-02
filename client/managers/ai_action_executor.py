"""Sequential executor for AI action plans."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import ValidationError

from client.core import logging
from client.managers.ai_action_permission_policy import AIPermissionPolicy
from client.managers.ai_action_registry import AtomicActionRegistry
from client.managers.ai_action_types import (
    AIActionEvent,
    AIActionPlan,
    ActionExecutionResult,
    ActionHandlerError,
    ActionPause,
    AtomicActionSpec,
    current_plan_step_outputs,
    mark_step_output_current,
)
from client.storage.ai_action_plan_store import AIActionPlanRecord, AIActionPlanStore


logger = logging.get_logger(__name__)

AIActionProgressCallback = Callable[[AIActionPlanRecord], Any]


@dataclass(frozen=True, slots=True)
class ActionRuntimeBudget:
    max_total_output_bytes: int = 262144
    max_result_ref_count: int = 8
    max_total_result_count: int = 500
    max_total_duration_ms: int = 600000
    max_total_model_tokens: int = 100000
    max_temp_result_bytes: int = 1048576


@dataclass(frozen=True, slots=True)
class RuntimeBudgetCheck:
    allowed: bool
    reason: str = ""


class AIActionExecutor:
    """Execute atomic action steps and persist progress after every step."""

    def __init__(
        self,
        *,
        registry: AtomicActionRegistry,
        store: AIActionPlanStore,
        permission_policy: AIPermissionPolicy | None = None,
        runtime_budget: ActionRuntimeBudget | None = None,
    ) -> None:
        self._registry = registry
        self._store = store
        self._permission_policy = permission_policy or AIPermissionPolicy()
        self._runtime_budget = runtime_budget or ActionRuntimeBudget()

    async def execute(
        self,
        record: AIActionPlanRecord,
        *,
        progress_callback: AIActionProgressCallback | None = None,
    ) -> ActionExecutionResult:
        plan = AIActionPlan.from_dict(dict(record.plan_json or {}))
        if not plan.steps:
            return ActionExecutionResult(state="failed", error_text="PLAN_SCHEMA_INVALID")
        outputs = current_plan_step_outputs(
            dict(record.step_outputs or {}),
            step_ids={step.id for step in plan.steps},
            plan_version=record.plan_version,
        )
        events = _plan_events(record.plan_json)

        for step in plan.steps:
            cancelled, record = await self._cancelled_result_if_requested(
                record,
                progress_callback=progress_callback,
            )
            if cancelled is not None:
                return cancelled
            outputs = current_plan_step_outputs(
                {**outputs, **dict(record.step_outputs or {})},
                step_ids={item.id for item in plan.steps},
                plan_version=record.plan_version,
            )
            if step.id in outputs:
                continue
            missing_deps = [dep for dep in step.depends_on if dep not in outputs]
            if missing_deps:
                return await self._fail_step_before_handler(
                    record,
                    outputs,
                    events,
                    step,
                    f"ARG_REFERENCE_INVALID: missing dependency {missing_deps[0]}",
                    progress_callback=progress_callback,
                )

            spec = self._registry.get(step.action)
            if spec is None:
                return await self._fail_step_before_handler(
                    record,
                    outputs,
                    events,
                    step,
                    f"ACTION_NOT_FOUND: {step.action}",
                    progress_callback=progress_callback,
                )
            if not spec.enabled and step.action != "message.send":
                return await self._fail_step_before_handler(
                    record,
                    outputs,
                    events,
                    step,
                    f"ACTION_DISABLED: {step.action}",
                    progress_callback=progress_callback,
                )

            try:
                resolved_args = _resolve_refs(step.args, outputs)
                self._check_guardrails(spec, resolved_args)
                validated_args = _validate_input(spec, resolved_args)
                self._check_guardrails(spec, validated_args)
            except ValueError as exc:
                return await self._fail_step_before_handler(
                    record,
                    outputs,
                    events,
                    step,
                    str(exc),
                    progress_callback=progress_callback,
                )

            permission = self._permission_policy.check_step(
                spec=spec,
                args=validated_args,
                plan_context={
                    "thread_id": record.thread_id,
                    "plan_id": record.id,
                    "plan_version": record.plan_version,
                    "step_id": step.id,
                    "action": step.action,
                },
            )
            if not permission.allowed:
                return await self._fail_step_before_handler(
                    record,
                    outputs,
                    events,
                    step,
                    permission.code or "PERMISSION_DENIED",
                    progress_callback=progress_callback,
                )

            _append_step_event(
                events,
                record_id=record.id,
                step=step,
                event_type="step_started",
                state="started",
                message=step.display_text,
            )
            plan_json = _plan_json_with_events(record.plan_json, events)
            record = await self._store.update_plan(
                record.id,
                plan_json=plan_json,
                reason=f"step_started_{step.id}",
                bump_version=False,
                state="running",
                current_step_id=step.id,
                step_outputs=outputs,
                waiting_payload={},
            ) or record
            await _emit_progress(progress_callback, record)

            handler = spec.handler
            if handler is None:
                _append_step_event(
                    events,
                    record_id=record.id,
                    step=step,
                    event_type="step_failed",
                    state="failed",
                    error_text=f"ACTION_NOT_FOUND: {step.action}",
                )
                record = await self._store.update_plan(
                    record.id,
                    plan_json=_plan_json_with_events(record.plan_json, events),
                    reason=f"step_failed_{step.id}",
                    bump_version=False,
                ) or record
                await _emit_progress(progress_callback, record)
                return await self._fail(
                    record,
                    outputs,
                    f"ACTION_NOT_FOUND: {step.action}",
                    progress_callback=progress_callback,
                )
            step_started = time.perf_counter()

            async def persist_attempt_event(
                *,
                event_type: str,
                state: str,
                attempt: int,
                max_attempts: int,
                error_text: str = "",
                retryable: bool | None = None,
                duration_ms: int = 0,
            ) -> None:
                nonlocal record
                _append_step_event(
                    events,
                    record_id=record.id,
                    step=step,
                    event_type=event_type,
                    state=state,
                    error_text=error_text,
                    duration_ms=duration_ms,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    retryable=retryable,
                )
                record = await self._store.update_plan(
                    record.id,
                    plan_json=_plan_json_with_events(record.plan_json, events),
                    reason=f"{event_type}_{step.id}",
                    bump_version=False,
                    state="running",
                    current_step_id=step.id,
                    step_outputs=outputs,
                    waiting_payload={},
                ) or record
                await _emit_progress(progress_callback, record)

            raw_output, execution_error = await _run_action_handler(
                spec,
                validated_args,
                {
                    "plan_id": record.id,
                    "plan_version": record.plan_version,
                    "step_id": step.id,
                    "store": self._store,
                    "step_outputs": outputs,
                },
                attempt_event_callback=persist_attempt_event,
            )
            cancelled, record = await self._cancelled_result_if_requested(
                record,
                progress_callback=progress_callback,
            )
            if cancelled is not None:
                return cancelled
            if execution_error:
                logger.info(
                    "[ai-perf] ai_action_step_finished plan_id=%s step_id=%s action=%s state=%s "
                    "duration_ms=%s result_count=%s result_ref=%s output_bytes=%s",
                    record.id,
                    step.id,
                    step.action,
                    "failed",
                    _elapsed_ms(step_started),
                    0,
                    False,
                    0,
                )
                _append_step_event(
                    events,
                    record_id=record.id,
                    step=step,
                    event_type="step_failed",
                    state="failed",
                    error_text=execution_error,
                    duration_ms=_elapsed_ms(step_started),
                    resource_usage=_step_resource_usage(
                        duration_ms=_elapsed_ms(step_started),
                        model_call_cost=_model_call_cost(spec),
                    ),
                )
                record = await self._store.update_plan(
                    record.id,
                    plan_json=_plan_json_with_events(record.plan_json, events),
                    reason=f"step_failed_{step.id}",
                    bump_version=False,
                ) or record
                await _emit_progress(progress_callback, record)
                return await self._fail(
                    record,
                    outputs,
                    execution_error,
                    progress_callback=progress_callback,
                )

            if isinstance(raw_output, ActionPause):
                payload = dict(raw_output.payload or {})
                payload["response_text"] = raw_output.response_text
                _append_step_event(
                    events,
                    record_id=record.id,
                    step=step,
                    event_type=_waiting_event_type(raw_output.state),
                    state=raw_output.state,
                    message=step.display_text,
                    duration_ms=_elapsed_ms(step_started),
                    resource_usage=_step_resource_usage(
                        duration_ms=_elapsed_ms(step_started),
                        model_call_cost=_model_call_cost(spec),
                    ),
                )
                record = await self._store.update_plan(
                    record.id,
                    plan_json=_plan_json_with_events(record.plan_json, events),
                    reason=f"{raw_output.state}_{step.id}",
                    bump_version=False,
                    state=raw_output.state,
                    current_step_id=step.id,
                    step_outputs=outputs,
                    waiting_payload=payload,
                ) or record
                await _emit_progress(progress_callback, record)
                logger.info(
                    "[ai-perf] ai_action_step_finished plan_id=%s step_id=%s action=%s state=%s "
                    "duration_ms=%s result_count=%s result_ref=%s output_bytes=%s",
                    record.id,
                    step.id,
                    step.action,
                    raw_output.state,
                    _elapsed_ms(step_started),
                    0,
                    False,
                    0,
                )
                return ActionExecutionResult(
                    state=raw_output.state,
                    response_text=raw_output.response_text,
                    final_output={"waiting_payload": payload},
                )

            raw_output_bytes = 0
            try:
                validated_output = _validate_output(spec, raw_output)
                raw_output_bytes = _json_size(validated_output)
                output = await self._enforce_output_size(record, step.id, spec, validated_output)
            except ValueError as exc:
                resource_limit = _resource_limit_from_error(str(exc))
                logger.info(
                    "[ai-perf] ai_action_step_finished plan_id=%s step_id=%s action=%s state=%s "
                    "duration_ms=%s result_count=%s result_ref=%s output_bytes=%s",
                    record.id,
                    step.id,
                    step.action,
                    "failed",
                    _elapsed_ms(step_started),
                    0,
                    False,
                    raw_output_bytes,
                )
                _append_step_event(
                    events,
                    record_id=record.id,
                    step=step,
                    event_type="step_failed",
                    state="failed",
                    error_text=str(exc),
                    duration_ms=_elapsed_ms(step_started),
                    resource_usage=_step_resource_usage(
                        duration_ms=_elapsed_ms(step_started),
                        output_bytes=raw_output_bytes,
                        model_call_cost=_model_call_cost(spec),
                    ),
                    resource_limit=resource_limit,
                )
                record = await self._store.update_plan(
                    record.id,
                    plan_json=_plan_json_with_events(record.plan_json, events),
                    reason=f"step_failed_{step.id}",
                    bump_version=False,
                ) or record
                await _emit_progress(progress_callback, record)
                return await self._fail(
                    record,
                    outputs,
                    str(exc),
                    progress_callback=progress_callback,
                )

            outputs[step.id] = output
            mark_step_output_current(outputs, step_id=step.id, plan_version=record.plan_version)
            result_count = _output_result_count(output)
            has_result_ref = isinstance(output.get("result_ref"), dict)
            model_tokens = _output_model_tokens(output)
            temp_result_bytes = _output_temp_result_bytes(output)
            logger.info(
                "[ai-perf] ai_action_step_finished plan_id=%s step_id=%s action=%s state=%s "
                "duration_ms=%s result_count=%s result_ref=%s output_bytes=%s",
                record.id,
                step.id,
                step.action,
                "completed",
                _elapsed_ms(step_started),
                result_count,
                has_result_ref,
                raw_output_bytes,
            )
            _append_step_event(
                events,
                record_id=record.id,
                step=step,
                event_type="step_completed",
                state="completed",
                result_count=result_count,
                duration_ms=_elapsed_ms(step_started),
                resource_usage=_step_resource_usage(
                    duration_ms=_elapsed_ms(step_started),
                    result_count=result_count,
                    output_bytes=raw_output_bytes,
                    result_ref=has_result_ref,
                    model_call_cost=_model_call_cost(spec),
                    model_tokens=model_tokens,
                    temp_result_bytes=temp_result_bytes,
                ),
            )
            plan_json = _plan_json_with_events(record.plan_json, events)
            record = await self._store.update_plan(
                record.id,
                plan_json=plan_json,
                reason=f"step_completed_{step.id}",
                bump_version=False,
                state="running",
                current_step_id=step.id,
                step_outputs=outputs,
                waiting_payload={},
            ) or record
            await _emit_progress(progress_callback, record)
            budget_check = _check_runtime_budget(plan_json, self._runtime_budget)
            if not budget_check.allowed:
                return await self._fail_runtime_budget(
                    record,
                    outputs,
                    events,
                    budget_check.reason,
                    progress_callback=progress_callback,
                )

        cancelled, record = await self._cancelled_result_if_requested(
            record,
            progress_callback=progress_callback,
        )
        if cancelled is not None:
            return cancelled
        return await self._complete(record, outputs, progress_callback=progress_callback)

    async def _complete(
        self,
        record: AIActionPlanRecord,
        outputs: dict[str, Any],
        *,
        progress_callback: AIActionProgressCallback | None = None,
    ) -> ActionExecutionResult:
        final = self._project_final(record, outputs)
        state = "running" if final.memory_context_lines else "done"
        plan_json = dict(record.plan_json or {})
        if state == "done":
            events = _plan_events(plan_json)
            if not any(str(event.get("type") or "") == "plan_completed" for event in events):
                events.append(
                    AIActionEvent(
                        step_id="",
                        action="plan",
                        state="done",
                        event_type="plan_completed",
                        plan_id=record.id,
                    ).to_dict()
                )
            plan_json["events"] = events[-20:]
        updated = await self._store.update_plan(
            record.id,
            plan_json=plan_json,
            reason="plan_completed" if state == "done" else "",
            bump_version=False,
            state=state,
            current_step_id="",
            step_outputs={**outputs, "final": dict(final.final_output or {})},
            waiting_payload={},
            completed_at=0 if state == "running" else time.time(),
        )
        await _emit_progress(progress_callback, updated or record)
        return final

    async def _cancelled_result_if_requested(
        self,
        record: AIActionPlanRecord,
        *,
        progress_callback: AIActionProgressCallback | None = None,
    ) -> tuple[ActionExecutionResult | None, AIActionPlanRecord]:
        latest = await self._store.get_plan(record.id) or record
        if latest.state != "cancelled":
            return None, latest
        updated = await self._ensure_cancelled_record(latest)
        await _emit_progress(progress_callback, updated)
        return ActionExecutionResult(state="cancelled", response_text="已取消这个操作。"), updated

    async def _ensure_cancelled_record(self, record: AIActionPlanRecord) -> AIActionPlanRecord:
        events = _plan_events(record.plan_json)
        has_cancel_event = any(str(event.get("type") or "") == "plan_cancelled" for event in events)
        plan_json = dict(record.plan_json or {})
        if not has_cancel_event:
            events.append(
                AIActionEvent(
                    step_id="",
                    action="plan",
                    state="cancelled",
                    event_type="plan_cancelled",
                    plan_id=record.id,
                ).to_dict()
            )
            plan_json["events"] = events[-20:]
        if has_cancel_event and not record.current_step_id and not record.waiting_payload:
            return record
        return await self._store.update_plan(
            record.id,
            plan_json=plan_json,
            reason="plan_cancelled",
            bump_version=False,
            state="cancelled",
            current_step_id="",
            waiting_payload={},
            completed_at=record.completed_at or time.time(),
        ) or record

    def _project_final(self, record: AIActionPlanRecord, outputs: dict[str, Any]) -> ActionExecutionResult:
        plan = AIActionPlan.from_dict(dict(record.plan_json or {}))
        source = str((plan.final or {}).get("source") or "").strip()
        final_output: Any = None
        if source:
            try:
                final_output = _resolve_ref(source, outputs)
            except ValueError:
                final_output = None
        if final_output is None and plan.steps:
            final_output = outputs.get(plan.steps[-1].id)
        if isinstance(final_output, dict):
            if final_output.get("requires_responder"):
                return ActionExecutionResult(
                    state="running",
                    memory_context_lines=tuple(
                        str(item or "").strip()
                        for item in list(final_output.get("context_lines") or [])
                        if str(item or "").strip()
                    ),
                    final_output=final_output,
                )
            text = str(final_output.get("text") or "").strip()
            if text:
                return ActionExecutionResult(state="done", response_text=text, final_output=final_output)
        if isinstance(final_output, str) and final_output.strip():
            return ActionExecutionResult(state="done", response_text=final_output.strip(), final_output={"text": final_output.strip()})
        return ActionExecutionResult(state="done", final_output={})

    async def _fail(
        self,
        record: AIActionPlanRecord,
        outputs: dict[str, Any],
        error_text: str,
        *,
        progress_callback: AIActionProgressCallback | None = None,
    ) -> ActionExecutionResult:
        updated = await self._store.update_plan(
            record.id,
            state="failed",
            step_outputs=outputs,
            error_text=error_text,
            completed_at=time.time(),
        )
        await _emit_progress(progress_callback, updated or record)
        return ActionExecutionResult(state="failed", response_text="这个操作执行失败，请稍后再试。", error_text=error_text)

    async def _fail_runtime_budget(
        self,
        record: AIActionPlanRecord,
        outputs: dict[str, Any],
        events: list[dict[str, Any]],
        reason: str,
        *,
        progress_callback: AIActionProgressCallback | None = None,
    ) -> ActionExecutionResult:
        error_text = f"RESOURCE_LIMIT_EXCEEDED: {str(reason or '').strip() or 'runtime_budget'}"
        events.append(
            AIActionEvent(
                step_id=str(record.current_step_id or ""),
                action="plan",
                state="failed",
                event_type="plan_resource_limit_exceeded",
                plan_id=record.id,
                error_code="RESOURCE_LIMIT_EXCEEDED",
                resource_limit=str(reason or "").strip(),
            ).to_dict()
        )
        updated = await self._store.update_plan(
            record.id,
            plan_json=_plan_json_with_events(record.plan_json, events),
            reason="plan_resource_limit_exceeded",
            bump_version=False,
            state="failed",
            current_step_id=record.current_step_id,
            step_outputs=outputs,
            waiting_payload={},
            error_text=error_text,
            completed_at=time.time(),
        )
        await _emit_progress(progress_callback, updated or record)
        return ActionExecutionResult(state="failed", response_text="这个操作超过资源限制，已停止后续步骤。", error_text=error_text)

    async def _fail_step_before_handler(
        self,
        record: AIActionPlanRecord,
        outputs: dict[str, Any],
        events: list[dict[str, Any]],
        step: Any,
        error_text: str,
        *,
        progress_callback: AIActionProgressCallback | None = None,
    ) -> ActionExecutionResult:
        _append_step_event(
            events,
            record_id=record.id,
            step=step,
            event_type="step_failed",
            state="failed",
            error_text=error_text,
        )
        updated = await self._store.update_plan(
            record.id,
            plan_json=_plan_json_with_events(record.plan_json, events),
            reason=f"step_failed_{str(getattr(step, 'id', '') or '')}",
            bump_version=False,
            state="failed",
            current_step_id=str(getattr(step, "id", "") or ""),
            step_outputs=outputs,
            waiting_payload={},
            error_text=error_text,
            completed_at=time.time(),
        )
        await _emit_progress(progress_callback, updated or record)
        return ActionExecutionResult(state="failed", response_text="这个操作执行失败，请稍后再试。", error_text=error_text)

    def _check_guardrails(self, spec: AtomicActionSpec, args: dict[str, Any]) -> None:
        if not isinstance(args, dict):
            raise ValueError("ARG_SCHEMA_INVALID")
        if _json_size(args) > spec.max_input_bytes:
            raise ValueError("PAYLOAD_TOO_LARGE: input")
        target_count = _guardrail_target_count(args, spec.target_arg_names)
        if target_count > 1 and not spec.allow_batch:
            raise ValueError("BATCH_NOT_ALLOWED")
        if spec.max_targets is not None and target_count > spec.max_targets:
            raise ValueError("PLAN_TOO_LARGE: too many targets")
        if spec.max_content_chars is not None and len(str(args.get("content") or "")) > spec.max_content_chars:
            raise ValueError("PAYLOAD_TOO_LARGE: content")
        if spec.require_resolved_target and not _has_resolved_target(args.get("target")):
            raise ValueError("ARG_SCHEMA_INVALID: target")
        if spec.require_preview and not _has_guardrail_value(args.get("preview")):
            raise ValueError("ARG_SCHEMA_INVALID: preview")
        if spec.idempotency_required and not str(args.get("idempotency_key") or "").strip():
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")

    async def _enforce_output_size(
        self,
        record: AIActionPlanRecord,
        step_id: str,
        spec: AtomicActionSpec,
        output: dict[str, Any],
    ) -> dict[str, Any]:
        output_size = _json_size(output)
        if output_size <= spec.max_output_json_bytes:
            return output
        if output_size > _positive_int(self._runtime_budget.max_temp_result_bytes):
            raise ValueError("RESOURCE_LIMIT_EXCEEDED: temp_result_bytes")
        temp = await self._store.create_temp_result(
            plan_id=record.id,
            step_id=step_id,
            result_type=spec.name,
            payload=output,
            payload_meta={
                "result_count": int(output.get("result_count") or 0),
                "estimated_chars": output_size,
            },
        )
        return {
            "result_ref": {
                "type": spec.name,
                "id": temp.id,
                "result_count": int(output.get("result_count") or 0),
                "estimated_chars": output_size,
                "expires_at": temp.expires_at,
            }
        }


async def _emit_progress(
    progress_callback: AIActionProgressCallback | None,
    record: AIActionPlanRecord,
) -> None:
    if progress_callback is None:
        return
    try:
        result = progress_callback(record)
        if inspect.isawaitable(result):
            await result
    except Exception:
        logger.exception("AI action progress callback failed")


async def _run_action_handler(
    spec: AtomicActionSpec,
    args: dict[str, Any],
    context: dict[str, Any],
    *,
    attempt_event_callback: Callable[..., Any] | None = None,
) -> tuple[Any, str]:
    handler = spec.handler
    if handler is None:
        return None, f"ACTION_NOT_FOUND: {spec.name}"
    attempts = _handler_attempt_count(spec)
    last_error = f"ACTION_FAILED: {spec.name}"
    for attempt in range(1, attempts + 1):
        attempt_started = time.perf_counter()
        try:
            timeout_seconds = max(0.001, float(spec.timeout_ms or 0) / 1000.0)
            return await asyncio.wait_for(handler(args, context), timeout=timeout_seconds), ""
        except TimeoutError:
            last_error = f"ACTION_TIMEOUT: {spec.name}"
        except asyncio.CancelledError:
            raise
        except ActionHandlerError as exc:
            return None, exc.error_text
        except Exception as exc:
            last_error = f"ACTION_FAILED: {spec.name}"
            logger.info(
                "[ai-diag] ai_action_step_attempt_failed action=%s attempt=%s max_attempts=%s retryable=%s error_type=%s",
                spec.name,
                attempt,
                attempts,
                _is_retryable_spec(spec),
                type(exc).__name__,
            )
        if attempt < attempts:
            await _emit_attempt_event(
                attempt_event_callback,
                event_type="step_attempt_failed",
                state="failed",
                attempt=attempt,
                max_attempts=attempts,
                error_text=last_error,
                retryable=_is_retryable_spec(spec),
                duration_ms=_elapsed_ms(attempt_started),
            )
            logger.info(
                "[ai-diag] ai_action_step_retrying action=%s attempt=%s next_attempt=%s max_attempts=%s last_error=%s",
                spec.name,
                attempt,
                attempt + 1,
                attempts,
                last_error.split(":", 1)[0],
            )
            await _emit_attempt_event(
                attempt_event_callback,
                event_type="step_retrying",
                state="retrying",
                attempt=attempt + 1,
                max_attempts=attempts,
                retryable=_is_retryable_spec(spec),
            )
    return None, last_error


async def _emit_attempt_event(
    callback: Callable[..., Any] | None,
    **payload: Any,
) -> None:
    if callback is None:
        return
    result = callback(**payload)
    if inspect.isawaitable(result):
        await result


def _handler_attempt_count(spec: AtomicActionSpec) -> int:
    if not _is_retryable_spec(spec):
        return 1
    try:
        retries = max(0, int(spec.max_retries or 0))
    except (TypeError, ValueError):
        retries = 0
    return 1 + retries


def _is_retryable_spec(spec: AtomicActionSpec) -> bool:
    return spec.kind == "read" and not spec.allow_side_effect


def _guardrail_target_count(args: dict[str, Any], target_arg_names: tuple[str, ...] = ()) -> int:
    for key in (*tuple(target_arg_names or ()), "targets", "target", "queries", "participants"):
        if key in args:
            return _guardrail_value_count(args.get(key))
    return 0


def _guardrail_value_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, list | tuple):
        return len(value)
    if isinstance(value, dict):
        return 1 if value else 0
    return 1 if str(value or "").strip() else 0


def _has_resolved_target(value: Any) -> bool:
    return isinstance(value, dict) and bool(str(value.get("contact_id") or "").strip())


def _has_guardrail_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict | list | tuple):
        return bool(value)
    return True


def _validate_input(spec: AtomicActionSpec, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("ARG_SCHEMA_INVALID")
    model = spec.input_model
    if model is None:
        return dict(value)
    validate = getattr(model, "model_validate", None)
    if not callable(validate):
        return dict(value)
    try:
        validated = validate(dict(value))
    except ValidationError as exc:
        raise ValueError(_validation_error_text("ARG_SCHEMA_INVALID", exc)) from exc
    dump = getattr(validated, "model_dump", None)
    if callable(dump):
        return dict(dump(mode="python", exclude_none=True))
    return dict(value)


def _validate_output(spec: AtomicActionSpec, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("OUTPUT_SCHEMA_INVALID")
    model = spec.output_model
    if model is None:
        return dict(value)
    validate = getattr(model, "model_validate", None)
    if not callable(validate):
        return dict(value)
    try:
        validated = validate(dict(value))
    except ValidationError as exc:
        raise ValueError(_validation_error_text("OUTPUT_SCHEMA_INVALID", exc)) from exc
    dump = getattr(validated, "model_dump", None)
    if callable(dump):
        return dict(dump(mode="python", exclude_none=True))
    return dict(value)


def _validation_error_text(code: str, exc: ValidationError) -> str:
    fields: list[str] = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", ()) if str(part))
        if loc and loc not in fields:
            fields.append(loc)
    if not fields:
        return code
    return f"{code}: {', '.join(fields[:3])}"


def _resolve_refs(value: Any, outputs: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return _resolve_ref(value, outputs)
    if isinstance(value, list):
        return [_resolve_refs(item, outputs) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_refs(item, outputs) for key, item in value.items()}
    return value


def _resolve_ref(ref: str, outputs: dict[str, Any]) -> Any:
    text = str(ref or "").strip()
    if not text.startswith("$"):
        return text
    path = text[1:]
    parts = path.split(".")
    if not parts or not parts[0]:
        raise ValueError("ARG_REFERENCE_INVALID")
    if parts[0] not in outputs:
        raise ValueError("ARG_REFERENCE_INVALID")
    current: Any = outputs[parts[0]]
    for raw_part in parts[1:]:
        name, indexes = _parse_path_part(raw_part)
        if name:
            if not isinstance(current, dict) or name not in current:
                raise ValueError("ARG_REFERENCE_INVALID")
            current = current[name]
        for index in indexes:
            if not isinstance(current, list) or index < 0 or index >= len(current):
                raise ValueError("ARG_REFERENCE_INVALID")
            current = current[index]
    return current


def _parse_path_part(part: str) -> tuple[str, list[int]]:
    text = str(part or "").strip()
    match = re.match(r"^(?P<name>[^\[]*)(?P<indexes>(?:\[\d+\])*)$", text)
    if not match:
        raise ValueError("ARG_REFERENCE_INVALID")
    name = match.group("name")
    indexes = [int(item) for item in re.findall(r"\[(\d+)\]", match.group("indexes") or "")]
    return name, indexes


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _output_result_count(output: dict[str, Any]) -> int:
    result_ref = output.get("result_ref") if isinstance(output.get("result_ref"), dict) else {}
    if result_ref:
        return int(result_ref.get("result_count") or 0)
    resolved_targets = 0
    for key in ("contacts", "groups"):
        values = output.get(key)
        if isinstance(values, list):
            resolved_targets += len(values)
    if resolved_targets:
        return resolved_targets
    for key in ("items", "messages", "results"):
        values = output.get(key)
        if isinstance(values, list):
            return len(values)
    return int(output.get("result_count") or 0)


def _output_model_tokens(output: dict[str, Any]) -> int:
    if bool(output.get("cache_hit")):
        return 0
    explicit = _positive_int(output.get("model_tokens"))
    if explicit:
        return explicit
    usage = output.get("usage")
    if not isinstance(usage, dict):
        return 0
    total = _positive_int(usage.get("total_tokens"))
    if total:
        return total
    return _positive_int(usage.get("prompt_tokens")) + _positive_int(usage.get("completion_tokens"))


def _output_temp_result_bytes(output: dict[str, Any]) -> int:
    result_ref = output.get("result_ref") if isinstance(output.get("result_ref"), dict) else {}
    if not result_ref:
        return 0
    return _positive_int(result_ref.get("estimated_chars"))


def _resource_limit_from_error(error_text: str) -> str:
    text = str(error_text or "").strip()
    prefix = "RESOURCE_LIMIT_EXCEEDED:"
    if not text.startswith(prefix):
        return ""
    return text.split(":", 1)[1].strip()


def _append_step_event(
    events: list[dict[str, Any]],
    *,
    record_id: str,
    step: Any,
    event_type: str,
    state: str,
    message: str = "",
    result_count: int = 0,
    error_text: str = "",
    duration_ms: int = 0,
    resource_usage: dict[str, Any] | None = None,
    attempt: int = 0,
    max_attempts: int = 0,
    retryable: bool | None = None,
    resource_limit: str = "",
) -> None:
    events.append(
        AIActionEvent(
            step_id=str(getattr(step, "id", "") or ""),
            action=str(getattr(step, "action", "") or ""),
            state=state,
            event_type=event_type,
            plan_id=record_id,
            message=message,
            result_count=result_count,
            error_code=_error_code(error_text),
            duration_ms=duration_ms,
            resource_usage=dict(resource_usage or {}),
            attempt=attempt,
            max_attempts=max_attempts,
            retryable=retryable,
            resource_limit=str(resource_limit or "").strip(),
        ).to_dict()
    )


def _plan_json_with_events(plan_json: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    payload = dict(plan_json or {})
    payload["events"] = events[-20:]
    payload["resource_usage"] = _aggregate_resource_usage(events)
    return payload


def _step_resource_usage(
    *,
    duration_ms: int = 0,
    result_count: int = 0,
    output_bytes: int = 0,
    result_ref: bool = False,
    model_call_cost: int = 0,
    model_tokens: int = 0,
    temp_result_bytes: int = 0,
) -> dict[str, Any]:
    return {
        "duration_ms": _positive_int(duration_ms),
        "result_count": _positive_int(result_count),
        "output_bytes": _positive_int(output_bytes),
        "result_ref": bool(result_ref),
        "model_call_cost": _positive_int(model_call_cost),
        "model_tokens": _positive_int(model_tokens),
        "temp_result_bytes": _positive_int(temp_result_bytes),
    }


def _aggregate_resource_usage(events: list[dict[str, Any]]) -> dict[str, int]:
    aggregate = {
        "total_duration_ms": 0,
        "total_result_count": 0,
        "total_output_bytes": 0,
        "total_model_call_cost": 0,
        "total_model_tokens": 0,
        "total_temp_result_bytes": 0,
        "result_ref_count": 0,
        "step_event_count": 0,
    }
    for event in events:
        if not isinstance(event, dict):
            continue
        usage = event.get("resource_usage")
        if not isinstance(usage, dict):
            continue
        aggregate["step_event_count"] += 1
        aggregate["total_duration_ms"] += _positive_int(usage.get("duration_ms"))
        aggregate["total_result_count"] += _positive_int(usage.get("result_count"))
        aggregate["total_output_bytes"] += _positive_int(usage.get("output_bytes"))
        aggregate["total_model_call_cost"] += _positive_int(usage.get("model_call_cost"))
        aggregate["total_model_tokens"] += _positive_int(usage.get("model_tokens"))
        aggregate["total_temp_result_bytes"] += _positive_int(usage.get("temp_result_bytes"))
        if bool(usage.get("result_ref")):
            aggregate["result_ref_count"] += 1
    return aggregate


def _check_runtime_budget(plan_json: dict[str, Any], budget: ActionRuntimeBudget) -> RuntimeBudgetCheck:
    usage = dict((plan_json or {}).get("resource_usage") or {})
    if _positive_int(usage.get("total_output_bytes")) > _positive_int(budget.max_total_output_bytes):
        return RuntimeBudgetCheck(False, "total_output_bytes")
    if _positive_int(usage.get("result_ref_count")) > _positive_int(budget.max_result_ref_count):
        return RuntimeBudgetCheck(False, "result_ref_count")
    if _positive_int(usage.get("total_result_count")) > _positive_int(budget.max_total_result_count):
        return RuntimeBudgetCheck(False, "total_result_count")
    if _positive_int(usage.get("total_duration_ms")) > _positive_int(budget.max_total_duration_ms):
        return RuntimeBudgetCheck(False, "total_duration_ms")
    if _positive_int(usage.get("total_model_tokens")) > _positive_int(budget.max_total_model_tokens):
        return RuntimeBudgetCheck(False, "total_model_tokens")
    return RuntimeBudgetCheck(True)


def _model_call_cost(spec: AtomicActionSpec) -> int:
    return _positive_int(getattr(spec, "model_call_cost", 0))


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _waiting_event_type(state: str) -> str:
    if state == "waiting_clarification":
        return "step_waiting_clarification"
    if state == "waiting_confirmation":
        return "step_waiting_confirmation"
    return "step_waiting"


def _error_code(error_text: str) -> str:
    text = str(error_text or "").strip()
    if not text:
        return ""
    code = text.split(":", 1)[0].strip()
    return code or "ACTION_FAILED"


def _plan_events(plan_json: dict[str, Any]) -> list[dict[str, Any]]:
    events = plan_json.get("events")
    return [dict(item) for item in list(events or []) if isinstance(item, dict)]

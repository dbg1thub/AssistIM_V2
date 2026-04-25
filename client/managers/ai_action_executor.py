"""Sequential executor for AI action plans."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from client.core import logging
from client.managers.ai_action_permission_policy import AIPermissionPolicy
from client.managers.ai_action_registry import AtomicActionRegistry
from client.managers.ai_action_types import (
    AIActionEvent,
    AIActionPlan,
    ActionExecutionResult,
    ActionPause,
    AtomicActionSpec,
)
from client.storage.ai_action_plan_store import AIActionPlanRecord, AIActionPlanStore


logger = logging.get_logger(__name__)


class AIActionExecutor:
    """Execute atomic action steps and persist progress after every step."""

    def __init__(
        self,
        *,
        registry: AtomicActionRegistry,
        store: AIActionPlanStore,
        permission_policy: AIPermissionPolicy | None = None,
    ) -> None:
        self._registry = registry
        self._store = store
        self._permission_policy = permission_policy or AIPermissionPolicy()

    async def execute(self, record: AIActionPlanRecord) -> ActionExecutionResult:
        plan = AIActionPlan.from_dict(dict(record.plan_json or {}))
        if not plan.steps:
            return ActionExecutionResult(state="failed", error_text="PLAN_SCHEMA_INVALID")
        outputs = dict(record.step_outputs or {})
        events = _plan_events(record.plan_json)

        for step in plan.steps:
            if step.id in outputs:
                continue
            missing_deps = [dep for dep in step.depends_on if dep not in outputs]
            if missing_deps:
                return await self._fail(record, outputs, f"ARG_REFERENCE_INVALID: missing dependency {missing_deps[0]}")

            spec = self._registry.get(step.action)
            if spec is None:
                return await self._fail(record, outputs, f"ACTION_NOT_FOUND: {step.action}")
            if not spec.enabled and step.action != "message.send":
                return await self._fail(record, outputs, f"ACTION_DISABLED: {step.action}")

            try:
                resolved_args = _resolve_refs(step.args, outputs)
                self._check_guardrails(spec, resolved_args)
            except ValueError as exc:
                return await self._fail(record, outputs, str(exc))

            permission = self._permission_policy.check_step(
                spec=spec,
                args=resolved_args,
                plan_context={"plan_id": record.id, "plan_version": record.plan_version},
            )
            if not permission.allowed:
                return await self._fail(record, outputs, permission.code or "PERMISSION_DENIED")

            events.append(
                AIActionEvent(
                    step_id=step.id,
                    action=step.action,
                    state="started",
                    message=step.display_text,
                ).to_dict()
            )
            await self._store.update_plan(
                record.id,
                state="running",
                current_step_id=step.id,
                step_outputs=outputs,
                waiting_payload={},
            )

            handler = spec.handler
            if handler is None:
                return await self._fail(record, outputs, f"ACTION_NOT_FOUND: {step.action}")
            step_started = time.perf_counter()
            try:
                raw_output = await handler(
                    resolved_args,
                    {
                        "plan_id": record.id,
                        "plan_version": record.plan_version,
                        "step_id": step.id,
                        "store": self._store,
                        "step_outputs": outputs,
                    },
                )
            except Exception:
                logger.exception("AI action step failed: %s", step.action)
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
                return await self._fail(record, outputs, f"ACTION_FAILED: {step.action}")

            if isinstance(raw_output, ActionPause):
                payload = dict(raw_output.payload or {})
                payload["response_text"] = raw_output.response_text
                await self._store.update_plan(
                    record.id,
                    state=raw_output.state,
                    current_step_id=step.id,
                    step_outputs=outputs,
                    waiting_payload=payload,
                )
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

            try:
                validated_output = _validate_output(raw_output)
                raw_output_bytes = _json_size(validated_output)
                output = await self._enforce_output_size(record, step.id, spec, validated_output)
            except ValueError as exc:
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
                return await self._fail(record, outputs, str(exc))

            outputs[step.id] = output
            _update_compat_slots(record.plan_json, step.id, output)
            result_count = _output_result_count(output)
            has_result_ref = isinstance(output.get("result_ref"), dict)
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
            events.append(
                AIActionEvent(
                    step_id=step.id,
                    action=step.action,
                    state="completed",
                    result_count=result_count,
                ).to_dict()
            )
            plan_json = dict(record.plan_json or {})
            plan_json["events"] = events[-20:]
            await self._store.update_plan(
                record.id,
                plan_json=plan_json,
                reason=f"step_completed_{step.id}",
                bump_version=False,
                state="running",
                current_step_id=step.id,
                step_outputs=outputs,
                waiting_payload={},
            )
            record = await self._store.get_plan(record.id) or record

        return await self._complete(record, outputs)

    async def _complete(self, record: AIActionPlanRecord, outputs: dict[str, Any]) -> ActionExecutionResult:
        final = self._project_final(record, outputs)
        state = "running" if final.memory_context_lines else "done"
        await self._store.update_plan(
            record.id,
            state=state,
            current_step_id="",
            step_outputs={**outputs, "final": dict(final.final_output or {})},
            waiting_payload={},
            completed_at=0 if state == "running" else time.time(),
        )
        return final

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
    ) -> ActionExecutionResult:
        await self._store.update_plan(
            record.id,
            state="failed",
            step_outputs=outputs,
            error_text=error_text,
            completed_at=time.time(),
        )
        return ActionExecutionResult(state="failed", response_text="这个操作执行失败，请稍后再试。", error_text=error_text)

    def _check_guardrails(self, spec: AtomicActionSpec, args: dict[str, Any]) -> None:
        if _json_size(args) > spec.max_input_bytes:
            raise ValueError("PAYLOAD_TOO_LARGE: input")
        if spec.name == "contact.resolve":
            queries = args.get("queries")
            if spec.max_targets is not None and isinstance(queries, list) and len(queries) > spec.max_targets:
                raise ValueError("PLAN_TOO_LARGE: too many targets")
        if spec.name == "message.send":
            content = str(args.get("content") or "")
            if spec.max_content_chars is not None and len(content) > spec.max_content_chars:
                raise ValueError("PAYLOAD_TOO_LARGE: content")
            target = args.get("target") if isinstance(args.get("target"), dict) else {}
            if spec.require_resolved_target and not str(target.get("contact_id") or "").strip():
                raise ValueError("ARG_SCHEMA_INVALID: target")
            if spec.idempotency_required and not str(args.get("idempotency_key") or "").strip():
                raise ValueError("IDEMPOTENCY_KEY_REQUIRED")

    async def _enforce_output_size(
        self,
        record: AIActionPlanRecord,
        step_id: str,
        spec: AtomicActionSpec,
        output: dict[str, Any],
    ) -> dict[str, Any]:
        if _json_size(output) <= spec.max_output_json_bytes:
            return output
        temp = await self._store.create_temp_result(
            plan_id=record.id,
            step_id=step_id,
            result_type=spec.name,
            payload=output,
            payload_meta={
                "result_count": int(output.get("result_count") or 0),
                "estimated_chars": _json_size(output),
            },
        )
        return {
            "result_ref": {
                "type": spec.name,
                "id": temp.id,
                "result_count": int(output.get("result_count") or 0),
                "estimated_chars": _json_size(output),
                "expires_at": temp.expires_at,
            }
        }


def _validate_output(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("OUTPUT_SCHEMA_INVALID")
    return dict(value)


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
    return int(output.get("result_count") or 0)


def _plan_events(plan_json: dict[str, Any]) -> list[dict[str, Any]]:
    events = plan_json.get("events")
    return [dict(item) for item in list(events or []) if isinstance(item, dict)]


def _update_compat_slots(plan_json: dict[str, Any], step_id: str, output: dict[str, Any]) -> None:
    compat = dict(plan_json.get("compat_slots") or {})
    if step_id.startswith("resolve") and isinstance(output.get("contacts"), list):
        contacts = [item for item in output["contacts"] if isinstance(item, dict)]
        if contacts:
            compat["resolved_contacts"] = contacts
    plan_json["compat_slots"] = compat

"""Normalize model action plans into executable atomic steps."""

from __future__ import annotations

from client.managers.ai_action_types import AIActionPlan, AIActionStep


class AIPlanNormalizer:
    """Deterministic cleanup for atomic action plans."""

    def __init__(self) -> None:
        self._last_rejection_reason = ""

    @property
    def last_rejection_reason(self) -> str:
        return self._last_rejection_reason

    def normalize(self, plan: AIActionPlan, *, user_text: str) -> AIActionPlan:
        self._last_rejection_reason = ""
        if not plan.is_action:
            self._last_rejection_reason = "plan_not_action"
            return plan
        if plan.control and not plan.steps:
            return plan
        if plan.steps:
            return self._normalize_atomic_plan(plan, user_text=user_text)
        self._last_rejection_reason = "action_without_steps"
        return AIActionPlan(is_action=False)

    def _normalize_atomic_plan(self, plan: AIActionPlan, *, user_text: str) -> AIActionPlan:
        steps: list[AIActionStep] = []
        seen_ids: set[str] = set()
        for index, step in enumerate(plan.steps, start=1):
            step_id = step.id or _default_step_id(step.action, index)
            if step_id in seen_ids:
                step_id = f"{step_id}_{index}"
            seen_ids.add(step_id)
            steps.append(
                AIActionStep(
                    id=step_id,
                    action=step.action,
                    depends_on=tuple(item for item in step.depends_on if item in seen_ids),
                    args=dict(step.args or {}),
                    display_text=step.display_text or _display_text(step.action),
                    explanation=step.explanation or _explanation(step.action),
                    fallback=step.fallback,
                )
            )
        steps = self._ensure_reference_dependencies(steps)
        steps = self._canonicalize_send_chain_refs(steps)
        steps = self._ensure_reference_dependencies(steps)
        steps = self._ensure_write_confirmation(steps)
        if self._has_confirmation_without_write(steps):
            self._last_rejection_reason = "confirmation_without_write"
            return AIActionPlan(is_action=False)
        invalid_reasons = self._invalid_atomic_write_chain_reasons(steps)
        if invalid_reasons:
            self._last_rejection_reason = ",".join(invalid_reasons)
            return AIActionPlan(is_action=False)
        return AIActionPlan(
            is_action=True,
            goal=plan.goal or _clip(user_text, 80),
            risk=_plan_risk(steps, plan.risk),
            steps=tuple(steps),
            final=dict(plan.final or {"type": "answer"}),
            control=dict(plan.control or {}),
        )

    def _ensure_write_confirmation(self, steps: list[AIActionStep]) -> list[AIActionStep]:
        output: list[AIActionStep] = []
        for step in steps:
            if step.action != "message.send":
                output.append(step)
                continue
            has_confirmation = any(
                prior.action == "user.confirm" and prior.id in set(step.depends_on)
                for prior in output
            )
            if has_confirmation:
                output.append(step)
                continue
            existing_confirm = _latest_complete_send_confirmation(output, send_step=step)
            if existing_confirm is not None:
                output.append(
                    AIActionStep(
                        id=step.id,
                        action=step.action,
                        depends_on=tuple(dict.fromkeys([*step.depends_on, existing_confirm.id])),
                        args=dict(step.args or {}),
                        display_text=step.display_text,
                        explanation=step.explanation,
                        fallback=step.fallback,
                    )
                )
                continue
            confirm_id = f"confirm_{step.id}"
            output.append(
                AIActionStep(
                    id=confirm_id,
                    action="user.confirm",
                    depends_on=step.depends_on,
                    args={
                        "risk": "high",
                        "preview": {
                            "operation": "发送消息",
                            "target": step.args.get("target") or "",
                            "content": step.args.get("content") or "",
                        },
                    },
                    display_text="等待你确认发送...",
                    explanation="发送消息会产生外部影响，必须先确认。",
                )
            )
            output.append(
                AIActionStep(
                    id=step.id,
                    action=step.action,
                    depends_on=tuple(dict.fromkeys([*step.depends_on, confirm_id])),
                    args=dict(step.args or {}),
                    display_text=step.display_text,
                    explanation=step.explanation,
                    fallback=step.fallback,
                )
            )
        return output

    @staticmethod
    def _canonicalize_send_chain_refs(steps: list[AIActionStep]) -> list[AIActionStep]:
        chains = _send_chain_refs(steps)
        if not chains:
            return steps
        confirm_drafts = {
            confirm_id: draft_id
            for draft_id, confirm_id in chains.values()
            if confirm_id
        }
        output: list[AIActionStep] = []
        for step in steps:
            if step.action == "user.confirm" and step.id in confirm_drafts:
                output.append(_canonicalize_confirm_step(step, draft_id=confirm_drafts[step.id]))
                continue
            if step.action == "message.send" and step.id in chains:
                draft_id, confirm_id = chains[step.id]
                output.append(_canonicalize_send_step(step, draft_id=draft_id, confirm_id=confirm_id))
                continue
            output.append(step)
        return output

    @staticmethod
    def _ensure_reference_dependencies(steps: list[AIActionStep]) -> list[AIActionStep]:
        output: list[AIActionStep] = []
        seen_ids: set[str] = set()
        for step in steps:
            refs = _refs_in_value(step.args)
            depends = tuple(
                dict.fromkeys(
                    [
                        *step.depends_on,
                        *(ref for ref in refs if ref in seen_ids and ref != step.id),
                    ]
                )
            )
            output.append(
                AIActionStep(
                    id=step.id,
                    action=step.action,
                    depends_on=depends,
                    args=dict(step.args or {}),
                    display_text=step.display_text,
                    explanation=step.explanation,
                    fallback=step.fallback,
                )
            )
            seen_ids.add(step.id)
        return output

    @staticmethod
    def _has_confirmation_without_write(steps: list[AIActionStep]) -> bool:
        write_step_ids = {
            step.id
            for step in steps
            if step.action in {"message.send", "friend.add", "moment.publish"}
        }
        if not write_step_ids:
            return any(step.action == "user.confirm" for step in steps)
        for step in steps:
            if step.action != "user.confirm":
                continue
            if not any(step.id in set(candidate.depends_on) for candidate in steps if candidate.id in write_step_ids):
                return True
        return False

    @staticmethod
    def _has_invalid_atomic_write_chain(steps: list[AIActionStep]) -> bool:
        return bool(AIPlanNormalizer._invalid_atomic_write_chain_reasons(steps))

    @staticmethod
    def _invalid_atomic_write_chain_reasons(steps: list[AIActionStep]) -> list[str]:
        by_id = {step.id: step for step in steps}
        reasons: list[str] = []
        for step in steps:
            if step.action == "message.draft" and not _message_draft_is_complete(step):
                reasons.append(f"{step.id}:message_draft_incomplete")
            if step.action != "message.send":
                continue
            if not _message_send_is_complete(step):
                reasons.append(f"{step.id}:message_send_incomplete")
            confirm_steps = [by_id.get(dep) for dep in step.depends_on if by_id.get(dep) and by_id[dep].action == "user.confirm"]
            if not confirm_steps:
                reasons.append(f"{step.id}:missing_user_confirm_dependency")
            if not any(_confirm_send_is_complete(confirm) for confirm in confirm_steps if confirm is not None):
                reasons.append(f"{step.id}:incomplete_user_confirm_preview")
            if not _refs_are_available(step.args, available=set(step.depends_on)):
                reasons.append(f"{step.id}:message_send_unavailable_ref")
        return reasons


def _latest_complete_send_confirmation(steps: list[AIActionStep], *, send_step: AIActionStep) -> AIActionStep | None:
    send_refs = _refs_in_value(send_step.args)
    for step in reversed(steps):
        if step.action != "user.confirm" or not _confirm_send_is_complete(step):
            continue
        confirm_refs = _refs_in_value(step.args)
        confirm_depends = set(step.depends_on)
        if not send_refs or send_refs & confirm_refs or send_refs & confirm_depends:
            return step
    return None


def _send_chain_refs(steps: list[AIActionStep]) -> dict[str, tuple[str, str]]:
    by_id = {step.id: step for step in steps}
    chains: dict[str, tuple[str, str]] = {}
    for step in steps:
        if step.action != "message.send":
            continue
        confirm_ids = [
            dep
            for dep in step.depends_on
            if (by_id.get(dep) is not None and by_id[dep].action == "user.confirm")
        ]
        for root in _refs_in_value(step.args.get("preview")):
            candidate = by_id.get(root)
            if candidate is not None and candidate.action == "user.confirm" and root not in confirm_ids:
                confirm_ids.append(root)

        draft_ids = {
            root
            for root in _refs_in_value(step.args)
            if (by_id.get(root) is not None and by_id[root].action == "message.draft")
        }
        for confirm_id in confirm_ids:
            confirm = by_id.get(confirm_id)
            if confirm is None:
                continue
            draft_ids.update(
                dep
                for dep in confirm.depends_on
                if (by_id.get(dep) is not None and by_id[dep].action == "message.draft")
            )
            draft_ids.update(
                root
                for root in _refs_in_value(confirm.args)
                if (by_id.get(root) is not None and by_id[root].action == "message.draft")
            )
        if len(draft_ids) == 1:
            chains[step.id] = (next(iter(draft_ids)), confirm_ids[0] if len(confirm_ids) == 1 else "")
    return chains


def _canonicalize_confirm_step(step: AIActionStep, *, draft_id: str) -> AIActionStep:
    args = dict(step.args or {})
    preview = dict(args.get("preview") or {}) if isinstance(args.get("preview"), dict) else {}
    if preview:
        preview["target"] = f"${draft_id}.target"
        preview["content"] = f"${draft_id}.content"
        args["preview"] = preview
    return AIActionStep(
        id=step.id,
        action=step.action,
        depends_on=step.depends_on,
        args=args,
        display_text=step.display_text,
        explanation=step.explanation,
        fallback=step.fallback,
    )


def _canonicalize_send_step(step: AIActionStep, *, draft_id: str, confirm_id: str) -> AIActionStep:
    args = dict(step.args or {})
    args["target"] = f"${draft_id}.target_entity"
    args["content"] = f"${draft_id}.content"
    args["idempotency_key"] = f"${draft_id}.idempotency_key"
    depends_on = step.depends_on
    if confirm_id:
        depends_on = tuple(dict.fromkeys([*depends_on, confirm_id]))
    return AIActionStep(
        id=step.id,
        action=step.action,
        depends_on=depends_on,
        args=args,
        display_text=step.display_text,
        explanation=step.explanation,
        fallback=step.fallback,
    )


def _message_draft_is_complete(step: AIActionStep) -> bool:
    args = dict(step.args or {})
    return (
        _has_value(args.get("target"))
        and _has_value(args.get("content"))
        and _refs_are_available(args, available=set(step.depends_on))
    )


def _message_send_is_complete(step: AIActionStep) -> bool:
    args = dict(step.args or {})
    return (
        _has_value(args.get("target"))
        and _has_value(args.get("content"))
        and _has_value(args.get("idempotency_key"))
    )


def _confirm_send_is_complete(step: AIActionStep) -> bool:
    args = dict(step.args or {})
    preview = args.get("preview") if isinstance(args.get("preview"), dict) else {}
    operation = str(preview.get("operation") or "").strip()
    return (
        "发送" in operation
        and _has_value(preview.get("target"))
        and _has_value(preview.get("content"))
        and _refs_are_available(preview, available=set(step.depends_on))
    )


def _refs_are_available(value: object, *, available: set[str]) -> bool:
    for ref in _refs_in_value(value):
        if ref not in available:
            return False
    return True


def _refs_in_value(value: object) -> set[str]:
    if isinstance(value, str):
        if not value.startswith("$"):
            return set()
        ref = value[1:]
        stops = [index for index in (ref.find("."), ref.find("[")) if index >= 0]
        root = ref[: min(stops) if stops else len(ref)]
        return {root} if root else set()
    if isinstance(value, list | tuple):
        refs: set[str] = set()
        for item in value:
            refs.update(_refs_in_value(item))
        return refs
    if isinstance(value, dict):
        refs: set[str] = set()
        for item in value.values():
            refs.update(_refs_in_value(item))
        return refs
    return set()


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list | tuple | dict):
        return bool(value)
    return True

def _default_step_id(action: str, index: int) -> str:
    base = str(action or "step").replace(".", "_").replace("-", "_").strip("_") or "step"
    return f"{base}_{index}"


def _display_text(action: str) -> str:
    return {
        "contact.resolve": "正在解析对象...",
        "memory.search": "正在检索本地记忆...",
        "memory.summarize": "正在整理检索结果...",
        "message.draft": "正在生成草稿...",
        "user.confirm": "等待你确认...",
        "message.send": "准备执行发送...",
    }.get(str(action or ""), "正在执行步骤...")


def _explanation(action: str) -> str:
    return {
        "contact.resolve": "把用户表达的对象解析为本地稳定实体。",
        "memory.search": "从本地 AI 记忆库检索相关聊天、语音和文件内容。",
        "memory.summarize": "把检索结果整理成可供 AI 回复使用的上下文。",
        "message.draft": "生成发送前可预览的草稿。",
        "user.confirm": "高风险或外部副作用操作需要用户确认。",
        "message.send": "执行发送动作；当前真实发送能力可能被禁用。",
    }.get(str(action or ""), "执行模型计划中的原子动作。")


def _plan_risk(steps: list[AIActionStep], fallback: str) -> str:
    if any(step.action == "message.send" for step in steps):
        return "high"
    normalized = str(fallback or "low").strip().lower()
    return normalized if normalized in {"low", "medium", "high"} else "low"


def _clip(value: str, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."

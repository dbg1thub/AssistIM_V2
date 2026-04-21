"""Normalize model action plans into executable atomic steps."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from client.managers.ai_action_types import AIActionPlan, AIActionStep


class AIPlanNormalizer:
    """Deterministic plan cleanup and legacy-plan conversion."""

    def normalize(self, plan: AIActionPlan, *, user_text: str) -> AIActionPlan:
        if not plan.is_action:
            return plan
        if plan.steps:
            return self._normalize_atomic_plan(plan, user_text=user_text)
        return self._from_legacy_plan(plan, user_text=user_text)

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
        steps = self._ensure_memory_search_contact_resolution(steps)
        steps = self._ensure_memory_summarize_source(steps, user_text=user_text)
        steps = self._ensure_write_confirmation(steps)
        if self._has_confirmation_without_write(steps):
            return AIActionPlan(is_action=False)
        if self._has_invalid_atomic_write_chain(steps):
            return AIActionPlan(is_action=False)
        return AIActionPlan(
            is_action=True,
            goal=plan.goal or _clip(user_text, 80),
            risk=_plan_risk(steps, plan.risk),
            steps=tuple(steps),
            final=dict(plan.final or {"type": "answer"}),
            action=plan.action,
            requires_app_data=plan.requires_app_data,
            requires_side_effect=plan.requires_side_effect or any(step.action == "message.send" for step in steps),
            slots=dict(plan.slots or {}),
            missing_slots=plan.missing_slots,
        )

    def _from_legacy_plan(self, plan: AIActionPlan, *, user_text: str) -> AIActionPlan:
        action = str(plan.action or "").strip()
        if action in {"cancel_action", "confirm_action", "select_contact_alias"}:
            return plan
        slots = _normalize_slots(dict(plan.slots or {}))
        if action == "memory_query":
            return self._legacy_memory_query(slots, user_text=user_text)
        if action == "send_message":
            return self._legacy_send_message(slots, user_text=user_text)
        if action == "add_friend":
            return self._disabled_legacy_write(action, slots, user_text=user_text)
        if action == "post_moment":
            return self._disabled_legacy_write(action, slots, user_text=user_text)
        return AIActionPlan(is_action=False)

    def _legacy_memory_query(self, slots: dict[str, Any], *, user_text: str) -> AIActionPlan:
        participants = _clean_list(slots.get("participants"))
        keywords = _clean_list(slots.get("keywords"))
        time_scope = _time_scope(slots.get("time_range"))
        if not participants and not keywords:
            return AIActionPlan(
                is_action=True,
                goal=_clip(user_text, 80),
                risk="low",
                action="memory_query",
                slots={
                    "participants": participants,
                    "keywords": keywords,
                    "time_scope": time_scope,
                    "query_text": user_text,
                },
                missing_slots=("query_terms",),
            )

        steps: list[AIActionStep] = []
        participant_ref: Any = []
        depends: list[str] = []
        if participants:
            steps.append(
                AIActionStep(
                    id="resolve_contacts",
                    action="contact.resolve",
                    args={"queries": participants, "allow_multiple": True},
                    display_text="正在解析联系人...",
                    explanation="用户提到了本地对象，需要先解析为稳定实体。",
                )
            )
            participant_ref = "$resolve_contacts.contacts"
            depends = ["resolve_contacts"]

        steps.append(
            AIActionStep(
                id="search_memory",
                action="memory.search",
                depends_on=tuple(depends),
                args={
                    "participants": participant_ref,
                    "participant_match": "any",
                    "time_scope": time_scope,
                    "keywords": keywords,
                    "question": user_text,
                },
                display_text="正在检索聊天摘要...",
                explanation="按已解析对象、关键词和范围检索本机聊天记忆。",
            )
        )
        steps.append(
            AIActionStep(
                id="summarize_memory",
                action="memory.summarize",
                depends_on=("search_memory",),
                args={"source": "$search_memory", "question": user_text},
                display_text="正在整理检索结果...",
                explanation="基于检索结果生成可回答用户问题的摘要材料。",
            )
        )
        compat_slots = {
            "participants": participants,
            "keywords": keywords,
            "time_scope": time_scope,
            "time_range": _legacy_time_range(time_scope),
            "query_text": user_text,
        }
        return AIActionPlan(
            is_action=True,
            goal=_clip(user_text, 80),
            risk="low",
            steps=tuple(steps),
            final={"type": "answer", "source": "$summarize_memory"},
            action="memory_query",
            requires_app_data=True,
            slots=compat_slots,
        )

    def _legacy_send_message(self, slots: dict[str, Any], *, user_text: str) -> AIActionPlan:
        target_user = str(slots.get("target_user") or "").strip()
        message_text = str(slots.get("message_text") or "").strip()
        missing = []
        if not target_user:
            missing.append("target_user")
        if not message_text:
            missing.append("message_text")
        if missing:
            return AIActionPlan(
                is_action=True,
                goal=_clip(user_text, 80),
                risk="high",
                action="send_message",
                requires_side_effect=True,
                slots={"target_user": target_user, "message_text": message_text},
                missing_slots=tuple(missing),
            )

        steps = (
            AIActionStep(
                id="resolve_target",
                action="contact.resolve",
                args={"queries": [target_user], "allow_multiple": False},
                display_text="正在解析发送对象...",
                explanation="发送消息前必须确认唯一目标。",
            ),
            AIActionStep(
                id="draft_message",
                action="message.draft",
                depends_on=("resolve_target",),
                args={"target": "$resolve_target.contacts[0]", "content": message_text},
                display_text="正在生成消息草稿...",
                explanation="发送前先生成可预览的消息草稿。",
            ),
            AIActionStep(
                id="confirm_send",
                action="user.confirm",
                depends_on=("draft_message",),
                args={
                    "risk": "high",
                    "preview": {
                        "operation": "发送消息",
                        "target": "$draft_message.target",
                        "content": "$draft_message.content",
                    },
                },
                display_text="等待你确认发送...",
                explanation="发送消息会产生外部影响，必须先确认。",
            ),
            AIActionStep(
                id="send_message",
                action="message.send",
                depends_on=("confirm_send", "draft_message"),
                args={
                    "target": "$draft_message.target_entity",
                    "content": "$draft_message.content",
                    "preview": "$draft_message.preview",
                    "idempotency_key": "$draft_message.idempotency_key",
                },
                display_text="准备发送消息...",
                explanation="确认后才会进入真实发送步骤；当前版本发送能力禁用。",
            ),
        )
        return AIActionPlan(
            is_action=True,
            goal=_clip(user_text, 80),
            risk="high",
            steps=steps,
            final={"type": "answer", "source": "$send_message.text"},
            action="send_message",
            requires_side_effect=True,
            slots={"target_user": target_user, "message_text": message_text},
        )

    def _disabled_legacy_write(self, action: str, slots: dict[str, Any], *, user_text: str) -> AIActionPlan:
        return AIActionPlan(
            is_action=True,
            goal=_clip(user_text, 80),
            risk="high",
            action=action,
            requires_side_effect=True,
            slots=dict(slots or {}),
            missing_slots=(),
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

    def _ensure_memory_summarize_source(self, steps: list[AIActionStep], *, user_text: str) -> list[AIActionStep]:
        by_id = {step.id: step for step in steps}
        output: list[AIActionStep] = []
        for step in steps:
            if step.action != "memory.summarize":
                output.append(step)
                continue
            args = dict(step.args or {})
            if args.get("source"):
                if not args.get("question"):
                    args["question"] = user_text
                output.append(
                    AIActionStep(
                        id=step.id,
                        action=step.action,
                        depends_on=step.depends_on,
                        args=args,
                        display_text=step.display_text,
                        explanation=step.explanation,
                        fallback=step.fallback,
                    )
                )
                continue

            source_step_id = ""
            for dep in step.depends_on:
                dep_step = by_id.get(dep)
                if dep_step is not None and dep_step.action == "memory.search":
                    source_step_id = dep_step.id
                    break
            if not source_step_id:
                output.append(step)
                continue

            args["source"] = f"${source_step_id}"
            args.setdefault("question", user_text)
            output.append(
                AIActionStep(
                    id=step.id,
                    action=step.action,
                    depends_on=step.depends_on,
                    args=args,
                    display_text=step.display_text,
                    explanation=step.explanation,
                    fallback=step.fallback,
                )
            )
        return output

    def _ensure_memory_search_contact_resolution(self, steps: list[AIActionStep]) -> list[AIActionStep]:
        output: list[AIActionStep] = []
        used_ids = {step.id for step in steps}
        for step in steps:
            if step.action != "memory.search" or _has_contact_resolve_dependency(step, steps):
                output.append(step)
                continue
            queries = _participant_queries_for_resolution(step.args.get("participants"))
            if not queries:
                output.append(step)
                continue
            resolve_id = _unique_step_id("resolve_contacts", used_ids)
            used_ids.add(resolve_id)
            output.append(
                AIActionStep(
                    id=resolve_id,
                    action="contact.resolve",
                    args={"queries": queries, "allow_multiple": True},
                    display_text="正在解析联系人...",
                    explanation="用户提到了本地对象，需要先解析为稳定实体。",
                )
            )
            args = dict(step.args or {})
            args["participants"] = f"${resolve_id}.contacts"
            output.append(
                AIActionStep(
                    id=step.id,
                    action=step.action,
                    depends_on=tuple(dict.fromkeys([*step.depends_on, resolve_id])),
                    args=args,
                    display_text=step.display_text,
                    explanation=step.explanation,
                    fallback=step.fallback,
                )
            )
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
        by_id = {step.id: step for step in steps}
        for step in steps:
            if step.action == "message.draft" and not _message_draft_is_complete(step):
                return True
            if step.action != "message.send":
                continue
            if not _message_send_is_complete(step):
                return True
            confirm_steps = [by_id.get(dep) for dep in step.depends_on if by_id.get(dep) and by_id[dep].action == "user.confirm"]
            if not confirm_steps:
                return True
            if not any(_confirm_send_is_complete(confirm) for confirm in confirm_steps if confirm is not None):
                return True
            if not _refs_are_available(step.args, available=set(step.depends_on)):
                return True
        return False


def _time_scope(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        scope_type = str(value.get("type") or "").strip()
        if scope_type == "all_history":
            return {"type": "all_history"}
        start_ts = _coerce_ts(value.get("start_ts") or value.get("start"))
        end_ts = _coerce_ts(value.get("end_ts") or value.get("end"))
        if start_ts is not None and end_ts is not None and end_ts > start_ts:
            return {
                "type": "range",
                "start_ts": start_ts,
                "end_ts": end_ts,
                "label": str(value.get("label") or "指定时间范围"),
            }
    return {"type": "all_history"}


def _legacy_time_range(scope: dict[str, Any]) -> dict[str, Any] | None:
    if scope.get("type") != "range":
        return None
    return {
        "start_ts": int(scope.get("start_ts") or 0),
        "end_ts": int(scope.get("end_ts") or 0),
        "label": str(scope.get("label") or "指定时间范围"),
    }


def _coerce_ts(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = " ".join(str(value or "").split())
    if not text:
        return None
    if text.isdigit():
        return int(text)
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _normalize_slots(slots: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(slots or {})
    normalized["participants"] = _clean_list(normalized.get("participants"))
    normalized["keywords"] = _clean_list(normalized.get("keywords"))
    for key in ("target_user", "message_text", "content"):
        if key in normalized:
            normalized[key] = " ".join(str(normalized.get(key) or "").split())
    return normalized


def _clean_list(value: object) -> list[str]:
    if value is None:
        return []
    raw = value if isinstance(value, list) else [value]
    items: list[str] = []
    for item in raw:
        text = " ".join(str(item or "").split()).strip(" ，,。？！?;；:：")
        if not text:
            continue
        if text not in items:
            items.append(text)
    return items[:8]


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


def _has_contact_resolve_dependency(step: AIActionStep, steps: list[AIActionStep]) -> bool:
    by_id = {candidate.id: candidate for candidate in steps}
    return any(by_id.get(dep) is not None and by_id[dep].action == "contact.resolve" for dep in step.depends_on)


def _participant_queries_for_resolution(value: object) -> list[str]:
    if value is None or _value_contains_ref(value):
        return []
    if isinstance(value, dict):
        return []
    raw = value if isinstance(value, list) else [value]
    if any(isinstance(item, dict) for item in raw):
        return []
    return _clean_list(raw)


def _value_contains_ref(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().startswith("$")
    if isinstance(value, list | tuple):
        return any(_value_contains_ref(item) for item in value)
    if isinstance(value, dict):
        return any(_value_contains_ref(item) for item in value.values())
    return False


def _unique_step_id(base: str, used_ids: set[str]) -> str:
    normalized = _default_step_id(base, 0).removesuffix("_0")
    if normalized not in used_ids:
        return normalized
    index = 2
    while f"{normalized}_{index}" in used_ids:
        index += 1
    return f"{normalized}_{index}"


def _default_step_id(action: str, index: int) -> str:
    base = str(action or "step").replace(".", "_").replace("-", "_").strip("_") or "step"
    return f"{base}_{index}"


def _display_text(action: str) -> str:
    return {
        "contact.resolve": "正在解析对象...",
        "memory.search": "正在检索本机数据...",
        "memory.summarize": "正在整理结果...",
        "message.draft": "正在生成草稿...",
        "user.confirm": "等待你确认...",
        "message.send": "准备执行发送...",
    }.get(str(action or ""), "正在执行步骤...")


def _explanation(action: str) -> str:
    return {
        "contact.resolve": "把用户表达的对象解析为本地稳定实体。",
        "memory.search": "按结构化条件检索本机数据。",
        "memory.summarize": "将检索结果整理成回答材料。",
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

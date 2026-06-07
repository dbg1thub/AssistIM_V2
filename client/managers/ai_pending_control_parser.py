"""Pending-state control parser for AI assistant actions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal


PendingControlType = Literal["confirm", "cancel", "select_contact_alias", "fill_slots", "unrelated"]
FORBIDDEN_PENDING_FIELDS = {"action", "actions", "args", "depends_on", "final", "skill", "steps"}
VALID_PENDING_CONTROL_TYPES = {"confirm", "cancel", "select_contact_alias", "fill_slots", "unrelated"}


@dataclass(frozen=True, slots=True)
class AIPendingControlDecision:
    """Structured decision for one user reply to a pending AI action."""

    type: PendingControlType
    selection_index: int | None = None
    contact_id: str = ""
    alias_text: str = ""
    slots: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


class AIPendingControlParser:
    """Parse user replies while an AI action is waiting for input."""

    SCHEMA_VERSION = "pending_control_v1"
    PROMPT_VERSION = "pending_control_prompt_v1"

    async def parse_with_model(
        self,
        user_text: str,
        *,
        pending_state: Any,
        task_manager: Any,
        max_tokens: int = 256,
        strict: bool = True,
    ) -> AIPendingControlDecision | None:
        deterministic = classify_obvious_pending_control(user_text, pending_state)
        if deterministic is not None:
            return deterministic
        if task_manager is None:
            return None
        request = self.build_request(user_text, pending_state=pending_state, max_tokens=max_tokens, strict=strict)
        snapshot = await task_manager.run_once(request)
        return parse_pending_control_json(str(getattr(snapshot, "content", "") or ""))

    def build_request(
        self,
        user_text: str,
        *,
        pending_state: Any,
        max_tokens: int = 256,
        strict: bool = True,
    ) -> Any:
        from client.services.ai_service import AIPrivacyScope, AIRequest, AITaskType

        return AIRequest(
            task_id="ai-pending-control-parse",
            task_type=AITaskType.CHAT,
            privacy_scope=AIPrivacyScope.GENERAL,
            must_be_local=True,
            stream=False,
            temperature=0.0,
            max_tokens=max(1, int(max_tokens or 1)),
            response_format={"type": "json_object", "schema": self.build_schema()} if strict else None,
            priority=4,
            system_prompt=self.system_prompt(),
            messages=[{"role": "user", "content": self.user_prompt(user_text, pending_state=pending_state)}],
            metadata={
                "source": "ai_pending_control_parser",
                "pending_control_schema_version": self.SCHEMA_VERSION,
                "pending_control_prompt_version": self.PROMPT_VERSION,
                "strict_json": bool(strict),
            },
        )

    @staticmethod
    def build_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["confirm", "cancel", "select_contact_alias", "fill_slots", "unrelated"],
                },
                "selection_index": {"type": "integer"},
                "contact_id": {"type": "string"},
                "alias_text": {"type": "string"},
                "slots": {"type": "object"},
                "reason": {"type": "string"},
            },
            "required": ["type"],
            "additionalProperties": False,
        }

    @staticmethod
    def system_prompt() -> str:
        return (
            "你是 AssistIM 的 pending 操作回复解析器。只输出 JSON object。\n"
            "只判断用户对当前 pending 操作的回复，不判断新的用户意图。\n"
            "允许的 type 只有 confirm、cancel、select_contact_alias、fill_slots、unrelated。\n"
            "waiting_confirmation 只能输出 confirm、cancel 或 unrelated。\n"
            "联系人候选选择输出 select_contact_alias，并填写 selection_index、contact_id 或 alias_text。\n"
            "缺少字段补充输出 fill_slots，并把用户补充的信息写入 slots。\n"
            "如果用户想修改已确认预览中的目标、内容或操作，输出 unrelated，不要重建计划。\n"
            "禁止生成执行步骤、原子动作、Skill 或执行计划。\n"
            "输出字段只能是 type、selection_index、contact_id、alias_text、slots、reason。"
        )

    @staticmethod
    def user_prompt(user_text: str, *, pending_state: Any) -> str:
        return (
            "当前 pending："
            + json.dumps(_pending_state_payload(pending_state), ensure_ascii=False, sort_keys=True, default=str)
            + "\n用户回复："
            + str(user_text or "").strip()
        )


def parse_pending_control_json(raw_output: str) -> AIPendingControlDecision | None:
    payload = _parse_json_object(raw_output)
    if payload is None:
        return None
    if FORBIDDEN_PENDING_FIELDS.intersection(payload):
        return None
    if set(payload) - {"type", "selection_index", "contact_id", "alias_text", "slots", "reason"}:
        return None
    control_type = str(payload.get("type") or "").strip()
    if control_type not in VALID_PENDING_CONTROL_TYPES:
        return None
    slots = payload.get("slots")
    if slots is not None and not isinstance(slots, dict):
        return None
    selection_index = _coerce_positive_int(payload.get("selection_index"))
    return AIPendingControlDecision(
        type=control_type,  # type: ignore[arg-type]
        selection_index=selection_index,
        contact_id=str(payload.get("contact_id") or "").strip(),
        alias_text=str(payload.get("alias_text") or "").strip(),
        slots=dict(slots or {}),
        reason=str(payload.get("reason") or "").strip(),
    )


def classify_obvious_pending_control(user_text: str, pending_state: Any) -> AIPendingControlDecision | None:
    text = _compact_text(user_text)
    if not text:
        return None
    state = str(getattr(pending_state, "state", "") or "").strip()
    waiting = dict(getattr(pending_state, "waiting_payload", {}) or {})
    waiting_type = str(waiting.get("type") or "").strip()
    if text in {"取消", "算了", "不用了", "停止", "放弃", "撤销", "cancel"}:
        return AIPendingControlDecision(type="cancel")
    if state == "waiting_confirmation" and waiting_type == "confirmation":
        if text in {"确认", "确定", "可以", "继续", "同意", "发送", "发吧", "好", "是", "yes", "ok"}:
            return AIPendingControlDecision(type="confirm")
        return None
    if state == "waiting_clarification" and waiting_type in {"contact_ambiguity", "target_too_many"}:
        selection_index = _extract_selection_index(text)
        if selection_index is not None:
            return AIPendingControlDecision(
                type="select_contact_alias",
                selection_index=selection_index,
                alias_text=str(selection_index),
            )
    return None


def _pending_state_payload(pending_state: Any) -> dict[str, Any]:
    return {
        "state": str(getattr(pending_state, "state", "") or "").strip(),
        "waiting_payload": dict(getattr(pending_state, "waiting_payload", {}) or {}),
    }


def _parse_json_object(raw_output: str) -> dict[str, Any] | None:
    text = str(raw_output or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _compact_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").casefold()).strip("，,。.!！?？;；:：")


def _extract_selection_index(text: str) -> int | None:
    if text.isdigit():
        return _coerce_positive_int(text)
    if text in {"一", "二", "三", "四", "五"}:
        return {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}.get(text)
    match = re.fullmatch(r"(?:第|选|选择)([1-5一二三四五])(?:个|位|项)?", text)
    if match is None:
        match = re.fullmatch(r"([1-5一二三四五])(?:个|位|项)", text)
    if match is None:
        return None
    token = match.group(1)
    if token.isdigit():
        return _coerce_positive_int(token)
    return {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}.get(token)


def _coerce_positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None

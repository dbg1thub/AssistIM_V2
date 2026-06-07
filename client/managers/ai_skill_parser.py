"""Offline parser utilities for model-facing AI skill intents."""

from __future__ import annotations

import json
import re
from typing import Any

from client.managers.ai_skill_compiler import AISkillCompiler
from client.managers.ai_skill_registry import AISkillRegistry
from client.managers.ai_skill_types import SkillConfidence, SkillIntent


FORBIDDEN_ATOMIC_FIELDS = {"action", "actions", "args", "depends_on", "final", "steps"}
VALID_INTENT_TYPES = {"skill", "unsupported", "clarification"}
VALID_CONFIDENCE = {"low", "medium", "high"}


class AISkillParser:
    """Build parser-facing contracts and parse model JSON into SkillIntent."""

    SCHEMA_VERSION = "skill_intent_v1"
    PROMPT_VERSION = "skill_intent_prompt_v1"

    def __init__(self, *, registry: AISkillRegistry | None = None) -> None:
        self._registry = registry or AISkillCompiler().registry

    @property
    def registry(self) -> AISkillRegistry:
        return self._registry

    def parse(self, raw_output: str) -> SkillIntent | None:
        return parse_skill_intent_json(raw_output, registry=self._registry)

    async def parse_with_model(
        self,
        user_text: str,
        *,
        task_manager: Any,
        max_tokens: int = 512,
        strict: bool = True,
    ) -> SkillIntent | None:
        request = self.build_request(user_text, max_tokens=max_tokens, strict=strict)
        snapshot = await task_manager.run_once(request)
        return self.parse(str(getattr(snapshot, "content", "") or ""))

    def build_request(self, user_text: str, *, max_tokens: int = 512, strict: bool = True) -> Any:
        from client.services.ai_service import AIPrivacyScope, AIRequest, AITaskType

        return AIRequest(
            task_id="ai-skill-parse",
            task_type=AITaskType.CHAT,
            privacy_scope=AIPrivacyScope.GENERAL,
            must_be_local=True,
            stream=False,
            temperature=0.0,
            max_tokens=max(1, int(max_tokens or 1)),
            response_format={"type": "json_object", "schema": self.build_schema()} if strict else None,
            priority=4,
            system_prompt=self.system_prompt(),
            messages=[{"role": "user", "content": self.user_prompt(user_text)}],
            metadata={
                "source": "ai_skill_parser",
                "skill_schema_version": self.SCHEMA_VERSION,
                "skill_prompt_version": self.PROMPT_VERSION,
                "registered_skills": list(self._registry.names()),
                "strict_json": bool(strict),
            },
        )

    def build_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["skill", "unsupported", "clarification"]},
                "skill": {"type": "string", "enum": list(self._registry.names())},
                "goal": {"type": "string"},
                "slots": {"type": "object"},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                "reason": {"type": "string"},
                "missing_slots": {"type": "array", "items": {"type": "string"}},
                "question": {"type": "string"},
            },
            "required": ["type", "goal"],
            "additionalProperties": False,
        }

    def system_prompt(self) -> str:
        return (
            "你是 AssistIM 的 Skill 意图解析器。只输出 JSON object。\n"
            "你只能输出 type=skill、unsupported 或 clarification。\n"
            "skill 必须从已注册 Skill 中选择；禁止输出原子动作链或执行步骤。\n"
            "你只负责语义分类和 slot 抽取，不负责生成执行步骤。\n"
            "搜索/查看 AssistIM 用户、好友、会话、消息、朋友圈和本地记忆都属于 AssistIM 能力。\n"
            "如果用户需要的能力没有对应 Skill，输出 unsupported，不要映射到相近 Skill。\n"
            f"{_skill_catalog_prompt(self._registry)}"
        )

    @staticmethod
    def user_prompt(user_text: str) -> str:
        return f"用户输入：{str(user_text or '').strip()}"


def parse_skill_intent_json(raw_output: str, *, registry: AISkillRegistry | None = None) -> SkillIntent | None:
    registry = registry or AISkillCompiler().registry
    payload = _parse_json_object(raw_output)
    if payload is None:
        return None
    if FORBIDDEN_ATOMIC_FIELDS.intersection(payload):
        return None
    intent_type = str(payload.get("type") or "").strip()
    if intent_type not in VALID_INTENT_TYPES:
        return None
    if intent_type == "skill":
        return _parse_skill_payload(payload, registry=registry)
    if intent_type == "unsupported":
        return _parse_unsupported_payload(payload)
    return _parse_clarification_payload(payload)


def _parse_skill_payload(payload: dict[str, Any], *, registry: AISkillRegistry) -> SkillIntent | None:
    allowed = {"type", "skill", "goal", "slots", "confidence", "reason"}
    if set(payload) - allowed:
        return None
    skill_id = str(payload.get("skill") or "").strip()
    spec = registry.get(skill_id)
    if spec is None or not spec.enabled:
        return None
    slots = payload.get("slots")
    if not isinstance(slots, dict):
        return None
    if not _slot_fields_are_known(slots, spec.input_model):
        return None
    confidence = str(payload.get("confidence") or "medium").strip().lower() or "medium"
    if confidence not in VALID_CONFIDENCE:
        return None
    return SkillIntent(
        type="skill",
        skill=skill_id,
        goal=str(payload.get("goal") or "").strip(),
        slots=dict(slots),
        confidence=confidence,  # type: ignore[arg-type]
        reason=str(payload.get("reason") or "").strip(),
    )


def _parse_unsupported_payload(payload: dict[str, Any]) -> SkillIntent | None:
    allowed = {"type", "goal", "reason"}
    if set(payload) - allowed:
        return None
    return SkillIntent(
        type="unsupported",
        goal=str(payload.get("goal") or "").strip(),
        reason=str(payload.get("reason") or "").strip(),
    )


def _parse_clarification_payload(payload: dict[str, Any]) -> SkillIntent | None:
    allowed = {"type", "goal", "missing_slots", "question", "reason"}
    if set(payload) - allowed:
        return None
    missing_slots = [
        str(item or "").strip()
        for item in list(payload.get("missing_slots") or [])
        if str(item or "").strip()
    ]
    question = str(payload.get("question") or "").strip()
    return SkillIntent(
        type="clarification",
        goal=str(payload.get("goal") or "").strip(),
        reason=str(payload.get("reason") or "").strip(),
        control={"missing_slots": missing_slots, "question": question},
    )


def _slot_fields_are_known(slots: dict[str, Any], input_model: type[Any]) -> bool:
    fields = getattr(input_model, "model_fields", None)
    if not isinstance(fields, dict):
        return True
    return not (set(slots) - set(fields))


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


def _skill_catalog_prompt(registry: AISkillRegistry) -> str:
    lines = ["已注册 Skill："]
    for skill_id in registry.names():
        spec = registry.get(skill_id)
        if spec is None or not spec.enabled:
            continue
        lines.append(f"- {spec.id}: {spec.description} slots={_skill_slot_prompt(spec.input_model)}")
    return "\n".join(lines)


def _skill_slot_prompt(input_model: type[Any]) -> str:
    fields = getattr(input_model, "model_fields", None)
    if not isinstance(fields, dict) or not fields:
        return "{}"
    parts: list[str] = []
    for name, field in fields.items():
        marker = "!" if callable(getattr(field, "is_required", None)) and field.is_required() else ""
        parts.append(f"{name}{marker}")
    return "{" + ", ".join(parts) + "}"

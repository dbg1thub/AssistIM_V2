"""Offline parser utilities for model-facing AI skill intents."""

from __future__ import annotations

import json
import re
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

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
        deterministic = parse_obvious_skill_intent(user_text)
        if deterministic is not None:
            return deterministic
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
            "type=skill 时必须输出 skill 和 slots；slots 没有字段也输出 {}。\n"
            "可选 slot 未提供时省略或使用默认值，不要因为缺少可选 slot 输出 unsupported。\n"
            "slot 值必须符合字段类型和 enum；除非字段允许 null，否则不要输出 null。\n"
            "搜索/查看 AssistIM 用户、好友、会话、消息、朋友圈和本地记忆都属于 AssistIM 能力。\n"
            "如果用户需要的能力没有对应 Skill，输出 unsupported，不要映射到相近 Skill。\n"
            f"{_skill_catalog_prompt(self._registry)}"
        )

    @staticmethod
    def user_prompt(user_text: str) -> str:
        return f"用户输入：{str(user_text or '').strip()}"


def parse_obvious_skill_intent(user_text: str) -> SkillIntent | None:
    text = _normalize_user_text(user_text)
    if not text:
        return None
    for parser in (
        _parse_file_content_skill,
        _parse_moment_skill,
        _parse_send_message_skill,
    ):
        intent = parser(text)
        if intent is not None:
            return intent
    return None


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
    if not _slot_values_are_valid(slots, spec.input_model):
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


def _parse_send_message_skill(text: str) -> SkillIntent | None:
    normalized = _strip_request_prefix(text)
    patterns = (
        re.compile(r"^(?:给|向|和|跟|对)\s*(?P<target>.+?)\s*(?:发送|告诉|转告|说|发)\s*(?P<content>.*)$"),
        re.compile(r"^(?:发送|发|告诉|转告)\s*(?:给|向)\s*(?P<target>.+?)(?:\s+(?P<content>.+))?$"),
    )
    for pattern in patterns:
        match = pattern.match(normalized)
        if not match:
            continue
        target = _clean_slot_text(match.group("target"))
        content = _clean_slot_text(match.groupdict().get("content") or "")
        if not target:
            return None
        if content:
            return SkillIntent(
                type="skill",
                skill="SEND_MESSAGE",
                goal=f"给 {target} 发送消息",
                slots={"target": target, "content": content},
                confidence="high",
                reason="deterministic_send_message_syntax",
            )
        return SkillIntent(
            type="clarification",
            skill="SEND_MESSAGE",
            goal=f"给 {target} 发送消息",
            slots={"target": target},
            confidence="high",
            reason="missing_message_content",
            control={
                "missing_slots": ["content"],
                "question": "你想发送什么内容？",
                "slots": {"target": target},
            },
        )
    return None


def _parse_moment_skill(text: str) -> SkillIntent | None:
    if "朋友圈" not in text:
        return None
    normalized = _strip_request_prefix(text)
    scope = _moment_scope(normalized)
    content_filter = _moment_content_filter(normalized)
    if any(term in normalized for term in ("几条", "多少条", "多少个", "多少", "数量", "数目")):
        return SkillIntent(
            type="skill",
            skill="COUNT_MOMENTS",
            goal="统计朋友圈数量",
            slots={"scope": scope, "content_filter": content_filter},
            confidence="high",
            reason="deterministic_moment_count",
        )
    if any(term in normalized for term in ("主要", "主题", "讲什么", "说什么", "内容", "总结", "概括")):
        return SkillIntent(
            type="skill",
            skill="SUMMARIZE_MOMENTS",
            goal="总结朋友圈内容",
            slots={
                "scope": scope,
                "content_filter": content_filter,
                "question": normalized,
                "limit": 20,
            },
            confidence="high",
            reason="deterministic_moment_summary",
        )
    if any(term in normalized for term in ("查看", "看看", "看下", "看一下", "浏览", "列表")):
        return SkillIntent(
            type="skill",
            skill="LIST_MOMENTS",
            goal="查看朋友圈列表",
            slots={"scope": scope, "content_filter": content_filter, "page": 1, "size": 20},
            confidence="high",
            reason="deterministic_moment_list",
        )
    return None


def _parse_file_content_skill(text: str) -> SkillIntent | None:
    if "文件" not in text:
        return None
    if not any(term in text for term in ("内容", "摘要", "总结", "讲什么", "说什么", "有什么", "是什么")):
        return None
    participants: list[str] = []
    target_match = re.search(r"(?:给|向)\s*(?P<target>.+?)\s*(?:发送|发|传|上传)(?:的)?", text)
    if target_match:
        target = _clean_slot_text(target_match.group("target"))
        if target:
            participants.append(target)
    keywords = _file_query_keywords(text)
    return SkillIntent(
        type="skill",
        skill="FILE_CONTENT_QA",
        goal="检索文件内容",
        slots={
            "participants": participants[:5],
            "question": text,
            "keywords": keywords,
            "time_scope": {"type": "all_history"},
            "limit": 8,
        },
        confidence="high",
        reason="deterministic_file_content_query",
    )


def _moment_scope(text: str) -> str:
    if any(term in text for term in ("我发", "我发布", "我发过", "我发的", "我的朋友圈")):
        return "mine"
    if any(term in text for term in ("点赞", "赞过", "我赞")):
        return "liked"
    return "all"


def _moment_content_filter(text: str) -> str:
    if any(term in text for term in ("图片", "照片", "视频", "媒体")):
        return "media"
    if "链接" in text:
        return "links"
    return "all"


def _file_query_keywords(text: str) -> list[str]:
    keywords: list[str] = []
    quoted = re.findall(r"[「『“\"]([^」』”\"]+)[」』”\"]", text)
    for item in quoted:
        cleaned = _clean_slot_text(item)
        if cleaned and cleaned not in keywords:
            keywords.append(cleaned)
    for match in re.finditer(r"([^\s，,。？?；;：:]+?\.[A-Za-z0-9\u4e00-\u9fff]{1,12})\s*文件", text):
        cleaned = _clean_slot_text(match.group(1))
        if cleaned and cleaned not in keywords:
            keywords.append(cleaned)
    return keywords[:5]


def _strip_request_prefix(text: str) -> str:
    return re.sub(r"^(?:帮我和用户|帮我给用户|请|麻烦|帮我|替我|帮忙)\s*", "", text).strip()


def _normalize_user_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _clean_slot_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip(" ，,。？！?;；:：")


def _slot_fields_are_known(slots: dict[str, Any], input_model: type[Any]) -> bool:
    fields = getattr(input_model, "model_fields", None)
    if not isinstance(fields, dict):
        return True
    return not (set(slots) - set(fields))


def _slot_values_are_valid(slots: dict[str, Any], input_model: type[Any]) -> bool:
    fields = getattr(input_model, "model_fields", None)
    if not isinstance(fields, dict):
        return True
    for name, value in slots.items():
        field = fields.get(name)
        if field is None:
            return False
        if value is None and not _annotation_allows_none(getattr(field, "annotation", Any)):
            return False
    return True


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
        required = callable(getattr(field, "is_required", None)) and field.is_required()
        part = f"{name}{_annotation_prompt(getattr(field, 'annotation', Any))}"
        if required:
            part += "!"
        else:
            part += " optional"
            default_text = _field_default_prompt(field)
            if default_text:
                part += f" default={default_text}"
        parts.append(part)
    return "{" + ", ".join(parts) + "}"


def _annotation_prompt(annotation: Any) -> str:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Literal:
        values = "|".join(str(item) for item in args)
        return f" enum[{values}]"
    if origin in (Union, UnionType):
        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) == 1:
            return _annotation_prompt(non_none[0])
    if origin in (list, tuple):
        return " list"
    if annotation in (str, int, float, bool, dict):
        return f" {annotation.__name__}"
    return ""


def _annotation_allows_none(annotation: Any) -> bool:
    if annotation is Any:
        return True
    if annotation is type(None):
        return True
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        return any(arg is type(None) for arg in get_args(annotation))
    return False


def _field_default_prompt(field: Any) -> str:
    if getattr(field, "default_factory", None) is not None:
        return ""
    default = getattr(field, "default", None)
    if default is None or str(default) == "PydanticUndefined":
        return ""
    if isinstance(default, (str, int, float, bool)):
        return str(default)
    return ""

"""First-stage gate for deciding whether a user turn needs AssistIM capabilities."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


FORBIDDEN_INTENT_FIELDS = {"action", "actions", "args", "depends_on", "final", "skill", "slots", "steps"}


@dataclass(frozen=True, slots=True)
class AIActionIntentDecision:
    """Model output for the lightweight action/chat routing stage."""

    is_action: bool
    confidence: float = 1.0
    reason: str = ""


class AIActionIntentGate:
    """Classify whether the input should enter the AssistIM skill layer."""

    SCHEMA_VERSION = "assistim_intent_gate_v1"
    PROMPT_VERSION = "assistim_intent_gate_prompt_v1"

    async def classify(
        self,
        user_text: str,
        *,
        task_manager: Any,
        max_tokens: int = 128,
        strict: bool = True,
    ) -> AIActionIntentDecision | None:
        deterministic = classify_obvious_action_intent(user_text)
        if deterministic is not None:
            return deterministic
        if task_manager is None:
            return None
        request = self.build_request(user_text, max_tokens=max_tokens, strict=strict)
        snapshot = await task_manager.run_once(request)
        return parse_action_intent_decision_json(str(getattr(snapshot, "content", "") or ""))

    def build_request(self, user_text: str, *, max_tokens: int = 128, strict: bool = True) -> Any:
        from client.services.ai_service import AIPrivacyScope, AIRequest, AITaskType

        return AIRequest(
            task_id="ai-action-intent-gate",
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
                "source": "ai_action_intent_gate",
                "intent_schema_version": self.SCHEMA_VERSION,
                "intent_prompt_version": self.PROMPT_VERSION,
                "strict_json": bool(strict),
            },
        )

    @staticmethod
    def build_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "is_action": {"type": "boolean"},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["is_action", "confidence", "reason"],
            "additionalProperties": False,
        }

    @staticmethod
    def system_prompt() -> str:
        return (
            "你是 AssistIM 的用户意图判断器。只输出一个 JSON object。\n"
            "只判断当前用户输入是否需要读取或操作 AssistIM 的应用数据或接口。\n"
            "AssistIM 能力范围包括用户、好友、好友申请、群组、会话、消息、文件、朋友圈和本地记忆。\n"
            "在本产品上下文中，用户直接说用户、好友、好友申请、群、会话、消息、文件、朋友圈、聊天记录或本地记忆，默认指 AssistIM 内对象。\n"
            "不要因为用户没有写出 AssistIM 字样就判定为普通问答。\n"
            "带有搜索、查看、查询、发送、添加、删除、处理、总结、回忆、聊过什么等意图，且对象属于 AssistIM 能力范围时，is_action=true。\n"
            "用户要求搜索、查看、发送、处理 AssistIM 范围内对象，或要求 AssistIM 代执行相关操作时，is_action=true。\n"
            "即使后续能力可能不支持，只要用户要求 AssistIM 代执行或读取应用数据，也输出 is_action=true。\n"
            "用户只是闲聊、解释概念、写作、翻译、代码分析、外部知识问答，或询问如何完成某事但没有要求代操作 AssistIM 时，is_action=false。\n"
            "禁止输出 skill、slots、steps、actions、args 或执行计划。\n"
            "输出字段只能是 is_action、confidence、reason。"
        )

    @staticmethod
    def user_prompt(user_text: str) -> str:
        return f"用户输入：{str(user_text or '').strip()}"


def parse_action_intent_decision_json(raw_output: str) -> AIActionIntentDecision | None:
    payload = _parse_json_object(raw_output)
    if payload is None:
        return None
    if FORBIDDEN_INTENT_FIELDS.intersection(payload):
        return None
    if set(payload) - {"is_action", "confidence", "reason"}:
        return None
    if not isinstance(payload.get("is_action"), bool):
        return None
    try:
        confidence = float(payload.get("confidence"))
    except (TypeError, ValueError):
        return None
    confidence = max(0.0, min(1.0, confidence))
    return AIActionIntentDecision(
        is_action=bool(payload["is_action"]),
        confidence=confidence,
        reason=str(payload.get("reason") or "").strip(),
    )


def classify_obvious_action_intent(user_text: str) -> AIActionIntentDecision | None:
    text = _compact_text(user_text)
    if not text:
        return AIActionIntentDecision(is_action=False, confidence=1.0, reason="empty_input")
    app_object_terms = (
        "用户",
        "好友",
        "好友申请",
        "群",
        "群组",
        "会话",
        "消息",
        "文件",
        "朋友圈",
        "聊天记录",
        "本地记忆",
        "记忆",
    )
    app_action_terms = (
        "搜索",
        "查看",
        "查询",
        "检查",
        "发送",
        "发",
        "说",
        "添加",
        "加",
        "删除",
        "删",
        "接受",
        "同意",
        "拒绝",
        "总结",
        "回忆",
    )
    if any(term in text for term in app_object_terms) and any(term in text for term in app_action_terms):
        return AIActionIntentDecision(is_action=True, confidence=0.98, reason="assistim_object_action")
    if any(term in text for term in ("聊过什么", "聊了什么", "之前聊过", "聊天历史", "历史消息")):
        return AIActionIntentDecision(is_action=True, confidence=0.98, reason="assistim_memory_query")
    if re.search(r"^(?:给|向|和|跟|对).+(?:说|发|发送|告诉|转告).+", text):
        return AIActionIntentDecision(is_action=True, confidence=0.97, reason="assistim_send_request")
    if re.search(r"^(?:发|发送|告诉|转告)(?:给|向).+", text):
        return AIActionIntentDecision(is_action=True, confidence=0.97, reason="assistim_send_request")
    delegated = any(term in text for term in ("帮我", "替我", "帮忙"))
    delegated_action = any(term in text for term in ("删除", "删掉", "移除", "撤回", "召回", "上传", "建群", "创建群", "拉进群"))
    if delegated and delegated_action:
        return AIActionIntentDecision(is_action=True, confidence=0.9, reason="delegated_operation_request")
    if any(term in text for term in ("怎么", "如何", "是什么意思", "是什么")) and not delegated:
        return AIActionIntentDecision(is_action=False, confidence=0.95, reason="howto_or_explanation")
    return None


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
    return re.sub(r"\s+", "", str(value or "").casefold())

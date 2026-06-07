"""Deterministic compiler from AI skills to existing AI action plans."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from client.managers.ai_action_types import AIActionPlan, AIActionStep
from client.managers.ai_skill_registry import create_default_skill_registry
from client.managers.ai_skill_types import SkillCompileResult, SkillIntent


class AISkillCompiler:
    """Compile a stable semantic skill into the existing atomic action-plan format."""

    def __init__(self) -> None:
        self._registry = create_default_skill_registry(compiler=self)

    def compile(self, intent: SkillIntent) -> SkillCompileResult:
        skill_id = str(intent.skill or "").strip()
        if intent.type == "unsupported":
            return SkillCompileResult.unsupported(skill_id, intent.reason or "该请求不支持。")
        if intent.type == "clarification":
            missing = tuple(str(item or "").strip() for item in tuple(intent.control.get("missing_slots") or ()) if str(item or "").strip())
            return SkillCompileResult.clarification(skill_id, missing_slots=missing, question=str(intent.control.get("question") or ""))
        spec = self._registry.get(skill_id)
        if spec is None or not spec.enabled:
            return SkillCompileResult.unsupported(skill_id, f"未注册 Skill: {skill_id}")
        try:
            slots = spec.input_model.model_validate(dict(intent.slots or {}))
        except ValidationError as exc:
            missing_slots = _missing_required_slots(exc)
            return SkillCompileResult.clarification(
                skill_id,
                missing_slots=missing_slots,
                question=_clarification_question(skill_id, missing_slots),
                reason=_validation_reason(exc),
            )
        plan = spec.compiler(intent, slots)
        return SkillCompileResult.plan_result(skill_id, plan)

    def compile_search_user(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        keyword = str(getattr(slots, "keyword", "") or "").strip()
        return AIActionPlan(
            is_action=True,
            goal=_goal(intent, f"搜索用户 {keyword}"),
            risk="low",
            steps=(
                AIActionStep(
                    id="search_user",
                    action="user.search",
                    args={"keyword": keyword, "page": 1, "size": 10},
                    depends_on=(),
                ),
            ),
            final={"source": "$search_user"},
        )

    def compile_view_user_profile(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        target = str(getattr(slots, "target", "") or "").strip()
        return AIActionPlan(
            is_action=True,
            goal=_goal(intent, f"查看 {target} 的资料"),
            risk="low",
            steps=(
                AIActionStep(
                    id="resolve_target",
                    action="contact.resolve",
                    args={"queries": [target], "allow_multiple": False},
                    depends_on=(),
                ),
                AIActionStep(
                    id="get_profile",
                    action="user.get",
                    args={"user_id": "$resolve_target.contacts[0].id"},
                    depends_on=("resolve_target",),
                ),
            ),
            final={"source": "$get_profile"},
        )

    def compile_send_message(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        target = str(getattr(slots, "target", "") or "").strip()
        content = str(getattr(slots, "content", "") or "").strip()
        return AIActionPlan(
            is_action=True,
            goal=_goal(intent, f"给 {target} 发送消息"),
            risk="high",
            steps=(
                AIActionStep(
                    id="resolve_target",
                    action="contact.resolve",
                    args={"queries": [target], "allow_multiple": False},
                    depends_on=(),
                ),
                AIActionStep(
                    id="draft_message",
                    action="message.draft",
                    args={
                        "target": "$resolve_target.contacts[0]",
                        "content": content,
                        "source": "skill:SEND_MESSAGE",
                    },
                    depends_on=("resolve_target",),
                ),
                AIActionStep(
                    id="confirm_send",
                    action="user.confirm",
                    args={
                        "risk": "high",
                        "preview": {
                            "operation": "发送消息",
                            "target": "$draft_message.target",
                            "content": "$draft_message.content",
                        },
                    },
                    depends_on=("draft_message",),
                ),
                AIActionStep(
                    id="send_message",
                    action="message.send",
                    args={
                        "target": "$draft_message.target_entity",
                        "content": "$draft_message.content",
                        "preview": "$draft_message.preview",
                        "idempotency_key": "$draft_message.idempotency_key",
                    },
                    depends_on=("confirm_send",),
                ),
            ),
            final={"source": "$send_message"},
        )

    def compile_send_friend_request(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        keyword = str(getattr(slots, "keyword", "") or "").strip()
        message = str(getattr(slots, "message", "") or "").strip()
        return AIActionPlan(
            is_action=True,
            goal=_goal(intent, f"向 {keyword} 发送好友申请"),
            risk="high",
            steps=(
                AIActionStep(
                    id="search_user",
                    action="user.search",
                    args={"keyword": keyword, "page": 1, "size": 10},
                    depends_on=(),
                ),
                AIActionStep(
                    id="confirm_request",
                    action="user.confirm",
                    args={
                        "risk": "high",
                        "preview": {
                            "operation": "发送好友申请",
                            "target": "$search_user.items[0]",
                            "content": message or "发送好友申请",
                        },
                    },
                    depends_on=("search_user",),
                ),
                AIActionStep(
                    id="send_friend_request",
                    action="friend.request.send",
                    args={
                        "target_user_id": "$search_user.items[0].id",
                        "message": message or None,
                        "preview": "$confirm_request.preview",
                        "idempotency_key": "$confirm_request.preview_fingerprint",
                    },
                    depends_on=("confirm_request",),
                ),
            ),
            final={"source": "$send_friend_request"},
        )

    def compile_memory_qa(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        participants = [str(item or "").strip() for item in list(getattr(slots, "participants", []) or []) if str(item or "").strip()]
        question = str(getattr(slots, "question", "") or "").strip()
        time_scope = dict(getattr(slots, "time_scope", {}) or {"type": "all_history"})
        keywords = [str(item or "").strip() for item in list(getattr(slots, "keywords", []) or []) if str(item or "").strip()]
        limit = int(getattr(slots, "limit", 8) or 8)
        return AIActionPlan(
            is_action=True,
            goal=_goal(intent, question or "查询本地记忆"),
            risk="low",
            steps=(
                AIActionStep(
                    id="resolve_participants",
                    action="contact.resolve",
                    args={"queries": participants, "allow_multiple": True},
                    depends_on=(),
                ),
                AIActionStep(
                    id="search_memory",
                    action="memory.search",
                    args={
                        "participants": "$resolve_participants.contacts",
                        "participant_match": "any",
                        "time_scope": time_scope,
                        "keywords": keywords,
                        "question": question,
                        "limit": limit,
                        "return_raw_content": False,
                    },
                    depends_on=("resolve_participants",),
                ),
                AIActionStep(
                    id="summarize_memory",
                    action="memory.summarize",
                    args={"source": "$search_memory", "question": question, "style": "summary"},
                    depends_on=("search_memory",),
                ),
            ),
            final={"source": "$summarize_memory"},
        )


def _goal(intent: SkillIntent, fallback: str) -> str:
    return str(intent.goal or "").strip() or fallback


def _missing_required_slots(exc: ValidationError) -> tuple[str, ...]:
    missing: list[str] = []
    for error in exc.errors():
        if str(error.get("type") or "") != "missing":
            continue
        loc = tuple(error.get("loc") or ())
        if loc:
            missing.append(str(loc[0]))
    return tuple(dict.fromkeys(missing))


def _validation_reason(exc: ValidationError) -> str:
    messages: list[str] = []
    for error in exc.errors()[:3]:
        loc = ".".join(str(item) for item in tuple(error.get("loc") or ())) or "slots"
        messages.append(f"{loc}: {error.get('msg')}")
    return "; ".join(messages)


def _clarification_question(skill_id: str, missing_slots: tuple[str, ...]) -> str:
    if not missing_slots:
        return "请补充必要信息。"
    if skill_id == "SEND_MESSAGE" and missing_slots == ("target",):
        return "你想把消息发给谁？"
    if skill_id == "SEND_MESSAGE" and missing_slots == ("content",):
        return "你想发送什么内容？"
    return f"请补充：{', '.join(missing_slots)}。"

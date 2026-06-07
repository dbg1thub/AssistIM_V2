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

    @property
    def registry(self):
        return self._registry

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
        source = str(getattr(slots, "source", "") or "contact").strip()
        if source == "user_id":
            return self._single_step_plan(
                intent,
                fallback=f"查看 {target} 的资料",
                step_id="get_profile",
                action="user.get",
                args={"user_id": target},
            )
        if source == "search":
            return AIActionPlan(
                is_action=True,
                goal=_goal(intent, f"查看 {target} 的资料"),
                risk="low",
                steps=(
                    AIActionStep(
                        id="search_user",
                        action="user.search",
                        args={"keyword": target, "page": 1, "size": 10},
                        depends_on=(),
                    ),
                    AIActionStep(
                        id="get_profile",
                        action="user.get",
                        args={"user_id": "$search_user.items[0].id"},
                        depends_on=("search_user",),
                    ),
                ),
                final={"source": "$get_profile"},
            )
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

    def compile_list_friends(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        return self._single_step_plan(intent, fallback="查看好友列表", step_id="list_friends", action="friend.list", args={})

    def compile_check_friendship(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        target = str(getattr(slots, "target", "") or "").strip()
        source = str(getattr(slots, "source", "") or "search").strip()
        if source == "user_id":
            return self._single_step_plan(
                intent,
                fallback=f"检查和 {target} 是否是好友",
                step_id="check_friendship",
                action="friend.check",
                args={"user_id": target},
            )
        return AIActionPlan(
            is_action=True,
            goal=_goal(intent, f"检查和 {target} 是否是好友"),
            risk="low",
            steps=(
                AIActionStep(
                    id="search_user",
                    action="user.search",
                    args={"keyword": target, "page": 1, "size": 10},
                    depends_on=(),
                ),
                AIActionStep(
                    id="check_friendship",
                    action="friend.check",
                    args={"user_id": "$search_user.items[0].id"},
                    depends_on=("search_user",),
                ),
            ),
            final={"source": "$check_friendship"},
        )

    def compile_list_friend_requests(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        return self._single_step_plan(
            intent,
            fallback="查看好友申请列表",
            step_id="list_friend_requests",
            action="friend.request.list",
            args={},
        )

    def compile_list_groups(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        return self._single_step_plan(intent, fallback="查看群组列表", step_id="list_groups", action="group.list", args={})

    def compile_view_group(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        target = str(getattr(slots, "target", "") or "").strip()
        source = str(getattr(slots, "source", "") or "group_id").strip()
        if source == "group_id":
            return self._single_step_plan(
                intent,
                fallback=f"查看群组 {target}",
                step_id="get_group",
                action="group.get",
                args={"group_id": target},
            )
        return AIActionPlan(
            is_action=True,
            goal=_goal(intent, f"查看群组 {target}"),
            risk="low",
            steps=(
                AIActionStep(
                    id="resolve_group",
                    action="contact.resolve",
                    args={"queries": [target], "allow_multiple": False},
                    depends_on=(),
                ),
                AIActionStep(
                    id="get_group",
                    action="group.get",
                    args={"group_id": "$resolve_group.groups[0].id"},
                    depends_on=("resolve_group",),
                ),
            ),
            final={"source": "$get_group"},
        )

    def compile_list_sessions(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        return self._single_step_plan(intent, fallback="查看会话列表", step_id="list_sessions", action="session.list", args={})

    def compile_view_session(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        session_id = str(getattr(slots, "session_id", "") or "").strip()
        return self._single_step_plan(
            intent,
            fallback=f"查看会话 {session_id}",
            step_id="get_session",
            action="session.get",
            args={"session_id": session_id},
        )

    def compile_list_session_messages(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        session_id = str(getattr(slots, "session_id", "") or "").strip()
        limit = int(getattr(slots, "limit", 50) or 50)
        before_seq = getattr(slots, "before_seq", None)
        return self._single_step_plan(
            intent,
            fallback=f"查看会话 {session_id} 的最近消息",
            step_id="list_messages",
            action="message.list",
            args={"session_id": session_id, "limit": limit, "before_seq": before_seq},
        )

    def compile_list_uploaded_files(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        limit = int(getattr(slots, "limit", 50) or 50)
        return self._single_step_plan(
            intent,
            fallback="查看上传过的文件",
            step_id="list_files",
            action="file.list",
            args={"limit": limit},
        )

    def compile_list_moments(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        page = int(getattr(slots, "page", 1) or 1)
        size = int(getattr(slots, "size", 20) or 20)
        return self._single_step_plan(
            intent,
            fallback="查看朋友圈列表",
            step_id="list_moments",
            action="moment.list",
            args={"page": page, "size": size},
        )

    def compile_list_user_moments(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        target = str(getattr(slots, "target", "") or "").strip()
        source = str(getattr(slots, "source", "") or "user_id").strip()
        page = int(getattr(slots, "page", 1) or 1)
        size = int(getattr(slots, "size", 20) or 20)
        if source == "user_id":
            return self._single_step_plan(
                intent,
                fallback=f"查看 {target} 的朋友圈",
                step_id="list_moments",
                action="moment.list",
                args={"user_id": target, "page": page, "size": size},
            )
        if source == "search":
            return AIActionPlan(
                is_action=True,
                goal=_goal(intent, f"查看 {target} 的朋友圈"),
                risk="low",
                steps=(
                    AIActionStep(
                        id="search_user",
                        action="user.search",
                        args={"keyword": target, "page": 1, "size": 10},
                        depends_on=(),
                    ),
                    AIActionStep(
                        id="list_moments",
                        action="moment.list",
                        args={"user_id": "$search_user.items[0].id", "page": page, "size": size},
                        depends_on=("search_user",),
                    ),
                ),
                final={"source": "$list_moments"},
            )
        return AIActionPlan(
            is_action=True,
            goal=_goal(intent, f"查看 {target} 的朋友圈"),
            risk="low",
            steps=(
                AIActionStep(
                    id="resolve_target",
                    action="contact.resolve",
                    args={"queries": [target], "allow_multiple": False},
                    depends_on=(),
                ),
                AIActionStep(
                    id="list_moments",
                    action="moment.list",
                    args={"user_id": "$resolve_target.contacts[0].id", "page": page, "size": size},
                    depends_on=("resolve_target",),
                ),
            ),
            final={"source": "$list_moments"},
        )

    def compile_view_moment(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        moment_id = str(getattr(slots, "moment_id", "") or "").strip()
        return self._single_step_plan(
            intent,
            fallback=f"查看朋友圈 {moment_id}",
            step_id="get_moment",
            action="moment.get",
            args={"moment_id": moment_id},
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

    def compile_accept_friend_request(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        request_id = str(getattr(slots, "request_id", "") or "").strip()
        return self._friend_request_decision_plan(
            intent,
            request_id=request_id,
            operation="接受好友申请",
            action="friend.request.accept",
        )

    def compile_reject_friend_request(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        request_id = str(getattr(slots, "request_id", "") or "").strip()
        return self._friend_request_decision_plan(
            intent,
            request_id=request_id,
            operation="拒绝好友申请",
            action="friend.request.reject",
        )

    def compile_memory_qa(self, intent: SkillIntent, slots: BaseModel) -> AIActionPlan:
        participants = [str(item or "").strip() for item in list(getattr(slots, "participants", []) or []) if str(item or "").strip()]
        question = str(getattr(slots, "question", "") or "").strip()
        time_scope = dict(getattr(slots, "time_scope", {}) or {"type": "all_history"})
        keywords = [str(item or "").strip() for item in list(getattr(slots, "keywords", []) or []) if str(item or "").strip()]
        limit = int(getattr(slots, "limit", 8) or 8)
        memory_args = {
            "participants": "$resolve_participants.contacts" if participants else [],
            "participant_match": "any",
            "time_scope": time_scope,
            "keywords": keywords,
            "question": question,
            "limit": limit,
            "return_raw_content": False,
        }
        if not participants:
            return AIActionPlan(
                is_action=True,
                goal=_goal(intent, question or "查询本地记忆"),
                risk="low",
                steps=(
                    AIActionStep(
                        id="search_memory",
                        action="memory.search",
                        args=memory_args,
                        depends_on=(),
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
                    args=memory_args,
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

    def _single_step_plan(
        self,
        intent: SkillIntent,
        *,
        fallback: str,
        step_id: str,
        action: str,
        args: dict[str, Any],
    ) -> AIActionPlan:
        return AIActionPlan(
            is_action=True,
            goal=_goal(intent, fallback),
            risk="low",
            steps=(
                AIActionStep(
                    id=step_id,
                    action=action,
                    args=dict(args),
                    depends_on=(),
                ),
            ),
            final={"source": f"${step_id}"},
        )

    def _friend_request_decision_plan(
        self,
        intent: SkillIntent,
        *,
        request_id: str,
        operation: str,
        action: str,
    ) -> AIActionPlan:
        return AIActionPlan(
            is_action=True,
            goal=_goal(intent, f"{operation} {request_id}"),
            risk="high",
            steps=(
                AIActionStep(
                    id="confirm_request",
                    action="user.confirm",
                    args={
                        "risk": "high",
                        "preview": {
                            "operation": operation,
                            "target": request_id,
                            "content": operation,
                        },
                    },
                    depends_on=(),
                ),
                AIActionStep(
                    id="handle_request",
                    action=action,
                    args={
                        "request_id": request_id,
                        "preview": "$confirm_request.preview",
                        "idempotency_key": "$confirm_request.preview_fingerprint",
                    },
                    depends_on=("confirm_request",),
                ),
            ),
            final={"source": "$handle_request"},
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

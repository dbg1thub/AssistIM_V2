"""Registry for model-facing AI skills."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from client.managers.ai_skill_types import SkillSpec


class _SkillInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchUserSkillInput(_SkillInputModel):
    keyword: str = Field(min_length=1)


class ViewUserProfileSkillInput(_SkillInputModel):
    target: str = Field(min_length=1)
    source: str = "contact"


class SendMessageSkillInput(_SkillInputModel):
    target: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=500)


class SendFriendRequestSkillInput(_SkillInputModel):
    keyword: str = Field(min_length=1)
    message: str | None = Field(default=None, max_length=500)


class MemoryQASkillInput(_SkillInputModel):
    participants: list[str] = Field(min_length=1, max_length=5)
    question: str = Field(min_length=1)
    time_scope: dict[str, Any] = Field(default_factory=lambda: {"type": "all_history"})
    keywords: list[str] = Field(default_factory=list)
    limit: int = Field(default=8, ge=1, le=50)


class AISkillRegistry:
    """Small registry for stable semantic skills."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillSpec] = {}

    def register(self, spec: SkillSpec) -> None:
        skill_id = str(spec.id or "").strip()
        if not skill_id:
            raise ValueError("skill id is required")
        self._skills[skill_id] = spec

    def get(self, skill_id: str) -> SkillSpec | None:
        return self._skills.get(str(skill_id or "").strip())

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._skills))


def create_default_skill_registry(*, compiler: Any) -> AISkillRegistry:
    registry = AISkillRegistry()
    registry.register(
        SkillSpec(
            id="SEARCH_USER",
            description="在 AssistIM 中搜索用户账号。",
            input_model=SearchUserSkillInput,
            risk_level="low",
            requires_confirmation=False,
            compiler=compiler.compile_search_user,
        )
    )
    registry.register(
        SkillSpec(
            id="VIEW_USER_PROFILE",
            description="查看一个用户的公开资料。",
            input_model=ViewUserProfileSkillInput,
            risk_level="low",
            requires_confirmation=False,
            compiler=compiler.compile_view_user_profile,
        )
    )
    registry.register(
        SkillSpec(
            id="SEND_MESSAGE",
            description="向联系人发送一条文本消息。",
            input_model=SendMessageSkillInput,
            risk_level="high",
            requires_confirmation=True,
            compiler=compiler.compile_send_message,
        )
    )
    registry.register(
        SkillSpec(
            id="SEND_FRIEND_REQUEST",
            description="向 AssistIM 用户发送好友申请。",
            input_model=SendFriendRequestSkillInput,
            risk_level="high",
            requires_confirmation=True,
            compiler=compiler.compile_send_friend_request,
        )
    )
    registry.register(
        SkillSpec(
            id="MEMORY_QA",
            description="检索并总结本地聊天记忆。",
            input_model=MemoryQASkillInput,
            risk_level="low",
            requires_confirmation=False,
            compiler=compiler.compile_memory_qa,
        )
    )
    return registry

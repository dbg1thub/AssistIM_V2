"""Registry for model-facing AI skills."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from client.managers.ai_skill_types import SkillSpec


class _SkillInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchUserSkillInput(_SkillInputModel):
    keyword: str = Field(min_length=1)


class ViewUserProfileSkillInput(_SkillInputModel):
    target: str = Field(min_length=1)
    source: Literal["contact", "search", "user_id"] = "contact"


class EmptySkillInput(_SkillInputModel):
    pass


class MomentListSkillInput(_SkillInputModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=50)


class FileListSkillInput(_SkillInputModel):
    limit: int = Field(default=50, ge=1, le=200)


class CheckFriendshipSkillInput(_SkillInputModel):
    target: str = Field(min_length=1)
    source: Literal["search", "user_id"] = "search"


class ViewGroupSkillInput(_SkillInputModel):
    target: str = Field(min_length=1)
    source: Literal["contact", "group_id"] = "group_id"


class ViewSessionSkillInput(_SkillInputModel):
    session_id: str = Field(min_length=1)


class ListSessionMessagesSkillInput(_SkillInputModel):
    session_id: str = Field(min_length=1)
    limit: int = Field(default=50, ge=1, le=200)
    before_seq: int | None = Field(default=None, ge=1)


class ListUserMomentsSkillInput(_SkillInputModel):
    target: str = Field(min_length=1)
    source: Literal["contact", "search", "user_id"] = "user_id"
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=50)


class ViewMomentSkillInput(_SkillInputModel):
    moment_id: str = Field(min_length=1)


class SendMessageSkillInput(_SkillInputModel):
    target: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=500)


class SendFriendRequestSkillInput(_SkillInputModel):
    keyword: str = Field(min_length=1)
    message: str | None = Field(default=None, max_length=500)


class FriendRequestDecisionSkillInput(_SkillInputModel):
    request_id: str = Field(min_length=1)


class MemoryQASkillInput(_SkillInputModel):
    participants: list[str] = Field(default_factory=list, max_length=5)
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
            id="LIST_FRIENDS",
            description="查看当前账号好友列表。",
            input_model=EmptySkillInput,
            risk_level="low",
            requires_confirmation=False,
            compiler=compiler.compile_list_friends,
        )
    )
    registry.register(
        SkillSpec(
            id="CHECK_FRIENDSHIP",
            description="检查当前账号和一个用户是否是好友。",
            input_model=CheckFriendshipSkillInput,
            risk_level="low",
            requires_confirmation=False,
            compiler=compiler.compile_check_friendship,
        )
    )
    registry.register(
        SkillSpec(
            id="LIST_FRIEND_REQUESTS",
            description="查看当前账号好友申请列表。",
            input_model=EmptySkillInput,
            risk_level="low",
            requires_confirmation=False,
            compiler=compiler.compile_list_friend_requests,
        )
    )
    registry.register(
        SkillSpec(
            id="LIST_GROUPS",
            description="查看当前账号加入的群组列表。",
            input_model=EmptySkillInput,
            risk_level="low",
            requires_confirmation=False,
            compiler=compiler.compile_list_groups,
        )
    )
    registry.register(
        SkillSpec(
            id="VIEW_GROUP",
            description="查看一个群组详情。",
            input_model=ViewGroupSkillInput,
            risk_level="low",
            requires_confirmation=False,
            compiler=compiler.compile_view_group,
        )
    )
    registry.register(
        SkillSpec(
            id="LIST_SESSIONS",
            description="查看当前账号会话列表。",
            input_model=EmptySkillInput,
            risk_level="low",
            requires_confirmation=False,
            compiler=compiler.compile_list_sessions,
        )
    )
    registry.register(
        SkillSpec(
            id="VIEW_SESSION",
            description="查看一个会话详情。",
            input_model=ViewSessionSkillInput,
            risk_level="low",
            requires_confirmation=False,
            compiler=compiler.compile_view_session,
        )
    )
    registry.register(
        SkillSpec(
            id="LIST_SESSION_MESSAGES",
            description="查看一个会话的最近消息。",
            input_model=ListSessionMessagesSkillInput,
            risk_level="low",
            requires_confirmation=False,
            compiler=compiler.compile_list_session_messages,
        )
    )
    registry.register(
        SkillSpec(
            id="LIST_UPLOADED_FILES",
            description="查看当前账号上传过的文件列表。",
            input_model=FileListSkillInput,
            risk_level="low",
            requires_confirmation=False,
            compiler=compiler.compile_list_uploaded_files,
        )
    )
    registry.register(
        SkillSpec(
            id="LIST_MOMENTS",
            description="查看当前账号可见的朋友圈列表。",
            input_model=MomentListSkillInput,
            risk_level="low",
            requires_confirmation=False,
            compiler=compiler.compile_list_moments,
        )
    )
    registry.register(
        SkillSpec(
            id="LIST_USER_MOMENTS",
            description="查看指定用户的朋友圈列表。",
            input_model=ListUserMomentsSkillInput,
            risk_level="low",
            requires_confirmation=False,
            compiler=compiler.compile_list_user_moments,
        )
    )
    registry.register(
        SkillSpec(
            id="VIEW_MOMENT",
            description="查看一条朋友圈详情。",
            input_model=ViewMomentSkillInput,
            risk_level="low",
            requires_confirmation=False,
            compiler=compiler.compile_view_moment,
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
            id="ACCEPT_FRIEND_REQUEST",
            description="接受一条好友申请。",
            input_model=FriendRequestDecisionSkillInput,
            risk_level="high",
            requires_confirmation=True,
            compiler=compiler.compile_accept_friend_request,
        )
    )
    registry.register(
        SkillSpec(
            id="REJECT_FRIEND_REQUEST",
            description="拒绝一条好友申请。",
            input_model=FriendRequestDecisionSkillInput,
            risk_level="high",
            requires_confirmation=True,
            compiler=compiler.compile_reject_friend_request,
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

"""Atomic action registry and first action implementations."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from client.core import logging
from client.managers.ai_action_cache import AIActionCache
from client.managers.ai_action_io_models import (
    ContactResolveInput,
    ContactResolveOutput,
    EmptyReadInput,
    FileListInput,
    FriendRequestDecisionInput,
    FriendRequestSendInput,
    GroupGetInput,
    MemorySearchInput,
    MemorySearchOutput,
    MemorySummarizeInput,
    MemorySummarizeOutput,
    MessageDraftInput,
    MessageListInput,
    MessageDraftOutput,
    MessageSendInput,
    MessageSendOutput,
    MomentGetInput,
    MomentListInput,
    PagedReadInput,
    ServerReadOutput,
    ServerWriteOutput,
    SessionGetInput,
    UserConfirmInput,
    UserGetInput,
    UserSearchInput,
)
from client.managers.ai_action_types import (
    ActionHandlerError,
    ActionPause,
    AtomicActionSpec,
    confirmation_preview_fingerprint,
)
logger = logging.get_logger(__name__)


CONTACT_RESOLVE_CACHE_NAMESPACE = "contact.resolve"
CONTACT_RESOLVE_RESOLVER_VERSION = "contact_resolve:v1"
MEMORY_SUMMARIZE_DIRECT_MAX_LINES = 6
MEMORY_SUMMARIZE_DIRECT_MAX_CONTEXT_CHARS = 1200
MEMORY_SUMMARIZE_CHUNK_SIZE = 4
MEMORY_SUMMARIZE_CHUNK_DEFAULT_ITEM_MAX_CHARS = 34
MEMORY_SUMMARIZE_CHUNK_FILE_ITEM_MAX_CHARS = 260
MEMORY_SUMMARIZE_CACHE_NAMESPACE = "memory.summarize"
MEMORY_SUMMARIZE_PROMPT_VERSION = "memory_summarize_context:v3"
MEMORY_SUMMARIZE_MODEL_ID = "ai_action_memory_summarizer:v1"


@dataclass(frozen=True, slots=True)
class _ServerReadRoute:
    path: str
    path_args: tuple[str, ...] = ()
    param_args: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _ServerWriteRoute:
    method: str
    path: str
    path_args: tuple[str, ...] = ()
    body_args: tuple[str, ...] = ()


SERVER_READ_ACTION_ROUTES: dict[str, _ServerReadRoute] = {
    "user.search": _ServerReadRoute("/users/search", param_args=("keyword", "page", "size")),
    "user.get": _ServerReadRoute("/users/{user_id}", path_args=("user_id",)),
    "friend.list": _ServerReadRoute("/friends"),
    "friend.check": _ServerReadRoute("/friends/check/{user_id}", path_args=("user_id",)),
    "friend.request.list": _ServerReadRoute("/friends/requests"),
    "group.list": _ServerReadRoute("/groups"),
    "group.get": _ServerReadRoute("/groups/{group_id}", path_args=("group_id",)),
    "session.list": _ServerReadRoute("/sessions"),
    "session.get": _ServerReadRoute("/sessions/{session_id}", path_args=("session_id",)),
    "message.list": _ServerReadRoute("/sessions/{session_id}/messages", path_args=("session_id",), param_args=("limit", "before_seq")),
    "file.list": _ServerReadRoute("/files", param_args=("limit",)),
    "moment.list": _ServerReadRoute("/moments", param_args=("user_id", "page", "size")),
    "moment.get": _ServerReadRoute("/moments/{moment_id}", path_args=("moment_id",)),
}

SERVER_WRITE_ACTION_ROUTES: dict[str, _ServerWriteRoute] = {
    "friend.request.send": _ServerWriteRoute("POST", "/friends/requests", body_args=("target_user_id", "message")),
    "friend.request.accept": _ServerWriteRoute("POST", "/friends/requests/{request_id}/accept", path_args=("request_id",)),
    "friend.request.reject": _ServerWriteRoute("POST", "/friends/requests/{request_id}/reject", path_args=("request_id",)),
}

SERVER_READ_ACTION_LABELS: dict[str, str] = {
    "user.search": "用户搜索",
    "user.get": "用户资料查询",
    "friend.list": "好友列表查询",
    "friend.check": "好友关系查询",
    "friend.request.list": "好友申请查询",
    "group.list": "群组列表查询",
    "group.get": "群组详情查询",
    "session.list": "会话列表查询",
    "session.get": "会话详情查询",
    "message.list": "会话消息列表查询",
    "file.list": "文件列表查询",
    "moment.list": "朋友圈列表查询",
    "moment.get": "朋友圈详情查询",
}

SERVER_WRITE_ACTION_LABELS: dict[str, str] = {
    "friend.request.send": "发送好友申请",
    "friend.request.accept": "接受好友申请",
    "friend.request.reject": "拒绝好友申请",
}


class AIActionServerReadClient:
    """Read-only bridge from AI actions to existing /api/v1 REST endpoints."""

    def __init__(self, http_client: Any | None = None) -> None:
        self._http_client = http_client

    async def execute(self, action_name: str, args: dict[str, Any]) -> Any:
        route = SERVER_READ_ACTION_ROUTES.get(str(action_name or "").strip())
        if route is None:
            raise ActionHandlerError(f"ACTION_NOT_FOUND: {action_name}")
        path_args = {
            name: _url_path_arg(args.get(name))
            for name in route.path_args
        }
        path = route.path.format(**path_args) if path_args else route.path
        params = {
            name: args.get(name)
            for name in route.param_args
            if args.get(name) not in (None, "")
        }
        return await self._http().get(path, params=params or None)

    def _http(self) -> Any:
        if self._http_client is None:
            from client.network.http_client import get_http_client

            self._http_client = get_http_client()
        return self._http_client


class AIActionServerWriteClient:
    """Write bridge from confirmed AI actions to existing /api/v1 REST endpoints."""

    def __init__(self, http_client: Any | None = None) -> None:
        self._http_client = http_client

    async def execute(self, action_name: str, args: dict[str, Any]) -> Any:
        route = SERVER_WRITE_ACTION_ROUTES.get(str(action_name or "").strip())
        if route is None:
            raise ActionHandlerError(f"ACTION_NOT_FOUND: {action_name}")
        path_args = {
            name: _url_path_arg(args.get(name))
            for name in route.path_args
        }
        path = route.path.format(**path_args) if path_args else route.path
        body = {
            name: args.get(name)
            for name in route.body_args
            if args.get(name) not in (None, "")
        }
        idempotency_key = str(args.get("idempotency_key") or "").strip()
        headers = {"X-Idempotency-Key": idempotency_key} if idempotency_key else None
        if route.method.upper() == "POST":
            if route.body_args:
                return await self._http().post(path, json=body, headers=headers)
            return await self._http().post(path, headers=headers)
        raise ActionHandlerError(f"ACTION_NOT_FOUND: {action_name}")

    def _http(self) -> Any:
        if self._http_client is None:
            from client.network.http_client import get_http_client

            self._http_client = get_http_client()
        return self._http_client


class AIActionMessageSender:
    """Send AI-confirmed text through the existing chat message pipeline."""

    def __init__(self, *, session_manager: Any | None = None, message_manager: Any | None = None) -> None:
        self._session_manager = session_manager
        self._message_manager = message_manager

    async def send_text_to_contact(
        self,
        *,
        target: dict,
        content: str,
        idempotency_key: str,
        plan_id: str,
    ) -> dict[str, Any]:
        normalized_target = dict(target or {})
        contact_id = str(normalized_target.get("contact_id") or normalized_target.get("id") or "").strip()
        label = _contact_label(normalized_target) or "目标联系人"
        normalized_content = str(content or "").strip()
        normalized_key = str(idempotency_key or "").strip()
        if not contact_id:
            return _message_send_failed(
                "TARGET_NOT_RESOLVED",
                f"没有找到可发送的联系人，请重新指定收件人。",
                target=normalized_target,
                content=normalized_content,
            )
        session = self._find_direct_session(contact_id)
        if session is None:
            return _message_send_failed(
                "SESSION_NOT_FOUND",
                f"没有找到可发送的会话，请先打开或创建与{label}的私聊。",
                target=normalized_target,
                content=normalized_content,
            )
        session_id = str(getattr(session, "session_id", "") or "").strip()
        if not session_id:
            return _message_send_failed(
                "SESSION_NOT_FOUND",
                f"没有找到可发送的会话，请先打开或创建与{label}的私聊。",
                target=normalized_target,
                content=normalized_content,
            )

        try:
            from client.models.message import MessageStatus, MessageType
        except Exception as exc:
            logger.exception("AI action message send contracts unavailable")
            return _message_send_failed(
                "SEND_CONTRACT_UNAVAILABLE",
                "发送链路暂时不可用，请稍后再试。",
                target=normalized_target,
                content=normalized_content,
                error=str(exc),
            )

        try:
            message = await self._message_manager_instance().send_message(
                session_id=session_id,
                content=normalized_content,
                message_type=MessageType.TEXT,
                msg_id=_stable_message_id(plan_id=plan_id, idempotency_key=normalized_key),
                extra={
                    "ai_action_send": {
                        "plan_id": str(plan_id or ""),
                        "idempotency_key": normalized_key,
                        "target_contact_id": contact_id,
                    }
                },
            )
        except Exception as exc:
            logger.exception("AI action message send failed")
            return _message_send_failed(
                "SEND_FAILED",
                "发送失败，请稍后再试。",
                target=normalized_target,
                content=normalized_content,
                error=str(exc),
            )

        status_value = _status_value(getattr(message, "status", ""))
        message_id = str(getattr(message, "message_id", "") or "")
        if status_value == MessageStatus.FAILED.value:
            return _message_send_failed(
                "SEND_FAILED",
                "发送失败，请稍后再试。",
                target=normalized_target,
                content=normalized_content,
                session_id=session_id,
                message_id=message_id,
            )
        if status_value == MessageStatus.AWAITING_SECURITY_CONFIRMATION.value:
            return {
                "status": "pending_security_review",
                "text": f"发送前需要完成身份验证，消息已暂存给{label}。",
                "target": normalized_target,
                "content_chars": len(normalized_content),
                "session_id": session_id,
                "message_id": message_id,
            }
        return {
            "status": "sent",
            "text": f"已发送给{label}。",
            "target": normalized_target,
            "content_chars": len(normalized_content),
            "session_id": session_id,
            "message_id": message_id,
        }

    def _session_manager_instance(self):
        if self._session_manager is None:
            from client.managers.session_manager import get_session_manager

            self._session_manager = get_session_manager()
        return self._session_manager

    def _message_manager_instance(self):
        if self._message_manager is None:
            from client.managers.message_manager import get_message_manager

            self._message_manager = get_message_manager()
        return self._message_manager

    def _find_direct_session(self, contact_id: str):
        manager = self._session_manager_instance()
        current = getattr(manager, "current_session", None)
        if _session_matches_direct_contact(current, contact_id):
            return current
        for session in list(getattr(manager, "sessions", []) or []):
            if _session_matches_direct_contact(session, contact_id):
                return session
        return None


class AtomicActionRegistry:
    """Registry for executable atomic actions."""

    def __init__(
        self,
        *,
        contact_resolver: Any,
        memory_manager: Any | None = None,
        memory_summarizer: Any | None = None,
        message_sender: Any | None = None,
        server_reader: Any | None = None,
        server_writer: Any | None = None,
        action_cache: AIActionCache | None = None,
    ) -> None:
        self._contact_resolver = contact_resolver
        self._memory_manager = memory_manager
        self._memory_summarizer = memory_summarizer
        self._message_sender = message_sender
        self._server_reader = server_reader
        self._server_writer = server_writer
        self._action_cache = action_cache or AIActionCache()
        self._actions: dict[str, AtomicActionSpec] = {}
        self._register_defaults()

    def get(self, name: str) -> AtomicActionSpec | None:
        return self._actions.get(str(name or "").strip())

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._actions))

    def _register(self, spec: AtomicActionSpec) -> None:
        _validate_action_spec(spec)
        self._actions[spec.name] = spec

    def _register_server_read(
        self,
        name: str,
        *,
        input_model: type[Any],
        prompt_purpose: str,
        prompt_notes: tuple[str, ...] = (),
        max_result_items: int | None = None,
    ) -> None:
        self._register(
            AtomicActionSpec(
                name=name,
                kind="read",
                risk_level="low",
                handler=self._server_read_handler(name),
                input_model=input_model,
                output_model=ServerReadOutput,
                max_output_json_bytes=65536,
                timeout_ms=15000,
                max_retries=1,
                max_targets=max_result_items,
                result_budget_kind="server_read",
                default_result_limit=max_result_items or 0,
                max_result_items=max_result_items,
                prompt_purpose=prompt_purpose,
                prompt_notes=(
                    "这是只读服务端动作，不需要 user.confirm。",
                    "只能用于读取当前账号通过现有接口可见的数据，不产生外部副作用。",
                    *prompt_notes,
                ),
            )
        )

    def _register_server_write(
        self,
        name: str,
        *,
        input_model: type[Any],
        prompt_purpose: str,
        prompt_notes: tuple[str, ...] = (),
        planner_required_predecessors: tuple[str, ...] = ("user.confirm",),
        planner_required_arg_refs: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._register(
            AtomicActionSpec(
                name=name,
                kind="write",
                risk_level="high",
                handler=self._server_write_handler(name),
                input_model=input_model,
                output_model=ServerWriteOutput,
                enabled=True,
                requires_confirmation=True,
                max_targets=1,
                allow_batch=False,
                require_preview=True,
                allow_side_effect=True,
                idempotency_required=True,
                allow_auto_resume_after_confirm=False,
                max_output_json_bytes=65536,
                timeout_ms=15000,
                max_retries=0,
                target_arg_names=("target_user_id", "request_id"),
                prompt_purpose=prompt_purpose,
                prompt_notes=prompt_notes,
                planner_required_predecessors=planner_required_predecessors,
                planner_required_arg_refs={
                    "preview": ("user.confirm.preview",),
                    "idempotency_key": ("user.confirm.preview_fingerprint",),
                    **dict(planner_required_arg_refs or {}),
                },
                planner_forbidden_literal_args=("preview", "idempotency_key"),
            )
        )

    def _server_read_handler(self, action_name: str):
        async def handler(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
            return await self._server_read(action_name, args, context)

        return handler

    def _server_write_handler(self, action_name: str):
        async def handler(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
            return await self._server_write(action_name, args, context)

        return handler

    def _register_defaults(self) -> None:
        self._register(
            AtomicActionSpec(
                name="contact.resolve",
                kind="read",
                risk_level="low",
                handler=self._contact_resolve,
                input_model=ContactResolveInput,
                output_model=ContactResolveOutput,
                max_targets=5,
                allow_batch=True,
                target_arg_names=("queries",),
                prompt_purpose="解析用户表达的联系人、群名、用户名或备注名为本地稳定实体。",
                prompt_notes=(
                    "queries 必须来自用户明确表达的对象名称。",
                    "allow_multiple=false 表示该动作需要单一目标，命中多个候选时由系统澄清。",
                    "中文表达“我和 X”“我跟 X”“与 X”中的 X 是联系人或会话对象，应放入 queries。",
                ),
            )
        )
        self._register_server_read(
            "user.search",
            input_model=UserSearchInput,
            prompt_purpose="通过服务端用户搜索接口查找用户。",
            prompt_notes=("keyword 必须来自用户明确提供的搜索词。",),
            max_result_items=100,
        )
        self._register_server_read(
            "user.get",
            input_model=UserGetInput,
            prompt_purpose="查看一个用户的公开资料。",
            prompt_notes=("user_id 必须来自上游结果或用户明确提供的稳定 ID。",),
            max_result_items=1,
        )
        self._register_server_read(
            "friend.list",
            input_model=EmptyReadInput,
            prompt_purpose="查看当前账号好友列表。",
            max_result_items=100,
        )
        self._register_server_read(
            "friend.check",
            input_model=UserGetInput,
            prompt_purpose="检查当前账号和一个用户是否已经是好友。",
            prompt_notes=("user_id 必须来自 user.search/user.get 的结果，或用户明确提供的稳定用户 ID。",),
            max_result_items=1,
        )
        self._register_server_read(
            "friend.request.list",
            input_model=EmptyReadInput,
            prompt_purpose="查看当前账号的好友申请列表。",
            max_result_items=100,
        )
        self._register_server_write(
            "friend.request.send",
            input_model=FriendRequestSendInput,
            prompt_purpose="通过现有好友申请接口向目标用户发送好友申请。",
            prompt_notes=(
                "target_user_id 应来自 user.search 的用户结果；不要把用户名或昵称直接作为 target_user_id。",
                "message 是好友申请附言，可为空。",
            ),
            planner_required_predecessors=("user.search", "user.confirm"),
            planner_required_arg_refs={"target_user_id": ("user.search.items[0].id",)},
        )
        self._register_server_write(
            "friend.request.accept",
            input_model=FriendRequestDecisionInput,
            prompt_purpose="接受一条已存在的好友申请。",
            prompt_notes=("request_id 必须来自用户明确提供的申请 ID，或来自 friend.request.list 的结果。",),
        )
        self._register_server_write(
            "friend.request.reject",
            input_model=FriendRequestDecisionInput,
            prompt_purpose="拒绝一条已存在的好友申请。",
            prompt_notes=("request_id 必须来自用户明确提供的申请 ID，或来自 friend.request.list 的结果。",),
        )
        self._register_server_read(
            "group.list",
            input_model=EmptyReadInput,
            prompt_purpose="查看当前账号加入的群组列表。",
            max_result_items=100,
        )
        self._register_server_read(
            "group.get",
            input_model=GroupGetInput,
            prompt_purpose="查看一个群组详情。",
            prompt_notes=("group_id 必须来自上游结果或用户明确提供的稳定 ID。",),
            max_result_items=1,
        )
        self._register_server_read(
            "session.list",
            input_model=EmptyReadInput,
            prompt_purpose="查看当前账号会话列表。",
            max_result_items=100,
        )
        self._register_server_read(
            "session.get",
            input_model=SessionGetInput,
            prompt_purpose="查看一个会话详情。",
            prompt_notes=("session_id 必须来自上游结果或用户明确提供的稳定 ID。",),
            max_result_items=1,
        )
        self._register_server_read(
            "message.list",
            input_model=MessageListInput,
            prompt_purpose="查看一个会话的最近消息列表。",
            prompt_notes=(
                "session_id 必须来自 session.list/session.get 的结果，或用户明确提供的稳定会话 ID。",
                "limit 控制返回消息数量；before_seq 为空表示从最新消息向前读取。",
            ),
            max_result_items=200,
        )
        self._register_server_read(
            "file.list",
            input_model=FileListInput,
            prompt_purpose="查看当前账号上传过的文件列表。",
            max_result_items=200,
        )
        self._register_server_read(
            "moment.list",
            input_model=MomentListInput,
            prompt_purpose="查看朋友圈列表。",
            prompt_notes=("user_id 为空表示查看当前可见时间线。",),
            max_result_items=50,
        )
        self._register_server_read(
            "moment.get",
            input_model=MomentGetInput,
            prompt_purpose="查看一条朋友圈详情。",
            prompt_notes=("moment_id 必须来自上游结果或用户明确提供的稳定 ID。",),
            max_result_items=1,
        )
        self._register(
            AtomicActionSpec(
                name="memory.search",
                kind="read",
                risk_level="low",
                handler=self._memory_search,
                input_model=MemorySearchInput,
                output_model=MemorySearchOutput,
                allow_all_history=True,
                allow_cross_session=True,
                max_output_json_bytes=32768,
                result_budget_kind="memory",
                result_limit_arg_names=("limit", "max_items"),
                default_result_limit=8,
                max_result_items=50,
                prompt_purpose="检索本地聊天记忆、摘要和可用消息索引。",
                prompt_notes=(
                    "用于用户询问历史、回顾、总结或查找已存在内容。",
                    "time_scope.type 可表达 all_history 等结构化范围；question 保留用户问题。",
                    "用户输入中出现联系人、群名或对话对象时，先使用 contact.resolve；participants 引用 contact.resolve 的 contacts 或 groups 输出，不直接把自然语言名称写入 participants，也不要只把名称留在 question 或 keywords。",
                    "未限定具体时间窗口的历史回顾问题，time_scope.type 使用 all_history。",
                ),
            )
        )
        self._register(
            AtomicActionSpec(
                name="memory.summarize",
                kind="read",
                risk_level="low",
                handler=self._memory_summarize,
                input_model=MemorySummarizeInput,
                output_model=MemorySummarizeOutput,
                allow_all_history=True,
                allow_cross_session=True,
                max_input_bytes=32768,
                max_output_json_bytes=32768,
                model_call_cost=1,
                estimated_input_tokens=2048,
                estimated_output_tokens=512,
                prompt_purpose="把 memory.search 的结构化结果压缩为面向用户问题的回答摘要。",
                planner_required_predecessors=("memory.search",),
                prompt_notes=(
                    "source 应引用上游检索结果，不直接引用用户自然语言。",
                    "当用户目标是回答、总结或解释检索到的历史内容时，memory.search 之后应接 memory.summarize；只有用户明确只要原始列表或原始记录时才把检索结果作为 final。",
                    "历史回顾问题默认需要自然语言回答，不是返回原始列表；除非用户明确要求列表或原始记录，否则必须在 search 后使用 memory.summarize。",
                ),
            )
        )
        self._register(
            AtomicActionSpec(
                name="message.draft",
                kind="read",
                risk_level="low",
                handler=self._message_draft,
                input_model=MessageDraftInput,
                output_model=MessageDraftOutput,
                max_content_chars=2000,
                prompt_purpose="根据已解析目标和明确文本内容生成发送预览、目标实体和幂等键。",
                prompt_notes=(
                    "只准备草稿和 preview，不产生外部副作用。",
                    "单目标写操作的联系人解析应设置 allow_multiple=false，必须显式输出 allow_multiple=false。",
                ),
                planner_required_predecessors=("contact.resolve",),
                planner_required_arg_refs={"target": ("contact.resolve.contacts[0]",)},
                planner_forbidden_literal_args=("target",),
            )
        )
        self._register(
            AtomicActionSpec(
                name="user.confirm",
                kind="read",
                risk_level="medium",
                handler=self._user_confirm,
                input_model=UserConfirmInput,
                prompt_purpose="在执行外部副作用前暂停并请求用户确认 preview。",
                prompt_notes=(
                    "确认动作必须服务于明确写操作，不能用于普通读取任务。",
                    "preview 不能是字符串引用，operation、target、content 必须放在 preview 对象内部。",
                ),
                planner_required_object_args={"preview": ("operation", "target", "content")},
            )
        )
        self._register(
            AtomicActionSpec(
                name="message.send",
                kind="write",
                risk_level="high",
                handler=self._message_send,
                input_model=MessageSendInput,
                output_model=MessageSendOutput,
                enabled=True,
                requires_confirmation=True,
                max_targets=1,
                allow_batch=False,
                require_resolved_target=True,
                require_preview=True,
                max_content_chars=500,
                allow_auto_resume_after_confirm=False,
                allow_side_effect=True,
                idempotency_required=True,
                prompt_purpose="通过现有会话发送已确认的文本消息。",
                prompt_notes=(
                    "必须依赖 user.confirm 的确认结果。",
                    "target、content、preview 和 idempotency_key 应来自上游草稿或确认上下文。",
                    "不要引用 user.confirm 输出作为 message.send 的 target/content/idempotency_key 参数。",
                ),
                planner_required_predecessors=("message.draft", "user.confirm"),
                planner_required_arg_refs={
                    "target": ("message.draft.target_entity",),
                    "content": ("message.draft.content",),
                    "preview": ("message.draft.preview", "user.confirm.preview"),
                    "idempotency_key": ("message.draft.idempotency_key",),
                },
                planner_forbidden_literal_args=("target", "content", "preview", "idempotency_key"),
            )
        )

    def prompt_contract(self) -> str:
        """Return a compact model-facing contract generated from registered action specs."""

        lines = ["已注册 action 能力："]
        if any(_is_server_read_spec(spec) for spec in self._actions.values()):
            lines.append(
                "服务端只读 action 通用：kind=read risk=low，不需要 user.confirm；"
                "输出 text/items/item/result_count/result。"
            )
        for name in _prompt_contract_action_order(self.names()):
            spec = self._actions[name]
            formatter = _format_server_read_prompt_contract if _is_server_read_spec(spec) else _format_action_prompt_contract
            lines.append(formatter(spec))
        return "\n".join(lines)

    async def _server_read(self, action_name: str, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        del context
        reader = self._require_server_reader()
        execute = getattr(reader, "execute", None)
        if not callable(execute):
            raise RuntimeError("SERVER_READ_UNAVAILABLE")
        payload = await execute(action_name, dict(args or {}))
        return _normalize_server_read_output(action_name, payload)

    async def _server_write(self, action_name: str, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        del context
        writer = self._require_server_writer()
        execute = getattr(writer, "execute", None)
        if not callable(execute):
            raise RuntimeError("SERVER_WRITE_UNAVAILABLE")
        payload = await execute(action_name, dict(args or {}))
        return _normalize_server_write_output(action_name, payload)

    def _require_server_reader(self) -> Any:
        if self._server_reader is None:
            self._server_reader = AIActionServerReadClient()
        return self._server_reader

    def _require_server_writer(self) -> Any:
        if self._server_writer is None:
            self._server_writer = AIActionServerWriteClient()
        return self._server_writer

    async def _memory_search(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        del context
        payload = _MemorySearchInput.from_args(args)
        manager = self._require_memory_manager()
        search = getattr(manager, "search_for_action", None)
        if not callable(search):
            raise RuntimeError("MEMORY_SEARCH_UNAVAILABLE")
        raw_output = await search(
            question=payload.question,
            participants=payload.participants,
            participant_match=payload.participant_match,
            time_scope=payload.time_scope,
            keywords=payload.keywords,
            limit=payload.limit,
        )
        return _normalize_memory_search_output(raw_output, question=payload.question)

    async def _memory_summarize(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        payload = await _MemorySummarizeInput.from_args(args, store=context.get("store"))
        result_count = int(payload.source.get("result_count") or 0)
        cache_key = _memory_summarize_cache_key(
            source=payload.source,
            question=payload.question,
            prompt_version=MEMORY_SUMMARIZE_PROMPT_VERSION,
            model_id=MEMORY_SUMMARIZE_MODEL_ID,
        )
        if cache_key:
            cached = self._action_cache.get(MEMORY_SUMMARIZE_CACHE_NAMESPACE, cache_key)
            if isinstance(cached, dict):
                cached["cache_hit"] = True
                cached["cache_namespace"] = MEMORY_SUMMARIZE_CACHE_NAMESPACE
                cached["cache_version"] = MEMORY_SUMMARIZE_PROMPT_VERSION
                cached["cache_model_id"] = MEMORY_SUMMARIZE_MODEL_ID
                return cached
        context_lines = [
            str(item or "").strip()
            for item in list(payload.source.get("context_lines") or [])
            if str(item or "").strip()
        ]
        if not context_lines and isinstance(payload.source.get("results"), list):
            context_lines = [
                _memory_result_context_line(dict(item))
                for item in payload.source["results"]
                if isinstance(item, dict)
            ]
            context_lines = [line for line in context_lines if line]
        if not context_lines:
            question = payload.question or str(payload.source.get("question") or "")
            text = f"没有找到相关记录。用户问题：{question or '本地记忆查询'}。"
            output = {
                "text": text,
                "result_count": result_count,
                "input_result_count": result_count,
                "context_chars": 0,
                "chunked": False,
                "chunk_count": 0,
                "status": "empty",
                "cache_hit": False,
                "cache_namespace": MEMORY_SUMMARIZE_CACHE_NAMESPACE,
                "cache_version": MEMORY_SUMMARIZE_PROMPT_VERSION,
                "cache_model_id": MEMORY_SUMMARIZE_MODEL_ID,
            }
            if cache_key:
                self._action_cache.set(MEMORY_SUMMARIZE_CACHE_NAMESPACE, cache_key, output)
            return output
        summary = _summarize_memory_context_lines(
            context_lines,
            input_result_count=result_count or len(context_lines),
        )
        summarizer = self._require_memory_summarizer()
        question = payload.question or str(payload.source.get("question") or "")
        try:
            summary_result = await summarizer.summarize(
                question=question,
                context_lines=list(summary["context_lines"]),
                style=payload.style,
                input_result_count=summary["input_result_count"],
            )
        except RuntimeError as exc:
            fallback_reason = _memory_summarize_model_failure_reason(exc)
            if not fallback_reason:
                raise
            logger.warning(
                "AI action memory summarize degraded reason=%s result_count=%s context_chars=%s",
                fallback_reason,
                result_count or len(context_lines),
                summary["context_chars"],
            )
            return _memory_summarize_degraded_output(
                summary=summary,
                question=question,
                result_count=result_count or len(context_lines),
                fallback_reason=fallback_reason,
            )
        text = " ".join(str(summary_result.get("text") or "").split()).strip()
        if not text:
            logger.warning(
                "AI action memory summarize degraded reason=model_empty result_count=%s context_chars=%s",
                result_count or len(context_lines),
                summary["context_chars"],
            )
            return _memory_summarize_degraded_output(
                summary=summary,
                question=question,
                result_count=result_count or len(context_lines),
                fallback_reason="model_empty",
            )
        summary_usage = _memory_summarize_usage(summary_result)
        output = {
            "requires_responder": False,
            "context_lines": summary["context_lines"],
            "question": payload.question,
            "result_count": result_count or len(context_lines),
            "input_result_count": summary["input_result_count"],
            "context_chars": summary["context_chars"],
            "chunked": summary["chunked"],
            "chunk_count": summary["chunk_count"],
            "status": "ready",
            "text": text,
            "summary_model_id": str(summary_result.get("summary_model_id") or MEMORY_SUMMARIZE_MODEL_ID),
            "model_chunk_count": int(summary_result.get("model_chunk_count") or 0),
            "usage": summary_usage,
            "model_tokens": _memory_summarize_model_tokens(summary_result, usage=summary_usage),
            "cache_hit": False,
            "cache_namespace": MEMORY_SUMMARIZE_CACHE_NAMESPACE,
            "cache_version": MEMORY_SUMMARIZE_PROMPT_VERSION,
            "cache_model_id": MEMORY_SUMMARIZE_MODEL_ID,
        }
        if cache_key:
            self._action_cache.set(MEMORY_SUMMARIZE_CACHE_NAMESPACE, cache_key, output)
        return output

    def _require_memory_manager(self) -> Any:
        if self._memory_manager is None:
            from client.managers.conversation_memory_manager import ConversationMemoryManager

            self._memory_manager = ConversationMemoryManager()
        return self._memory_manager

    def _require_memory_summarizer(self) -> Any:
        if self._memory_summarizer is None:
            from client.managers.ai_action_memory_summarizer import AIActionMemorySummarizer

            self._memory_summarizer = AIActionMemorySummarizer()
        return self._memory_summarizer

    async def _contact_resolve(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | ActionPause:
        queries = _clean_list(args.get("queries"))
        allow_multiple = bool(args.get("allow_multiple", True))
        cache_index_version = await self._contact_index_version()
        cache_key = _contact_resolve_cache_key(
            queries=queries,
            allow_multiple=allow_multiple,
            index_version=cache_index_version,
            resolver_version=CONTACT_RESOLVE_RESOLVER_VERSION,
        )
        if cache_key:
            cached = self._action_cache.get(CONTACT_RESOLVE_CACHE_NAMESPACE, cache_key)
            if isinstance(cached, dict):
                cached["cache_hit"] = True
                cached["cache_namespace"] = CONTACT_RESOLVE_CACHE_NAMESPACE
                cached["cache_index_version"] = cache_index_version
                cached["cache_resolver_version"] = CONTACT_RESOLVE_RESOLVER_VERSION
                return cached
        contacts: list[dict[str, Any]] = []
        unresolved: list[str] = []
        for query in queries:
            matches = await self._exact_contact_matches(query)
            if len(matches) > 1:
                candidates = [_candidate_to_dict(candidate, raw=query) for candidate in matches[:5]]
                return ActionPause(
                    state="waiting_clarification",
                    payload={
                        "type": "contact_ambiguity",
                        "step_id": str(context.get("step_id") or ""),
                        "query": query,
                        "candidates": candidates,
                        "partial_contacts": contacts,
                        "unresolved": unresolved,
                    },
                    response_text=_alias_ambiguity_question(query, candidates),
                )
            if len(matches) == 1:
                contacts.append(_candidate_to_dict(matches[0], raw=query))
                continue
            unresolved.append(query)
            contacts.append(_raw_contact(query))

        if not allow_multiple and len(contacts) > 1:
            return ActionPause(
                state="waiting_clarification",
                payload={
                    "type": "target_too_many",
                    "step_id": str(context.get("step_id") or ""),
                    "candidates": contacts,
                },
                response_text="这个操作只能选择一个目标，请补充更明确的对象。",
            )
        output = {
            "contacts": contacts,
            "groups": [],
            "ambiguous": [],
            "unresolved": unresolved,
            "cache_hit": False,
            "cache_namespace": CONTACT_RESOLVE_CACHE_NAMESPACE,
            "cache_resolver_version": CONTACT_RESOLVE_RESOLVER_VERSION,
        }
        if cache_index_version:
            output["cache_index_version"] = cache_index_version
        if cache_key:
            self._action_cache.set(CONTACT_RESOLVE_CACHE_NAMESPACE, cache_key, output)
        return output

    async def _contact_index_version(self) -> str:
        get_version = getattr(self._contact_resolver, "get_contact_index_version", None)
        if not callable(get_version):
            return ""
        try:
            return str(await get_version() or "").strip()
        except Exception:
            logger.exception("Failed to resolve contact cache index version")
            return ""

    async def _exact_contact_matches(self, query: str) -> list[Any]:
        exact = getattr(self._contact_resolver, "_exact_matches", None)
        if callable(exact):
            try:
                return list(await exact(query))
            except Exception:
                logger.debug("contact.resolve exact lookup failed", exc_info=True)
                return []
        expand = getattr(self._contact_resolver, "expand_terms", None)
        if callable(expand):
            try:
                resolution = await expand([query])
            except Exception:
                logger.debug("contact.resolve expand lookup failed", exc_info=True)
                return []
            if bool(getattr(resolution, "is_ambiguous", False)):
                return list(getattr(resolution, "candidates", ()) or ())
        return []

    async def _message_draft(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        del context
        target_entity = _coerce_contact(args.get("target"))
        content = str(args.get("content") or args.get("source") or "").strip()
        if isinstance(args.get("source"), dict):
            content = str(args["source"].get("text") or "").strip()
        if not content:
            content = "我整理好了相关内容，稍后发你。"
        if len(content) > 500:
            content = content[:500].rstrip()
        target = _contact_label(target_entity)
        idempotency_key = hashlib.sha256(
            json.dumps({"target": target_entity.get("contact_id"), "content": content}, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:32]
        preview = {"operation": "发送消息", "target": target, "content": content}
        return {
            "target": target,
            "target_entity": target_entity,
            "content": content,
            "preview": preview,
            "idempotency_key": idempotency_key,
        }

    async def _user_confirm(self, args: dict[str, Any], context: dict[str, Any]) -> ActionPause:
        preview = args.get("preview") if isinstance(args.get("preview"), dict) else {}
        risk = str(args.get("risk") or "high").strip() or "high"
        operation = str(preview.get("operation") or "").strip()
        target = str(preview.get("target") or "").strip()
        content = str(preview.get("content") or "").strip()
        if "发送" in operation and (not target or not content):
            text = "发送前缺少明确的目标或内容，请补充后再继续。"
            return ActionPause(
                state="waiting_clarification",
                payload={
                    "type": "clarification",
                    "step_id": str(context.get("step_id") or ""),
                    "missing": ["target_or_content"],
                    "response_text": text,
                },
                response_text=text,
            )
        text = _confirmation_text(preview, risk=risk)
        return ActionPause(
            state="waiting_confirmation",
            payload={
                "type": "confirmation",
                "step_id": str(context.get("step_id") or ""),
                "risk": risk,
                "preview": preview,
                "preview_fingerprint": confirmation_preview_fingerprint(preview, risk=risk),
                "response_text": text,
                "plan_version": int(context.get("plan_version") or 1),
            },
            response_text=text,
        )

    async def _message_send(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        target = _coerce_contact(args.get("target"))
        content = str(args.get("content") or "").strip()
        idempotency_key = str(args.get("idempotency_key") or "").strip()
        if not idempotency_key:
            return {"status": "failed", "error_code": "IDEMPOTENCY_KEY_REQUIRED", "text": "发送前缺少幂等键，已停止。"}
        sender = self._message_sender or AIActionMessageSender()
        send = getattr(sender, "send_text_to_contact", None)
        if not callable(send):
            return _message_send_failed(
                "SEND_CONTRACT_UNAVAILABLE",
                "发送链路暂时不可用，请稍后再试。",
                target=target,
                content=content,
            )
        result = await send(
            target=target,
            content=content,
            idempotency_key=idempotency_key,
            plan_id=str(context.get("plan_id") or ""),
        )
        return _normalize_message_send_output(result, target=target, content=content)


@dataclass(frozen=True, slots=True)
class _MemorySearchInput:
    question: str
    participants: list[Any]
    participant_match: str
    time_scope: dict[str, Any]
    keywords: list[str]
    limit: int

    @classmethod
    def from_args(cls, args: dict[str, Any]) -> "_MemorySearchInput":
        question = " ".join(str(args.get("question") or "").split())
        keywords = _clean_list(args.get("keywords"))
        if not question and keywords:
            question = " ".join(keywords)
        participant_match = str(args.get("participant_match") or "any").strip().lower() or "any"
        if participant_match not in {"any", "all", "direct_only", "group_only"}:
            participant_match = "any"
        time_scope = args.get("time_scope") if isinstance(args.get("time_scope"), dict) else {}
        time_type = str(time_scope.get("type") or "all_history").strip().lower() or "all_history"
        normalized_time_scope = dict(time_scope)
        normalized_time_scope["type"] = time_type
        try:
            limit = max(1, min(50, int(args.get("limit") or args.get("max_items") or 8)))
        except (TypeError, ValueError):
            limit = 8
        return cls(
            question=question,
            participants=_clean_participants(args.get("participants")),
            participant_match=participant_match,
            time_scope=normalized_time_scope,
            keywords=keywords,
            limit=limit,
        )


@dataclass(frozen=True, slots=True)
class _MemorySummarizeInput:
    source: dict[str, Any]
    question: str
    style: str

    @classmethod
    async def from_args(cls, args: dict[str, Any], *, store: Any) -> "_MemorySummarizeInput":
        source = args.get("source")
        if isinstance(source, dict) and "result_ref" in source:
            result_ref = dict(source.get("result_ref") or {})
            result_id = str(result_ref.get("id") or "").strip()
            get_temp_result = getattr(store, "get_temp_result", None)
            if not result_id or not callable(get_temp_result):
                raise ActionHandlerError("TEMP_RESULT_EXPIRED")
            record = await get_temp_result(result_id)
            if record is None:
                raise ActionHandlerError("TEMP_RESULT_EXPIRED")
            source = dict(getattr(record, "payload", {}) or {})
        if not isinstance(source, dict):
            source = {}
        return cls(
            source=dict(source),
            question=" ".join(str(args.get("question") or "").split()),
            style=" ".join(str(args.get("style") or "summary").split()) or "summary",
        )


def _clean_participants(value: object) -> list[Any]:
    raw = value if isinstance(value, list) else ([value] if value else [])
    participants: list[Any] = []
    for item in raw:
        if isinstance(item, dict):
            participants.append(dict(item))
            continue
        text = " ".join(str(item or "").split()).strip(" ，,。？！?;；:：")
        if text:
            participants.append(text)
    return participants[:20]


def _normalize_memory_search_output(value: Any, *, question: str) -> dict[str, Any]:
    output = dict(value or {}) if isinstance(value, dict) else {}
    results = [dict(item) for item in list(output.get("results") or []) if isinstance(item, dict)]
    context_lines = [
        str(item or "").strip()
        for item in list(output.get("context_lines") or [])
        if str(item or "").strip()
    ]
    preview = [dict(item) for item in list(output.get("preview") or results[:3]) if isinstance(item, dict)]
    normalized = {
        "results": results,
        "preview": preview[:8],
        "context_lines": context_lines,
        "result_count": int(output.get("result_count") or len(results) or len(context_lines)),
        "truncated": bool(output.get("truncated")),
        "fallback_used": bool(output.get("fallback_used")),
        "summary_result_count": int(output.get("summary_result_count") or 0),
        "message_fallback_count": int(output.get("message_fallback_count") or 0),
        "question": question,
    }
    if any(
        key in output
        for key in ("cache_hit", "cache_namespace", "cache_index_version", "cache_search_version")
    ):
        normalized["cache_hit"] = bool(output.get("cache_hit"))
        if str(output.get("cache_namespace") or "").strip():
            normalized["cache_namespace"] = str(output.get("cache_namespace") or "").strip()
        if str(output.get("cache_index_version") or "").strip():
            normalized["cache_index_version"] = str(output.get("cache_index_version") or "").strip()
        if str(output.get("cache_search_version") or "").strip():
            normalized["cache_search_version"] = str(output.get("cache_search_version") or "").strip()
    return normalized


def _normalize_server_read_output(action_name: str, payload: Any) -> dict[str, Any]:
    action = str(action_name or "").strip()
    items, item, result_count = _server_read_result_shape(payload)
    return {
        "action": action,
        "status": "ready",
        "text": _server_read_text(action, result_count),
        "result_count": result_count,
        "items": items,
        "item": item,
        "result": payload,
    }


def _server_read_result_shape(payload: Any) -> tuple[list[Any], dict[str, Any], int]:
    if isinstance(payload, list):
        return list(payload), {}, len(payload)
    if isinstance(payload, dict):
        items = _server_read_items(payload)
        if items is not None:
            return items, {}, _server_read_count(payload, fallback=len(items))
        return [], dict(payload), 1 if payload else 0
    return [], {}, 0


def _server_read_items(payload: dict[str, Any]) -> list[Any] | None:
    for key in ("items", "messages", "sessions", "users", "friends", "groups", "files", "moments", "requests", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return list(value)
    return None


def _server_read_count(payload: dict[str, Any], *, fallback: int) -> int:
    for key in ("total", "count", "result_count"):
        try:
            if payload.get(key) is not None:
                return max(0, int(payload.get(key)))
        except (TypeError, ValueError):
            continue
    return max(0, int(fallback or 0))


def _server_read_text(action_name: str, result_count: int) -> str:
    label = SERVER_READ_ACTION_LABELS.get(str(action_name or "").strip(), "服务端只读查询")
    return f"已完成{label}，返回 {max(0, int(result_count or 0))} 条结果。"


def _normalize_server_write_output(action_name: str, payload: Any) -> dict[str, Any]:
    action = str(action_name or "").strip()
    status = _server_write_status(payload)
    return {
        "action": action,
        "status": status,
        "text": _server_write_text(action, status),
        "result": payload,
        "error_code": "" if status == "done" else status.upper(),
    }


def _server_write_status(payload: Any) -> str:
    if isinstance(payload, dict):
        explicit = str(payload.get("status") or "").strip().lower()
        if explicit in {"failed", "error"}:
            return "failed"
    return "done"


def _server_write_text(action_name: str, status: str) -> str:
    label = SERVER_WRITE_ACTION_LABELS.get(str(action_name or "").strip(), "服务端写操作")
    if status == "done":
        return f"已完成{label}。"
    return f"{label}未完成。"


def _url_path_arg(value: Any) -> str:
    text = str(value or "").strip().strip("/")
    if not text:
        raise ActionHandlerError("ARG_SCHEMA_INVALID: path")
    return text


class _PromptContractContactResolver:
    async def get_contact_index_version(self) -> str:
        return ""


def build_default_action_prompt_contract() -> str:
    """Build the canonical planner action contract without touching runtime services."""

    return AtomicActionRegistry(contact_resolver=_PromptContractContactResolver()).prompt_contract()


def build_default_action_names() -> tuple[str, ...]:
    """Build the canonical registered action name list without touching runtime services."""

    return AtomicActionRegistry(contact_resolver=_PromptContractContactResolver()).names()


def _format_action_prompt_contract(spec: AtomicActionSpec) -> str:
    parts = [
        f"- {spec.name}: kind={spec.kind}",
        f"risk={spec.risk_level}",
    ]
    if spec.prompt_purpose:
        parts.append(f"用途={spec.prompt_purpose}")
    input_fields = _model_prompt_fields(spec.input_model)
    if input_fields:
        parts.append(f"输入字段 {input_fields}")
    elif spec.input_model is not None:
        parts.append("输入字段 无")
    output_fields = _model_prompt_fields(spec.output_model)
    if output_fields:
        parts.append(f"输出字段 {output_fields}")
    constraints = _spec_prompt_constraints(spec)
    if constraints:
        parts.append(f"约束 {constraints}")
    planning_constraints = _spec_planner_constraints(spec)
    if planning_constraints:
        parts.append(f"规划契约 {planning_constraints}")
    for note in spec.prompt_notes:
        normalized = " ".join(str(note or "").split())
        if normalized:
            parts.append(f"说明 {normalized}")
    return "；".join(parts) + "。"


def _prompt_contract_action_order(names: tuple[str, ...]) -> tuple[str, ...]:
    priority = (
        "contact.resolve",
        "memory.search",
        "memory.summarize",
        "message.draft",
        "user.confirm",
        "message.send",
    )
    available = {str(name or "").strip() for name in names}
    ordered = [name for name in priority if name in available]
    ordered.extend(name for name in names if name not in set(ordered))
    return tuple(ordered)


def _format_server_read_prompt_contract(spec: AtomicActionSpec) -> str:
    parts = [
        f"- {spec.name}: kind=read",
        "risk=low",
    ]
    if spec.prompt_purpose:
        parts.append(f"用途={spec.prompt_purpose}")
    input_fields = _model_prompt_fields(spec.input_model)
    if input_fields:
        parts.append(f"输入字段 {input_fields}")
    elif spec.input_model is not None:
        parts.append("输入字段 无")
    for note in spec.prompt_notes:
        normalized = " ".join(str(note or "").split())
        if not normalized or _is_common_server_read_note(normalized):
            continue
        parts.append(f"说明 {normalized}")
    return "；".join(parts) + "。"


def _is_server_read_spec(spec: AtomicActionSpec) -> bool:
    return spec.output_model is ServerReadOutput and spec.name in SERVER_READ_ACTION_ROUTES


def _is_common_server_read_note(note: str) -> bool:
    return note.startswith("这是只读服务端动作") or note.startswith("只能用于读取当前账号")


def _model_prompt_fields(model: type[Any] | None) -> str:
    fields = getattr(model, "model_fields", None)
    if not fields:
        return ""
    items: list[str] = []
    for name, field in fields.items():
        type_name = _annotation_prompt_name(getattr(field, "annotation", Any))
        item = f"{name}:{type_name}"
        is_required = getattr(field, "is_required", None)
        if callable(is_required) and is_required():
            item += " required"
        items.append(item)
    return ", ".join(items)


def _annotation_prompt_name(annotation: Any) -> str:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Literal:
        return "Literal[" + ", ".join(repr(arg) for arg in args) + "]"
    if origin in {list, tuple, set, frozenset}:
        item_type = _annotation_prompt_name(args[0]) if args else "Any"
        return f"{origin.__name__}[{item_type}]"
    if origin is dict:
        key_type = _annotation_prompt_name(args[0]) if args else "Any"
        value_type = _annotation_prompt_name(args[1]) if len(args) > 1 else "Any"
        return f"dict[{key_type}, {value_type}]"
    if origin in {Union, UnionType}:
        return " | ".join(_annotation_prompt_name(arg) for arg in args)
    if annotation is Any:
        return "Any"
    if annotation is None or annotation is type(None):
        return "None"
    name = getattr(annotation, "__name__", "")
    if name:
        return str(name)
    return str(annotation).replace("typing.", "")


def _spec_prompt_constraints(spec: AtomicActionSpec) -> str:
    values = [
        f"enabled={_bool_prompt(spec.enabled)}",
        f"requires_confirmation={_bool_prompt(spec.requires_confirmation)}",
        f"allow_side_effect={_bool_prompt(spec.allow_side_effect)}",
    ]
    if spec.max_targets is not None:
        values.append(f"max_targets={spec.max_targets}")
    if spec.max_content_chars is not None:
        values.append(f"max_content_chars={spec.max_content_chars}")
    if spec.idempotency_required:
        values.append("idempotency_required=true")
    if spec.require_preview:
        values.append("require_preview=true")
    if spec.require_resolved_target:
        values.append("require_resolved_target=true")
    if spec.default_result_limit:
        values.append(f"default_result_limit={spec.default_result_limit}")
    if spec.max_result_items is not None:
        values.append(f"max_result_items={spec.max_result_items}")
    return ", ".join(values)


def _spec_planner_constraints(spec: AtomicActionSpec) -> str:
    values: list[str] = []
    for action_name in spec.planner_required_predecessors:
        normalized = str(action_name or "").strip()
        if normalized:
            values.append(f"前置动作 {normalized}")
    for field_name, refs in spec.planner_required_arg_refs.items():
        normalized_field = str(field_name or "").strip()
        if not normalized_field:
            continue
        normalized_refs = [
            str(ref or "").strip()
            for ref in list(refs or ())
            if str(ref or "").strip()
        ]
        for ref in normalized_refs:
            values.append(f"字段引用 {normalized_field}<-{ref}")
    for arg_name, required_fields in spec.planner_required_object_args.items():
        normalized_arg = str(arg_name or "").strip()
        if not normalized_arg:
            continue
        values.append(f"{normalized_arg} 必须是对象")
        for field_name in list(required_fields or ()):
            normalized_field = str(field_name or "").strip()
            if normalized_field:
                values.append(f"对象字段 {normalized_arg}.{normalized_field} 必填")
    for arg_name, field_refs in spec.planner_required_object_arg_refs.items():
        normalized_arg = str(arg_name or "").strip()
        if not normalized_arg:
            continue
        for field_name, refs in dict(field_refs or {}).items():
            normalized_field = str(field_name or "").strip()
            if not normalized_field:
                continue
            for ref in list(refs or ()):
                normalized_ref = str(ref or "").strip()
                if normalized_ref:
                    values.append(f"对象字段 {normalized_arg}.{normalized_field}<-{normalized_ref}")
    for arg_name, field_values in spec.planner_required_object_arg_contains.items():
        normalized_arg = str(arg_name or "").strip()
        if not normalized_arg:
            continue
        for field_name, expected_values in dict(field_values or {}).items():
            normalized_field = str(field_name or "").strip()
            if not normalized_field:
                continue
            for expected in list(expected_values or ()):
                normalized_expected = str(expected or "").strip()
                if normalized_expected:
                    values.append(f"对象字段 {normalized_arg}.{normalized_field} 包含 {normalized_expected}")
    for field_name in spec.planner_forbidden_literal_args:
        normalized = str(field_name or "").strip()
        if normalized:
            values.append(f"不允许直接使用自然语言对象作为 {normalized}")
    return ", ".join(values)


def _bool_prompt(value: bool) -> str:
    return "true" if bool(value) else "false"


def _contact_resolve_cache_key(
    *,
    queries: list[str],
    allow_multiple: bool,
    index_version: str,
    resolver_version: str,
) -> str | None:
    normalized_index_version = str(index_version or "").strip()
    normalized_resolver_version = str(resolver_version or "").strip()
    if not normalized_index_version or not normalized_resolver_version:
        return None
    payload = {
        "allow_multiple": bool(allow_multiple),
        "index_version": normalized_index_version,
        "queries": [str(query or "").strip().casefold() for query in list(queries or [])],
        "resolver_version": normalized_resolver_version,
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _memory_summarize_cache_key(
    *,
    source: dict[str, Any],
    question: str,
    prompt_version: str,
    model_id: str,
) -> str | None:
    normalized_prompt_version = str(prompt_version or "").strip()
    normalized_model_id = str(model_id or "").strip()
    if not normalized_prompt_version or not normalized_model_id:
        return None
    payload = {
        "model_id": normalized_model_id,
        "prompt_version": normalized_prompt_version,
        "question": " ".join(str(question or "").split()),
        "source": _memory_summarize_source_cache_payload(source),
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _memory_summarize_source_cache_payload(source: dict[str, Any]) -> dict[str, Any]:
    payload = dict(source or {}) if isinstance(source, dict) else {}
    context_lines = [
        str(item or "").strip()
        for item in list(payload.get("context_lines") or [])
        if str(item or "").strip()
    ]
    results: list[dict[str, Any]] = []
    for item in list(payload.get("results") or []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text_preview") or item.get("text") or "").strip()
        results.append(
            {
                "source_id": str(item.get("source_id") or "").strip(),
                "source_type": str(item.get("source_type") or "").strip(),
                "title": str(item.get("title") or "").strip(),
                "text_checksum": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
    return {
        "context_lines_checksum": hashlib.sha256(_stable_json(context_lines).encode("utf-8")).hexdigest(),
        "result_count": int(payload.get("result_count") or len(results) or len(context_lines)),
        "results": results,
        "truncated": bool(payload.get("truncated")),
    }


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _memory_result_context_line(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "").strip()
    text = str(item.get("text_preview") or item.get("text") or "").strip()
    if title and text:
        return f"{title}；摘要：{text}"
    return text or title


def _memory_summarize_model_failure_reason(exc: RuntimeError) -> str:
    message = str(exc or "").strip()
    if message == "MEMORY_SUMMARIZE_FAILED":
        return "model_failed"
    if message == "MEMORY_SUMMARIZE_EMPTY_OUTPUT":
        return "model_empty"
    return ""


def _memory_summarize_usage(summary_result: dict[str, Any]) -> dict[str, int]:
    usage = summary_result.get("usage")
    if not isinstance(usage, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, raw in usage.items():
        try:
            amount = max(0, int(raw or 0))
        except (TypeError, ValueError):
            continue
        if amount:
            normalized[str(key)] = amount
    return normalized


def _memory_summarize_model_tokens(summary_result: dict[str, Any], *, usage: dict[str, int]) -> int:
    try:
        explicit = max(0, int(summary_result.get("model_tokens") or 0))
    except (TypeError, ValueError):
        explicit = 0
    if explicit:
        return explicit
    if usage.get("total_tokens"):
        return int(usage["total_tokens"])
    return int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)


def _memory_summarize_degraded_output(
    *,
    summary: dict[str, Any],
    question: str,
    result_count: int,
    fallback_reason: str,
) -> dict[str, Any]:
    context_lines = [
        str(item or "").strip()
        for item in list(summary.get("context_lines") or [])
        if str(item or "").strip()
    ]
    input_result_count = int(summary.get("input_result_count") or result_count or len(context_lines))
    return {
        "requires_responder": False,
        "context_lines": context_lines,
        "question": question,
        "result_count": int(result_count or len(context_lines)),
        "input_result_count": input_result_count,
        "context_chars": int(summary.get("context_chars") or sum(len(line) for line in context_lines)),
        "chunked": bool(summary.get("chunked")),
        "chunk_count": int(summary.get("chunk_count") or 0),
        "status": "degraded",
        "text": _memory_summarize_degraded_text(context_lines, input_result_count=input_result_count),
        "summary_model_id": MEMORY_SUMMARIZE_MODEL_ID,
        "model_chunk_count": 0,
        "fallback_used": True,
        "fallback_reason": fallback_reason,
        "cache_hit": False,
        "cache_namespace": MEMORY_SUMMARIZE_CACHE_NAMESPACE,
        "cache_version": MEMORY_SUMMARIZE_PROMPT_VERSION,
        "cache_model_id": MEMORY_SUMMARIZE_MODEL_ID,
    }


def _memory_summarize_degraded_text(context_lines: list[str], *, input_result_count: int) -> str:
    lines = [
        _clip_text(str(line or "").strip(), 220)
        for line in list(context_lines or [])
        if str(line or "").strip()
    ][:5]
    count = max(int(input_result_count or 0), len(lines))
    if not lines:
        return f"模型总结暂不可用。已检索到 {count} 条相关记录，但暂时无法生成摘要。"
    header = "模型总结暂不可用，以下是根据本地检索结果提取的证据摘要："
    count_line = f"共检索到 {count} 条相关记录。"
    evidence = [f"{index}. {line}" for index, line in enumerate(lines, start=1)]
    return "\n".join([header, count_line, *evidence])


def _summarize_memory_context_lines(context_lines: list[str], *, input_result_count: int) -> dict[str, Any]:
    lines = [str(line or "").strip() for line in list(context_lines or []) if str(line or "").strip()]
    raw_chars = sum(len(line) for line in lines)
    if (
        len(lines) <= MEMORY_SUMMARIZE_DIRECT_MAX_LINES
        and raw_chars <= MEMORY_SUMMARIZE_DIRECT_MAX_CONTEXT_CHARS
    ):
        return {
            "context_lines": lines,
            "input_result_count": max(int(input_result_count or 0), len(lines)),
            "context_chars": raw_chars,
            "chunked": False,
            "chunk_count": 0,
        }
    chunks: list[str] = []
    for start in range(0, len(lines), MEMORY_SUMMARIZE_CHUNK_SIZE):
        chunk = lines[start : start + MEMORY_SUMMARIZE_CHUNK_SIZE]
        snippets = [_clip_memory_context_line(line) for line in chunk]
        end = start + len(chunk)
        chunks.append(f"检索结果 {start + 1}-{end}：" + "；".join(snippets))
    return {
        "context_lines": chunks,
        "input_result_count": max(int(input_result_count or 0), len(lines)),
        "context_chars": sum(len(line) for line in chunks),
        "chunked": bool(chunks),
        "chunk_count": len(chunks),
    }


def _clip_memory_context_line(line: str) -> str:
    return _clip_text(line, _memory_context_line_clip_limit(line))


def _memory_context_line_clip_limit(line: str) -> int:
    text = str(line or "")
    if "文件总结：" in text or "文件内容片段：" in text:
        return MEMORY_SUMMARIZE_CHUNK_FILE_ITEM_MAX_CHARS
    return MEMORY_SUMMARIZE_CHUNK_DEFAULT_ITEM_MAX_CHARS


def _clip_text(value: str, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


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


def _candidate_to_dict(candidate: Any, *, raw: str) -> dict[str, Any]:
    contact_id = str(getattr(candidate, "contact_id", "") or "").strip()
    display_name = str(getattr(candidate, "display_name", "") or "").strip()
    username = str(getattr(candidate, "username", "") or "").strip()
    nickname = str(getattr(candidate, "nickname", "") or "").strip()
    remark = str(getattr(candidate, "remark", "") or "").strip()
    assistim_id = str(getattr(candidate, "assistim_id", "") or "").strip()
    aliases = []
    for term in (remark, display_name, nickname, username, assistim_id, contact_id, raw):
        if term and term not in aliases:
            aliases.append(term)
    return {
        "raw": raw,
        "contact_id": contact_id,
        "username": username,
        "nickname": nickname,
        "remark": remark,
        "display_name": display_name or remark or nickname or username or contact_id or raw,
        "assistim_id": assistim_id,
        "aliases": aliases,
        "resolved": bool(contact_id),
    }


def _raw_contact(query: str) -> dict[str, Any]:
    return {
        "raw": query,
        "contact_id": query,
        "username": "",
        "nickname": "",
        "remark": "",
        "display_name": query,
        "assistim_id": "",
        "aliases": [query],
        "resolved": False,
    }


def _coerce_contacts(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    return [_coerce_contact(item) for item in raw_items if _coerce_contact(item)]


def _validate_action_spec(spec: AtomicActionSpec) -> None:
    name = str(getattr(spec, "name", "") or "").strip()
    if not name:
        raise ValueError("ACTION_SPEC_INVALID: unnamed action")
    kind = str(getattr(spec, "kind", "") or "").strip()
    risk = str(getattr(spec, "risk_level", "") or "").strip()
    if kind not in {"read", "write"}:
        raise ValueError(f"ACTION_SPEC_INVALID: {name}: kind")
    if risk not in {"low", "medium", "high"}:
        raise ValueError(f"ACTION_SPEC_INVALID: {name}: risk_level")
    if _positive_spec_int(getattr(spec, "max_input_bytes", 0)) <= 0:
        raise ValueError(f"ACTION_SPEC_INVALID: {name}: max_input_bytes")
    if _positive_spec_int(getattr(spec, "max_output_json_bytes", 0)) <= 0:
        raise ValueError(f"ACTION_SPEC_INVALID: {name}: max_output_json_bytes")
    if _positive_spec_int(getattr(spec, "timeout_ms", 0)) <= 0:
        raise ValueError(f"ACTION_SPEC_INVALID: {name}: timeout_ms")
    try:
        max_retries = int(getattr(spec, "max_retries", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"ACTION_SPEC_INVALID: {name}: max_retries") from exc
    if max_retries < 0:
        raise ValueError(f"ACTION_SPEC_INVALID: {name}: max_retries")
    for attr in ("model_call_cost", "estimated_input_tokens", "estimated_output_tokens"):
        try:
            value = int(getattr(spec, attr, 0) or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"ACTION_SPEC_INVALID: {name}: {attr}") from exc
        if value < 0:
            raise ValueError(f"ACTION_SPEC_INVALID: {name}: {attr}")
    if kind == "read":
        if bool(getattr(spec, "allow_side_effect", False)):
            raise ValueError(f"ACTION_SPEC_INVALID: {name}: read_side_effect")
        return
    if risk != "high":
        raise ValueError(f"ACTION_SPEC_INVALID: {name}: write_risk")
    if not bool(getattr(spec, "allow_side_effect", False)):
        raise ValueError(f"ACTION_SPEC_INVALID: {name}: write_side_effect")
    if not bool(getattr(spec, "requires_confirmation", False)):
        raise ValueError(f"ACTION_SPEC_INVALID: {name}: confirmation")
    if bool(getattr(spec, "allow_batch", False)):
        raise ValueError(f"ACTION_SPEC_INVALID: {name}: batch")
    if getattr(spec, "max_targets", None) != 1:
        raise ValueError(f"ACTION_SPEC_INVALID: {name}: max_targets")
    if not bool(getattr(spec, "require_preview", False)):
        raise ValueError(f"ACTION_SPEC_INVALID: {name}: preview")
    if not bool(getattr(spec, "idempotency_required", False)):
        raise ValueError(f"ACTION_SPEC_INVALID: {name}: idempotency")
    if bool(getattr(spec, "allow_auto_resume_after_confirm", True)):
        raise ValueError(f"ACTION_SPEC_INVALID: {name}: auto_resume")


def _positive_spec_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _coerce_contact(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        payload = dict(value)
        if not payload.get("display_name"):
            payload["display_name"] = payload.get("remark") or payload.get("nickname") or payload.get("username") or payload.get("contact_id") or payload.get("raw") or ""
        return payload
    text = " ".join(str(value or "").split())
    return _raw_contact(text) if text else {}


def _contact_label(contact: dict[str, Any]) -> str:
    return str(
        contact.get("display_name")
        or contact.get("remark")
        or contact.get("nickname")
        or contact.get("username")
        or contact.get("contact_id")
        or contact.get("raw")
        or ""
    ).strip()


def _session_matches_direct_contact(session: Any, contact_id: str) -> bool:
    normalized_contact_id = str(contact_id or "").strip()
    if session is None or not normalized_contact_id:
        return False
    if bool(getattr(session, "is_ai_session", False)):
        return False
    if str(getattr(session, "session_type", "") or "").strip() != "direct":
        return False
    extra = dict(getattr(session, "extra", {}) or {})
    counterpart_id = str(extra.get("counterpart_id") or "").strip()
    if counterpart_id and counterpart_id == normalized_contact_id:
        return True
    participant_ids = {
        str(item or "").strip()
        for item in list(getattr(session, "participant_ids", []) or [])
        if str(item or "").strip()
    }
    return normalized_contact_id in participant_ids


def _stable_message_id(*, plan_id: str, idempotency_key: str) -> str:
    raw = f"assistim-ai-action:{str(plan_id or '').strip()}:{str(idempotency_key or '').strip()}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


def _status_value(status: Any) -> str:
    return str(getattr(status, "value", status) or "").strip()


def _message_send_failed(
    error_code: str,
    text: str,
    *,
    target: dict[str, Any],
    content: str,
    session_id: str = "",
    message_id: str = "",
    error: str = "",
) -> dict[str, Any]:
    output = {
        "status": "failed",
        "error_code": str(error_code or "SEND_FAILED").strip() or "SEND_FAILED",
        "text": str(text or "发送失败，请稍后再试。").strip() or "发送失败，请稍后再试。",
        "target": dict(target or {}),
        "content_chars": len(str(content or "")),
    }
    if session_id:
        output["session_id"] = session_id
    if message_id:
        output["message_id"] = message_id
    if error:
        output["error"] = error
    return output


def _normalize_message_send_output(result: Any, *, target: dict[str, Any], content: str) -> dict[str, Any]:
    payload = dict(result or {}) if isinstance(result, dict) else {}
    status = str(payload.get("status") or "").strip() or "sent"
    text = str(payload.get("text") or "").strip()
    if not text:
        label = _contact_label(target) or "目标联系人"
        text = f"已发送给{label}。" if status == "sent" else "发送失败，请稍后再试。"
    payload["status"] = status
    payload["text"] = text
    payload["target"] = dict(payload.get("target") or target or {})
    try:
        content_chars = int(payload.get("content_chars") or len(str(content or "")))
    except (TypeError, ValueError):
        content_chars = len(str(content or ""))
    payload["content_chars"] = max(0, content_chars)
    if "error_code" in payload:
        payload["error_code"] = str(payload.get("error_code") or "")
    return payload


def _alias_ambiguity_question(query: str, candidates: list[dict[str, Any]]) -> str:
    lines = [f"我找到了多个叫“{query}”的联系人，请回复序号确认要选哪一个："]
    for index, candidate in enumerate(candidates[:5], start=1):
        label = _contact_label(candidate)
        username = str(candidate.get("username") or candidate.get("assistim_id") or "").strip()
        contact_id = str(candidate.get("contact_id") or "").strip()
        details = " / ".join(
            item for item in (label, f"username: {username}" if username else "", f"id: {contact_id}" if contact_id else "") if item
        )
        lines.append(f"{index}. {details}")
    return "\n".join(lines)


def _confirmation_text(preview: dict[str, Any], *, risk: str) -> str:
    operation = str(preview.get("operation") or "执行操作").strip()
    target = str(preview.get("target") or "目标对象").strip()
    content = str(preview.get("content") or "").strip()
    if len(content) > 220:
        content = content[:220].rstrip() + "..."
    risk_text = "这是高风险操作，确认后才会继续。" if risk == "high" else "确认后才会继续。"
    if content:
        return f"确认要{operation}给{target}吗？\n内容预览：{content}\n{risk_text}"
    return f"确认要{operation}吗？\n目标：{target}\n{risk_text}"

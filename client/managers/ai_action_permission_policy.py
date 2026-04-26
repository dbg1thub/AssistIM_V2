"""Permission policy boundary for AI action execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from client.managers.ai_action_types import AtomicActionSpec


RAW_CONTENT_FLAGS = {
    "allow_raw_message_quote",
    "include_full_messages",
    "include_message_plaintext",
    "include_raw_content",
    "raw_content",
    "raw_messages",
    "return_full_messages",
    "return_raw_content",
}
RAW_CONTENT_MODES = {
    "full_messages",
    "full_text",
    "message_plaintext",
    "plaintext",
    "raw",
    "raw_content",
    "raw_messages",
}
CROSS_SESSION_FLAGS = {
    "cross_session",
    "include_cross_session",
}
CROSS_SESSION_SCOPES = {
    "*",
    "all",
    "all_sessions",
    "any_session",
    "cross_session",
    "global",
}
SESSION_LIST_FIELDS = {
    "session_ids",
    "source_session_ids",
    "target_session_ids",
}
SESSION_SCOPE_FIELDS = {
    "scope",
    "search_scope",
    "session_scope",
    "source_scope",
}


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    code: str = ""
    message: str = ""


class AIPermissionPolicy:
    """Central permission hook for action execution.

    The first implementation is intentionally conservative but permissive for
    local read-only actions. The boundary exists so contact/group/E2EE scopes
    can be enforced without spreading permission checks into action handlers.
    """

    def check_step(
        self,
        *,
        spec: AtomicActionSpec,
        args: dict[str, Any],
        plan_context: dict[str, Any] | None = None,
    ) -> PermissionDecision:
        del plan_context
        normalized_args = dict(args or {})
        if spec.kind == "write" and not spec.allow_side_effect:
            return PermissionDecision(False, "PERMISSION_DENIED", "这个操作当前不允许产生外部影响。")
        if spec.kind == "read":
            if not spec.allow_raw_content_return and _requests_raw_content(normalized_args):
                return PermissionDecision(False, "PERMISSION_DENIED", "这个操作当前不允许返回完整原文。")
            if not spec.allow_cross_session and _requests_cross_session(normalized_args):
                return PermissionDecision(False, "PERMISSION_DENIED", "这个操作当前不允许跨会话读取。")
        return PermissionDecision(True)


def _requests_raw_content(args: dict[str, Any]) -> bool:
    for key in RAW_CONTENT_FLAGS:
        if _truthy(args.get(key)):
            return True
    mode = str(args.get("mode") or args.get("output_mode") or args.get("return_mode") or "").strip().lower()
    if mode in RAW_CONTENT_MODES:
        return True
    fields = args.get("fields")
    if isinstance(fields, list):
        normalized_fields = {str(item or "").strip().lower() for item in fields}
        if normalized_fields.intersection(RAW_CONTENT_FLAGS | RAW_CONTENT_MODES):
            return True
    return False


def _requests_cross_session(args: dict[str, Any]) -> bool:
    for key in CROSS_SESSION_FLAGS:
        if _truthy(args.get(key)):
            return True
    for key in SESSION_SCOPE_FIELDS:
        scope = str(args.get(key) or "").strip().lower()
        if scope in CROSS_SESSION_SCOPES:
            return True
    for key in SESSION_LIST_FIELDS:
        value = args.get(key)
        if isinstance(value, list):
            session_ids = [str(item or "").strip() for item in value if str(item or "").strip()]
            if len(set(session_ids)) > 1:
                return True
            if any(session_id.lower() in CROSS_SESSION_SCOPES for session_id in session_ids):
                return True
        elif str(value or "").strip().lower() in CROSS_SESSION_SCOPES:
            return True
    return False


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "raw", "full", "all"}
    return False

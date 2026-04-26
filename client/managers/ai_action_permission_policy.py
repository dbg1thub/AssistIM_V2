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
CONTACT_ID_FIELDS = {
    "contact_id",
    "friend_id",
    "target_user_id",
    "user_id",
}
GROUP_ID_FIELDS = {
    "group_id",
}
ENTITY_TYPE_FIELDS = {
    "entity_type",
    "kind",
    "target_type",
    "type",
}
CONTACT_ENTITY_TYPES = {
    "contact",
    "direct",
    "friend",
    "private",
    "user",
}
GROUP_ENTITY_TYPES = {
    "group",
    "group_chat",
    "room",
}
TAG_FIELDS = {
    "labels",
    "sensitive_tags",
    "tags",
}
SINGLE_TAG_FIELDS = {
    "label",
    "sensitive_tag",
    "tag",
}
E2EE_FIELDS = {
    "e2ee",
    "encrypted",
    "is_e2ee",
    "uses_e2ee",
}
E2EE_STATE_FIELDS = {
    "crypto_mode",
    "encryption_mode",
    "mode",
}
PERMISSION_DENIED_MESSAGE = "这个操作当前没有权限访问所请求的对象。"


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    code: str = ""
    message: str = ""


@dataclass(frozen=True, slots=True)
class AIPermissionScope:
    allowed_contacts: tuple[str, ...] = ()
    allowed_groups: tuple[str, ...] = ()
    excluded_contacts: tuple[str, ...] = ()
    excluded_groups: tuple[str, ...] = ()
    sensitive_tags: tuple[str, ...] = ()
    allow_e2ee_plaintext: bool = False
    allow_raw_message_quote: bool = True


class AIPermissionPolicy:
    """Central permission hook for action execution.

    The first implementation is intentionally conservative but permissive for
    local read-only actions. The boundary exists so contact/group/E2EE scopes
    can be enforced without spreading permission checks into action handlers.
    """

    def __init__(self, *, scope: AIPermissionScope | None = None) -> None:
        self._scope = scope or AIPermissionScope()
        self._allowed_contacts = _normalize_set(self._scope.allowed_contacts)
        self._allowed_groups = _normalize_set(self._scope.allowed_groups)
        self._excluded_contacts = _normalize_set(self._scope.excluded_contacts)
        self._excluded_groups = _normalize_set(self._scope.excluded_groups)
        self._sensitive_tags = _normalize_set(self._scope.sensitive_tags)

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
        if self._requests_disallowed_scope(normalized_args):
            return PermissionDecision(False, "PERMISSION_DENIED", PERMISSION_DENIED_MESSAGE)
        if spec.kind == "read":
            if _requests_raw_content(normalized_args) and (
                not spec.allow_raw_content_return or not self._scope.allow_raw_message_quote
            ):
                return PermissionDecision(False, "PERMISSION_DENIED", "这个操作当前不允许返回完整原文。")
            if not spec.allow_cross_session and _requests_cross_session(normalized_args):
                return PermissionDecision(False, "PERMISSION_DENIED", "这个操作当前不允许跨会话读取。")
        return PermissionDecision(True)

    def _requests_disallowed_scope(self, args: dict[str, Any]) -> bool:
        for entity in _iter_structured_entities(args):
            contact_id = _entity_contact_id(entity)
            if contact_id:
                if contact_id in self._excluded_contacts:
                    return True
                if self._allowed_contacts and contact_id not in self._allowed_contacts:
                    return True
            group_id = _entity_group_id(entity)
            if group_id:
                if group_id in self._excluded_groups:
                    return True
                if self._allowed_groups and group_id not in self._allowed_groups:
                    return True
            if self._sensitive_tags and _entity_tags(entity).intersection(self._sensitive_tags):
                return True
            if not self._scope.allow_e2ee_plaintext and _entity_uses_e2ee(entity):
                return True
        return False


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


def _iter_structured_entities(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _iter_structured_entities(item)
        return
    if isinstance(value, list | tuple):
        for item in value:
            yield from _iter_structured_entities(item)


def _entity_contact_id(entity: dict[str, Any]) -> str:
    for field in CONTACT_ID_FIELDS:
        text = _normalized_text(entity.get(field))
        if text:
            return text
    if _entity_type(entity) in CONTACT_ENTITY_TYPES:
        return _normalized_text(entity.get("id"))
    return ""


def _entity_group_id(entity: dict[str, Any]) -> str:
    for field in GROUP_ID_FIELDS:
        text = _normalized_text(entity.get(field))
        if text:
            return text
    if _entity_type(entity) in GROUP_ENTITY_TYPES:
        return _normalized_text(entity.get("id"))
    return ""


def _entity_type(entity: dict[str, Any]) -> str:
    for field in ENTITY_TYPE_FIELDS:
        text = _normalized_text(entity.get(field)).lower()
        if text:
            return text
    return ""


def _entity_tags(entity: dict[str, Any]) -> set[str]:
    tags: set[str] = set()
    for field in TAG_FIELDS:
        value = entity.get(field)
        if isinstance(value, list | tuple | set):
            tags.update(_normalized_text(item).lower() for item in value if _normalized_text(item))
        else:
            text = _normalized_text(value).lower()
            if text:
                tags.add(text)
    for field in SINGLE_TAG_FIELDS:
        text = _normalized_text(entity.get(field)).lower()
        if text:
            tags.add(text)
    return tags


def _entity_uses_e2ee(entity: dict[str, Any]) -> bool:
    for field in E2EE_FIELDS:
        if _truthy(entity.get(field)):
            return True
    for field in E2EE_STATE_FIELDS:
        value = _normalized_text(entity.get(field)).lower()
        if value in {"e2ee", "encrypted", "end_to_end", "end-to-end"}:
            return True
    return False


def _normalize_set(values: tuple[str, ...]) -> set[str]:
    return {_normalized_text(value) for value in values if _normalized_text(value)}


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "raw", "full", "all"}
    return False

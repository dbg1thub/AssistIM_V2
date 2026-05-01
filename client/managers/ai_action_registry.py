"""Atomic action registry and first action implementations."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from client.core import logging
from client.managers.ai_action_cache import AIActionCache
from client.managers.ai_action_io_models import (
    ContactResolveInput,
    ContactResolveOutput,
    MemorySearchInput,
    MemorySearchOutput,
    MemorySummarizeInput,
    MemorySummarizeOutput,
    MessageDraftInput,
    MessageDraftOutput,
    MessageSendInput,
    MessageSendOutput,
    UserConfirmInput,
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
        action_cache: AIActionCache | None = None,
    ) -> None:
        self._contact_resolver = contact_resolver
        self._memory_manager = memory_manager
        self._memory_summarizer = memory_summarizer
        self._message_sender = message_sender
        self._action_cache = action_cache or AIActionCache()
        self._actions: dict[str, AtomicActionSpec] = {}
        self._register_defaults()

    def get(self, name: str) -> AtomicActionSpec | None:
        return self._actions.get(str(name or "").strip())

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._actions))

    def _register(self, spec: AtomicActionSpec) -> None:
        self._actions[spec.name] = spec

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
            )
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
            )
        )
        self._register(
            AtomicActionSpec(
                name="user.confirm",
                kind="read",
                risk_level="medium",
                handler=self._user_confirm,
                input_model=UserConfirmInput,
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
            )
        )

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
        summary_result = await summarizer.summarize(
            question=payload.question or str(payload.source.get("question") or ""),
            context_lines=list(summary["context_lines"]),
            style=payload.style,
            input_result_count=summary["input_result_count"],
        )
        text = " ".join(str(summary_result.get("text") or "").split()).strip()
        if not text:
            raise ActionHandlerError("MEMORY_SUMMARIZE_EMPTY_OUTPUT")
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

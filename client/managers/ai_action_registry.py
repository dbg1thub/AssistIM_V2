"""Atomic action registry and first action implementations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from client.core import logging
from client.managers.ai_action_types import ActionPause, AtomicActionSpec
logger = logging.get_logger(__name__)


MEMORY_SUMMARIZE_DIRECT_MAX_LINES = 6
MEMORY_SUMMARIZE_DIRECT_MAX_CONTEXT_CHARS = 1200
MEMORY_SUMMARIZE_CHUNK_SIZE = 4
MEMORY_SUMMARIZE_CHUNK_ITEM_MAX_CHARS = 34


class AtomicActionRegistry:
    """Registry for executable atomic actions."""

    def __init__(
        self,
        *,
        contact_resolver: Any,
        memory_manager: Any | None = None,
    ) -> None:
        self._contact_resolver = contact_resolver
        self._memory_manager = memory_manager
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
                max_content_chars=2000,
            )
        )
        self._register(
            AtomicActionSpec(
                name="user.confirm",
                kind="read",
                risk_level="medium",
                handler=self._user_confirm,
            )
        )
        self._register(
            AtomicActionSpec(
                name="message.send",
                kind="write",
                risk_level="high",
                handler=self._message_send,
                enabled=False,
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
            return {
                "text": text,
                "result_count": result_count,
                "input_result_count": result_count,
                "context_chars": 0,
                "chunked": False,
                "chunk_count": 0,
                "status": "empty",
            }
        summary = _summarize_memory_context_lines(
            context_lines,
            input_result_count=result_count or len(context_lines),
        )
        return {
            "requires_responder": True,
            "context_lines": summary["context_lines"],
            "question": payload.question,
            "result_count": result_count or len(context_lines),
            "input_result_count": summary["input_result_count"],
            "context_chars": summary["context_chars"],
            "chunked": summary["chunked"],
            "chunk_count": summary["chunk_count"],
            "status": "ready",
        }

    def _require_memory_manager(self) -> Any:
        if self._memory_manager is None:
            from client.managers.conversation_memory_manager import ConversationMemoryManager

            self._memory_manager = ConversationMemoryManager()
        return self._memory_manager

    async def _contact_resolve(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | ActionPause:
        queries = _clean_list(args.get("queries"))
        allow_multiple = bool(args.get("allow_multiple", True))
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
        return {"contacts": contacts, "groups": [], "ambiguous": [], "unresolved": unresolved}

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
                "response_text": text,
                "plan_version": int(context.get("plan_version") or 1),
            },
            response_text=text,
        )

    async def _message_send(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        del context
        target = _coerce_contact(args.get("target"))
        content = str(args.get("content") or "").strip()
        if not str(args.get("idempotency_key") or "").strip():
            return {"status": "failed", "error_code": "IDEMPOTENCY_KEY_REQUIRED", "text": "发送前缺少幂等键，已停止。"}
        text = (
            f"已确认要给{_contact_label(target) or '目标联系人'}发送“{content}”。"
            "当前版本还没有接入真实发送能力，所以不会实际发送。"
        )
        return {"status": "disabled", "text": text, "target": target, "content_chars": len(content)}


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
            if result_id and callable(get_temp_result):
                record = await get_temp_result(result_id)
                if record is not None:
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
    return {
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
        snippets = [_clip_text(line, MEMORY_SUMMARIZE_CHUNK_ITEM_MAX_CHARS) for line in chunk]
        end = start + len(chunk)
        chunks.append(f"检索结果 {start + 1}-{end}：" + "；".join(snippets))
    return {
        "context_lines": chunks,
        "input_result_count": max(int(input_result_count or 0), len(lines)),
        "context_chars": sum(len(line) for line in chunks),
        "chunked": bool(chunks),
        "chunk_count": len(chunks),
    }


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

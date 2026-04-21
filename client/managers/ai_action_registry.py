"""Atomic action registry and first action implementations."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from client.core import logging
from client.managers.ai_action_types import ActionPause, AtomicActionSpec
from client.managers.conversation_memory_manager import ConversationMemoryManager


logger = logging.get_logger(__name__)


class AtomicActionRegistry:
    """Registry for executable atomic actions."""

    def __init__(
        self,
        *,
        memory_manager: ConversationMemoryManager,
        contact_resolver: Any,
    ) -> None:
        self._memory_manager = memory_manager
        self._contact_resolver = contact_resolver
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
                max_output_json_bytes=65536,
            )
        )
        self._register(
            AtomicActionSpec(
                name="memory.summarize",
                kind="read",
                risk_level="low",
                handler=self._memory_summarize,
                max_input_bytes=65536,
                max_output_json_bytes=65536,
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

    async def _memory_search(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        del context
        participants = _coerce_contacts(args.get("participants"))
        keywords = _clean_list(args.get("keywords"))
        time_scope = args.get("time_scope") if isinstance(args.get("time_scope"), dict) else {"type": "all_history"}
        start_ts: int | None = None
        end_ts: int | None = None
        if str(time_scope.get("type") or "") == "range":
            start_ts = _coerce_int(time_scope.get("start_ts") or time_scope.get("start"))
            end_ts = _coerce_int(time_scope.get("end_ts") or time_scope.get("end"))
        terms = _query_terms(participants, keywords)
        query_text = str(args.get("question") or "").strip()
        context_result = await self._memory_manager.build_context_for_structured_query(
            query_text=query_text,
            start_ts=start_ts,
            end_ts=end_ts,
            terms=terms,
            participant_ids=[
                str(contact.get("contact_id") or "").strip()
                for contact in participants
                if str(contact.get("contact_id") or "").strip()
            ],
            participant_aliases=_participant_aliases(participants),
            query_kind="history",
        )
        lines = list(context_result.lines or ())
        return {
            "results": lines,
            "result_count": len(lines),
            "truncated": False,
            "query_terms": terms,
            "participants": participants,
            "participant_match": str(args.get("participant_match") or "any"),
            "time_scope": dict(time_scope),
            "question": query_text,
        }

    async def _memory_summarize(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        source = args.get("source")
        if isinstance(source, dict) and isinstance(source.get("result_ref"), dict):
            temp_store = context.get("store")
            get_temp = getattr(temp_store, "get_temp_result", None)
            if callable(get_temp):
                temp = await get_temp(str(source["result_ref"].get("id") or ""))
                source = dict(temp.payload if temp is not None else {})
        results = []
        if isinstance(source, dict):
            results = [str(item or "").strip() for item in list(source.get("results") or []) if str(item or "").strip()]
        elif isinstance(source, list):
            results = [str(item or "").strip() for item in source if str(item or "").strip()]
        question = str(args.get("question") or "").strip()
        if not results:
            return {
                "text": "没有查到相关聊天摘要。你可以换一个时间范围、对象或关键词再试。",
                "context_lines": [],
                "result_count": 0,
                "requires_responder": False,
                "question": question,
            }
        return {
            "text": "",
            "context_lines": results,
            "result_count": len(results),
            "requires_responder": True,
            "question": question,
        }

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


def _query_terms(participants: list[dict[str, Any]], keywords: list[str]) -> list[str]:
    terms: list[str] = []
    for contact in participants:
        aliases = contact.get("aliases") if isinstance(contact.get("aliases"), list) else []
        values = [
            contact.get("raw"),
            contact.get("remark"),
            contact.get("display_name"),
            contact.get("nickname"),
            contact.get("username"),
            contact.get("assistim_id"),
            contact.get("contact_id"),
            *aliases,
        ]
        for value in values:
            text = " ".join(str(value or "").split()).strip(" ，,。")
            if text and text not in terms:
                terms.append(text)
    for keyword in keywords:
        if keyword and keyword not in terms:
            terms.append(keyword)
    return terms[:20]


def _participant_aliases(participants: list[dict[str, Any]]) -> list[str]:
    aliases: list[str] = []
    for contact in participants:
        raw_aliases = contact.get("aliases") if isinstance(contact.get("aliases"), list) else []
        values = [
            contact.get("raw"),
            contact.get("remark"),
            contact.get("display_name"),
            contact.get("nickname"),
            contact.get("username"),
            contact.get("assistim_id"),
            contact.get("contact_id"),
            *raw_aliases,
        ]
        for value in values:
            text = " ".join(str(value or "").split()).strip(" ，,。")
            if text and text not in aliases:
                aliases.append(text)
    return aliases[:20]


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


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

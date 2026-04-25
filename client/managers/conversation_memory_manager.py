from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Any, Sequence

from client.core import logging
from client.managers.ai_action_cache import AIActionCache
from client.managers.conversation_ann_index import ConversationAnnIndex
from client.managers.conversation_rag_planner import (
    ConversationRagParticipant,
    ConversationRagPlanner,
    ConversationRagSemanticPlan,
)
from client.managers.conversation_vector_index import ConversationVectorIndex, DenseVector
from client.services.local_ai_memory_store import get_local_ai_memory_store
from client.storage.database import Database, get_database


logger = logging.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ConversationMemoryContext:
    """Bounded local chat-memory context for one AI assistant request."""

    lines: tuple[str, ...]
    query_kind: str = ""
    requires_confirmation: bool = False
    confirmation_prompt: str = ""
    pending_query_text: str = ""

    @property
    def has_context(self) -> bool:
        return bool(self.lines)


@dataclass(frozen=True, slots=True)
class _MemoryQuery:
    text: str
    start_ts: int | None
    end_ts: int | None
    terms: tuple[str, ...]
    query_kind: str
    requires_confirmation: bool = False


@dataclass(frozen=True, slots=True)
class _ResolvedParticipant:
    mention: str
    display_name: str
    aliases: tuple[str, ...]


def _action_memory_search_cache_key(
    *,
    question: str,
    participants: Sequence[_ResolvedParticipant],
    participant_match: str,
    start_ts: int | None,
    end_ts: int | None,
    keywords: Sequence[str],
    terms: Sequence[str],
    limit: int,
    index_version: str,
    search_version: str,
    model_id: str,
) -> str | None:
    normalized_index_version = str(index_version or "").strip()
    normalized_search_version = str(search_version or "").strip()
    normalized_model_id = str(model_id or "").strip()
    if not normalized_index_version or not normalized_search_version or not normalized_model_id:
        return None
    payload = {
        "index_version": normalized_index_version,
        "keywords": sorted(
            {
                str(term or "").strip().casefold()
                for term in list(keywords or [])
                if str(term or "").strip()
            }
        ),
        "limit": max(1, int(limit or 1)),
        "model_id": normalized_model_id,
        "participant_match": str(participant_match or "any").strip().lower() or "any",
        "participants": [
            {
                "aliases": list(participant.aliases),
                "display_name": participant.display_name,
                "mention": participant.mention,
            }
            for participant in list(participants or [])
        ],
        "question": " ".join(str(question or "").split()),
        "search_version": normalized_search_version,
        "terms": list(
            dict.fromkeys(
                str(term or "").strip().casefold()
                for term in list(terms or [])
                if str(term or "").strip()
            )
        ),
        "time_scope": {
            "end_ts": end_ts,
            "start_ts": start_ts,
        },
    }
    return hashlib.sha256(_stable_cache_json(payload).encode("utf-8")).hexdigest()


def _stable_cache_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ConversationMemoryManager:
    """Search local conversation-memory summaries for AI assistant history questions."""

    DEFAULT_LOOKBACK_DAYS = 7
    SEARCH_CANDIDATE_LIMIT = 40
    EXPANDED_SEARCH_CANDIDATE_LIMIT = 200
    RAG_CANDIDATE_LIMIT = 120
    RAG_RESULT_LIMIT = 4
    RAG_MESSAGE_RESULT_LIMIT = 2
    RAG_MIN_SCORE = 1.6
    ACTION_SEARCH_SUMMARY_ENOUGH_MIN_CONTEXT_CHARS = 120
    ACTION_SEARCH_SUMMARY_ENOUGH_MIN_TOP_SCORE = 2.8
    AI_MEMORY_MIN_SCORE = 0.0
    AI_MEMORY_SOURCE_TYPE_SUMMARY = "conversation_summary"
    AI_MEMORY_SOURCE_TYPE_FILE_SUMMARY = "file_summary"
    AI_MEMORY_SOURCE_TYPE_FILE_TEXT_CHUNK = "file_text_chunk"
    AI_MEMORY_SOURCE_TYPE_VOICE_TRANSCRIPT = "voice_transcript"
    AI_MEMORY_SOURCE_TYPES = (
        AI_MEMORY_SOURCE_TYPE_SUMMARY,
        AI_MEMORY_SOURCE_TYPE_FILE_SUMMARY,
        AI_MEMORY_SOURCE_TYPE_FILE_TEXT_CHUNK,
        AI_MEMORY_SOURCE_TYPE_VOICE_TRANSCRIPT,
    )
    CONTEXT_RESULT_LIMIT = 6
    CONTEXT_LINE_MAX_CHARS = 260
    MESSAGE_FALLBACK_SESSION_LIMIT = 5
    MESSAGE_FALLBACK_PER_SESSION_LIMIT = 40
    MESSAGE_FALLBACK_RESULT_LIMIT = 8
    ACTION_MEMORY_SEARCH_CACHE_NAMESPACE = "memory.search"
    ACTION_MEMORY_SEARCH_VERSION = "action_memory_search:v1"

    _HISTORY_INTENTS = (
        "聊了什么",
        "聊过什么",
        "聊什么",
        "聊啥",
        "谈了什么",
        "谈过什么",
        "聊天记录",
        "聊天摘要",
        "聊天历史",
        "总结",
        "回顾",
        "说过什么",
        "提到什么",
    )
    _MEMORY_REFERENCES = (
        "聊天记录",
        "聊天摘要",
        "聊天历史",
        "会话摘要",
        "会话记录",
        "对话记录",
        "历史记录",
        "之前聊",
        "上次聊",
    )
    _LOOKUP_ACTIONS = (
        "查",
        "查询",
        "检索",
        "搜索",
        "找",
        "看看",
        "看下",
        "看一下",
        "总结",
        "回顾",
        "整理",
    )
    _TIME_HINTS = (
        "今天",
        "昨天",
        "这周",
        "本周",
        "上周",
        "最近",
        "一周",
    )
    _AFFIRMATIVE_CONFIRMATIONS = (
        "确认",
        "是的",
        "对",
        "可以",
        "查吧",
        "开始查",
        "帮我查",
        "要查",
        "就查",
        "嗯",
        "好",
    )
    _NEGATIVE_CONFIRMATIONS = (
        "不用",
        "不要",
        "别查",
        "不查",
        "先不",
        "取消",
    )
    _STOP_TERMS = {
        "今天",
        "昨天",
        "这周",
        "本周",
        "上周",
        "最近",
        "一周",
        "聊天",
        "聊天记录",
        "记录",
        "总结",
        "回顾",
        "什么",
        "我和",
        "和我",
        "我们",
        "你能",
        "帮我",
        "帮我看看",
        "帮我查",
        "看看",
        "看下",
        "看一下",
        "确认",
        "可以",
        "查询",
        "检索",
        "搜索",
        "查吧",
        "一下",
        "the",
        "and",
        "what",
        "chat",
        "summary",
    }
    def __init__(
        self,
        db: Database | None = None,
        *,
        semantic_planner: Any | None = None,
        vector_index: ConversationVectorIndex | None = None,
        ann_index: ConversationAnnIndex | None = None,
        ai_memory_store: Any | None = None,
        action_cache: AIActionCache | None = None,
    ) -> None:
        self._db = db or get_database()
        self._semantic_planner = semantic_planner or ConversationRagPlanner()
        self._vector_index = vector_index or ConversationVectorIndex()
        self._ann_index = ann_index or ConversationAnnIndex(model_id=self._vector_index.model_id)
        self._ai_memory_store = ai_memory_store or get_local_ai_memory_store()
        self._action_cache = action_cache or AIActionCache()
        self._item_vector_cache: dict[str, DenseVector] = {}

    async def inspect_rag_retrieval_for_ai_chat(
        self,
        query_text: str,
        *,
        previous_messages: Sequence[Any] | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Return one structured diagnostic snapshot for AI-chat RAG retrieval."""
        text = " ".join(str(query_text or "").split())
        debug: dict[str, Any] = {
            "query_text": text,
            "use_rag": False,
            "query_kind": "",
            "rewritten_query": "",
            "terms": [],
            "alias_terms": [],
            "ann_namespace": "",
            "query_buckets": [],
            "ann_candidate_count": 0,
            "vector_store": "local_ai_memory",
            "vector_store_candidate_count": 0,
            "top_candidates": [],
            "context_lines": [],
            "fallback_lines": [],
            "fallback_used": False,
            "requires_confirmation": False,
            "confirmation_prompt": "",
            "rag_min_score": self.RAG_MIN_SCORE,
        }
        if not text:
            return debug

        raw_plan = await self._semantic_planner.plan(text, previous_messages=previous_messages)
        plan = self._normalize_rag_plan(raw_plan, fallback_query=text)
        debug["plan"] = raw_plan
        if plan is None or not plan.use_rag:
            return debug

        query_base = " ".join(str(plan.memory_query or plan.user_goal or text).split())
        resolved, unresolved, ambiguous = await self._resolve_rag_participants(plan.participants)
        query_terms = self._query_terms_from_plan(plan, resolved)
        debug.update(
            {
                "use_rag": True,
                "query_kind": str(plan.query_kind or ""),
                "rewritten_query": query_base,
                "terms": list(query_terms),
                "alias_terms": list(self._participant_alias_terms(resolved)),
                "participants": [
                    {"mention": participant.mention, "role": participant.role}
                    for participant in plan.participants
                ],
                "resolved_participants": [
                    {
                        "mention": participant.mention,
                        "display_name": participant.display_name,
                        "aliases": list(participant.aliases),
                    }
                    for participant in resolved
                ],
                "participant_relation": plan.participant_relation,
                "unresolved_participants": list(unresolved),
                "ambiguous_participants": {
                    mention: [self._contact_option_label(contact) for contact in matches[:5]]
                    for mention, matches in ambiguous.items()
                },
                "time_range": {"start_ts": plan.start_ts, "end_ts": plan.end_ts},
            }
        )
        if plan.participant_relation == "unknown":
            debug["requires_confirmation"] = True
            debug["confirmation_prompt"] = self._relation_confirmation_prompt(plan)
            return debug
        if unresolved or ambiguous:
            debug["requires_confirmation"] = True
            debug["confirmation_prompt"] = self._participant_confirmation_prompt(unresolved, ambiguous)
            return debug

        query_vector = await self._vector_index.encode_query(
            query=query_base,
            terms=query_terms,
            contact_aliases=(),
        )
        items = await self._search_ai_summary_memory(
            query_vector=query_vector,
            start_ts=plan.start_ts,
            end_ts=plan.end_ts,
            limit=self.RAG_CANDIDATE_LIMIT,
        )
        debug["vector_store_candidate_count"] = len(items)
        query = _MemoryQuery(
            text=query_base,
            start_ts=plan.start_ts,
            end_ts=plan.end_ts,
            terms=query_terms,
            query_kind=str(plan.query_kind or "rag"),
        )
        ranked = await self._rank_rag_items(
            self._filter_items_for_relation(items, resolved, plan.participant_relation),
            query,
            query_vector=query_vector,
        )
        debug["top_candidates"] = [
            {
                "score": round(float(score), 4),
                "session_id": str(item.get("session_id") or ""),
                "source_id": str(item.get("source_id") or ""),
                "title": str(item.get("title") or ""),
                "ann_match_count": int(item.get("ann_match_count") or 0),
            }
            for score, item in ranked[: max(1, int(top_k or 5))]
        ]
        context_lines = [
            self._format_item(item)
            for score, item in ranked[: self.RAG_RESULT_LIMIT]
            if score >= self.RAG_MIN_SCORE
        ]
        debug["context_lines"] = list(context_lines)
        debug["context_line_count"] = len(context_lines)
        if not context_lines:
            debug["no_memory_context_line"] = self._no_memory_context_line(plan)
        return debug

    async def build_rag_context_for_ai_chat(
        self,
        query_text: str,
        *,
        previous_messages: Sequence[Any] | None = None,
    ) -> ConversationMemoryContext:
        """Return retrieved local summary evidence for a general AI assistant turn."""
        text = " ".join(str(query_text or "").split())
        if not text:
            return ConversationMemoryContext(lines=(), query_kind="")
        raw_plan = await self._semantic_planner.plan(text, previous_messages=previous_messages)
        plan = self._normalize_rag_plan(raw_plan, fallback_query=text)
        if plan is None or not plan.use_rag:
            return ConversationMemoryContext(lines=(), query_kind="")
        if plan.participant_relation == "unknown":
            return ConversationMemoryContext(
                lines=(),
                query_kind=plan.query_kind,
                requires_confirmation=True,
                confirmation_prompt=self._relation_confirmation_prompt(plan),
                pending_query_text=plan.memory_query or plan.user_goal or text,
            )
        resolved, unresolved, ambiguous = await self._resolve_rag_participants(plan.participants)
        if unresolved or ambiguous:
            return ConversationMemoryContext(
                lines=(),
                query_kind=plan.query_kind,
                requires_confirmation=True,
                confirmation_prompt=self._participant_confirmation_prompt(unresolved, ambiguous),
                pending_query_text=plan.memory_query or plan.user_goal or text,
            )

        query_base = " ".join(str(plan.memory_query or plan.user_goal or text).split())
        query_terms = self._query_terms_from_plan(plan, resolved)
        query_vector = await self._vector_index.encode_query(
            query=query_base,
            terms=query_terms,
            contact_aliases=(),
        )
        items = await self._search_ai_summary_memory(
            query_vector=query_vector,
            start_ts=plan.start_ts,
            end_ts=plan.end_ts,
            limit=self.RAG_CANDIDATE_LIMIT,
        )

        query = _MemoryQuery(
            text=query_base,
            start_ts=plan.start_ts,
            end_ts=plan.end_ts,
            terms=query_terms,
            query_kind=str(plan.query_kind or "rag"),
        )
        lines = await self._context_lines_for_rag_items(
            items,
            query,
            query_vector=query_vector,
            resolved_participants=resolved,
            relation=plan.participant_relation,
        )
        if not lines:
            lines = (self._no_memory_context_line(plan),)
        return ConversationMemoryContext(lines=lines, query_kind=query.query_kind)

    async def build_reply_suggestion_rag_context(
        self,
        session_id: str,
        query_text: str,
        *,
        max_end_ts: int | None = None,
        min_start_ts: int | None = None,
        result_limit: int = 3,
        candidate_limit: int = 80,
    ) -> ConversationMemoryContext:
        """Return related summary-memory lines for reply suggestions in one chat session."""
        normalized_session_id = str(session_id or "").strip()
        text = " ".join(str(query_text or "").split())
        if not normalized_session_id or not text:
            return ConversationMemoryContext(lines=(), query_kind="reply_suggestion_rag")

        query_terms = tuple(self._tokenize_for_rag(text)[:16])
        try:
            query_vector = await self._vector_index.encode_query(
                query=text,
                terms=query_terms,
                contact_aliases=(),
            )
        except Exception:
            logger.exception("Failed to encode reply-suggestion RAG query")
            return ConversationMemoryContext(lines=(), query_kind="reply_suggestion_rag")

        normalized_max_end_ts = int(max_end_ts) if max_end_ts is not None else None
        normalized_min_start_ts = int(min_start_ts) if min_start_ts is not None else None
        items = await self._search_ai_summary_memory(
            query_vector=query_vector,
            session_id=normalized_session_id,
            start_ts=normalized_min_start_ts,
            end_ts=normalized_max_end_ts,
            limit=max(1, min(200, int(candidate_limit or 80))),
        )
        query = _MemoryQuery(
            text=text,
            start_ts=normalized_min_start_ts,
            end_ts=normalized_max_end_ts,
            terms=query_terms,
            query_kind="reply_suggestion_rag",
        )
        ranked = await self._rank_rag_items(items, query, query_vector=query_vector)
        limit = max(1, min(8, int(result_limit or 3)))
        lines = [
            self._format_item(item)
            for score, item in ranked
            if score >= self.RAG_MIN_SCORE
        ][:limit]
        return ConversationMemoryContext(lines=tuple(line for line in lines if line), query_kind=query.query_kind)

    async def _search_ai_summary_memory(
        self,
        *,
        query_vector: DenseVector,
        limit: int,
        start_ts: int | None = None,
        end_ts: int | None = None,
        session_id: str = "",
    ) -> list[dict[str, Any]]:
        if self._ai_memory_store is None:
            return []
        owner_scope = await self._ai_memory_owner_scope()
        if not owner_scope:
            return []
        normalized_limit = max(1, int(limit or self.RAG_CANDIDATE_LIMIT))
        search_limit = max(normalized_limit, min(500, normalized_limit * 4))
        try:
            results = await self._ai_memory_store.search(
                query_vector=query_vector.values,
                owner_scope=owner_scope,
                source_types=self.AI_MEMORY_SOURCE_TYPES,
                embedding_model_id=self._vector_index.model_id,
                limit=search_limit,
                min_score=self.AI_MEMORY_MIN_SCORE,
            )
        except Exception:
            logger.exception("Failed to query local AI memory vector store")
            return []
        items: list[dict[str, Any]] = []
        for result in list(results or []):
            item = self._ai_memory_result_to_summary_item(result)
            if item is None:
                continue
            if not self._summary_item_matches_bounds(
                item,
                start_ts=start_ts,
                end_ts=end_ts,
                session_id=session_id,
            ):
                continue
            items.append(item)
            if len(items) >= normalized_limit:
                break
        return items

    async def _ai_memory_owner_scope(self) -> str:
        get_app_state = getattr(self._db, "get_app_state", None)
        if not callable(get_app_state):
            return ""
        try:
            user_id = str(await get_app_state(Database.AUTH_USER_ID_STATE_KEY) or "").strip()
        except Exception:
            logger.exception("Failed to resolve current account for local AI memory search")
            return ""
        if not user_id:
            return ""
        return f"account:{user_id}"

    def _ai_memory_result_to_summary_item(self, result: Any) -> dict[str, Any] | None:
        item = getattr(result, "item", None)
        if item is None:
            return None
        metadata = dict(getattr(item, "metadata", {}) or {})
        try:
            start_ts = int(metadata.get("bucket_start_ts") or metadata.get("start_ts") or 0)
            end_ts = int(metadata.get("bucket_end_ts") or metadata.get("end_ts") or start_ts)
        except (TypeError, ValueError):
            start_ts = 0
            end_ts = 0
        keywords = metadata.get("keywords")
        if not isinstance(keywords, list):
            keywords = []
        participants = metadata.get("participants")
        if not isinstance(participants, list):
            participants = []
        item_source_type = str(getattr(item, "source_type", "") or "").strip()
        source_id = str(metadata.get("legacy_source_id") or getattr(item, "source_id", "") or "").strip()
        vector_values = tuple(getattr(item, "vector", ()) or ())
        return {
            "session_id": str(metadata.get("session_id") or ""),
            "source_type": str(metadata.get("legacy_source_type") or item_source_type or "summary"),
            "source_id": source_id,
            "source_version": int(metadata.get("source_version") or 1),
            "start_ts": start_ts,
            "end_ts": end_ts,
            "title": str(getattr(item, "title", "") or ""),
            "text": str(getattr(item, "text", "") or ""),
            "keywords": [str(value or "").strip() for value in keywords if str(value or "").strip()],
            "participants": [str(value or "").strip() for value in participants if str(value or "").strip()],
            "embedding_id": str(metadata.get("embedding_id") or ""),
            "embedding_model": str(getattr(item, "embedding_model_id", "") or ""),
            "embedding_content_hash": str(getattr(item, "content_hash", "") or ""),
            "embedding_dim": len(vector_values),
            "embedding_vector": [float(value) for value in vector_values],
            "embedding_updated_at": int(getattr(item, "updated_at", 0) or 0),
            "ann_match_count": 0,
            "vector_store_score": float(getattr(result, "score", 0.0) or 0.0),
            "created_at": int(getattr(item, "created_at", 0) or 0),
            "updated_at": int(getattr(item, "updated_at", 0) or 0),
        }

    @staticmethod
    def _summary_item_matches_bounds(
        item: dict[str, Any],
        *,
        start_ts: int | None,
        end_ts: int | None,
        session_id: str = "",
    ) -> bool:
        normalized_session_id = str(session_id or "").strip()
        if normalized_session_id and str(item.get("session_id") or "").strip() != normalized_session_id:
            return False
        item_start_ts = int(item.get("start_ts") or 0)
        item_end_ts = int(item.get("end_ts") or item_start_ts or 0)
        if start_ts is not None and item_end_ts < int(start_ts or 0):
            return False
        if end_ts is not None and item_start_ts > int(end_ts or 0):
            return False
        return True

    async def _context_lines_for_rag_items(
        self,
        items: list[dict[str, Any]],
        query: _MemoryQuery,
        *,
        query_vector: DenseVector,
        resolved_participants: Sequence[_ResolvedParticipant],
        relation: str,
    ) -> tuple[str, ...]:
        normalized_relation = str(relation or "separate").strip().lower() or "separate"
        if normalized_relation in {"separate", "compare"} and resolved_participants:
            lines: list[str] = []
            per_participant_limit = max(1, self.RAG_RESULT_LIMIT // max(1, len(resolved_participants)))
            for participant in resolved_participants:
                filtered = self._filter_items_for_participant(items, participant)
                ranked = await self._rank_rag_items(filtered, query, query_vector=query_vector)
                for score, item in ranked:
                    if score < self.RAG_MIN_SCORE:
                        continue
                    line = self._format_item(item)
                    if line:
                        lines.append(f"联系人：{participant.display_name}；{line}")
                    if len([entry for entry in lines if entry.startswith(f"联系人：{participant.display_name}；")]) >= per_participant_limit:
                        break
            return tuple(lines[: self.RAG_RESULT_LIMIT])

        filtered = self._filter_items_for_relation(items, resolved_participants, normalized_relation)
        ranked = await self._rank_rag_items(filtered, query, query_vector=query_vector)
        return tuple(
            self._format_item(item)
            for score, item in ranked[: self.RAG_RESULT_LIMIT]
            if score >= self.RAG_MIN_SCORE
        )

    async def _resolve_rag_participants(
        self,
        participants: Sequence[ConversationRagParticipant],
    ) -> tuple[tuple[_ResolvedParticipant, ...], tuple[str, ...], dict[str, tuple[dict[str, Any], ...]]]:
        resolved: list[_ResolvedParticipant] = []
        unresolved: list[str] = []
        ambiguous: dict[str, tuple[dict[str, Any], ...]] = {}
        for participant in list(participants or []):
            mention = " ".join(str(getattr(participant, "mention", "") or "").split())
            if not mention:
                continue
            matches = await self._lookup_contact_mention(mention)
            if not matches:
                unresolved.append(mention)
                continue
            if len(matches) > 1:
                ambiguous[mention] = tuple(matches)
                continue
            resolved.append(self._contact_to_resolved_participant(mention, matches[0]))
        return tuple(resolved), tuple(unresolved), ambiguous

    async def _resolve_action_participants(self, participants: Sequence[Any]) -> tuple[_ResolvedParticipant, ...]:
        resolved: list[_ResolvedParticipant] = []
        for item in list(participants or []):
            if isinstance(item, dict):
                participant = self._action_contact_to_resolved_participant(item)
                if participant is not None:
                    resolved.append(participant)
                continue
            mention = " ".join(str(item or "").split()).strip(" ，,。？！?;；:：")
            if not mention:
                continue
            matches = await self._lookup_contact_mention(mention)
            if len(matches) == 1:
                resolved.append(self._contact_to_resolved_participant(mention, matches[0]))
                continue
            alias = mention.casefold()
            resolved.append(_ResolvedParticipant(mention=mention, display_name=mention, aliases=(alias,)))
        return tuple(resolved)

    async def _lookup_contact_mention(self, mention: str) -> list[dict[str, Any]]:
        exact_resolver = getattr(self._db, "resolve_contacts_cache_alias", None)
        fuzzy_search = getattr(self._db, "search_contacts", None)
        matches: list[dict[str, Any]] = []
        if callable(exact_resolver):
            try:
                matches.extend(list(await exact_resolver(mention, limit=10)))
            except Exception:
                logger.exception("Failed to resolve contact alias for RAG")
        if not matches and callable(fuzzy_search):
            try:
                matches.extend(list(await fuzzy_search(mention, limit=10)))
            except Exception:
                logger.exception("Failed to search contact alias for RAG")
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for contact in matches:
            contact_id = str(contact.get("id") or contact.get("contact_id") or "").strip()
            key = contact_id.casefold() if contact_id else repr(sorted(contact.items()))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(dict(contact))
        return deduped

    def _action_contact_to_resolved_participant(self, contact: dict[str, Any]) -> _ResolvedParticipant | None:
        mention = (
            str(contact.get("raw") or "").strip()
            or str(contact.get("display_name") or "").strip()
            or str(contact.get("remark") or "").strip()
            or str(contact.get("nickname") or "").strip()
            or str(contact.get("username") or "").strip()
            or str(contact.get("contact_id") or contact.get("id") or "").strip()
        )
        display_name = (
            str(contact.get("display_name") or "").strip()
            or str(contact.get("remark") or "").strip()
            or str(contact.get("nickname") or "").strip()
            or str(contact.get("username") or "").strip()
            or str(contact.get("contact_id") or contact.get("id") or "").strip()
            or mention
        )
        aliases = list(self._contact_alias_values(contact))
        for alias in list(contact.get("aliases") or []):
            normalized = str(alias or "").strip().casefold()
            if normalized and normalized not in aliases:
                aliases.append(normalized)
        if mention and mention.casefold() not in aliases:
            aliases.append(mention.casefold())
        if not display_name and not aliases:
            return None
        return _ResolvedParticipant(
            mention=mention or display_name,
            display_name=display_name or mention,
            aliases=tuple(aliases or [display_name.casefold()]),
        )

    def _contact_to_resolved_participant(self, mention: str, contact: dict[str, Any]) -> _ResolvedParticipant:
        aliases = self._contact_alias_values(contact)
        display_name = (
            str(contact.get("remark") or "").strip()
            or str(contact.get("display_name") or "").strip()
            or str(contact.get("nickname") or "").strip()
            or str(contact.get("username") or "").strip()
            or str(contact.get("id") or "").strip()
            or mention
        )
        if mention.casefold() not in aliases:
            aliases = tuple(dict.fromkeys([mention.casefold(), *aliases]))
        return _ResolvedParticipant(mention=mention, display_name=display_name, aliases=aliases)

    @staticmethod
    def _action_time_bounds(time_scope: dict[str, Any]) -> tuple[int | None, int | None]:
        scope = dict(time_scope or {})
        scope_type = str(scope.get("type") or "all_history").strip().lower() or "all_history"
        if scope_type in {"all", "all_history", "history"}:
            return None, None
        if scope_type in {"range", "absolute"}:
            return (
                ConversationMemoryManager._coerce_action_ts(scope.get("start_ts") or scope.get("start")),
                ConversationMemoryManager._coerce_action_ts(scope.get("end_ts") or scope.get("end")),
            )
        now = datetime.now()
        if scope_type in {"today", "yesterday"}:
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start = today if scope_type == "today" else today - timedelta(days=1)
            end = today + timedelta(days=1) if scope_type == "today" else today
            return int(start.timestamp()), int(end.timestamp())
        if scope_type in {"recent", "last_days"}:
            try:
                days = max(1.0, min(365.0, float(scope.get("days") or 7)))
            except (TypeError, ValueError):
                days = 7.0
            return int((now - timedelta(days=days)).timestamp()), int((now + timedelta(seconds=1)).timestamp())
        return None, None

    @staticmethod
    def _coerce_action_ts(value: Any) -> int | None:
        if value is None or value == "":
            return None
        if isinstance(value, int | float):
            timestamp = int(value)
            return int(timestamp / 1000) if timestamp > 10_000_000_000 else timestamp
        text = str(value or "").strip()
        if not text:
            return None
        try:
            timestamp = int(float(text))
            return int(timestamp / 1000) if timestamp > 10_000_000_000 else timestamp
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return int(parsed.timestamp())
        except ValueError:
            return None

    def _empty_action_search_result(
        self,
        *,
        question: str,
        start_ts: int | None,
        end_ts: int | None,
    ) -> dict[str, Any]:
        return {
            "results": [],
            "preview": [],
            "context_lines": [],
            "result_count": 0,
            "truncated": False,
            "fallback_used": False,
            "summary_result_count": 0,
            "message_fallback_count": 0,
            "query": {
                "question": " ".join(str(question or "").split()),
                "terms": [],
                "start_ts": start_ts,
                "end_ts": end_ts,
                "participant_match": "any",
                "participants": [],
            },
        }

    def _action_memory_result(self, item: dict[str, Any], *, score: float) -> dict[str, Any]:
        return {
            "source_type": str(item.get("source_type") or "").strip(),
            "source_id": str(item.get("source_id") or "").strip(),
            "session_id": str(item.get("session_id") or "").strip(),
            "title": str(item.get("title") or "").strip(),
            "text_preview": self._clip(str(item.get("text") or ""), 220),
            "participants": list(item.get("participants") or []),
            "keywords": list(item.get("keywords") or []),
            "start_ts": int(item.get("start_ts") or 0),
            "end_ts": int(item.get("end_ts") or item.get("start_ts") or 0),
            "score": round(float(score), 4),
        }

    def _action_message_fallback_result(self, line: str, *, index: int) -> dict[str, Any]:
        return {
            "source_type": "message_fallback",
            "source_id": f"message_fallback:{index}",
            "session_id": "",
            "title": "原始消息线索",
            "text_preview": self._clip(str(line or ""), 220),
            "participants": [],
            "keywords": [],
            "start_ts": 0,
            "end_ts": 0,
            "score": 0.0,
        }

    def _action_summary_search_is_enough(
        self,
        selected: Sequence[tuple[float, dict[str, Any]]],
        context_lines: Sequence[str],
    ) -> bool:
        if not selected or not context_lines:
            return False
        if len(selected) >= 2:
            return True
        total_context_chars = sum(len(str(line or "")) for line in context_lines)
        if total_context_chars >= self.ACTION_SEARCH_SUMMARY_ENOUGH_MIN_CONTEXT_CHARS:
            return True
        top_score = max(float(score) for score, _item in selected)
        if top_score >= self.ACTION_SEARCH_SUMMARY_ENOUGH_MIN_TOP_SCORE:
            return True
        sessions = {
            str(item.get("session_id") or "").strip()
            for _score, item in selected
            if str(item.get("session_id") or "").strip()
        }
        dates = {
            self._format_ts(int(item.get("start_ts") or 0)).split(" ", 1)[0]
            for _score, item in selected
            if int(item.get("start_ts") or 0) > 0
        }
        return len(sessions) >= 2 or len(dates) >= 2

    @staticmethod
    def _contact_alias_values(contact: dict[str, Any]) -> tuple[str, ...]:
        values: list[str] = []
        for key in ("id", "contact_id", "username", "nickname", "remark", "display_name", "name", "assistim_id"):
            normalized = str(contact.get(key) or "").strip().casefold()
            if normalized and normalized not in values:
                values.append(normalized)
        return tuple(values)

    @staticmethod
    def _participant_alias_terms(participants: Sequence[_ResolvedParticipant]) -> tuple[str, ...]:
        values: list[str] = []
        for participant in list(participants or []):
            for alias in participant.aliases:
                if alias and alias not in values:
                    values.append(alias)
        return tuple(values)

    def _query_terms_from_plan(
        self,
        plan: ConversationRagSemanticPlan,
        participants: Sequence[_ResolvedParticipant],
    ) -> tuple[str, ...]:
        values = [str(plan.memory_query or plan.user_goal or "").strip().casefold()]
        values.extend(self._participant_alias_terms(participants))
        return tuple(value for value in dict.fromkeys(values) if value)

    def _filter_items_for_relation(
        self,
        items: list[dict[str, Any]],
        participants: Sequence[_ResolvedParticipant],
        relation: str,
    ) -> list[dict[str, Any]]:
        if not participants:
            return list(items or [])
        normalized_relation = str(relation or "separate").strip().lower()
        if normalized_relation == "together":
            return [
                item
                for item in list(items or [])
                if all(self._item_matches_participant(item, participant) for participant in participants)
            ]
        return [
            item
            for item in list(items or [])
            if any(self._item_matches_participant(item, participant) for participant in participants)
        ]

    def _filter_items_for_participant(
        self,
        items: list[dict[str, Any]],
        participant: _ResolvedParticipant,
    ) -> list[dict[str, Any]]:
        return [item for item in list(items or []) if self._item_matches_participant(item, participant)]

    def _item_matches_participant(self, item: dict[str, Any], participant: _ResolvedParticipant) -> bool:
        values = self._memory_item_identity_values(item)
        return self._any_value_matches(values, set(participant.aliases))

    @staticmethod
    def _memory_item_identity_values(item: dict[str, Any]) -> set[str]:
        values: set[str] = set()

        def add(value: object) -> None:
            normalized = str(value or "").strip().casefold()
            if normalized:
                values.add(normalized)

        add(item.get("session_id"))
        add(item.get("title"))
        for value in list(item.get("participants") or []):
            add(value)
        for value in list(item.get("keywords") or []):
            add(value)
        return values

    @staticmethod
    def _relation_confirmation_prompt(plan: ConversationRagSemanticPlan) -> str:
        mentions = "、".join(participant.mention for participant in plan.participants) or "这些联系人"
        return f"你是想分别查询 {mentions} 的聊天，还是查询他们共同参与的会话？请明确一下。"

    def _participant_confirmation_prompt(
        self,
        unresolved: Sequence[str],
        ambiguous: dict[str, tuple[dict[str, Any], ...]],
    ) -> str:
        lines: list[str] = []
        for mention in unresolved:
            lines.append(f"没有找到联系人：{mention}。请确认一下具体是谁。")
        for mention, matches in ambiguous.items():
            options = "；".join(self._contact_option_label(contact) for contact in matches[:5])
            lines.append(f"{mention} 匹配到多个联系人：{options}。请指定要查哪一个。")
        return "\n".join(lines) if lines else "联系人不明确，请补充具体对象。"

    @staticmethod
    def _contact_option_label(contact: dict[str, Any]) -> str:
        name = (
            str(contact.get("remark") or "").strip()
            or str(contact.get("display_name") or "").strip()
            or str(contact.get("nickname") or "").strip()
            or str(contact.get("username") or "").strip()
            or str(contact.get("id") or "").strip()
        )
        username = str(contact.get("username") or "").strip()
        contact_id = str(contact.get("id") or "").strip()
        detail = username or contact_id
        return f"{name}({detail})" if detail and detail != name else name

    @staticmethod
    def _no_memory_context_line(plan: ConversationRagSemanticPlan) -> str:
        query = " ".join(str(plan.memory_query or plan.user_goal or "").split())
        return f"未检索到匹配的聊天记忆。用户问题：{query or '聊天记录相关问题'}。请如实说明没有找到相关记录，不要编造。"

    @staticmethod
    def _normalize_rag_plan(raw_plan: Any, *, fallback_query: str) -> ConversationRagSemanticPlan | None:
        if raw_plan is None:
            return None
        if isinstance(raw_plan, ConversationRagSemanticPlan):
            return raw_plan
        return ConversationRagPlanner.coerce_plan(raw_plan, fallback_query=fallback_query)

    async def _expand_contact_alias_terms(self, text: str, terms: Sequence[str]) -> list[str]:
        exact_resolver = getattr(self._db, "resolve_contacts_cache_alias", None)
        fuzzy_search = getattr(self._db, "search_contacts", None)
        if not callable(exact_resolver) and not callable(fuzzy_search):
            return []
        expanded: list[str] = []
        candidates = self._contact_alias_candidates(text, terms)
        for candidate in candidates:
            matches: list[dict[str, Any]] = []
            if callable(exact_resolver):
                try:
                    matches.extend(list(await exact_resolver(candidate, limit=5)))
                except Exception:
                    logger.exception("Failed to resolve contact alias for RAG")
            if not matches and callable(fuzzy_search):
                try:
                    matches.extend(list(await fuzzy_search(candidate, limit=5)))
                except Exception:
                    logger.exception("Failed to search contact alias for RAG")
            for contact in matches:
                for value in (
                    contact.get("id"),
                    contact.get("username"),
                    contact.get("nickname"),
                    contact.get("remark"),
                    contact.get("display_name"),
                    contact.get("assistim_id"),
                ):
                    normalized = str(value or "").strip().casefold()
                    if normalized and normalized not in expanded and normalized not in terms:
                        expanded.append(normalized)
        return expanded


    def _contact_alias_candidates(self, text: str, terms: Sequence[str]) -> list[str]:
        candidates: list[str] = []
        token_pool = list(dict.fromkeys([*self._tokenize_for_rag(text), *list(terms or [])]))
        token_pool.sort(key=len, reverse=True)
        for term in token_pool:
            normalized_term = str(term or "").strip().casefold()
            if not normalized_term:
                continue
            if len(normalized_term) < 2:
                continue
            if normalized_term not in candidates:
                candidates.append(normalized_term)
            if len(candidates) >= 6:
                break
        return candidates

    async def build_ai_chat_memory_context(
        self,
        query_text: str,
        *,
        previous_messages: Sequence[Any] | None = None,
    ) -> ConversationMemoryContext:
        """Return formatted local memory lines when the prompt asks about chat history."""
        confirmed_query_text = self._confirmed_pending_query_text(query_text, previous_messages=previous_messages)
        query = self._parse_query(confirmed_query_text or query_text, confirmed=bool(confirmed_query_text))
        if query.requires_confirmation:
            return ConversationMemoryContext(
                lines=(),
                query_kind=query.query_kind,
                requires_confirmation=True,
                confirmation_prompt=self._confirmation_prompt(query.text),
                pending_query_text=query.text,
            )
        if not query.query_kind:
            return ConversationMemoryContext(lines=(), query_kind="")
        try:
            query_vector = await self._vector_index.encode_query(
                query=query.text,
                terms=query.terms,
                contact_aliases=(),
            )
        except Exception:
            logger.exception("Failed to encode local conversation memory query")
            return ConversationMemoryContext(lines=(), query_kind=query.query_kind)
        items = await self._search_ai_summary_memory(
            query_vector=query_vector,
            start_ts=query.start_ts,
            end_ts=query.end_ts,
            limit=self.SEARCH_CANDIDATE_LIMIT,
        )

        ranked = self._rank_items(items, query)
        if query.terms and not ranked and len(items) >= self.SEARCH_CANDIDATE_LIMIT:
            expanded_items = await self._search_ai_summary_memory(
                query_vector=query_vector,
                start_ts=query.start_ts,
                end_ts=query.end_ts,
                limit=self.EXPANDED_SEARCH_CANDIDATE_LIMIT,
            )
            if len(expanded_items) > len(items):
                ranked = self._rank_items(expanded_items, query)
        lines = tuple(self._format_item(item) for _score, item in ranked[: self.CONTEXT_RESULT_LIMIT])
        return ConversationMemoryContext(lines=lines, query_kind=query.query_kind)

    async def build_context_for_structured_query(
        self,
        *,
        query_text: str,
        start_ts: int | None,
        end_ts: int | None,
        terms: Sequence[str] | None = None,
        participant_ids: Sequence[str] | None = None,
        participant_aliases: Sequence[str] | None = None,
        query_kind: str = "history",
    ) -> ConversationMemoryContext:
        """Return memory context for an already validated action query."""
        query = _MemoryQuery(
            text=" ".join(str(query_text or "").split()),
            start_ts=start_ts,
            end_ts=end_ts,
            terms=tuple(str(term or "").strip().lower() for term in list(terms or []) if str(term or "").strip()),
            query_kind=str(query_kind or "history").strip() or "history",
        )
        try:
            query_vector = await self._vector_index.encode_query(
                query=query.text,
                terms=query.terms,
                contact_aliases=participant_aliases or (),
            )
        except Exception:
            logger.exception("Failed to encode structured local conversation memory query")
            return ConversationMemoryContext(lines=(), query_kind=query.query_kind)
        items = await self._search_ai_summary_memory(
            query_vector=query_vector,
            start_ts=query.start_ts,
            end_ts=query.end_ts,
            limit=self.SEARCH_CANDIDATE_LIMIT,
        )

        ranked = self._rank_items(items, query)
        if query.terms and not ranked and len(items) >= self.SEARCH_CANDIDATE_LIMIT:
            expanded_items = await self._search_ai_summary_memory(
                query_vector=query_vector,
                start_ts=query.start_ts,
                end_ts=query.end_ts,
                limit=self.EXPANDED_SEARCH_CANDIDATE_LIMIT,
            )
            if len(expanded_items) > len(items):
                ranked = self._rank_items(expanded_items, query)
        lines = tuple(self._format_item(item) for _score, item in ranked[: self.CONTEXT_RESULT_LIMIT])
        if not lines:
            lines = tuple(
                await self._message_fallback_lines(
                    query,
                    participant_ids=participant_ids,
                    participant_aliases=participant_aliases,
                )
            )
        return ConversationMemoryContext(lines=lines, query_kind=query.query_kind)

    async def search_for_action(
        self,
        *,
        question: str,
        participants: Sequence[Any] | None = None,
        participant_match: str = "any",
        time_scope: dict[str, Any] | None = None,
        keywords: Sequence[str] | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Return structured memory search results for AI action workflow."""
        normalized_limit = max(1, min(20, int(limit or 8)))
        query_text = " ".join(str(question or "").split())
        keyword_terms = tuple(
            str(term or "").strip().casefold()
            for term in list(keywords or [])
            if str(term or "").strip()
        )
        resolved_participants = await self._resolve_action_participants(participants or ())
        participant_aliases = self._participant_alias_terms(resolved_participants)
        start_ts, end_ts = self._action_time_bounds(time_scope or {})
        if not query_text:
            query_text = " ".join([*keyword_terms, *(participant.display_name for participant in resolved_participants)]).strip()
        if not query_text:
            return self._empty_action_search_result(question=question, start_ts=start_ts, end_ts=end_ts)

        query_terms = tuple(
            dict.fromkeys(
                [
                    *self._tokenize_for_rag(query_text),
                    *keyword_terms,
                    *participant_aliases,
                ]
            )
        )[:24]
        normalized_participant_match = str(participant_match or "any").strip().lower() or "any"
        cache_index_version = await self._action_memory_index_version()
        cache_key = _action_memory_search_cache_key(
            question=query_text,
            participants=resolved_participants,
            participant_match=normalized_participant_match,
            start_ts=start_ts,
            end_ts=end_ts,
            keywords=keyword_terms,
            terms=query_terms,
            limit=normalized_limit,
            index_version=cache_index_version,
            search_version=self.ACTION_MEMORY_SEARCH_VERSION,
            model_id=self._vector_index.model_id,
        )
        if cache_key:
            cached = self._action_cache.get(self.ACTION_MEMORY_SEARCH_CACHE_NAMESPACE, cache_key)
            if isinstance(cached, dict):
                cached["cache_hit"] = True
                cached["cache_namespace"] = self.ACTION_MEMORY_SEARCH_CACHE_NAMESPACE
                cached["cache_index_version"] = cache_index_version
                cached["cache_search_version"] = self.ACTION_MEMORY_SEARCH_VERSION
                return cached

        try:
            query_vector = await self._vector_index.encode_query(
                query=query_text,
                terms=query_terms,
                contact_aliases=participant_aliases,
            )
        except Exception:
            logger.exception("Failed to encode AI action memory query")
            return self._empty_action_search_result(question=query_text, start_ts=start_ts, end_ts=end_ts)

        candidate_limit = max(self.RAG_CANDIDATE_LIMIT, normalized_limit * 8)
        items = await self._search_ai_summary_memory(
            query_vector=query_vector,
            start_ts=start_ts,
            end_ts=end_ts,
            limit=candidate_limit,
        )
        relation = "together" if str(participant_match or "").strip().lower() == "all" else "separate"
        filtered = self._filter_items_for_relation(items, resolved_participants, relation)
        memory_query = _MemoryQuery(
            text=query_text,
            start_ts=start_ts,
            end_ts=end_ts,
            terms=query_terms,
            query_kind="action_memory_search",
        )
        ranked = await self._rank_rag_items(filtered, memory_query, query_vector=query_vector)
        matched = [(score, item) for score, item in ranked if score >= self.RAG_MIN_SCORE]
        selected = matched[:normalized_limit]
        results = [
            self._action_memory_result(item, score=score)
            for score, item in selected
        ]
        context_lines = [
            line
            for line in (self._format_item(item) for _score, item in selected)
            if line
        ]
        summary_enough = self._action_summary_search_is_enough(selected, context_lines)
        fallback_lines: list[str] = []
        if not summary_enough:
            remaining = max(1, normalized_limit - len(context_lines))
            fallback_lines = (
                await self._message_fallback_lines(
                    memory_query,
                    participant_ids=participant_aliases,
                    participant_aliases=participant_aliases,
                )
            )[:remaining]
        fallback_results = [
            self._action_message_fallback_result(line, index=index)
            for index, line in enumerate(fallback_lines, start=1)
        ]
        if fallback_lines:
            context_lines.extend(line for line in fallback_lines if line)
            results.extend(fallback_results)
        output = {
            "results": results,
            "preview": results[:3],
            "context_lines": context_lines,
            "result_count": len(matched) + len(fallback_results),
            "truncated": len(matched) > len(selected),
            "fallback_used": bool(fallback_results),
            "summary_result_count": len(matched),
            "message_fallback_count": len(fallback_results),
            "cache_hit": False,
            "cache_namespace": self.ACTION_MEMORY_SEARCH_CACHE_NAMESPACE,
            "cache_search_version": self.ACTION_MEMORY_SEARCH_VERSION,
            "query": {
                "question": query_text,
                "terms": list(query_terms),
                "start_ts": start_ts,
                "end_ts": end_ts,
                "participant_match": normalized_participant_match,
                "participants": [
                    {
                        "mention": participant.mention,
                        "display_name": participant.display_name,
                        "aliases": list(participant.aliases),
                    }
                    for participant in resolved_participants
                ],
            },
        }
        if cache_index_version:
            output["cache_index_version"] = cache_index_version
        if cache_key and not fallback_results:
            self._action_cache.set(self.ACTION_MEMORY_SEARCH_CACHE_NAMESPACE, cache_key, output)
        return output

    async def _action_memory_index_version(self) -> str:
        get_version = getattr(self._db, "get_conversation_memory_index_version", None)
        if not callable(get_version):
            return ""
        try:
            return str(await get_version() or "").strip()
        except Exception:
            logger.exception("Failed to resolve local AI memory index version")
            return ""

    def _parse_query(self, query_text: str, *, confirmed: bool = False) -> _MemoryQuery:
        text = " ".join(str(query_text or "").split())
        if not text:
            return _MemoryQuery(text="", start_ts=None, end_ts=None, terms=(), query_kind="")
        lower = text.lower()
        terms = tuple(self._extract_terms(text))
        if not self._has_memory_reference(lower) and not self._has_direct_history_intent(lower):
            return _MemoryQuery(text=text, start_ts=None, end_ts=None, terms=terms, query_kind="")
        if not confirmed and not self._is_explicit_memory_query(lower, terms=terms):
            return _MemoryQuery(
                text=text,
                start_ts=None,
                end_ts=None,
                terms=terms,
                query_kind="needs_confirmation",
                requires_confirmation=True,
            )

        start_dt, end_dt, kind = self._time_range(text)
        return _MemoryQuery(
            text=text,
            start_ts=int(start_dt.timestamp()) if start_dt is not None else None,
            end_ts=int(end_dt.timestamp()) if end_dt is not None else None,
            terms=terms,
            query_kind=kind or "history",
        )

    def _has_direct_history_intent(self, text: str) -> bool:
        return any(token in text for token in self._HISTORY_INTENTS)

    def _has_memory_reference(self, text: str) -> bool:
        if any(token in text for token in self._MEMORY_REFERENCES):
            return True
        return bool(re.search(r"(?:我|我们)?(?:和|跟|与)[a-z0-9_\-\u4e00-\u9fff]{2,}(?:聊|谈)", text))

    def _is_explicit_memory_query(self, text: str, *, terms: tuple[str, ...]) -> bool:
        has_time = any(token in text for token in self._TIME_HINTS)
        has_target = bool(terms)
        has_lookup_action = any(token in text for token in self._LOOKUP_ACTIONS)
        if self._has_direct_history_intent(text) and (has_time or has_target):
            return True
        if has_lookup_action and self._has_memory_reference(text) and (has_time or has_target):
            return True
        return False

    def _confirmed_pending_query_text(
        self,
        query_text: str,
        *,
        previous_messages: Sequence[Any] | None,
    ) -> str:
        current_text = " ".join(str(query_text or "").split())
        if not self._is_affirmative_confirmation(current_text):
            return ""
        for message in reversed(list(previous_messages or [])[-6:]):
            role = self._message_role(message)
            if role == "user":
                return ""
            if role != "assistant":
                continue
            pending_query = self._message_pending_memory_query(message)
            if not pending_query:
                return ""
            return f"{pending_query} {current_text}".strip()
        return ""

    def _is_affirmative_confirmation(self, text: str) -> bool:
        normalized = " ".join(str(text or "").lower().split())
        if not normalized:
            return False
        if any(token in normalized for token in self._NEGATIVE_CONFIRMATIONS):
            return False
        return any(token in normalized for token in self._AFFIRMATIVE_CONFIRMATIONS)

    @staticmethod
    def _message_role(message: Any) -> str:
        role = getattr(message, "role", "")
        value = getattr(role, "value", role)
        return str(value or "").strip().lower()

    @staticmethod
    def _message_pending_memory_query(message: Any) -> str:
        extra = getattr(message, "extra", None)
        if not isinstance(extra, dict):
            return ""
        data = extra.get("memory_confirmation")
        if not isinstance(data, dict):
            return ""
        return str(data.get("query") or "").strip()

    @staticmethod
    def _confirmation_prompt(query_text: str) -> str:
        preview = " ".join(str(query_text or "").split())
        if len(preview) > 80:
            preview = preview[:80].rstrip() + "..."
        return (
            "你是想让我查询本机聊天记录来回答这个问题吗？\n"
            f"待确认的问题：{preview or '聊天记录相关问题'}\n"
            "请回复“确认”后我再查询；也可以同时补充联系人或时间范围。"
        )

    def _time_range(self, text: str) -> tuple[datetime | None, datetime | None, str]:
        start_dt, end_dt, kind, _ = self._time_range_with_hint(text, default_recent=True)
        return start_dt, end_dt, kind

    def _time_range_with_hint(
        self,
        text: str,
        *,
        default_recent: bool,
    ) -> tuple[datetime | None, datetime | None, str, bool]:
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if "今天" in text:
            return today, today + timedelta(days=1), "today", True
        if "昨天" in text:
            start = today - timedelta(days=1)
            return start, today, "yesterday", True
        if "上周" in text:
            start = today - timedelta(days=today.weekday() + 7)
            return start, start + timedelta(days=7), "last_week", True
        if "这周" in text or "本周" in text:
            start = today - timedelta(days=today.weekday())
            return start, start + timedelta(days=7), "this_week", True
        if "一周" in text or "最近" in text:
            return now - timedelta(days=self.DEFAULT_LOOKBACK_DAYS), now + timedelta(seconds=1), "recent", True
        if default_recent:
            return now - timedelta(days=self.DEFAULT_LOOKBACK_DAYS), now + timedelta(seconds=1), "recent", False
        return None, None, "", False

    def _rank_items(
        self,
        items: list[dict[str, Any]],
        query: _MemoryQuery,
    ) -> list[tuple[float, dict[str, Any]]]:
        ranked: list[tuple[float, dict[str, Any]]] = []
        for item in list(items or []):
            text_blob = self._item_blob(item)
            score = 1.0
            for term in query.terms:
                if term and term in text_blob:
                    score += 2.0
            if query.terms and score <= 1.0:
                continue
            end_ts = int(item.get("end_ts") or 0)
            score += min(1.0, max(0.0, end_ts / max(1, int(datetime.now().timestamp()))) * 0.01)
            ranked.append((score, item))
        ranked.sort(key=lambda pair: (pair[0], int(pair[1].get("end_ts") or 0)), reverse=True)
        return ranked

    async def _rank_rag_items(
        self,
        items: list[dict[str, Any]],
        query: _MemoryQuery,
        *,
        query_vector: DenseVector | None = None,
    ) -> list[tuple[float, dict[str, Any]]]:
        candidates = await self._prepare_rag_candidates(items)
        if not candidates:
            return []
        if query_vector is None:
            query_vector = await self._vector_index.encode_query(
                query=query.text,
                terms=query.terms,
                contact_aliases=(),
            )

        document_frequency: dict[str, int] = {}
        for candidate in candidates:
            combined = (
                candidate["participant_terms"]
                | candidate["keyword_terms"]
                | candidate["title_terms"]
                | candidate["text_terms"]
            )
            for term in combined:
                document_frequency[term] = int(document_frequency.get(term, 0)) + 1

        ranked: list[tuple[float, dict[str, Any]]] = []
        now_ts = int(datetime.now().timestamp())
        total_docs = max(1, len(candidates))
        for candidate in candidates:
            score = 0.0
            for term in query.terms:
                idf = 1.0 + math.log((1.0 + total_docs) / (1.0 + float(document_frequency.get(term, 0))))
                score += self._candidate_term_score(candidate, term) * idf
            vector_score = query_vector.cosine(candidate["vector"])
            score += vector_score * 3.2
            if query.text and query.text.casefold() in candidate["text_blob"]:
                score += 1.2
            if query.text and query.text.casefold() in candidate["title_blob"]:
                score += 1.4
            score += min(
                float(candidate["item"].get("ann_match_count") or 0),
                float(self._ann_index.band_count),
            ) * 0.18
            if score <= 0.0:
                continue
            end_ts = int(candidate["item"].get("end_ts") or 0)
            age_days = max(0.0, float(now_ts - end_ts) / 86400.0) if end_ts > 0 else 365.0
            score += max(0.0, 0.35 - min(age_days, 45.0) / 180.0)
            ranked.append((score, candidate["item"]))
        ranked.sort(key=lambda pair: (pair[0], int(pair[1].get("end_ts") or 0)), reverse=True)
        return ranked

    async def _prepare_rag_candidates(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for item in list(items or []):
            candidate = self._item_terms(item)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _item_terms(self, item: dict[str, Any]) -> dict[str, Any] | None:
        title = str(item.get("title") or "")
        text = str(item.get("text") or "")
        keyword_values = [str(value or "") for value in list(item.get("keywords") or [])]
        participant_values = [str(value or "") for value in list(item.get("participants") or [])]
        cache_key = self._item_vector_cache_key(item)
        if cache_key not in self._item_vector_cache:
            raw_vector = list(item.get("embedding_vector") or [])
            if not raw_vector:
                return None
            try:
                self._item_vector_cache[cache_key] = DenseVector(values=tuple(float(value) for value in raw_vector))
            except (TypeError, ValueError):
                return None
        return {
            "item": item,
            "title_blob": title.casefold(),
            "text_blob": text.casefold(),
            "title_terms": set(self._tokenize_for_rag(title)),
            "text_terms": set(self._tokenize_for_rag(text)),
            "keyword_terms": set(
                token
                for value in keyword_values
                for token in {value.casefold(), *self._tokenize_for_rag(value)}
                if token
            ),
            "participant_terms": set(
                token
                for value in participant_values
                for token in {value.casefold(), *self._tokenize_for_rag(value)}
                if token
            ),
            "vector": self._item_vector_cache[cache_key],
        }

    @staticmethod
    def _item_vector_cache_key(item: dict[str, Any]) -> str:
        return "|".join(
            [
                str(item.get("session_id") or ""),
                str(item.get("source_type") or ""),
                str(item.get("source_id") or ""),
                str(item.get("source_version") or ""),
                str(item.get("embedding_model") or ""),
                str(item.get("embedding_content_hash") or ""),
            ]
        )

    def _candidate_term_score(self, candidate: dict[str, Any], term: str) -> float:
        if term in candidate["participant_terms"]:
            return 3.4
        if term in candidate["keyword_terms"]:
            return 2.8
        if term in candidate["title_terms"]:
            return 2.3
        if term in candidate["text_terms"]:
            return 1.5
        if term and term in candidate["title_blob"]:
            return 1.2
        if term and term in candidate["text_blob"]:
            return 0.8
        return 0.0

    def _item_blob(self, item: dict[str, Any]) -> str:
        values: list[str] = [
            str(item.get("title") or ""),
            str(item.get("text") or ""),
            " ".join(str(value or "") for value in list(item.get("keywords") or [])),
            " ".join(str(value or "") for value in list(item.get("participants") or [])),
        ]
        return " ".join(values).lower()

    async def _message_fallback_lines(
        self,
        query: _MemoryQuery,
        *,
        participant_ids: Sequence[str] | None,
        participant_aliases: Sequence[str] | None,
    ) -> list[str]:
        get_messages = getattr(self._db, "get_messages", None)
        if not callable(get_messages):
            return await self._search_message_lines(query)
        sessions = await self._candidate_message_sessions(
            query,
            participant_ids=participant_ids,
            participant_aliases=participant_aliases,
        )
        if not sessions:
            return await self._search_message_lines(query)
        lines: list[str] = []
        normalized_participant_ids = {
            str(participant_id or "").strip().casefold()
            for participant_id in list(participant_ids or [])
            if str(participant_id or "").strip()
        }
        normalized_participant_aliases = {
            str(alias or "").strip().casefold()
            for alias in list(participant_aliases or [])
            if str(alias or "").strip()
        }
        has_participant_filter = bool(normalized_participant_ids or normalized_participant_aliases)
        for session in sessions[: self.MESSAGE_FALLBACK_SESSION_LIMIT]:
            session_id = str(getattr(session, "session_id", "") or "").strip()
            if not session_id:
                continue
            is_direct_participant_session = has_participant_filter and self._is_direct_session(session)
            try:
                messages = list(await get_messages(session_id, limit=self.MESSAGE_FALLBACK_PER_SESSION_LIMIT))
            except Exception:
                logger.exception("Failed to query fallback local messages")
                continue
            for message in messages:
                if not self._message_in_time_range(message, query):
                    continue
                if (
                    has_participant_filter
                    and not is_direct_participant_session
                    and not self._message_matches_participants(
                        message,
                        participant_ids=normalized_participant_ids,
                        participant_aliases=normalized_participant_aliases,
                    )
                ):
                    continue
                if not has_participant_filter and not self._message_matches_terms(message, query.terms):
                    continue
                line = self._format_message_line(message, session=session)
                if line and line not in lines:
                    lines.append(line)
                if len(lines) >= self.MESSAGE_FALLBACK_RESULT_LIMIT:
                    return lines
        return lines

    async def _candidate_message_sessions(
        self,
        query: _MemoryQuery,
        *,
        participant_ids: Sequence[str] | None,
        participant_aliases: Sequence[str] | None,
    ) -> list[Any]:
        get_all_sessions = getattr(self._db, "get_all_sessions", None)
        if not callable(get_all_sessions):
            return []
        try:
            sessions = list(await get_all_sessions())
        except Exception:
            logger.exception("Failed to query fallback local sessions")
            return []
        normalized_participant_ids = {
            str(participant_id or "").strip().casefold()
            for participant_id in list(participant_ids or [])
            if str(participant_id or "").strip()
        }
        normalized_participant_aliases = {
            str(alias or "").strip().casefold()
            for alias in list(participant_aliases or [])
            if str(alias or "").strip()
        }
        terms = {str(term or "").strip().casefold() for term in query.terms if str(term or "").strip()}
        candidates: list[Any] = []
        for session in sessions:
            session_values = self._session_identity_values(session)
            if normalized_participant_ids and (normalized_participant_ids & session_values):
                candidates.append(session)
                continue
            if normalized_participant_aliases and self._any_value_matches(session_values, normalized_participant_aliases):
                candidates.append(session)
                continue
            if terms and any(term and any(term in value for value in session_values) for term in terms):
                candidates.append(session)
        candidates.sort(key=lambda item: getattr(item, "last_message_time", None) or getattr(item, "updated_at", None) or datetime.min, reverse=True)
        return candidates

    async def _search_message_lines(self, query: _MemoryQuery) -> list[str]:
        search_messages = getattr(self._db, "search_messages", None)
        if not callable(search_messages):
            return []
        lines: list[str] = []
        for term in query.terms:
            try:
                messages = list(await search_messages(term, limit=self.MESSAGE_FALLBACK_RESULT_LIMIT))
            except Exception:
                logger.exception("Failed to search fallback local messages")
                continue
            for message in messages:
                if not self._message_in_time_range(message, query):
                    continue
                line = self._format_message_line(message, session=None)
                if line and line not in lines:
                    lines.append(line)
                if len(lines) >= self.MESSAGE_FALLBACK_RESULT_LIMIT:
                    return lines
        return lines

    async def _rag_message_fallback_lines(self, query: _MemoryQuery) -> list[str]:
        sessions = await self._candidate_message_sessions(
            query,
            participant_ids=None,
            participant_aliases=None,
        )
        get_messages = getattr(self._db, "get_messages", None)
        if not callable(get_messages):
            return []

        ranked: list[tuple[float, str]] = []
        for session in sessions[: self.MESSAGE_FALLBACK_SESSION_LIMIT]:
            session_id = str(getattr(session, "session_id", "") or "").strip()
            if not session_id:
                continue
            session_values = self._session_identity_values(session)
            try:
                messages = list(await get_messages(session_id, limit=self.MESSAGE_FALLBACK_PER_SESSION_LIMIT))
            except Exception:
                logger.exception("Failed to query RAG fallback local messages")
                continue
            for message in messages:
                if not self._message_in_time_range(message, query):
                    continue
                score = self._rag_message_score(message, session=session, query=query, session_values=session_values)
                if score <= 0.0:
                    continue
                line = self._format_message_line(message, session=session)
                if line:
                    ranked.append((score, line))

        if ranked:
            ranked.sort(key=lambda pair: pair[0], reverse=True)
            lines: list[str] = []
            for _score, line in ranked:
                if line not in lines:
                    lines.append(line)
                if len(lines) >= self.RAG_MESSAGE_RESULT_LIMIT:
                    return lines
            return lines

        return await self._search_message_lines(query)

    def _rag_message_score(
        self,
        message: Any,
        *,
        session: Any,
        query: _MemoryQuery,
        session_values: set[str],
    ) -> float:
        del session
        content = str(getattr(message, "content", "") or "").casefold()
        if not content:
            return 0.0
        sender_values = self._message_sender_identity_values(message)
        score = 0.0
        for term in query.terms:
            normalized_term = str(term or "").strip().casefold()
            if not normalized_term:
                continue
            if normalized_term in session_values:
                score += 1.2
            elif self._any_value_matches(session_values, {normalized_term}):
                score += 1.0
            if normalized_term in sender_values or self._any_value_matches(sender_values, {normalized_term}):
                score += 0.8
            if normalized_term in content:
                score += 1.6
        if query.text and str(query.text).casefold() in content:
            score += 1.0
        return score

    @staticmethod
    def _message_in_time_range(message: Any, query: _MemoryQuery) -> bool:
        timestamp = getattr(message, "timestamp", None)
        if timestamp is None:
            return True
        try:
            ts = int(timestamp.timestamp() if hasattr(timestamp, "timestamp") else float(timestamp))
        except (TypeError, ValueError, OSError):
            return True
        if query.start_ts is not None and ts < int(query.start_ts):
            return False
        if query.end_ts is not None and ts > int(query.end_ts):
            return False
        return True

    def _message_matches_participants(
        self,
        message: Any,
        *,
        participant_ids: set[str],
        participant_aliases: set[str],
    ) -> bool:
        if bool(getattr(message, "is_self", False)):
            return True
        values = self._message_sender_identity_values(message)
        return bool((participant_ids and participant_ids & values) or self._any_value_matches(values, participant_aliases))

    @staticmethod
    def _message_matches_terms(message: Any, terms: Sequence[str]) -> bool:
        text = str(getattr(message, "content", "") or "").casefold()
        return any(str(term or "").strip().casefold() in text for term in terms if str(term or "").strip())

    @staticmethod
    def _is_direct_session(session: Any) -> bool:
        return str(getattr(session, "session_type", "") or "").strip().casefold() == "direct"

    def _session_identity_values(self, session: Any) -> set[str]:
        values: set[str] = set()

        def add(value: object) -> None:
            normalized = str(value or "").strip().casefold()
            if normalized:
                values.add(normalized)

        add(getattr(session, "session_id", ""))
        add(getattr(session, "name", ""))
        display_name = getattr(session, "display_name", None)
        if callable(display_name):
            add(display_name())
        for participant_id in list(getattr(session, "participant_ids", []) or []):
            add(participant_id)

        extra = getattr(session, "extra", {}) or {}
        if isinstance(extra, dict):
            for key in (
                "counterpart_id",
                "counterpart_name",
                "counterpart_nickname",
                "counterpart_username",
                "counterpart_display_name",
                "last_message_sender_id",
                "last_message_sender_name",
            ):
                add(extra.get(key))
            for member in list(extra.get("members") or []):
                if not isinstance(member, dict):
                    continue
                for key in ("id", "user_id", "display_name", "remark", "group_nickname", "nickname", "username"):
                    add(member.get(key))
        return values

    @staticmethod
    def _message_sender_identity_values(message: Any) -> set[str]:
        values: set[str] = set()

        def add(value: object) -> None:
            normalized = str(value or "").strip().casefold()
            if normalized:
                values.add(normalized)

        add(getattr(message, "sender_id", ""))
        extra = getattr(message, "extra", {}) or {}
        if isinstance(extra, dict):
            for key in ("sender_name", "sender_nickname", "sender_username", "sender_display_name"):
                add(extra.get(key))
        return values

    @staticmethod
    def _any_value_matches(values: set[str], aliases: set[str]) -> bool:
        for alias in aliases:
            if not alias:
                continue
            for value in values:
                if alias == value or alias in value:
                    return True
        return False

    def _format_message_line(self, message: Any, *, session: Any | None) -> str:
        content = " ".join(str(getattr(message, "content", "") or "").split())
        if not content:
            return ""
        timestamp = getattr(message, "timestamp", None)
        if timestamp is not None and hasattr(timestamp, "strftime"):
            time_text = timestamp.strftime("%Y-%m-%d %H:%M")
        else:
            time_text = ""
        session_name = ""
        if session is not None:
            display_name = getattr(session, "display_name", None)
            session_name = str(display_name() if callable(display_name) else getattr(session, "name", "") or "").strip()
        speaker = "我" if bool(getattr(message, "is_self", False)) else str(getattr(message, "sender_id", "") or "对方")
        parts = []
        if time_text:
            parts.append(f"[{time_text}]")
        if session_name:
            parts.append(f"会话：{session_name}")
        parts.append(f"{speaker}：{self._clip(content, self.CONTEXT_LINE_MAX_CHARS)}")
        return "；".join(parts)

    def _format_item(self, item: dict[str, Any]) -> str:
        start_label = self._format_ts(int(item.get("start_ts") or 0))
        end_label = self._format_ts(int(item.get("end_ts") or 0), time_only=True)
        participants = "、".join(list(item.get("participants") or [])[:4])
        text = self._clip(str(item.get("text") or ""), self.CONTEXT_LINE_MAX_CHARS)
        title = str(item.get("title") or "").strip()
        parts = [f"[{start_label}-{end_label}]"]
        if title:
            parts.append(title)
        if participants:
            parts.append(f"参与者：{participants}")
        if text:
            parts.append(f"摘要：{text}")
        return "；".join(parts)

    @staticmethod
    def _format_ts(value: int, *, time_only: bool = False) -> str:
        try:
            fmt = "%H:%M" if time_only else "%Y-%m-%d %H:%M"
            return datetime.fromtimestamp(int(value or 0)).strftime(fmt)
        except (OSError, ValueError):
            return str(int(value or 0))

    def _extract_terms(self, text: str) -> list[str]:
        normalized = text.lower()
        terms: list[str] = []
        for matched in re.findall(r"(?:我)?(?:和|跟|与)([a-z0-9_\-\u4e00-\u9fff]{2,})", normalized):
            cleaned = re.sub(r"(聊了什么|聊过什么|聊什么|聊啥|谈了什么|谈过什么|聊天记录|说过什么|提到什么|总结|回顾)$", "", matched).strip()
            cleaned = cleaned.rstrip("的").strip()
            if cleaned and cleaned not in self._STOP_TERMS and cleaned not in terms:
                terms.append(cleaned)
        normalized = re.sub(
            r"(聊了什么|聊过什么|聊什么|聊啥|谈了什么|谈过什么|聊天记录|说过什么|提到什么|总结|回顾|今天|昨天|这周|本周|上周|最近|一周|帮我|请|吗|呢|？|\?)",
            " ",
            normalized,
        )
        tokens = re.findall(r"[a-z0-9_\-\u4e00-\u9fff]{2,}", normalized)
        for token in tokens:
            if token in self._STOP_TERMS:
                continue
            if token not in terms:
                terms.append(token)
            if len(terms) >= 6:
                break
        return terms

    def _extract_rag_terms(self, text: str) -> list[str]:
        normalized = " ".join(str(text or "").casefold().split())
        segmented = re.sub(r"[，。！？、；：,.!?;:/\\]+", " ", normalized)
        segmented = re.sub(r"[的了过吗呢呀吧啊嘛是]", " ", segmented)
        terms: list[str] = []
        for matched in re.findall(r"(?:我)?(?:和|跟|与)([a-z0-9_\-\u4e00-\u9fff]{2,})", normalized):
            cleaned = matched.rstrip("的呢吗呀吧都").strip()
            if cleaned and cleaned not in self._STOP_TERMS and cleaned not in terms:
                terms.append(cleaned)
        for token in self._tokenize_for_rag(segmented):
            if token in self._STOP_TERMS:
                continue
            if token not in terms:
                terms.append(token)
            if len(terms) >= 16:
                break
        return terms

    @staticmethod
    def _tokenize_for_rag(text: str) -> list[str]:
        tokens: list[str] = []
        for part in re.findall(r"[a-z0-9_\-]+|[\u4e00-\u9fff]{2,}", str(text or "").casefold()):
            normalized = part.strip()
            if not normalized:
                continue
            if re.fullmatch(r"[a-z0-9_\-]+", normalized):
                if normalized not in tokens:
                    tokens.append(normalized)
                continue
            if len(normalized) <= 4:
                if normalized not in tokens:
                    tokens.append(normalized)
                continue
            for size in (2, 3, 4):
                for index in range(0, len(normalized) - size + 1):
                    token = normalized[index : index + size].strip()
                    if token and token not in tokens:
                        tokens.append(token)
        return tokens

    @staticmethod
    def _query_has_enough_signal(terms: Sequence[str]) -> bool:
        meaningful = [str(term or "").strip() for term in list(terms or []) if str(term or "").strip()]
        if len(meaningful) >= 2:
            return True
        return any(len(term) >= 3 for term in meaningful)

    @staticmethod
    def _clip(value: str, max_chars: int) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

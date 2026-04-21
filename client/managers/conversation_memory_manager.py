from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Sequence

from client.core import logging
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


class ConversationMemoryManager:
    """Search local conversation-memory summaries for AI assistant history questions."""

    DEFAULT_LOOKBACK_DAYS = 7
    SEARCH_CANDIDATE_LIMIT = 40
    EXPANDED_SEARCH_CANDIDATE_LIMIT = 200
    CONTEXT_RESULT_LIMIT = 6
    CONTEXT_LINE_MAX_CHARS = 260
    MESSAGE_FALLBACK_SESSION_LIMIT = 5
    MESSAGE_FALLBACK_PER_SESSION_LIMIT = 40
    MESSAGE_FALLBACK_RESULT_LIMIT = 8

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

    def __init__(self, db: Database | None = None) -> None:
        self._db = db or get_database()

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
        list_items = getattr(self._db, "list_conversation_memory_items", None)
        if list_items is None:
            return ConversationMemoryContext(lines=(), query_kind=query.query_kind)
        try:
            items = await list_items(
                source_type="summary",
                start_ts=query.start_ts,
                end_ts=query.end_ts,
                limit=self.SEARCH_CANDIDATE_LIMIT,
            )
        except Exception:
            logger.exception("Failed to query local conversation memory")
            return ConversationMemoryContext(lines=(), query_kind=query.query_kind)

        ranked = self._rank_items(items, query)
        if query.terms and not ranked and len(items) >= self.SEARCH_CANDIDATE_LIMIT:
            try:
                expanded_items = await list_items(
                    source_type="summary",
                    start_ts=query.start_ts,
                    end_ts=query.end_ts,
                    limit=self.EXPANDED_SEARCH_CANDIDATE_LIMIT,
                )
            except Exception:
                logger.exception("Failed to query expanded local conversation memory")
                expanded_items = []
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
        list_items = getattr(self._db, "list_conversation_memory_items", None)
        if list_items is None:
            return ConversationMemoryContext(lines=(), query_kind=query.query_kind)
        try:
            items = await list_items(
                source_type="summary",
                start_ts=query.start_ts,
                end_ts=query.end_ts,
                limit=self.SEARCH_CANDIDATE_LIMIT,
            )
        except Exception:
            logger.exception("Failed to query local conversation memory")
            return ConversationMemoryContext(lines=(), query_kind=query.query_kind)

        ranked = self._rank_items(items, query)
        if query.terms and not ranked and len(items) >= self.SEARCH_CANDIDATE_LIMIT:
            try:
                expanded_items = await list_items(
                    source_type="summary",
                    start_ts=query.start_ts,
                    end_ts=query.end_ts,
                    limit=self.EXPANDED_SEARCH_CANDIDATE_LIMIT,
                )
            except Exception:
                logger.exception("Failed to query expanded local conversation memory")
                expanded_items = []
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
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if "今天" in text:
            return today, today + timedelta(days=1), "today"
        if "昨天" in text:
            start = today - timedelta(days=1)
            return start, today, "yesterday"
        if "上周" in text:
            start = today - timedelta(days=today.weekday() + 7)
            return start, start + timedelta(days=7), "last_week"
        if "这周" in text or "本周" in text:
            start = today - timedelta(days=today.weekday())
            return start, start + timedelta(days=7), "this_week"
        if "一周" in text or "最近" in text:
            return now - timedelta(days=self.DEFAULT_LOOKBACK_DAYS), now + timedelta(seconds=1), "recent"
        return now - timedelta(days=self.DEFAULT_LOOKBACK_DAYS), now + timedelta(seconds=1), "recent"

    def _rank_items(self, items: list[dict[str, Any]], query: _MemoryQuery) -> list[tuple[float, dict[str, Any]]]:
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

    @staticmethod
    def _clip(value: str, max_chars: int) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

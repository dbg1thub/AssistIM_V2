"""
Search Manager Module

Local search functionality backed by the storage layer.
"""
import asyncio
from dataclasses import dataclass
from typing import Any, Optional

from client.core import logging
from client.core.i18n import tr
from client.core.logging import setup_logging
from client.models.message import ChatMessage
from client.storage.database import get_database


setup_logging()
logger = logging.get_logger(__name__)


@dataclass
class SearchResult:
    """One aggregated chat-history result grouped by session."""

    message: ChatMessage
    matched_text: str
    highlight_ranges: list[tuple[int, int]]
    session_name: str = ""
    session_avatar: str = ""
    session_type: str = ""
    match_count: int = 1


@dataclass
class ContactSearchResult:
    """One contact search result with the matched field preserved."""

    contact: dict[str, Any]
    matched_text: str
    highlight_ranges: list[tuple[int, int]]
    matched_field: str = ""


@dataclass
class GroupSearchResult:
    """One group search result with one matched field preview."""

    group: dict[str, Any]
    matched_text: str
    highlight_ranges: list[tuple[int, int]]
    matched_field: str = ""


@dataclass
class SearchCatalogResults:
    """Aggregated local search results across cached domains."""

    messages: list[SearchResult]
    contacts: list[ContactSearchResult]
    groups: list[GroupSearchResult]
    message_total: int = 0
    contact_total: int = 0
    group_total: int = 0


class SearchManager:
    """
    Local search manager.

    Features:
        - Search chat history by keyword
        - Search cached contacts and groups
        - Offer one aggregate local search entry point for sidebar search UI
    """

    def __init__(self):
        self._db = get_database()
        self._message_results: list[SearchResult] = []
        self._last_catalog_results = SearchCatalogResults(messages=[], contacts=[], groups=[])

    async def search(
        self,
        keyword: str,
        session_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[SearchResult]:
        """Search cached messages by keyword and aggregate hits by session."""
        if not keyword or not keyword.strip():
            self._message_results = []
            return []

        normalized_keyword = keyword.strip()
        normalized_limit = max(1, int(limit or 0))
        results = await self._search_message_sessions(normalized_keyword, session_id=session_id, limit=normalized_limit)
        self._message_results = results
        logger.debug("Found %s message sessions", len(results))
        return results

    async def search_contacts(
        self,
        keyword: str,
        limit: int = 20,
    ) -> list[ContactSearchResult]:
        """Search cached contacts by keyword."""
        if not keyword or not keyword.strip():
            return []

        normalized_keyword = keyword.strip()
        contacts = await self._search_contacts(normalized_keyword, limit)
        return [
            result
            for result in (self._highlight_contact_match(contact, normalized_keyword) for contact in contacts)
            if result is not None
        ]

    async def search_groups(
        self,
        keyword: str,
        limit: int = 20,
    ) -> list[GroupSearchResult]:
        """Search cached groups by keyword."""
        if not keyword or not keyword.strip():
            return []

        normalized_keyword = keyword.strip()
        groups = await self._search_groups(normalized_keyword, limit)
        return [
            result
            for result in (self._highlight_group_match(group, normalized_keyword) for group in groups)
            if result is not None
        ]

    async def search_all(
        self,
        keyword: str,
        *,
        session_id: Optional[str] = None,
        message_limit: int = 50,
        contact_limit: int = 20,
        group_limit: int = 20,
    ) -> SearchCatalogResults:
        """Search messages, contacts, and groups from local cache."""
        if not keyword or not keyword.strip():
            empty = SearchCatalogResults(messages=[], contacts=[], groups=[], message_total=0, contact_total=0, group_total=0)
            self._last_catalog_results = empty
            return empty

        normalized_keyword = keyword.strip()
        count_messages = getattr(self._db, "count_search_message_sessions", None)
        count_contacts = getattr(self._db, "count_search_contacts", None)
        count_groups = getattr(self._db, "count_search_groups", None)

        messages, contacts, groups, message_total, contact_total, group_total = await asyncio.gather(
            self._search_message_sessions(normalized_keyword, session_id=session_id, limit=message_limit),
            self.search_contacts(normalized_keyword, limit=contact_limit),
            self.search_groups(normalized_keyword, limit=group_limit),
            count_messages(normalized_keyword, session_id=session_id) if callable(count_messages) else self._immediate_value(0),
            count_contacts(normalized_keyword) if callable(count_contacts) else self._immediate_value(0),
            count_groups(normalized_keyword) if callable(count_groups) else self._immediate_value(0),
        )
        if message_total <= 0:
            message_total = len(messages)
        if contact_total <= 0:
            contact_total = len(contacts)
        if group_total <= 0:
            group_total = len(groups)
        catalog = SearchCatalogResults(messages=messages, contacts=contacts, groups=groups)
        catalog.message_total = int(message_total)
        catalog.contact_total = int(contact_total)
        catalog.group_total = int(group_total)
        self._last_catalog_results = catalog
        logger.debug(
            "Found %s local search results (%s message sessions, %s contacts, %s groups)",
            len(messages) + len(contacts) + len(groups),
            len(messages),
            len(contacts),
            len(groups),
        )
        return catalog

    async def _search_message_sessions(
        self,
        keyword: str,
        *,
        session_id: Optional[str],
        limit: int,
    ) -> list[SearchResult]:
        """Search message hits and aggregate them by session without mutating catalog state."""
        normalized_limit = max(1, int(limit or 0))
        messages = await self._search_messages_grouped(keyword, session_id=session_id, limit=normalized_limit)
        session_metadata_cache = await self._resolve_message_session_metadata_bulk(
            [message.session_id for message in messages]
        )
        grouped_results: dict[str, SearchResult] = {}
        ordered_session_ids: list[str] = []

        for message in messages:
            metadata = session_metadata_cache.get(message.session_id, {})
            result = self._highlight_message_matches(
                message,
                keyword,
                session_name=metadata.get("session_name", ""),
                session_avatar=metadata.get("session_avatar", ""),
                session_type=metadata.get("session_type", ""),
            )
            if result is None:
                continue

            existing = grouped_results.get(message.session_id)
            if existing is None:
                grouped_results[message.session_id] = result
                ordered_session_ids.append(message.session_id)
                continue

            existing.match_count += 1
            if self._message_result_rank(result) > self._message_result_rank(existing):
                result.match_count = existing.match_count
                grouped_results[message.session_id] = result

        return [grouped_results[session] for session in ordered_session_ids[:normalized_limit]]

    async def _search_messages(
        self,
        keyword: str,
        session_id: Optional[str],
        limit: int,
    ) -> list[ChatMessage]:
        """Search messages through the formal storage API."""
        try:
            return await self._db.search_messages(keyword, session_id=session_id, limit=limit)
        except Exception as exc:
            logger.error(f"Message search error: {exc}")
            return []

    async def _search_messages_grouped(
        self,
        keyword: str,
        *,
        session_id: Optional[str],
        limit: int,
    ) -> list[ChatMessage]:
        """Over-fetch raw hits so grouped message search can cover more unique sessions."""
        unique_session_ids: set[str] = set()
        collected: list[ChatMessage] = []
        raw_limit = max(limit, min(400, limit * 4))

        while True:
            messages = await self._search_messages(keyword, session_id, raw_limit)
            if not messages:
                return []
            collected = messages
            unique_session_ids = {
                str(message.session_id or "").strip()
                for message in messages
                if str(message.session_id or "").strip()
            }
            if len(unique_session_ids) >= limit or len(messages) < raw_limit or raw_limit >= 400:
                return collected
            raw_limit = min(400, raw_limit * 2)

    async def _search_contacts(
        self,
        keyword: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Search contacts through the formal storage API."""
        try:
            return await self._db.search_contacts(keyword, limit=limit)
        except Exception as exc:
            logger.error(f"Contact search error: {exc}")
            return []

    async def _search_groups(
        self,
        keyword: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Search groups through the formal storage API."""
        try:
            return await self._db.search_groups(keyword, limit=limit)
        except Exception as exc:
            logger.error(f"Group search error: {exc}")
            return []

    async def _resolve_message_session_metadata_bulk(
        self,
        session_ids: list[str],
    ) -> dict[str, dict[str, str]]:
        """Resolve lightweight session metadata for one search batch."""
        get_session_search_metadata = getattr(self._db, "get_session_search_metadata", None)
        if not callable(get_session_search_metadata):
            return {}
        try:
            return await get_session_search_metadata(session_ids)
        except Exception as exc:
            logger.debug("Search session metadata batch lookup failed: %s", exc)
            return {}

    def _highlight_message_matches(
        self,
        message: ChatMessage,
        keyword: str,
        *,
        session_name: str = "",
        session_avatar: str = "",
        session_type: str = "",
    ) -> Optional[SearchResult]:
        """Find highlight ranges for one matched message preview."""
        match = self._build_highlight_payload(message.content or "", keyword)
        if match is None:
            return None

        matched_text, highlight_ranges = match
        return SearchResult(
            message=message,
            matched_text=matched_text,
            highlight_ranges=highlight_ranges,
            session_name=session_name,
            session_avatar=session_avatar,
            session_type=session_type,
            match_count=1,
        )

    def _highlight_contact_match(
        self,
        contact: dict[str, Any],
        keyword: str,
    ) -> Optional[ContactSearchResult]:
        """Highlight the first matching contact field."""
        for field_name, field_value in (
            ("display_name", contact.get("display_name") or contact.get("name") or ""),
            ("nickname", contact.get("nickname") or ""),
            ("remark", contact.get("remark") or ""),
            ("assistim_id", contact.get("assistim_id") or ""),
            ("region", contact.get("region") or ""),
        ):
            match = self._build_highlight_payload(str(field_value or ""), keyword)
            if match is None:
                continue
            matched_text, highlight_ranges = match
            return ContactSearchResult(
                contact=contact,
                matched_text=matched_text,
                highlight_ranges=highlight_ranges,
                matched_field=field_name,
            )
        return None

    def _highlight_group_match(
        self,
        group: dict[str, Any],
        keyword: str,
    ) -> Optional[GroupSearchResult]:
        """Highlight the first matching group field."""
        name_match = self._build_highlight_payload(str(group.get("name") or ""), keyword)
        if name_match is not None:
            matched_text, highlight_ranges = name_match
            return GroupSearchResult(
                group=group,
                matched_text=matched_text,
                highlight_ranges=highlight_ranges,
                matched_field="name",
            )

        for preview in self._group_member_previews(group):
            match = self._build_highlight_payload(preview, keyword)
            if match is None:
                continue
            matched_text, highlight_ranges = match
            return GroupSearchResult(
                group=group,
                matched_text=matched_text,
                highlight_ranges=highlight_ranges,
                matched_field="member",
            )

        member_search_text = str(group.get("member_search_text") or "")
        if member_search_text:
            preview_match = self._build_highlight_payload(member_search_text, keyword)
            if preview_match is None:
                return None
            matched_text, highlight_ranges = preview_match
            return GroupSearchResult(
                group=group,
                matched_text=matched_text,
                highlight_ranges=highlight_ranges,
                matched_field="member",
            )
        return None

    @staticmethod
    def _group_member_previews(group: dict[str, Any]) -> list[str]:
        """Return lightweight member preview strings stored in local group cache."""
        extra = dict(group.get("extra") or {})
        previews = extra.get("member_previews") or []
        return [str(item or "") for item in previews if str(item or "").strip()]

    def _build_highlight_payload(
        self,
        content: str,
        keyword: str,
    ) -> Optional[tuple[str, list[tuple[int, int]]]]:
        """Return one preview snippet and highlight ranges for one text field."""
        ranges = self._find_highlight_ranges(content, keyword)
        if not ranges:
            return None

        first_match_start, first_match_end = ranges[0]
        snippet_start = max(0, first_match_start - 20)
        snippet_end = min(len(content), first_match_end + 20)
        matched_text = content[snippet_start:snippet_end]
        if snippet_start > 0:
            matched_text = "..." + matched_text
        if snippet_end < len(content):
            matched_text = matched_text + "..."
        prefix_offset = 3 if snippet_start > 0 else 0
        clipped_ranges: list[tuple[int, int]] = []
        for start, end in ranges:
            if end <= snippet_start or start >= snippet_end:
                continue
            clipped_ranges.append(
                (
                    max(start, snippet_start) - snippet_start + prefix_offset,
                    min(end, snippet_end) - snippet_start + prefix_offset,
                )
            )
        return matched_text, clipped_ranges

    @staticmethod
    def _find_highlight_ranges(content: str, keyword: str) -> list[tuple[int, int]]:
        """Find every literal keyword occurrence in one content string."""
        content_lower = str(content or "").lower()
        keyword_lower = str(keyword or "").lower()
        if not keyword_lower:
            return []

        ranges: list[tuple[int, int]] = []
        start = 0
        while True:
            pos = content_lower.find(keyword_lower, start)
            if pos == -1:
                break
            ranges.append((pos, pos + len(keyword_lower)))
            start = pos + 1
        return ranges

    @staticmethod
    async def _immediate_value(value: int) -> int:
        """Return one immediate value through an awaitable for gather compatibility."""
        return int(value or 0)

    def get_result_at(self, index: int) -> Optional[SearchResult]:
        """Get message search result at index."""
        if 0 <= index < len(self._message_results):
            return self._message_results[index]
        return None

    @property
    def result_count(self) -> int:
        """Get number of aggregated message search results."""
        return len(self._message_results)

    @property
    def last_catalog_results(self) -> SearchCatalogResults:
        """Return the latest aggregate local search snapshot."""
        return self._last_catalog_results

    def clear_results(self) -> None:
        """Clear cached search results."""
        self._message_results = []
        self._last_catalog_results = SearchCatalogResults(messages=[], contacts=[], groups=[], message_total=0, contact_total=0, group_total=0)

    async def close(self) -> None:
        """Drop cached account-scoped search results and retire the singleton."""
        self.clear_results()
        self._db = None
        global _search_manager
        if _search_manager is self:
            _search_manager = None

    @staticmethod
    def _message_result_rank(result: SearchResult) -> tuple[int, int, int]:
        """Prefer richer, tighter snippets when multiple hits map to one session."""
        keyword_hits = len(result.highlight_ranges)
        preview_length = len(str(result.matched_text or ""))
        first_hit = result.highlight_ranges[0][0] if result.highlight_ranges else 10**9
        return (keyword_hits, -first_hit, -preview_length)


_search_manager: Optional[SearchManager] = None


def peek_search_manager() -> Optional[SearchManager]:
    """Return the existing search manager singleton if it was created."""
    return _search_manager


def get_search_manager() -> SearchManager:
    """Get the global search manager instance."""
    global _search_manager
    if _search_manager is None:
        _search_manager = SearchManager()
    return _search_manager


async def search_messages(
    keyword: str,
    session_id: Optional[str] = None,
    limit: int = 100,
) -> list[SearchResult]:
    """Search messages by keyword."""
    manager = get_search_manager()
    return await manager.search(keyword, session_id, limit)


async def search_all(
    keyword: str,
    *,
    session_id: Optional[str] = None,
    message_limit: int = 50,
    contact_limit: int = 20,
    group_limit: int = 20,
) -> SearchCatalogResults:
    """Search the local message, contact, and group caches."""
    manager = get_search_manager()
    return await manager.search_all(
        keyword,
        session_id=session_id,
        message_limit=message_limit,
        contact_limit=contact_limit,
        group_limit=group_limit,
    )

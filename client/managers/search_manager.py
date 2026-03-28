"""
Search Manager Module

Local search functionality backed by the storage layer.
"""
from dataclasses import dataclass
from typing import Any, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.models.message import ChatMessage
from client.storage.database import get_database


setup_logging()
logger = logging.get_logger(__name__)


@dataclass
class SearchResult:
    """Message search result with highlighted content."""

    message: ChatMessage
    matched_text: str
    highlight_ranges: list[tuple[int, int]]


@dataclass
class ContactSearchResult:
    """Contact search result with one highlighted field preview."""

    contact: dict[str, Any]
    matched_text: str
    highlight_ranges: list[tuple[int, int]]


@dataclass
class GroupSearchResult:
    """Group search result with one highlighted field preview."""

    group: dict[str, Any]
    matched_text: str
    highlight_ranges: list[tuple[int, int]]


@dataclass
class SearchCatalogResults:
    """Aggregated local search results across cached domains."""

    messages: list[SearchResult]
    contacts: list[ContactSearchResult]
    groups: list[GroupSearchResult]


class SearchManager:
    """
    Local search manager.

    Features:
        - Search chat history by keyword
        - Search cached contacts and groups
        - Offer one aggregate local search entry point for future UI work
    """

    def __init__(self):
        self._db = get_database()
        self._current_results: list[SearchResult] = []
        self._last_catalog_results = SearchCatalogResults(messages=[], contacts=[], groups=[])

    async def search(
        self,
        keyword: str,
        session_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[SearchResult]:
        """Search cached messages by keyword."""
        if not keyword or not keyword.strip():
            self._current_results = []
            return []

        keyword = keyword.strip()
        logger.info(f"Searching messages: '{keyword}', session: {session_id}")

        messages = await self._search_messages(keyword, session_id, limit)
        results = [
            result
            for result in (self._highlight_message_matches(message, keyword) for message in messages)
            if result is not None
        ]

        self._current_results = results
        logger.info(f"Found {len(results)} messages")
        return results

    async def search_contacts(
        self,
        keyword: str,
        limit: int = 20,
    ) -> list[ContactSearchResult]:
        """Search cached contacts by keyword."""
        if not keyword or not keyword.strip():
            return []

        keyword = keyword.strip()
        contacts = await self._search_contacts(keyword, limit)
        return [
            result
            for result in (self._highlight_contact_match(contact, keyword) for contact in contacts)
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

        keyword = keyword.strip()
        groups = await self._search_groups(keyword, limit)
        return [
            result
            for result in (self._highlight_group_match(group, keyword) for group in groups)
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
            empty = SearchCatalogResults(messages=[], contacts=[], groups=[])
            self._current_results = []
            self._last_catalog_results = empty
            return empty

        normalized_keyword = keyword.strip()
        messages = await self.search(normalized_keyword, session_id=session_id, limit=message_limit)
        contacts = await self.search_contacts(normalized_keyword, limit=contact_limit)
        groups = await self.search_groups(normalized_keyword, limit=group_limit)
        catalog = SearchCatalogResults(messages=messages, contacts=contacts, groups=groups)
        self._last_catalog_results = catalog
        logger.info(
            "Found %s local search results (%s messages, %s contacts, %s groups)",
            len(messages) + len(contacts) + len(groups),
            len(messages),
            len(contacts),
            len(groups),
        )
        return catalog

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

    def _highlight_message_matches(
        self,
        message: ChatMessage,
        keyword: str,
    ) -> Optional[SearchResult]:
        """Find highlight ranges for keyword in message content."""
        match = self._build_highlight_payload(message.content or "", keyword)
        if match is None:
            return None

        matched_text, highlight_ranges = match
        return SearchResult(
            message=message,
            matched_text=matched_text,
            highlight_ranges=highlight_ranges,
        )

    def _highlight_contact_match(
        self,
        contact: dict[str, Any],
        keyword: str,
    ) -> Optional[ContactSearchResult]:
        """Highlight the first matching contact field."""
        for field in (
            contact.get("display_name") or contact.get("name") or "",
            contact.get("username") or "",
            contact.get("nickname") or "",
            contact.get("remark") or "",
            contact.get("assistim_id") or "",
            contact.get("signature") or "",
        ):
            match = self._build_highlight_payload(str(field or ""), keyword)
            if match is None:
                continue
            matched_text, highlight_ranges = match
            return ContactSearchResult(
                contact=contact,
                matched_text=matched_text,
                highlight_ranges=highlight_ranges,
            )
        return None

    def _highlight_group_match(
        self,
        group: dict[str, Any],
        keyword: str,
    ) -> Optional[GroupSearchResult]:
        """Highlight the first matching group field."""
        for field in (
            group.get("name") or "",
            group.get("id") or "",
            group.get("session_id") or "",
        ):
            match = self._build_highlight_payload(str(field or ""), keyword)
            if match is None:
                continue
            matched_text, highlight_ranges = match
            return GroupSearchResult(
                group=group,
                matched_text=matched_text,
                highlight_ranges=highlight_ranges,
            )
        return None

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
        matched_text = content[max(0, first_match_start - 20):first_match_end + 20]
        if first_match_start > 20:
            matched_text = "..." + matched_text
        if first_match_end < len(content) - 20:
            matched_text = matched_text + "..."
        return matched_text, ranges

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

    def get_result_at(self, index: int) -> Optional[SearchResult]:
        """Get message search result at index."""
        if 0 <= index < len(self._current_results):
            return self._current_results[index]
        return None

    @property
    def result_count(self) -> int:
        """Get number of message search results."""
        return len(self._current_results)

    @property
    def last_catalog_results(self) -> SearchCatalogResults:
        """Return the latest aggregate local search snapshot."""
        return self._last_catalog_results

    def clear_results(self) -> None:
        """Clear cached search results."""
        self._current_results = []
        self._last_catalog_results = SearchCatalogResults(messages=[], contacts=[], groups=[])


_search_manager: Optional[SearchManager] = None


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

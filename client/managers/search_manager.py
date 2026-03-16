"""
Search Manager Module

Message search functionality with database queries.
"""
import asyncio
import re
from dataclasses import dataclass
from typing import Optional

from client.core import logging
from client.core.logging import setup_logging
from client.models.message import ChatMessage, MessageType
from client.storage.database import get_database


setup_logging()
logger = logging.get_logger(__name__)


@dataclass
class SearchResult:
    """Search result with highlighted content."""

    message: ChatMessage
    matched_text: str
    highlight_ranges: list[tuple[int, int]]  # (start, end) positions


class SearchManager:
    """
    Message search manager.

    Features:
        - Search messages by keyword
        - Search within specific session or all sessions
        - Highlight matching text
    """

    def __init__(self):
        self._db = get_database()
        self._current_results: list[SearchResult] = []
        self._search_task: Optional[asyncio.Task] = None
        self._running = False

    async def search(
        self,
        keyword: str,
        session_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[SearchResult]:
        """
        Search messages by keyword.

        Args:
            keyword: Search keyword
            session_id: Optional session ID to limit search
            limit: Maximum results

        Returns:
            List of SearchResult with highlighted matches
        """
        if not keyword or not keyword.strip():
            return []

        keyword = keyword.strip()
        logger.info(f"Searching messages: '{keyword}', session: {session_id}")

        # Search in database
        messages = await self._search_messages(keyword, session_id, limit)

        # Build results with highlights
        results = []
        for message in messages:
            result = self._highlight_matches(message, keyword)
            if result:
                results.append(result)

        self._current_results = results
        logger.info(f"Found {len(results)} messages")

        return results

    async def _search_messages(
        self,
        keyword: str,
        session_id: Optional[str],
        limit: int,
    ) -> list[ChatMessage]:
        """Search messages in database."""
        try:
            if session_id:
                # Search within specific session
                cursor = await self._db.execute(
                    """
                    SELECT * FROM messages
                    WHERE session_id = ? AND content LIKE ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (session_id, f"%{keyword}%", limit),
                )
            else:
                # Search all sessions
                cursor = await self._db.execute(
                    """
                    SELECT * FROM messages
                    WHERE content LIKE ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (f"%{keyword}%", limit),
                )

            rows = await cursor.fetchall()

            # Convert rows to messages
            messages = []
            for row in rows:
                message = self._db._row_to_message(row)
                if message:
                    messages.append(message)

            return messages

        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    def _highlight_matches(
        self,
        message: ChatMessage,
        keyword: str,
    ) -> Optional[SearchResult]:
        """Find highlight ranges for keyword in message content."""
        content = message.content or ""
        keyword_lower = keyword.lower()
        content_lower = content.lower()

        # Find all occurrences
        ranges = []
        start = 0

        while True:
            pos = content_lower.find(keyword_lower, start)
            if pos == -1:
                break
            ranges.append((pos, pos + len(keyword)))
            start = pos + 1

        if not ranges:
            return None

        # Get matched text for preview
        first_match_start, first_match_end = ranges[0]
        matched_text = content[max(0, first_match_start - 20):first_match_end + 20]

        # Add ellipsis if needed
        if first_match_start > 20:
            matched_text = "..." + matched_text
        if first_match_end < len(content) - 20:
            matched_text = matched_text + "..."

        return SearchResult(
            message=message,
            matched_text=matched_text,
            highlight_ranges=ranges,
        )

    def get_result_at(self, index: int) -> Optional[SearchResult]:
        """Get search result at index."""
        if 0 <= index < len(self._current_results):
            return self._current_results[index]
        return None

    @property
    def result_count(self) -> int:
        """Get number of search results."""
        return len(self._current_results)

    def clear_results(self) -> None:
        """Clear search results."""
        self._current_results = []


# Global instance
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

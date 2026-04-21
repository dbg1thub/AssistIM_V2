"""Small semantic cache placeholder for AI action workflow."""

from __future__ import annotations

from typing import Any


class AIActionCache:
    """In-memory cache used within one client process."""

    def __init__(self) -> None:
        self._items: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self._items.get(str(key or ""))

    def set(self, key: str, value: Any) -> None:
        normalized_key = str(key or "").strip()
        if normalized_key:
            self._items[normalized_key] = value

    def clear(self) -> None:
        self._items.clear()

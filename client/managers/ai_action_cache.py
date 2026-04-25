"""Small semantic cache placeholder for AI action workflow."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class AIActionCache:
    """In-memory cache used within one client process."""

    def __init__(self) -> None:
        self._items: dict[str, Any] = {}

    def get(self, namespace: str, key: str | None = None) -> Any:
        normalized_key = self._normalize_key(namespace, key)
        if not normalized_key:
            return None
        value = self._items.get(normalized_key)
        return deepcopy(value) if value is not None else None

    def set(self, namespace: str, key: str | Any, value: Any | None = None) -> None:
        if value is None:
            normalized_key = self._normalize_key(namespace)
            stored_value = key
        else:
            normalized_key = self._normalize_key(namespace, str(key or ""))
            stored_value = value
        if normalized_key:
            self._items[normalized_key] = deepcopy(stored_value)

    def clear(self) -> None:
        self._items.clear()

    @staticmethod
    def _normalize_key(namespace: str, key: str | None = None) -> str:
        normalized_namespace = str(namespace or "").strip()
        normalized_key = str(key or "").strip()
        if normalized_key:
            return f"{normalized_namespace}:{normalized_key}" if normalized_namespace else normalized_key
        return normalized_namespace

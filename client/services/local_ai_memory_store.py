"""Unified local vector memory store for AI semantic sources."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence

from client.core.config_backend import APP_ROOT


class LocalAIMemoryStoreError(RuntimeError):
    """Stable error surface for the local AI memory store."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clean_source_type(value: Any) -> str:
    return _clean_text(value).lower()


def _metadata_json(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _normalize_vector(values: Sequence[float] | tuple[float, ...], *, allow_empty: bool = False) -> tuple[float, ...]:
    vector: list[float] = []
    for value in list(values or ()):
        try:
            normalized = float(value)
        except (TypeError, ValueError) as exc:
            raise LocalAIMemoryStoreError("AI_MEMORY_ITEM_INVALID", "AI memory vector contains a non-numeric value") from exc
        if not math.isfinite(normalized):
            raise LocalAIMemoryStoreError("AI_MEMORY_ITEM_INVALID", "AI memory vector contains a non-finite value")
        vector.append(normalized)
    if not vector and not allow_empty:
        raise LocalAIMemoryStoreError("AI_MEMORY_ITEM_INVALID", "AI memory vector must not be empty")
    return tuple(vector)


def _cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(float(lv) * float(rv) for lv, rv in zip(left, right))
    left_norm = math.sqrt(sum(float(value) * float(value) for value in left))
    right_norm = math.sqrt(sum(float(value) * float(value) for value in right))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def build_ai_memory_id(*, owner_scope: str, source_type: str, source_id: str, chunk_id: str = "") -> str:
    """Build a deterministic id for one semantic memory item."""

    payload = {
        "chunk_id": _clean_text(chunk_id),
        "owner_scope": _clean_text(owner_scope),
        "source_id": _clean_text(source_id),
        "source_type": _clean_source_type(source_type),
    }
    raw_value = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()


def _build_content_hash(*, title: str, text: str, metadata: dict[str, Any]) -> str:
    raw_value = _metadata_json(
        {
            "metadata": metadata,
            "text": _clean_text(text),
            "title": _clean_text(title),
        }
    )
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()


def _quote_lancedb_value(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _in_expression(column: str, values: Sequence[str]) -> str:
    quoted_values = ", ".join(_quote_lancedb_value(value) for value in values)
    return f"{column} IN ({quoted_values})"


def build_ai_memory_filter_expression(
    *,
    owner_scope: str = "",
    source_types: Sequence[str] = (),
    source_type: str = "",
    source_id: str = "",
    embedding_model_id: str = "",
    memory_ids: Sequence[str] = (),
) -> str:
    """Build a SQL-like LanceDB filter expression with escaped values."""

    clauses: list[str] = []
    normalized_memory_ids = [_clean_text(value) for value in list(memory_ids or ()) if _clean_text(value)]
    if normalized_memory_ids:
        clauses.append(_in_expression("memory_id", normalized_memory_ids))
    normalized_owner_scope = _clean_text(owner_scope)
    if normalized_owner_scope:
        clauses.append(f"owner_scope = {_quote_lancedb_value(normalized_owner_scope)}")
    normalized_source_types = [
        _clean_source_type(value) for value in list(source_types or ()) if _clean_source_type(value)
    ]
    normalized_source_type = _clean_source_type(source_type)
    if normalized_source_type:
        normalized_source_types.append(normalized_source_type)
    deduped_source_types = list(dict.fromkeys(normalized_source_types))
    if len(deduped_source_types) == 1:
        clauses.append(f"source_type = {_quote_lancedb_value(deduped_source_types[0])}")
    elif deduped_source_types:
        clauses.append(_in_expression("source_type", deduped_source_types))
    normalized_source_id = _clean_text(source_id)
    if normalized_source_id:
        clauses.append(f"source_id = {_quote_lancedb_value(normalized_source_id)}")
    normalized_embedding_model_id = _clean_text(embedding_model_id)
    if normalized_embedding_model_id:
        clauses.append(f"embedding_model_id = {_quote_lancedb_value(normalized_embedding_model_id)}")
    return " AND ".join(clauses)


@dataclass(frozen=True, slots=True)
class AIMemoryItem:
    """One vectorized semantic item stored for AI retrieval."""

    owner_scope: str
    source_type: str
    source_id: str
    text: str
    vector: tuple[float, ...]
    embedding_model_id: str
    chunk_id: str = ""
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    memory_id: str = ""
    content_hash: str = ""
    created_at: int | None = None
    updated_at: int | None = None

    def __post_init__(self) -> None:
        owner_scope = _clean_text(self.owner_scope)
        source_type = _clean_source_type(self.source_type)
        source_id = _clean_text(self.source_id)
        chunk_id = _clean_text(self.chunk_id)
        title = _clean_text(self.title)
        text = _clean_text(self.text)
        embedding_model_id = _clean_text(self.embedding_model_id)
        metadata = dict(self.metadata or {})
        vector = _normalize_vector(self.vector)
        if not owner_scope or not source_type or not source_id or not text or not embedding_model_id:
            raise LocalAIMemoryStoreError(
                "AI_MEMORY_ITEM_INVALID",
                "AI memory item requires owner_scope, source_type, source_id, text and embedding_model_id",
            )
        now = int(time.time())
        memory_id = _clean_text(self.memory_id) or build_ai_memory_id(
            owner_scope=owner_scope,
            source_type=source_type,
            source_id=source_id,
            chunk_id=chunk_id,
        )
        content_hash = _clean_text(self.content_hash) or _build_content_hash(
            title=title,
            text=text,
            metadata=metadata,
        )
        object.__setattr__(self, "owner_scope", owner_scope)
        object.__setattr__(self, "source_type", source_type)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "chunk_id", chunk_id)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "vector", vector)
        object.__setattr__(self, "embedding_model_id", embedding_model_id)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "memory_id", memory_id)
        object.__setattr__(self, "content_hash", content_hash)
        object.__setattr__(self, "created_at", int(self.created_at or now))
        object.__setattr__(self, "updated_at", int(self.updated_at or now))

    @property
    def embedding_dim(self) -> int:
        return len(self.vector)

    def to_record(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "owner_scope": self.owner_scope,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "chunk_id": self.chunk_id,
            "title": self.title,
            "text": self.text,
            "embedding_model_id": self.embedding_model_id,
            "embedding_dim": self.embedding_dim,
            "content_hash": self.content_hash,
            "metadata_json": _metadata_json(self.metadata),
            "created_at": int(self.created_at or 0),
            "updated_at": int(self.updated_at or 0),
            "vector": [float(value) for value in self.vector],
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "AIMemoryItem":
        metadata: dict[str, Any] = {}
        raw_metadata = record.get("metadata")
        if isinstance(raw_metadata, dict):
            metadata = dict(raw_metadata)
        else:
            try:
                loaded_metadata = json.loads(str(record.get("metadata_json") or "{}"))
            except json.JSONDecodeError:
                loaded_metadata = {}
            if isinstance(loaded_metadata, dict):
                metadata = loaded_metadata
        raw_vector = record.get("vector")
        return cls(
            owner_scope=str(record.get("owner_scope") or ""),
            source_type=str(record.get("source_type") or ""),
            source_id=str(record.get("source_id") or ""),
            chunk_id=str(record.get("chunk_id") or ""),
            title=str(record.get("title") or ""),
            text=str(record.get("text") or ""),
            vector=tuple(raw_vector) if raw_vector is not None else (),
            embedding_model_id=str(record.get("embedding_model_id") or ""),
            metadata=metadata,
            memory_id=str(record.get("memory_id") or ""),
            content_hash=str(record.get("content_hash") or ""),
            created_at=int(record.get("created_at") or 0),
            updated_at=int(record.get("updated_at") or 0),
        )


@dataclass(frozen=True, slots=True)
class AIMemorySearchResult:
    item: AIMemoryItem
    score: float
    raw_distance: float | None = None


class LocalAIMemoryStore(Protocol):
    async def upsert_item(self, item: AIMemoryItem) -> None:
        ...

    async def upsert_items(self, items: Sequence[AIMemoryItem]) -> None:
        ...

    async def search(
        self,
        *,
        query_vector: Sequence[float],
        owner_scope: str,
        embedding_model_id: str,
        source_types: Sequence[str] = (),
        limit: int = 8,
        min_score: float = 0.0,
    ) -> list[AIMemorySearchResult]:
        ...

    async def delete_source(self, *, owner_scope: str, source_type: str, source_id: str) -> None:
        ...


class InMemoryAIMemoryStore:
    """Deterministic memory store used for tests and local algorithm validation."""

    def __init__(self) -> None:
        self._items: dict[str, AIMemoryItem] = {}
        self._lock = asyncio.Lock()

    async def upsert_item(self, item: AIMemoryItem) -> None:
        await self.upsert_items([item])

    async def upsert_items(self, items: Sequence[AIMemoryItem]) -> None:
        async with self._lock:
            for item in list(items or ()):
                self._items[item.memory_id] = item

    async def search(
        self,
        *,
        query_vector: Sequence[float],
        owner_scope: str,
        embedding_model_id: str,
        source_types: Sequence[str] = (),
        limit: int = 8,
        min_score: float = 0.0,
    ) -> list[AIMemorySearchResult]:
        query = _normalize_vector(tuple(query_vector) if query_vector is not None else (), allow_empty=True)
        if not query or limit <= 0:
            return []
        normalized_owner_scope = _clean_text(owner_scope)
        normalized_model_id = _clean_text(embedding_model_id)
        normalized_source_types = {
            _clean_source_type(value) for value in list(source_types or ()) if _clean_source_type(value)
        }
        async with self._lock:
            candidates = list(self._items.values())
        results: list[AIMemorySearchResult] = []
        for item in candidates:
            if item.owner_scope != normalized_owner_scope:
                continue
            if normalized_model_id and item.embedding_model_id != normalized_model_id:
                continue
            if normalized_source_types and item.source_type not in normalized_source_types:
                continue
            score = _cosine_similarity(query, item.vector)
            if score < float(min_score):
                continue
            results.append(AIMemorySearchResult(item=item, score=score))
        results.sort(key=lambda result: (result.score, int(result.item.updated_at or 0)), reverse=True)
        return results[: int(limit)]

    async def delete_source(self, *, owner_scope: str, source_type: str, source_id: str) -> None:
        normalized_owner_scope = _clean_text(owner_scope)
        normalized_source_type = _clean_source_type(source_type)
        normalized_source_id = _clean_text(source_id)
        async with self._lock:
            for memory_id, item in list(self._items.items()):
                if (
                    item.owner_scope == normalized_owner_scope
                    and item.source_type == normalized_source_type
                    and item.source_id == normalized_source_id
                ):
                    self._items.pop(memory_id, None)


@dataclass(slots=True)
class LocalAIMemoryStoreConfig:
    db_path: str = field(
        default_factory=lambda: str(
            Path(str(os.getenv("ASSISTIM_AI_MEMORY_VECTOR_PATH", "") or "")).expanduser().resolve()
            if str(os.getenv("ASSISTIM_AI_MEMORY_VECTOR_PATH", "") or "").strip()
            else APP_ROOT / "data" / "ai_memory" / "lancedb"
        )
    )
    table_name: str = field(
        default_factory=lambda: _clean_text(os.getenv("ASSISTIM_AI_MEMORY_TABLE", "ai_memory")) or "ai_memory"
    )


class LanceDBAIMemoryStore:
    """LanceDB-backed local vector store for AI semantic memory."""

    def __init__(self, config: LocalAIMemoryStoreConfig | None = None) -> None:
        self._config = config or LocalAIMemoryStoreConfig()
        self._db: Any | None = None
        self._table: Any | None = None
        self._lock = asyncio.Lock()

    @property
    def config(self) -> LocalAIMemoryStoreConfig:
        return self._config

    async def upsert_item(self, item: AIMemoryItem) -> None:
        await self.upsert_items([item])

    async def upsert_items(self, items: Sequence[AIMemoryItem]) -> None:
        normalized_items = [item for item in list(items or ()) if isinstance(item, AIMemoryItem)]
        if not normalized_items:
            return
        async with self._lock:
            await asyncio.to_thread(self._upsert_items_sync, normalized_items)

    async def search(
        self,
        *,
        query_vector: Sequence[float],
        owner_scope: str,
        embedding_model_id: str,
        source_types: Sequence[str] = (),
        limit: int = 8,
        min_score: float = 0.0,
    ) -> list[AIMemorySearchResult]:
        query = _normalize_vector(tuple(query_vector) if query_vector is not None else (), allow_empty=True)
        if not query or limit <= 0:
            return []
        async with self._lock:
            return await asyncio.to_thread(
                self._search_sync,
                query,
                _clean_text(owner_scope),
                _clean_text(embedding_model_id),
                tuple(source_types or ()),
                int(limit),
                float(min_score),
            )

    async def delete_source(self, *, owner_scope: str, source_type: str, source_id: str) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._delete_source_sync,
                _clean_text(owner_scope),
                _clean_source_type(source_type),
                _clean_text(source_id),
            )

    def _connect_sync(self):
        if self._db is not None:
            return self._db
        try:
            lancedb = importlib.import_module("lancedb")
        except ImportError as exc:
            raise LocalAIMemoryStoreError(
                "AI_MEMORY_VECTOR_DB_UNAVAILABLE",
                "lancedb is not installed. Install dependencies from requirements.txt first.",
            ) from exc
        db_path = Path(self._config.db_path).expanduser().resolve()
        db_path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(db_path))
        return self._db

    def _open_table_sync(self):
        if self._table is not None:
            return self._table
        db = self._connect_sync()
        table_names = None
        try:
            table_names = set(db.table_names())
        except Exception:
            table_names = None
        if table_names is not None and self._config.table_name not in table_names:
            return None
        try:
            self._table = db.open_table(self._config.table_name)
        except Exception as exc:
            if table_names is None:
                return None
            raise LocalAIMemoryStoreError(
                "AI_MEMORY_VECTOR_DB_OPEN_FAILED",
                f"Failed to open local AI memory vector table: {self._config.table_name}",
            ) from exc
        return self._table

    def _create_table_sync(self, records: list[dict[str, Any]]):
        db = self._connect_sync()
        self._table = db.create_table(self._config.table_name, data=records)
        return self._table

    def _ensure_table_sync(self, records: list[dict[str, Any]]):
        table = self._open_table_sync()
        if table is not None:
            return table, False
        return self._create_table_sync(records), True

    def _upsert_items_sync(self, items: Sequence[AIMemoryItem]) -> None:
        records = [item.to_record() for item in items]
        table, created = self._ensure_table_sync(records)
        if created:
            return
        merge_insert = getattr(table, "merge_insert", None)
        if callable(merge_insert):
            try:
                (
                    merge_insert("memory_id")
                    .when_matched_update_all()
                    .when_not_matched_insert_all()
                    .execute(records)
                )
                return
            except (AttributeError, TypeError):
                pass
        memory_ids = [record["memory_id"] for record in records]
        delete_filter = build_ai_memory_filter_expression(memory_ids=memory_ids)
        if delete_filter:
            table.delete(delete_filter)
        table.add(records)

    def _search_sync(
        self,
        query_vector: tuple[float, ...],
        owner_scope: str,
        embedding_model_id: str,
        source_types: Sequence[str],
        limit: int,
        min_score: float,
    ) -> list[AIMemorySearchResult]:
        table = self._open_table_sync()
        if table is None:
            return []
        filter_expression = build_ai_memory_filter_expression(
            owner_scope=owner_scope,
            source_types=source_types,
            embedding_model_id=embedding_model_id,
        )
        query = table.search(list(query_vector))
        if filter_expression:
            query = query.where(filter_expression)
        rows = list(query.limit(max(limit, 1)).to_list())
        results: list[AIMemorySearchResult] = []
        for row in rows:
            item = AIMemoryItem.from_record(dict(row))
            score = _cosine_similarity(query_vector, item.vector)
            if score < min_score:
                continue
            raw_distance = row.get("_distance")
            results.append(
                AIMemorySearchResult(
                    item=item,
                    score=score,
                    raw_distance=float(raw_distance) if raw_distance is not None else None,
                )
            )
        results.sort(key=lambda result: (result.score, int(result.item.updated_at or 0)), reverse=True)
        return results[:limit]

    def _delete_source_sync(self, owner_scope: str, source_type: str, source_id: str) -> None:
        table = self._open_table_sync()
        if table is None:
            return
        filter_expression = build_ai_memory_filter_expression(
            owner_scope=owner_scope,
            source_type=source_type,
            source_id=source_id,
        )
        if filter_expression:
            table.delete(filter_expression)


_local_ai_memory_store: LanceDBAIMemoryStore | None = None


def get_local_ai_memory_store(config: LocalAIMemoryStoreConfig | None = None) -> LanceDBAIMemoryStore:
    global _local_ai_memory_store
    if config is not None:
        return LanceDBAIMemoryStore(config)
    if _local_ai_memory_store is None:
        _local_ai_memory_store = LanceDBAIMemoryStore()
    return _local_ai_memory_store

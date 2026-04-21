from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Iterable

from client.services.local_embedding_gguf_runtime import (
    LocalEmbeddingGGUFRuntime,
    get_local_embedding_runtime,
)


@dataclass(frozen=True, slots=True)
class DenseVector:
    values: tuple[float, ...]

    def cosine(self, other: "DenseVector") -> float:
        if not self.values or not other.values:
            return 0.0
        if len(self.values) != len(other.values):
            raise ValueError("Embedding vectors must have the same dimension")
        dot = sum(float(left) * float(right) for left, right in zip(self.values, other.values))
        left_norm = math.sqrt(sum(float(value) * float(value) for value in self.values))
        right_norm = math.sqrt(sum(float(value) * float(value) for value in other.values))
        if left_norm <= 0.0 or right_norm <= 0.0:
            return 0.0
        return dot / (left_norm * right_norm)


class ConversationVectorIndex:
    """Dense embedding encoder for conversation summaries and queries."""

    def __init__(self, runtime: LocalEmbeddingGGUFRuntime | None = None) -> None:
        self._runtime = runtime or get_local_embedding_runtime()

    @property
    def model_id(self) -> str:
        return str(self._runtime.config.model_id or "").strip()

    async def encode_query(
        self,
        *,
        query: str,
        terms: Iterable[str] = (),
        contact_aliases: Iterable[str] = (),
    ) -> DenseVector:
        payload = self.build_query_payload(
            query=query,
            terms=terms,
            contact_aliases=contact_aliases,
        )
        vectors = await self._runtime.embed_texts([payload])
        return DenseVector(values=vectors[0] if vectors else ())

    async def encode_item(
        self,
        *,
        title: str,
        text: str,
        keywords: Iterable[str] = (),
        participants: Iterable[str] = (),
    ) -> DenseVector:
        payload = self.build_item_payload(
            title=title,
            text=text,
            keywords=keywords,
            participants=participants,
        )
        vectors = await self._runtime.embed_texts([payload])
        return DenseVector(values=vectors[0] if vectors else ())

    @staticmethod
    def build_query_payload(
        *,
        query: str,
        terms: Iterable[str],
        contact_aliases: Iterable[str],
    ) -> str:
        parts: list[str] = []
        normalized_query = " ".join(str(query or "").split())
        if normalized_query:
            parts.append(f"Query: {normalized_query}")
        normalized_terms = [str(term or "").strip() for term in list(terms or []) if str(term or "").strip()]
        if normalized_terms:
            parts.append(f"Keywords: {' | '.join(normalized_terms)}")
        normalized_aliases = [str(alias or "").strip() for alias in list(contact_aliases or []) if str(alias or "").strip()]
        if normalized_aliases:
            parts.append(f"Contacts: {' | '.join(normalized_aliases)}")
        return "\n".join(parts)

    @staticmethod
    def build_item_payload(
        *,
        title: str,
        text: str,
        keywords: Iterable[str],
        participants: Iterable[str],
    ) -> str:
        parts: list[str] = []
        normalized_title = " ".join(str(title or "").split())
        if normalized_title:
            parts.append(f"Title: {normalized_title}")
        normalized_text = " ".join(str(text or "").split())
        if normalized_text:
            parts.append(f"RetrievalSummary: {normalized_text}")
        normalized_keywords = [str(keyword or "").strip() for keyword in list(keywords or []) if str(keyword or "").strip()]
        if normalized_keywords:
            parts.append(f"Keywords: {' | '.join(normalized_keywords)}")
        normalized_participants = [
            str(participant or "").strip() for participant in list(participants or []) if str(participant or "").strip()
        ]
        if normalized_participants:
            parts.append(f"Participants: {' | '.join(normalized_participants)}")
        return "\n".join(parts)

    @classmethod
    def item_content_hash(
        cls,
        *,
        title: str,
        text: str,
        keywords: Iterable[str] = (),
        participants: Iterable[str] = (),
    ) -> str:
        payload = cls.build_item_payload(
            title=title,
            text=text,
            keywords=keywords,
            participants=participants,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

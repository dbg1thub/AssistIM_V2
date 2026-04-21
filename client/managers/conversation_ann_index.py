from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from client.managers.conversation_vector_index import DenseVector


@dataclass(frozen=True, slots=True)
class AnnBucket:
    band_index: int
    bucket_key: str


class ConversationAnnIndex:
    """Deterministic local ANN index based on signed random projection LSH."""

    VERSION = "srp-lsh-v1"
    DEFAULT_BAND_COUNT = 8
    DEFAULT_BITS_PER_BAND = 8

    def __init__(
        self,
        *,
        model_id: str,
        band_count: int = DEFAULT_BAND_COUNT,
        bits_per_band: int = DEFAULT_BITS_PER_BAND,
    ) -> None:
        self._model_id = str(model_id or "").strip()
        self._band_count = max(1, int(band_count or self.DEFAULT_BAND_COUNT))
        self._bits_per_band = max(1, int(bits_per_band or self.DEFAULT_BITS_PER_BAND))
        self._projection_cache: dict[int, tuple[tuple[float, ...], ...]] = {}

    @property
    def namespace(self) -> str:
        return f"{self.VERSION}:{self._model_id}:{self._band_count}x{self._bits_per_band}"

    @property
    def band_count(self) -> int:
        return self._band_count

    def buckets_for_vector(self, vector: DenseVector) -> tuple[AnnBucket, ...]:
        values = tuple(float(value) for value in vector.values)
        if not values:
            return ()
        hyperplanes = self._projection_planes(len(values))
        buckets: list[AnnBucket] = []
        for band_index in range(self._band_count):
            bucket_value = 0
            for bit_index in range(self._bits_per_band):
                plane = hyperplanes[band_index * self._bits_per_band + bit_index]
                dot = sum(left * right for left, right in zip(values, plane))
                if dot >= 0.0:
                    bucket_value |= 1 << bit_index
            width = max(2, (self._bits_per_band + 3) // 4)
            buckets.append(AnnBucket(band_index=band_index, bucket_key=f"{bucket_value:0{width}x}"))
        return tuple(buckets)

    def _projection_planes(self, dim: int) -> tuple[tuple[float, ...], ...]:
        cached = self._projection_cache.get(dim)
        if cached is not None:
            return cached
        total_planes = self._band_count * self._bits_per_band
        planes: list[tuple[float, ...]] = []
        for plane_index in range(total_planes):
            seed = self._seed(dim=dim, plane_index=plane_index)
            rng = random.Random(seed)
            planes.append(tuple(rng.uniform(-1.0, 1.0) for _ in range(dim)))
        normalized = tuple(planes)
        self._projection_cache[dim] = normalized
        return normalized

    def _seed(self, *, dim: int, plane_index: int) -> int:
        payload = f"{self.namespace}:{dim}:{plane_index}".encode("utf-8")
        digest = hashlib.sha256(payload).digest()
        return int.from_bytes(digest[:8], "big", signed=False)

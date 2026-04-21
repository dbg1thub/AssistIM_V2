"""Local GGUF embedding runtime backed by llama-cpp-python."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from client.core import logging
from client.core.config_backend import get_config
from client.services.local_gguf_runtime import (
    _ensure_windows_runtime_dependency_dirs,
    _parse_gpu_layers_env,
    _parse_int_env,
)

logger = logging.get_logger(__name__)


@dataclass(slots=True)
class LocalEmbeddingGGUFConfig:
    """Configuration for one local GGUF embedding runtime."""

    model_path: str = field(default_factory=lambda: str(get_config().ai.embedding_model_path))
    model_id: str = field(default_factory=lambda: str(get_config().ai.embedding_model_id))
    context_size: int = field(default_factory=lambda: int(get_config().ai.embedding_context_size))
    gpu_layers: int = field(
        default_factory=lambda: _parse_gpu_layers_env(
            "ASSISTIM_AI_EMBEDDING_GPU_LAYERS",
            int(get_config().ai.embedding_gpu_layers),
        )
    )
    cpu_threads: int = field(default_factory=lambda: _parse_int_env("ASSISTIM_AI_CPU_THREADS", int(get_config().ai.cpu_threads)))
    verbose: bool = field(default_factory=lambda: bool(get_config().ai.verbose))
    batch_size: int = field(default_factory=lambda: max(32, _parse_int_env("ASSISTIM_AI_EMBEDDING_BATCH_SIZE", 256)))
    metadata: dict[str, Any] = field(default_factory=dict)


class LocalEmbeddingGGUFRuntimeError(RuntimeError):
    """Stable local embedding runtime error."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


class LocalEmbeddingGGUFRuntime:
    """llama-cpp-python embedding runtime wrapper for one local embedding model."""

    def __init__(self, config: LocalEmbeddingGGUFConfig | None = None) -> None:
        self._config = config or LocalEmbeddingGGUFConfig()
        self._embedder = None
        self._load_lock = asyncio.Lock()
        self._load_task: asyncio.Task | None = None
        self._closed = False

    @property
    def config(self) -> LocalEmbeddingGGUFConfig:
        return self._config

    def _model_path(self) -> Path:
        return Path(self._config.model_path).expanduser().resolve()

    def _assert_model_available(self) -> Path:
        model_path = self._model_path()
        if not model_path.exists():
            raise LocalEmbeddingGGUFRuntimeError(
                "AI_EMBEDDING_MODEL_NOT_FOUND",
                f"Local embedding GGUF model not found: {model_path}",
            )
        if not model_path.is_file():
            raise LocalEmbeddingGGUFRuntimeError(
                "AI_EMBEDDING_MODEL_NOT_FOUND",
                f"Local embedding GGUF model path is not a file: {model_path}",
            )
        return model_path

    async def warmup(self) -> None:
        await self.load()

    async def load(self) -> None:
        if self._closed:
            raise LocalEmbeddingGGUFRuntimeError("AI_EMBEDDING_MODEL_UNAVAILABLE", "Local embedding runtime is closed")
        if self._embedder is not None:
            return
        task = await self._ensure_load_task()
        await asyncio.shield(task)

    async def embed_texts(self, texts: list[str]) -> list[tuple[float, ...]]:
        normalized = [" ".join(str(text or "").split()) for text in list(texts or []) if str(text or "").strip()]
        if not normalized:
            return []
        await self.load()
        try:
            vectors = await asyncio.to_thread(self._embed_sync, normalized)
        except LocalEmbeddingGGUFRuntimeError:
            raise
        except Exception as exc:
            raise LocalEmbeddingGGUFRuntimeError(
                "AI_EMBEDDING_GENERATION_FAILED",
                f"Local embedding generation failed: {exc}",
            ) from exc
        return [tuple(float(value) for value in vector) for vector in vectors]

    async def close(self) -> None:
        self._closed = True
        self._load_task = None
        embedder = self._embedder
        self._embedder = None
        close = getattr(embedder, "close", None)
        if callable(close):
            await asyncio.to_thread(close)

    async def _ensure_load_task(self) -> asyncio.Task:
        async with self._load_lock:
            if self._embedder is not None:
                completed = asyncio.get_running_loop().create_future()
                completed.set_result(self._embedder)
                return completed
            if self._load_task is not None and self._load_task.done():
                if self._load_task.cancelled():
                    self._load_task = None
                else:
                    try:
                        self._load_task.result()
                    except Exception:
                        self._load_task = None
            if self._load_task is None:
                model_path = self._assert_model_available()
                self._load_task = asyncio.create_task(self._load_async(model_path))
            return self._load_task

    async def _load_async(self, model_path: Path):
        logger.info(
            "[ai-perf] local_embedding_model_load_start provider=local_gguf_embedding model=%s path=%s n_ctx=%s gpu_layers=%s cpu_threads=%s",
            self._config.model_id,
            model_path,
            self._config.context_size,
            self._config.gpu_layers,
            self._config.cpu_threads,
        )
        try:
            embedder = await asyncio.to_thread(self._load_sync, model_path)
        except Exception:
            logger.exception(
                "[ai-perf] local_embedding_model_load_failed provider=local_gguf_embedding model=%s path=%s",
                self._config.model_id,
                model_path,
            )
            raise
        if self._closed:
            close = getattr(embedder, "close", None)
            if callable(close):
                await asyncio.to_thread(close)
            raise LocalEmbeddingGGUFRuntimeError("AI_EMBEDDING_MODEL_UNAVAILABLE", "Local embedding runtime is closed")
        self._embedder = embedder
        logger.info(
            "[ai-perf] local_embedding_model_load_done provider=local_gguf_embedding model=%s path=%s n_ctx=%s gpu_layers=%s cpu_threads=%s",
            self._config.model_id,
            model_path,
            self._config.context_size,
            self._config.gpu_layers,
            self._config.cpu_threads,
        )
        return embedder

    def _load_sync(self, model_path: Path):
        _ensure_windows_runtime_dependency_dirs()
        try:
            from llama_cpp.llama_embedding import LlamaEmbedding
        except ImportError as exc:
            raise LocalEmbeddingGGUFRuntimeError(
                "AI_EMBEDDING_PROVIDER_UNAVAILABLE",
                "llama-cpp-python embedding support is not installed",
            ) from exc

        kwargs: dict[str, Any] = {
            "model_path": str(model_path),
            "n_ctx": self._config.context_size,
            "n_gpu_layers": self._config.gpu_layers,
            "n_batch": self._config.batch_size,
            "n_ubatch": self._config.batch_size,
            "verbose": self._config.verbose,
        }
        if self._config.cpu_threads > 0:
            kwargs["n_threads"] = self._config.cpu_threads
        try:
            return LlamaEmbedding(**kwargs)
        except MemoryError as exc:
            raise LocalEmbeddingGGUFRuntimeError(
                "AI_EMBEDDING_RESOURCE_EXHAUSTED",
                "Insufficient memory to load local embedding model",
            ) from exc
        except Exception as exc:
            raise LocalEmbeddingGGUFRuntimeError(
                "AI_EMBEDDING_MODEL_LOAD_FAILED",
                f"Failed to load local embedding model: {exc}",
            ) from exc

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        if self._embedder is None:
            raise LocalEmbeddingGGUFRuntimeError(
                "AI_EMBEDDING_MODEL_UNAVAILABLE",
                "Local embedding model is not loaded",
            )
        try:
            vectors = self._embedder.embed(texts)
        except Exception as exc:
            raise LocalEmbeddingGGUFRuntimeError(
                "AI_EMBEDDING_GENERATION_FAILED",
                f"Local embedding generation failed: {exc}",
            ) from exc
        if not isinstance(vectors, list):
            raise LocalEmbeddingGGUFRuntimeError(
                "AI_EMBEDDING_GENERATION_FAILED",
                "Local embedding runtime returned an invalid payload",
            )
        if vectors and isinstance(vectors[0], float):
            return [list(float(value) for value in vectors)]
        return [list(float(value) for value in vector) for vector in vectors]


_embedding_runtime: LocalEmbeddingGGUFRuntime | None = None


def get_local_embedding_runtime() -> LocalEmbeddingGGUFRuntime:
    global _embedding_runtime
    if _embedding_runtime is None:
        _embedding_runtime = LocalEmbeddingGGUFRuntime()
    return _embedding_runtime

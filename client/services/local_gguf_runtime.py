"""Local GGUF runtime backed by llama-cpp-python.

The runtime keeps llama-cpp-python optional and lazily imports it only when a
local AI task actually needs the model.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from client.core import logging
from client.core.logging import setup_logging

setup_logging()
logger = logging.get_logger(__name__)


DEFAULT_MODEL_FILE = "qwen3.5-omni-2B-Q4_K_M.gguf"
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "resources" / "models" / DEFAULT_MODEL_FILE


@dataclass(slots=True)
class LocalGGUFConfig:
    """Configuration for one local GGUF model runtime."""

    model_path: str = field(default_factory=lambda: os.getenv("ASSISTIM_AI_MODEL_PATH", str(DEFAULT_MODEL_PATH)))
    model_id: str = field(default_factory=lambda: os.getenv("ASSISTIM_AI_MODEL_ID", "qwen3.5-omni-2B-Q4_K_M"))
    context_size: int = field(default_factory=lambda: _parse_int_env("ASSISTIM_AI_CONTEXT_SIZE", 4096))
    max_output_tokens: int = field(default_factory=lambda: _parse_int_env("ASSISTIM_AI_MAX_OUTPUT_TOKENS", 512))
    temperature: float = field(default_factory=lambda: _parse_float_env("ASSISTIM_AI_TEMPERATURE", 0.4))
    gpu_layers: int = field(default_factory=lambda: _parse_gpu_layers_env("ASSISTIM_AI_GPU_LAYERS", 0))
    verbose: bool = field(default_factory=lambda: os.getenv("ASSISTIM_AI_VERBOSE", "false").lower() == "true")


@dataclass(slots=True)
class LocalGGUFModelInfo:
    """Runtime model summary."""

    model: str
    model_path: str
    loaded: bool
    loading: bool = False
    runtime: str = "llama-cpp-python"
    context_size: int = 0
    max_output_tokens: int = 0
    gpu_layers: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LocalGGUFStreamChunk:
    """One streamed local generation delta."""

    content: str
    finish_reason: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class LocalGGUFRuntimeError(RuntimeError):
    """Runtime error carrying a stable AI error code string."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


def _parse_int_env(name: str, default: int) -> int:
    raw_value = str(os.getenv(name, "") or "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _parse_float_env(name: str, default: float) -> float:
    raw_value = str(os.getenv(name, "") or "").strip()
    if not raw_value:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _parse_gpu_layers_env(name: str, default: int) -> int:
    raw_value = str(os.getenv(name, "") or "").strip().lower()
    if not raw_value:
        return default
    if raw_value == "auto":
        return -1
    try:
        return int(raw_value)
    except ValueError:
        return default


def _extract_chat_content(data: dict[str, Any]) -> tuple[str, Optional[str], dict[str, int]]:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    return (
        str(message.get("content", "") or ""),
        choice.get("finish_reason"),
        dict(data.get("usage") or {}),
    )


def _extract_chat_delta(data: dict[str, Any]) -> tuple[str, Optional[str], dict[str, int]]:
    choice = (data.get("choices") or [{}])[0]
    delta = choice.get("delta") or {}
    return (
        str(delta.get("content", "") or ""),
        choice.get("finish_reason"),
        dict(data.get("usage") or {}),
    )


class LocalGGUFRuntime:
    """llama-cpp-python runtime wrapper for a single local model."""

    def __init__(self, config: LocalGGUFConfig | None = None) -> None:
        self._config = config or LocalGGUFConfig()
        self._llm = None
        self._load_lock = asyncio.Lock()
        self._load_task: asyncio.Task | None = None
        self._cancelled_task_ids: set[str] = set()
        self._active_task_ids: set[str] = set()
        self._closed = False

    @property
    def config(self) -> LocalGGUFConfig:
        """Return the runtime config."""
        return self._config

    def _model_path(self) -> Path:
        return Path(self._config.model_path).expanduser().resolve()

    def _assert_model_available(self) -> Path:
        model_path = self._model_path()
        if not model_path.exists():
            raise LocalGGUFRuntimeError(
                "AI_MODEL_NOT_FOUND",
                f"Local GGUF model not found: {model_path}",
            )
        if not model_path.is_file():
            raise LocalGGUFRuntimeError(
                "AI_MODEL_NOT_FOUND",
                f"Local GGUF model path is not a file: {model_path}",
            )
        return model_path

    async def health_check(self) -> dict[str, Any]:
        """Return basic model availability without loading the model."""
        model_path = self._assert_model_available()
        return {
            "model_path": str(model_path),
            "size_bytes": model_path.stat().st_size,
            "loaded": self._llm is not None,
            "loading": self._is_loading(),
        }

    async def get_model_info(self) -> LocalGGUFModelInfo:
        """Return runtime model metadata."""
        model_path = self._model_path()
        size_bytes = model_path.stat().st_size if model_path.exists() and model_path.is_file() else 0
        return LocalGGUFModelInfo(
            model=self._config.model_id,
            model_path=str(model_path),
            loaded=self._llm is not None,
            loading=self._is_loading(),
            context_size=self._config.context_size,
            max_output_tokens=self._config.max_output_tokens,
            gpu_layers=self._config.gpu_layers,
            metadata={"size_bytes": size_bytes},
        )

    def _is_loading(self) -> bool:
        task = self._load_task
        return bool(self._llm is None and task is not None and not task.done())

    async def load(self) -> None:
        """Load the GGUF model lazily."""
        if self._closed:
            raise LocalGGUFRuntimeError("AI_MODEL_UNAVAILABLE", "Local GGUF runtime is closed")
        if self._llm is not None:
            return
        task = await self._ensure_load_task()
        await asyncio.shield(task)

    async def warmup(self) -> None:
        """Ensure the local model is loaded for future requests."""
        await self.load()

    async def _ensure_load_task(self) -> asyncio.Task:
        async with self._load_lock:
            if self._llm is not None:
                completed = asyncio.get_running_loop().create_future()
                completed.set_result(self._llm)
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
        llm = await asyncio.to_thread(self._load_sync, model_path)
        if self._closed:
            await self._close_llm_instance(llm)
            raise LocalGGUFRuntimeError("AI_MODEL_UNAVAILABLE", "Local GGUF runtime is closed")
        self._llm = llm
        logger.info(
            "[ai-diag] local_model_load_done provider=local_gguf model=%s path=%s",
            self._config.model_id,
            model_path,
        )
        return llm

    def _load_sync(self, model_path: Path):
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise LocalGGUFRuntimeError(
                "AI_PROVIDER_UNAVAILABLE",
                "llama-cpp-python is not installed",
            ) from exc

        try:
            logger.info(
                "[ai-diag] local_model_load_start provider=local_gguf model=%s path=%s n_ctx=%s gpu_layers=%s",
                self._config.model_id,
                model_path,
                self._config.context_size,
                self._config.gpu_layers,
            )
            return Llama(
                model_path=str(model_path),
                n_ctx=self._config.context_size,
                n_gpu_layers=self._config.gpu_layers,
                verbose=self._config.verbose,
            )
        except LocalGGUFRuntimeError:
            raise
        except MemoryError as exc:
            raise LocalGGUFRuntimeError(
                "AI_RESOURCE_EXHAUSTED",
                "Insufficient memory to load local GGUF model",
            ) from exc
        except Exception as exc:
            raise LocalGGUFRuntimeError(
                "AI_MODEL_LOAD_FAILED",
                f"Failed to load local GGUF model: {exc}",
            ) from exc

    async def generate_once(
        self,
        *,
        task_id: str,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Generate one complete chat response."""
        await self.load()
        normalized_task_id = str(task_id or "").strip()
        self._cancelled_task_ids.discard(normalized_task_id)
        self._active_task_ids.add(normalized_task_id)
        try:
            self._raise_if_cancelled(normalized_task_id)
            data = await asyncio.to_thread(
                self._generate_once_sync,
                messages,
                temperature if temperature is not None else self._config.temperature,
                max_tokens or self._config.max_output_tokens,
            )
            content, finish_reason, usage = _extract_chat_content(dict(data or {}))
            self._raise_if_cancelled(normalized_task_id)
            return {
                "content": content,
                "model": model or self._config.model_id,
                "finish_reason": finish_reason,
                "usage": usage,
            }
        finally:
            self._active_task_ids.discard(normalized_task_id)
            self._cancelled_task_ids.discard(normalized_task_id)

    def _generate_once_sync(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        if self._llm is None:
            raise LocalGGUFRuntimeError("AI_MODEL_UNAVAILABLE", "Local model is not loaded")
        try:
            return self._llm.create_chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            )
        except Exception as exc:
            raise LocalGGUFRuntimeError(
                "AI_MODEL_UNAVAILABLE",
                f"Local generation failed: {exc}",
            ) from exc

    async def stream_chat(
        self,
        *,
        task_id: str,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[LocalGGUFStreamChunk]:
        """Stream chat deltas from llama-cpp-python without blocking the event loop."""
        await self.load()
        normalized_task_id = str(task_id or "").strip()
        self._cancelled_task_ids.discard(normalized_task_id)
        self._active_task_ids.add(normalized_task_id)

        queue: asyncio.Queue[LocalGGUFStreamChunk | BaseException | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def put_from_thread(item: LocalGGUFStreamChunk | BaseException | None) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, item)

        def worker() -> None:
            try:
                for raw_chunk in self._stream_sync(
                    messages,
                    temperature if temperature is not None else self._config.temperature,
                    max_tokens or self._config.max_output_tokens,
                ):
                    if self._is_cancelled(normalized_task_id):
                        put_from_thread(
                            LocalGGUFRuntimeError("AI_USER_CANCELLED", "Local generation cancelled")
                        )
                        return
                    content, finish_reason, usage = _extract_chat_delta(dict(raw_chunk or {}))
                    if content:
                        put_from_thread(
                            LocalGGUFStreamChunk(
                                content=content,
                                finish_reason=finish_reason,
                                metadata={"usage": usage, "model": model or self._config.model_id},
                            )
                        )
                put_from_thread(None)
            except BaseException as exc:
                put_from_thread(exc)

        worker_task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            self._active_task_ids.discard(normalized_task_id)
            self._cancelled_task_ids.discard(normalized_task_id)
            if not worker_task.done():
                await asyncio.wait({worker_task}, timeout=0)
            else:
                await worker_task

    def _stream_sync(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ):
        if self._llm is None:
            raise LocalGGUFRuntimeError("AI_MODEL_UNAVAILABLE", "Local model is not loaded")
        try:
            return self._llm.create_chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
        except Exception as exc:
            raise LocalGGUFRuntimeError(
                "AI_MODEL_UNAVAILABLE",
                f"Local streaming failed: {exc}",
            ) from exc

    async def cancel(self, task_id: str) -> None:
        """Mark one local task as cancelled."""
        normalized_task_id = str(task_id or "").strip()
        if normalized_task_id:
            self._cancelled_task_ids.add(normalized_task_id)

    def _is_cancelled(self, task_id: str) -> bool:
        return bool(task_id and task_id in self._cancelled_task_ids)

    def _raise_if_cancelled(self, task_id: str) -> None:
        if self._is_cancelled(task_id):
            raise LocalGGUFRuntimeError("AI_USER_CANCELLED", "Local generation cancelled")

    async def close(self) -> None:
        """Release runtime state."""
        self._closed = True
        for task_id in list(self._active_task_ids):
            await self.cancel(task_id)
        self._load_task = None
        llm = self._llm
        self._llm = None
        await self._close_llm_instance(llm)

    async def _close_llm_instance(self, llm) -> None:
        if llm is None:
            return
        close = getattr(llm, "close", None)
        if callable(close):
            await asyncio.to_thread(close)

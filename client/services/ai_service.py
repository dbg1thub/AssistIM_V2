"""AI service contracts and provider adapters."""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.network.http_client import get_http_client

setup_logging()
logger = logging.get_logger(__name__)


class AIProviderType(Enum):
    """Supported AI provider families."""

    OPENAI = "openai"
    OLLAMA = "ollama"
    HTTP = "http"
    LOCAL = "local"


class AITaskType(Enum):
    """AI task categories used for routing, diagnostics, and policy checks."""

    CHAT = "chat"
    REPLY_SUGGESTION = "reply_suggestion"
    INPUT_REWRITE = "input_rewrite"
    INPUT_POLISH = "input_polish"
    INPUT_SHORTEN = "input_shorten"
    TRANSLATE = "translate"
    SUMMARY = "summary"


class AIPrivacyScope(Enum):
    """Privacy scope declared by the caller for one AI request."""

    GENERAL = "general"
    DIRECT_CONTEXT = "direct_context"
    E2EE_PLAINTEXT = "e2ee_plaintext"
    SERVER_VISIBLE_AI = "server_visible_ai"


class AIStreamEventType(Enum):
    """Stream event types emitted by providers."""

    STARTED = "started"
    DELTA = "delta"
    DONE = "done"
    ERROR = "error"


class AIErrorCode(Enum):
    """Stable AI error codes surfaced by service and provider boundaries."""

    AI_MODEL_NOT_FOUND = "AI_MODEL_NOT_FOUND"
    AI_MODEL_LOAD_FAILED = "AI_MODEL_LOAD_FAILED"
    AI_MODEL_UNAVAILABLE = "AI_MODEL_UNAVAILABLE"
    AI_RUNTIME_BUSY = "AI_RUNTIME_BUSY"
    AI_CONTEXT_TOO_LONG = "AI_CONTEXT_TOO_LONG"
    AI_STREAM_INTERRUPTED = "AI_STREAM_INTERRUPTED"
    AI_USER_CANCELLED = "AI_USER_CANCELLED"
    AI_TIMEOUT = "AI_TIMEOUT"
    AI_PROVIDER_UNAVAILABLE = "AI_PROVIDER_UNAVAILABLE"
    AI_OUTPUT_INVALID = "AI_OUTPUT_INVALID"
    AI_PRIVACY_DENIED = "AI_PRIVACY_DENIED"
    AI_LOCAL_REQUIRED_UNAVAILABLE = "AI_LOCAL_REQUIRED_UNAVAILABLE"
    AI_RESOURCE_EXHAUSTED = "AI_RESOURCE_EXHAUSTED"
    AI_OUTPUT_TRUNCATED = "AI_OUTPUT_TRUNCATED"
    AI_MODEL_DOWNLOAD_FAILED = "AI_MODEL_DOWNLOAD_FAILED"
    AI_MODEL_CHECKSUM_FAILED = "AI_MODEL_CHECKSUM_FAILED"

    @classmethod
    def coerce(cls, value: object, *, default: "AIErrorCode") -> "AIErrorCode":
        """Return a known error code from an arbitrary value."""
        if isinstance(value, cls):
            return value
        normalized = str(value or "").strip()
        for code in cls:
            if normalized in {code.name, code.value}:
                return code
        return default


class AIServiceError(RuntimeError):
    """AI boundary error with a stable user-facing code."""

    def __init__(self, code: AIErrorCode, message: str = "") -> None:
        self.code = code
        super().__init__(message or code.value)


@dataclass(slots=True)
class AIRequest:
    """Provider-independent AI generation request."""

    messages: list[dict[str, str]]
    model: str = ""
    temperature: float = 0.7
    seed: int | None = None
    max_tokens: int = 2048
    stream: bool = True
    response_format: dict[str, Any] | None = None
    session_id: str = ""
    system_prompt: Optional[str] = None
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_type: AITaskType | str = AITaskType.CHAT
    must_be_local: bool = False
    privacy_scope: AIPrivacyScope | str = AIPrivacyScope.GENERAL
    max_output_chars: int = 0
    priority: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.task_id or "").strip():
            self.task_id = str(uuid.uuid4())
        self.task_type = _coerce_task_type(self.task_type)
        self.privacy_scope = _coerce_privacy_scope(self.privacy_scope)
        if self.seed is not None:
            try:
                self.seed = int(self.seed)
            except (TypeError, ValueError):
                self.seed = None
        self.max_tokens = max(1, int(self.max_tokens or 1))
        self.max_output_chars = max(0, int(self.max_output_chars or 0))


@dataclass(slots=True)
class AIResponse:
    """Final AI generation result."""

    content: str
    model: str
    task_id: str = ""
    provider: str = ""
    finish_reason: Optional[str] = None
    usage: dict[str, int] = field(default_factory=dict)
    truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AIStreamEvent:
    """One normalized provider stream event."""

    task_id: str
    event_type: AIStreamEventType | str
    session_id: str = ""
    content: str = ""
    finish_reason: Optional[str] = None
    response: Optional[AIResponse] = None
    error_code: Optional[AIErrorCode] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.event_type, str):
            self.event_type = AIStreamEventType(self.event_type)


@dataclass(slots=True)
class AIModelInfo:
    """Provider model and runtime summary."""

    provider: str
    model: str
    local: bool = False
    loaded: bool = False
    loading: bool = False
    runtime: str = ""
    model_path: str = ""
    context_size: int = 0
    max_output_tokens: int = 0
    gpu_layers: Optional[int] = None
    cpu_threads: int = 0
    supports_streaming: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


def _coerce_task_type(value: AITaskType | str) -> AITaskType:
    if isinstance(value, AITaskType):
        return value
    normalized = str(value or "").strip()
    try:
        return AITaskType(normalized)
    except ValueError:
        return AITaskType.CHAT


def _coerce_privacy_scope(value: AIPrivacyScope | str) -> AIPrivacyScope:
    if isinstance(value, AIPrivacyScope):
        return value
    normalized = str(value or "").strip()
    try:
        return AIPrivacyScope(normalized)
    except ValueError:
        return AIPrivacyScope.GENERAL


def _messages_for_request(request: AIRequest) -> list[dict[str, str]]:
    """Return OpenAI-style messages with an optional system prompt prepended."""
    messages: list[dict[str, str]] = []
    if request.system_prompt:
        messages.append({"role": "system", "content": str(request.system_prompt)})
    messages.extend(dict(message) for message in request.messages)
    return messages


def _truncate_response_if_needed(response: AIResponse, max_output_chars: int) -> AIResponse:
    """Apply a caller-level hard character cap."""
    if max_output_chars <= 0 or len(response.content) <= max_output_chars:
        return response
    return AIResponse(
        content=response.content[:max_output_chars],
        model=response.model,
        task_id=response.task_id,
        provider=response.provider,
        finish_reason=AIErrorCode.AI_OUTPUT_TRUNCATED.value,
        usage=dict(response.usage),
        truncated=True,
        metadata=dict(response.metadata),
    )


def _extract_openai_message_content(data: dict[str, Any]) -> tuple[str, Optional[str], dict[str, int]]:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    return (
        str(message.get("content", "") or ""),
        choice.get("finish_reason"),
        dict(data.get("usage") or {}),
    )


def _extract_stream_delta(chunk: dict[str, Any]) -> tuple[str, Optional[str], dict[str, int]]:
    choice = (chunk.get("choices") or [{}])[0]
    delta = choice.get("delta") or {}
    content = str(delta.get("content", "") or "")
    finish_reason = choice.get("finish_reason")
    usage = dict(chunk.get("usage") or {})
    return content, finish_reason, usage


class AIProvider(ABC):
    """Abstract base class for AI providers."""

    @property
    @abstractmethod
    def provider_type(self) -> AIProviderType:
        """Return provider type."""

    @abstractmethod
    async def generate_once(self, request: AIRequest) -> AIResponse:
        """Generate a complete non-streaming response."""

    @abstractmethod
    async def stream_chat(self, request: AIRequest) -> AsyncIterator[AIStreamEvent]:
        """Stream one response as normalized events."""
        if False:
            yield AIStreamEvent(task_id=request.task_id, event_type=AIStreamEventType.DONE)

    @abstractmethod
    async def cancel(self, task_id: str) -> None:
        """Cancel a provider task when supported."""

    @abstractmethod
    async def get_model_info(self) -> AIModelInfo:
        """Return provider model/runtime summary."""

    async def warmup(self) -> None:
        """Prepare provider runtime state for a future request."""
        return None

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""


class OpenAIProvider(AIProvider):
    """OpenAI-compatible hosted provider."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self._api_key = api_key
        self._base_url = base_url or "https://api.openai.com/v1"
        self._http = get_http_client()
        self._default_model = "gpt-3.5-turbo"

    @property
    def provider_type(self) -> AIProviderType:
        return AIProviderType.OPENAI

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def generate_once(self, request: AIRequest) -> AIResponse:
        payload = {
            "model": request.model or self._default_model,
            "messages": _messages_for_request(request),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        if request.response_format:
            payload["response_format"] = dict(request.response_format)
        data = await self._http.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            headers=self._headers(),
            use_auth=False,
        )
        content, finish_reason, usage = _extract_openai_message_content(dict(data or {}))
        response = AIResponse(
            content=content,
            model=str((data or {}).get("model") or request.model or self._default_model),
            task_id=request.task_id,
            provider=self.provider_type.value,
            finish_reason=finish_reason,
            usage=usage,
        )
        return _truncate_response_if_needed(response, request.max_output_chars)

    async def stream_chat(self, request: AIRequest) -> AsyncIterator[AIStreamEvent]:
        payload = {
            "model": request.model or self._default_model,
            "messages": _messages_for_request(request),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }
        if request.response_format:
            payload["response_format"] = dict(request.response_format)
        yield AIStreamEvent(
            task_id=request.task_id,
            session_id=request.session_id,
            event_type=AIStreamEventType.STARTED,
        )

        content_parts: list[str] = []
        finish_reason: Optional[str] = None
        usage: dict[str, int] = {}
        async for line in self._http.stream_lines(
            "POST",
            f"{self._base_url}/chat/completions",
            json=payload,
            headers=self._headers(),
            use_auth=False,
        ):
            if not line.startswith("data: "):
                continue
            if line == "data: [DONE]":
                finish_reason = finish_reason or "stop"
                break
            try:
                chunk = json.loads(line[6:])
            except json.JSONDecodeError as exc:
                logger.warning("Failed to parse OpenAI stream chunk: %s", exc)
                continue
            content, chunk_finish_reason, chunk_usage = _extract_stream_delta(chunk)
            if chunk_finish_reason:
                finish_reason = chunk_finish_reason
            if chunk_usage:
                usage = chunk_usage
            if not content:
                continue
            content_parts.append(content)
            yield AIStreamEvent(
                task_id=request.task_id,
                session_id=request.session_id,
                event_type=AIStreamEventType.DELTA,
                content=content,
            )

        response = _truncate_response_if_needed(
            AIResponse(
                content="".join(content_parts),
                model=request.model or self._default_model,
                task_id=request.task_id,
                provider=self.provider_type.value,
                finish_reason=finish_reason,
                usage=usage,
            ),
            request.max_output_chars,
        )
        yield AIStreamEvent(
            task_id=request.task_id,
            session_id=request.session_id,
            event_type=AIStreamEventType.DONE,
            finish_reason=response.finish_reason,
            response=response,
        )

    async def cancel(self, task_id: str) -> None:
        return None

    async def get_model_info(self) -> AIModelInfo:
        return AIModelInfo(
            provider=self.provider_type.value,
            model=self._default_model,
            local=False,
            loaded=True,
            loading=False,
            runtime="openai_compatible_http",
        )

    async def close(self) -> None:
        return None


class OllamaProvider(AIProvider):
    """Ollama local HTTP provider."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self._base_url = base_url
        self._http = get_http_client()
        self._default_model = "qwen2.5"

    @property
    def provider_type(self) -> AIProviderType:
        return AIProviderType.OLLAMA

    async def generate_once(self, request: AIRequest) -> AIResponse:
        payload = {
            "model": request.model or self._default_model,
            "messages": _messages_for_request(request),
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }
        data = await self._http.post(
            f"{self._base_url}/api/chat",
            json=payload,
            use_auth=False,
        )
        message = dict((data or {}).get("message") or {})
        response = AIResponse(
            content=str(message.get("content", "") or ""),
            model=request.model or self._default_model,
            task_id=request.task_id,
            provider=self.provider_type.value,
            finish_reason="stop" if (data or {}).get("done") else None,
        )
        return _truncate_response_if_needed(response, request.max_output_chars)

    async def stream_chat(self, request: AIRequest) -> AsyncIterator[AIStreamEvent]:
        payload = {
            "model": request.model or self._default_model,
            "messages": _messages_for_request(request),
            "stream": True,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }
        yield AIStreamEvent(
            task_id=request.task_id,
            session_id=request.session_id,
            event_type=AIStreamEventType.STARTED,
        )

        content_parts: list[str] = []
        finish_reason: Optional[str] = None
        async for line in self._http.stream_lines(
            "POST",
            f"{self._base_url}/api/chat",
            json=payload,
            use_auth=False,
        ):
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("Failed to parse Ollama stream chunk: %s", exc)
                continue
            content = str((chunk.get("message") or {}).get("content", "") or "")
            if chunk.get("done"):
                finish_reason = "stop"
            if not content:
                continue
            content_parts.append(content)
            yield AIStreamEvent(
                task_id=request.task_id,
                session_id=request.session_id,
                event_type=AIStreamEventType.DELTA,
                content=content,
            )

        response = _truncate_response_if_needed(
            AIResponse(
                content="".join(content_parts),
                model=request.model or self._default_model,
                task_id=request.task_id,
                provider=self.provider_type.value,
                finish_reason=finish_reason,
            ),
            request.max_output_chars,
        )
        yield AIStreamEvent(
            task_id=request.task_id,
            session_id=request.session_id,
            event_type=AIStreamEventType.DONE,
            finish_reason=response.finish_reason,
            response=response,
        )

    async def cancel(self, task_id: str) -> None:
        return None

    async def get_model_info(self) -> AIModelInfo:
        return AIModelInfo(
            provider=self.provider_type.value,
            model=self._default_model,
            local=True,
            loaded=True,
            loading=False,
            runtime="ollama_http",
        )

    async def close(self) -> None:
        return None


class HTTPProvider(OpenAIProvider):
    """Custom OpenAI-compatible HTTP provider."""

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ):
        super().__init__(api_key=api_key, base_url=base_url)
        self._custom_headers = headers or {}

    @property
    def provider_type(self) -> AIProviderType:
        return AIProviderType.HTTP

    def _headers(self) -> dict[str, str]:
        headers = dict(self._custom_headers)
        headers.setdefault("Content-Type", "application/json")
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers


class LocalGGUFProvider(AIProvider):
    """Local GGUF provider backed by llama-cpp-python runtime."""

    def __init__(self, runtime=None):
        if runtime is None:
            from client.services.local_gguf_runtime import LocalGGUFRuntime

            runtime = LocalGGUFRuntime()
        self._runtime = runtime

    @property
    def provider_type(self) -> AIProviderType:
        return AIProviderType.LOCAL

    async def generate_once(self, request: AIRequest) -> AIResponse:
        try:
            result = await self._runtime.generate_once(
                task_id=request.task_id,
                messages=_messages_for_request(request),
                model=request.model,
                temperature=request.temperature,
                seed=request.seed,
                response_format=request.response_format,
                max_tokens=request.max_tokens,
                task_type=getattr(request.task_type, "value", str(request.task_type)),
            )
        except Exception as exc:
            raise self._convert_runtime_error(exc) from exc
        response = AIResponse(
            content=str(result.get("content", "") or ""),
            model=str(result.get("model") or request.model or ""),
            task_id=request.task_id,
            provider="local_gguf",
            finish_reason=result.get("finish_reason"),
            usage=dict(result.get("usage") or {}),
            metadata=dict(result.get("metadata") or {}),
        )
        return _truncate_response_if_needed(response, request.max_output_chars)

    async def stream_chat(self, request: AIRequest) -> AsyncIterator[AIStreamEvent]:
        yield AIStreamEvent(
            task_id=request.task_id,
            session_id=request.session_id,
            event_type=AIStreamEventType.STARTED,
        )
        content_parts: list[str] = []
        truncated = False
        try:
            async for chunk in self._runtime.stream_chat(
                task_id=request.task_id,
                messages=_messages_for_request(request),
                model=request.model,
                temperature=request.temperature,
                seed=request.seed,
                response_format=request.response_format,
                max_tokens=request.max_tokens,
                task_type=getattr(request.task_type, "value", str(request.task_type)),
            ):
                content = str(getattr(chunk, "content", "") or "")
                if not content:
                    continue
                if request.max_output_chars > 0:
                    remaining = request.max_output_chars - sum(len(part) for part in content_parts)
                    if remaining <= 0:
                        truncated = True
                        await self.cancel(request.task_id)
                        break
                    if len(content) > remaining:
                        content = content[:remaining]
                        truncated = True
                content_parts.append(content)
                yield AIStreamEvent(
                    task_id=request.task_id,
                    session_id=request.session_id,
                    event_type=AIStreamEventType.DELTA,
                    content=content,
                    metadata=dict(getattr(chunk, "metadata", {}) or {}),
                )
                if truncated:
                    await self.cancel(request.task_id)
                    break
        except Exception as exc:
            raise self._convert_runtime_error(exc) from exc

        finish_reason = AIErrorCode.AI_OUTPUT_TRUNCATED.value if truncated else "stop"
        response = AIResponse(
            content="".join(content_parts),
            model=request.model,
            task_id=request.task_id,
            provider="local_gguf",
            finish_reason=finish_reason,
            truncated=truncated,
        )
        yield AIStreamEvent(
            task_id=request.task_id,
            session_id=request.session_id,
            event_type=AIStreamEventType.DONE,
            finish_reason=finish_reason,
            response=response,
        )

    async def cancel(self, task_id: str) -> None:
        await self._runtime.cancel(task_id)

    async def get_model_info(self) -> AIModelInfo:
        info = await self._runtime.get_model_info()
        return AIModelInfo(
            provider="local_gguf",
            model=str(getattr(info, "model", "") or ""),
            local=True,
            loaded=bool(getattr(info, "loaded", False)),
            loading=bool(getattr(info, "loading", False)),
            runtime=str(getattr(info, "runtime", "llama-cpp-python") or "llama-cpp-python"),
            model_path=str(getattr(info, "model_path", "") or ""),
            context_size=int(getattr(info, "context_size", 0) or 0),
            max_output_tokens=int(getattr(info, "max_output_tokens", 0) or 0),
            gpu_layers=getattr(info, "gpu_layers", None),
            cpu_threads=int(getattr(info, "cpu_threads", 0) or 0),
            supports_streaming=True,
            metadata=dict(getattr(info, "metadata", {}) or {}),
        )

    async def warmup(self) -> None:
        try:
            warmup = getattr(self._runtime, "warmup", None)
            if callable(warmup):
                await warmup()
                return
            await self._runtime.load()
        except Exception as exc:
            raise self._convert_runtime_error(exc) from exc

    async def close(self) -> None:
        await self._runtime.close()

    @staticmethod
    def _convert_runtime_error(exc: Exception) -> AIServiceError:
        code = AIErrorCode.coerce(
            getattr(exc, "code", ""),
            default=AIErrorCode.AI_MODEL_UNAVAILABLE,
        )
        return AIServiceError(code, str(exc) or code.value)


class AIService:
    """Provider boundary for AI generation requests."""

    def __init__(self, provider: Optional[AIProvider] = None):
        self._provider = provider

    @property
    def provider(self) -> Optional[AIProvider]:
        """Return the configured provider."""
        return self._provider

    def set_provider(self, provider: AIProvider) -> None:
        """Set the active provider."""
        self._provider = provider
        logger.info("AI provider set: %s", provider.provider_type.value)

    def _require_provider(self, request: AIRequest | None = None) -> AIProvider:
        if self._provider is None:
            raise AIServiceError(AIErrorCode.AI_PROVIDER_UNAVAILABLE, "AI provider not set")
        if request is not None and request.must_be_local and self._provider.provider_type != AIProviderType.LOCAL:
            raise AIServiceError(
                AIErrorCode.AI_LOCAL_REQUIRED_UNAVAILABLE,
                "Local AI is required but the active provider is not local",
            )
        return self._provider

    async def generate_once(self, request: AIRequest) -> AIResponse:
        """Generate a complete response with the active provider."""
        provider = self._require_provider(request)
        return await provider.generate_once(request)

    async def stream_chat(self, request: AIRequest) -> AsyncIterator[AIStreamEvent]:
        """Stream a response with the active provider."""
        provider = self._require_provider(request)
        async for event in provider.stream_chat(request):
            yield event

    async def cancel(self, task_id: str) -> None:
        """Cancel an active provider task when supported."""
        provider = self._require_provider()
        await provider.cancel(task_id)

    async def get_model_info(self) -> AIModelInfo:
        """Return the active provider model summary."""
        provider = self._require_provider()
        return await provider.get_model_info()

    async def warmup(self) -> None:
        """Warm up the active provider for future requests."""
        provider = self._require_provider()
        await provider.warmup()

    async def close(self) -> None:
        """Close the active provider."""
        if self._provider is not None:
            await self._provider.close()
            self._provider = None


_ai_service: Optional[AIService] = None


def peek_ai_service() -> Optional[AIService]:
    """Return the existing AI service singleton when present."""
    return _ai_service


def get_ai_service() -> AIService:
    """Return the global AI service singleton."""
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service

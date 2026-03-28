"""
AI Service Module

Service for AI chat with streaming support.
"""
import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.models.message import ChatMessage
from client.network.http_client import get_http_client


setup_logging()
logger = logging.get_logger(__name__)


class AIProviderType(Enum):
    """AI provider types."""
    
    OPENAI = "openai"
    OLLAMA = "ollama"
    LOCAL = "local"
    HTTP = "http"


@dataclass
class AIRequest:
    """AI chat request."""
    
    messages: list[dict[str, str]]
    model: str = "gpt-3.5-turbo"
    temperature: float = 0.7
    max_tokens: int = 2048
    stream: bool = True
    session_id: str = ""
    system_prompt: Optional[str] = None


@dataclass
class AIResponse:
    """AI chat response."""
    
    content: str
    model: str
    finish_reason: Optional[str] = None
    usage: dict[str, int] = field(default_factory=dict)


async def _stream_openai_compatible_chunks(
    http_client,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    on_chunk: Callable[[str], Any],
) -> tuple[str, Optional[str], dict[str, int]]:
    """Stream one OpenAI-compatible SSE response."""
    content_parts: list[str] = []
    finish_reason: Optional[str] = None
    usage: dict[str, int] = {}

    async for line in http_client.stream_lines(
        "POST",
        url,
        json=payload,
        headers=headers,
        use_auth=False,
    ):
        if not line.startswith("data: "):
            continue

        if line == "data: [DONE]":
            finish_reason = finish_reason or "stop"
            break

        try:
            chunk = json.loads(line[6:])
        except Exception as exc:
            logger.warning(f"Failed to parse stream chunk: {exc}")
            continue

        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        content = delta.get("content", "")
        if content:
            content_parts.append(content)
            on_chunk(content)

        finish_reason = choice.get("finish_reason") or finish_reason
        chunk_usage = chunk.get("usage")
        if isinstance(chunk_usage, dict):
            usage = chunk_usage

    return "".join(content_parts), finish_reason, usage


async def _stream_ndjson_chunks(
    http_client,
    url: str,
    payload: dict[str, Any],
    on_chunk: Callable[[str], Any],
) -> tuple[str, Optional[str]]:
    """Stream one newline-delimited JSON response."""
    content_parts: list[str] = []
    finish_reason: Optional[str] = None

    async for line in http_client.stream_lines(
        "POST",
        url,
        json=payload,
        use_auth=False,
    ):
        try:
            chunk = json.loads(line)
        except Exception as exc:
            logger.warning(f"Failed to parse stream chunk: {exc}")
            continue

        content = chunk.get("message", {}).get("content", "")
        if content:
            content_parts.append(content)
            on_chunk(content)

        if chunk.get("done"):
            finish_reason = "stop"
            break

    return "".join(content_parts), finish_reason


class AIProvider(ABC):
    """Abstract base class for AI providers."""
    
    @property
    @abstractmethod
    def provider_type(self) -> AIProviderType:
        """Return provider type."""
        pass
    
    @abstractmethod
    async def chat(self, request: AIRequest) -> AIResponse:
        """Send non-streaming chat request."""
        pass
    
    @abstractmethod
    async def stream_chat(
        self,
        request: AIRequest,
        on_chunk: Callable[[str], Any],
    ) -> AIResponse:
        """
        Send streaming chat request.
        
        Args:
            request: Chat request
            on_chunk: Callback for each chunk
        
        Returns:
            Final AI response
        """
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
        pass


class OpenAIProvider(AIProvider):
    """OpenAI API provider."""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self._api_key = api_key
        self._base_url = base_url or "https://api.openai.com/v1"
        self._http = get_http_client()
    
    @property
    def provider_type(self) -> AIProviderType:
        return AIProviderType.OPENAI
    
    async def chat(self, request: AIRequest) -> AIResponse:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        
        data = await self._http.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        
        choice = data["choices"][0]
        return AIResponse(
            content=choice["message"]["content"],
            model=data.get("model", request.model),
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage", {}),
        )
    
    async def stream_chat(
        self,
        request: AIRequest,
        on_chunk: Callable[[str], Any],
    ) -> AIResponse:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }

        content, finish_reason, usage = await _stream_openai_compatible_chunks(
            self._http,
            f"{self._base_url}/chat/completions",
            payload,
            headers,
            on_chunk,
        )

        return AIResponse(
            content=content,
            model=request.model,
            finish_reason=finish_reason,
            usage=usage,
        )
    
    async def close(self) -> None:
        pass


class OllamaProvider(AIProvider):
    """Ollama local provider."""
    
    def __init__(self, base_url: str = "http://localhost:11434"):
        self._base_url = base_url
        self._http = get_http_client()
    
    @property
    def provider_type(self) -> AIProviderType:
        return AIProviderType.OLLAMA
    
    async def chat(self, request: AIRequest) -> AIResponse:
        payload = {
            "model": request.model,
            "messages": request.messages,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }
        
        data = await self._http.post(
            f"{self._base_url}/api/chat",
            json=payload,
        )
        
        return AIResponse(
            content=data["message"]["content"],
            model=request.model,
            finish_reason="stop" if data.get("done") else None,
        )
    
    async def stream_chat(
        self,
        request: AIRequest,
        on_chunk: Callable[[str], Any],
    ) -> AIResponse:
        payload = {
            "model": request.model,
            "messages": request.messages,
            "stream": True,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }

        content, finish_reason = await _stream_ndjson_chunks(
            self._http,
            f"{self._base_url}/api/chat",
            payload,
            on_chunk,
        )

        return AIResponse(
            content=content,
            model=request.model,
            finish_reason=finish_reason,
        )
    
    async def close(self) -> None:
        pass


class HTTPProvider(AIProvider):
    """Custom HTTP API provider."""
    
    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ):
        self._base_url = base_url
        self._api_key = api_key
        self._custom_headers = headers or {}
        self._http = get_http_client()
    
    @property
    def provider_type(self) -> AIProviderType:
        return AIProviderType.HTTP
    
    async def chat(self, request: AIRequest) -> AIResponse:
        headers = dict(self._custom_headers)
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        
        payload = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        
        data = await self._http.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        
        choice = data["choices"][0]
        return AIResponse(
            content=choice["message"]["content"],
            model=data.get("model", request.model),
            finish_reason=choice.get("finish_reason"),
        )
    
    async def stream_chat(
        self,
        request: AIRequest,
        on_chunk: Callable[[str], Any],
    ) -> AIResponse:
        headers = dict(self._custom_headers)
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }

        content, finish_reason, _usage = await _stream_openai_compatible_chunks(
            self._http,
            f"{self._base_url}/chat/completions",
            payload,
            headers,
            on_chunk,
        )

        return AIResponse(
            content=content,
            model=request.model,
            finish_reason=finish_reason,
        )
    
    async def close(self) -> None:
        pass


class AIService:
    """
    Service for AI chat with streaming support.
    
    Responsibilities:
        - Manage AI providers
        - Stream AI responses
        - Handle message history
    """
    
    def __init__(self):
        self._provider: Optional[AIProvider] = None
        self._default_model = "gpt-3.5-turbo"
        self._default_temperature = 0.7
        self._default_max_tokens = 2048
    
    def set_provider(self, provider: AIProvider) -> None:
        """Set AI provider."""
        self._provider = provider
        logger.info(f"AI provider set: {provider.provider_type.value}")
    
    def set_default_model(self, model: str) -> None:
        """Set default model."""
        self._default_model = model
    
    def set_default_params(self, temperature: float = None, max_tokens: int = None) -> None:
        """Set default parameters."""
        if temperature is not None:
            self._default_temperature = temperature
        if max_tokens is not None:
            self._default_max_tokens = max_tokens
    
    @property
    def provider(self) -> Optional[AIProvider]:
        """Get current provider."""
        return self._provider
    
    def _build_messages(
        self,
        history: list[ChatMessage],
        system_prompt: Optional[str] = None,
    ) -> list[dict[str, str]]:
        """Build messages list for API."""
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        for msg in history:
            role = "assistant" if msg.is_ai else "user"
            messages.append({"role": role, "content": msg.content})
        
        return messages
    
    async def stream_chat(
        self,
        messages: list[ChatMessage],
        on_chunk: Callable[[str], Any],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        session_id: str = "",
    ) -> AIResponse:
        """
        Stream chat with AI.
        
        Args:
            messages: Conversation history
            on_chunk: Callback for each chunk (throttled to ~30ms)
            model: Model name
            temperature: Sampling temperature
            max_tokens: Max tokens
            system_prompt: System prompt
            session_id: Session ID
        
        Returns:
            Final AI response
        """
        if not self._provider:
            raise RuntimeError("AI provider not set")
        
        request = AIRequest(
            messages=self._build_messages(messages, system_prompt),
            model=model or self._default_model,
            temperature=temperature or self._default_temperature,
            max_tokens=max_tokens or self._default_max_tokens,
            stream=True,
            session_id=session_id,
            system_prompt=system_prompt,
        )
        
        return await self._provider.stream_chat(request, on_chunk)
    
    async def chat(
        self,
        messages: list[ChatMessage],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> AIResponse:
        """
        Non-streaming chat with AI.
        
        Args:
            messages: Conversation history
            model: Model name
            temperature: Sampling temperature
            max_tokens: Max tokens
            system_prompt: System prompt
        
        Returns:
            AI response
        """
        if not self._provider:
            raise RuntimeError("AI provider not set")
        
        request = AIRequest(
            messages=self._build_messages(messages, system_prompt),
            model=model or self._default_model,
            temperature=temperature or self._default_temperature,
            max_tokens=max_tokens or self._default_max_tokens,
            stream=False,
            system_prompt=system_prompt,
        )
        
        return await self._provider.chat(request)
    
    async def close(self) -> None:
        """Close provider."""
        if self._provider:
            await self._provider.close()
            self._provider = None


_ai_service: Optional[AIService] = None


def get_ai_service() -> AIService:
    """Get the global AI service instance."""
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service


def create_provider(
    provider_type: AIProviderType,
    **kwargs,
) -> AIProvider:
    """
    Factory function to create AI provider.
    
    Args:
        provider_type: Type of provider
        **kwargs: Provider-specific arguments
    
    Returns:
        AIProvider instance
    """
    if provider_type == AIProviderType.OPENAI:
        return OpenAIProvider(
            api_key=kwargs.get("api_key"),
            base_url=kwargs.get("base_url"),
        )
    elif provider_type == AIProviderType.OLLAMA:
        return OllamaProvider(
            base_url=kwargs.get("base_url", "http://localhost:11434"),
        )
    elif provider_type == AIProviderType.HTTP:
        return HTTPProvider(
            base_url=kwargs["base_url"],
            api_key=kwargs.get("api_key"),
            headers=kwargs.get("headers"),
        )
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")

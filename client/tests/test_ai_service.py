from __future__ import annotations

import asyncio
import sys
import types

if "aiohttp" not in sys.modules:
    aiohttp = types.ModuleType("aiohttp")

    class _DummyClientError(Exception):
        pass

    class _DummyClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class _DummyFormData:
        def __init__(self):
            self.fields = []

        def add_field(self, name, value, **kwargs):
            self.fields.append({'name': name, 'value': value, **kwargs})

    class _DummyClientSession:
        def __init__(self, *args, **kwargs):
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class _DummyClientResponse:
        status = 200

    aiohttp.ClientError = _DummyClientError
    aiohttp.FormData = _DummyFormData
    aiohttp.ClientTimeout = _DummyClientTimeout
    aiohttp.ClientSession = _DummyClientSession
    aiohttp.ClientResponse = _DummyClientResponse
    sys.modules["aiohttp"] = aiohttp

from client.services import ai_service as ai_service_module


class FakeStreamingHttpClient:
    def __init__(self, lines: list[str]) -> None:
        self.lines = list(lines)
        self.stream_calls: list[dict] = []
        self.ensure_session_calls = 0

    async def stream_lines(self, method: str, url: str, json=None, headers=None, use_auth=None):
        self.stream_calls.append(
            {
                'method': method,
                'url': url,
                'json': dict(json or {}),
                'headers': dict(headers or {}),
                'use_auth': use_auth,
            }
        )
        for line in self.lines:
            yield line

    async def _ensure_session(self):
        self.ensure_session_calls += 1
        raise AssertionError('AI providers should use HTTPClient.stream_lines, not _ensure_session')


def test_openai_provider_stream_chat_uses_public_http_stream_boundary(monkeypatch) -> None:
    fake_http = FakeStreamingHttpClient(
        [
            'data: {"choices": [{"delta": {"content": "Hel"}}]}',
            'data: {"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}], "usage": {"total_tokens": 5}}',
            'data: [DONE]',
        ]
    )

    monkeypatch.setattr(ai_service_module, 'get_http_client', lambda: fake_http)

    async def scenario() -> None:
        provider = ai_service_module.OpenAIProvider(api_key='demo-key', base_url='https://api.example.com/v1')
        chunks: list[str] = []
        response = await provider.stream_chat(
            ai_service_module.AIRequest(messages=[{'role': 'user', 'content': 'hello'}], model='demo-model'),
            chunks.append,
        )

        assert chunks == ['Hel', 'lo']
        assert response.content == 'Hello'
        assert response.finish_reason == 'stop'
        assert response.usage == {'total_tokens': 5}
        assert fake_http.ensure_session_calls == 0
        assert fake_http.stream_calls == [
            {
                'method': 'POST',
                'url': 'https://api.example.com/v1/chat/completions',
                'json': {
                    'model': 'demo-model',
                    'messages': [{'role': 'user', 'content': 'hello'}],
                    'temperature': 0.7,
                    'max_tokens': 2048,
                    'stream': True,
                },
                'headers': {
                    'Authorization': 'Bearer demo-key',
                    'Content-Type': 'application/json',
                },
                'use_auth': False,
            }
        ]

    asyncio.run(scenario())


def test_ollama_provider_stream_chat_uses_public_http_stream_boundary(monkeypatch) -> None:
    fake_http = FakeStreamingHttpClient(
        [
            '{"message": {"content": "Hi"}, "done": false}',
            '{"message": {"content": " there"}, "done": true}',
        ]
    )

    monkeypatch.setattr(ai_service_module, 'get_http_client', lambda: fake_http)

    async def scenario() -> None:
        provider = ai_service_module.OllamaProvider(base_url='http://localhost:11434')
        chunks: list[str] = []
        response = await provider.stream_chat(
            ai_service_module.AIRequest(messages=[{'role': 'user', 'content': 'hello'}], model='qwen2.5'),
            chunks.append,
        )

        assert chunks == ['Hi', ' there']
        assert response.content == 'Hi there'
        assert response.finish_reason == 'stop'
        assert fake_http.ensure_session_calls == 0
        assert fake_http.stream_calls == [
            {
                'method': 'POST',
                'url': 'http://localhost:11434/api/chat',
                'json': {
                    'model': 'qwen2.5',
                    'messages': [{'role': 'user', 'content': 'hello'}],
                    'stream': True,
                    'options': {
                        'temperature': 0.7,
                        'num_predict': 2048,
                    },
                },
                'headers': {},
                'use_auth': False,
            }
        ]

    asyncio.run(scenario())


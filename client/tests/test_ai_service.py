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
    def __init__(self, lines: list[str], post_response: dict | None = None) -> None:
        self.lines = list(lines)
        self.post_response = dict(post_response or {})
        self.stream_calls: list[dict] = []
        self.post_calls: list[dict] = []
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

    async def post(self, url: str, json=None, headers=None, use_auth=None):
        self.post_calls.append(
            {
                'url': url,
                'json': dict(json or {}),
                'headers': dict(headers or {}),
                'use_auth': use_auth,
            }
        )
        return dict(self.post_response)

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
        request = ai_service_module.AIRequest(
            messages=[{'role': 'user', 'content': 'hello'}],
            model='demo-model',
            task_id='task-1',
        )
        events = [event async for event in provider.stream_chat(request)]
        chunks = [event.content for event in events if event.event_type == ai_service_module.AIStreamEventType.DELTA]
        response = events[-1].response

        assert chunks == ['Hel', 'lo']
        assert response is not None
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
        request = ai_service_module.AIRequest(
            messages=[{'role': 'user', 'content': 'hello'}],
            model='qwen2.5',
            task_id='task-2',
        )
        events = [event async for event in provider.stream_chat(request)]
        chunks = [event.content for event in events if event.event_type == ai_service_module.AIStreamEventType.DELTA]
        response = events[-1].response

        assert chunks == ['Hi', ' there']
        assert response is not None
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


def test_openai_provider_generate_once_does_not_use_app_auth(monkeypatch) -> None:
    fake_http = FakeStreamingHttpClient(
        [],
        post_response={
            'model': 'demo-model',
            'choices': [{'message': {'content': 'done'}, 'finish_reason': 'stop'}],
            'usage': {'total_tokens': 3},
        },
    )
    monkeypatch.setattr(ai_service_module, 'get_http_client', lambda: fake_http)

    async def scenario() -> None:
        provider = ai_service_module.OpenAIProvider(api_key='demo-key', base_url='https://api.example.com/v1')
        response = await provider.generate_once(
            ai_service_module.AIRequest(
                messages=[{'role': 'user', 'content': 'hello'}],
                model='demo-model',
                task_id='task-3',
            )
        )

        assert response.content == 'done'
        assert fake_http.post_calls == [
            {
                'url': 'https://api.example.com/v1/chat/completions',
                'json': {
                    'model': 'demo-model',
                    'messages': [{'role': 'user', 'content': 'hello'}],
                    'temperature': 0.7,
                    'max_tokens': 2048,
                    'stream': False,
                },
                'headers': {
                    'Authorization': 'Bearer demo-key',
                    'Content-Type': 'application/json',
                },
                'use_auth': False,
            }
        ]

    asyncio.run(scenario())


def test_ai_service_rejects_remote_provider_when_local_is_required() -> None:
    async def scenario() -> None:
        service = ai_service_module.AIService(ai_service_module.OpenAIProvider(api_key='demo'))
        request = ai_service_module.AIRequest(
            messages=[{'role': 'user', 'content': 'hello'}],
            must_be_local=True,
        )
        try:
            await service.generate_once(request)
        except ai_service_module.AIServiceError as exc:
            assert exc.code == ai_service_module.AIErrorCode.AI_LOCAL_REQUIRED_UNAVAILABLE
        else:
            raise AssertionError('remote provider should be rejected for must_be_local requests')

    asyncio.run(scenario())


class FakeLocalRuntimeChunk:
    def __init__(self, content: str) -> None:
        self.content = content
        self.metadata = {}


class FakeLocalRuntime:
    def __init__(self) -> None:
        self.cancelled: list[str] = []
        self.warmup_calls = 0

    async def generate_once(self, **kwargs):
        return {
            'content': 'local result',
            'model': kwargs.get('model') or 'local-model',
            'finish_reason': 'stop',
            'usage': {'total_tokens': 4},
        }

    async def stream_chat(self, **kwargs):
        for content in ['lo', 'cal']:
            yield FakeLocalRuntimeChunk(content)

    async def cancel(self, task_id: str) -> None:
        self.cancelled.append(task_id)

    async def get_model_info(self):
        return type(
            'Info',
            (),
            {
                'model': 'local-model',
                'loaded': True,
                'loading': False,
                'runtime': 'fake',
                'model_path': 'model.gguf',
                'context_size': 4096,
                'max_output_tokens': 512,
                'gpu_layers': 0,
                'metadata': {},
            },
        )()

    async def warmup(self) -> None:
        self.warmup_calls += 1

    async def close(self) -> None:
        return None


def test_local_gguf_provider_streams_fake_runtime_chunks() -> None:
    async def scenario() -> None:
        provider = ai_service_module.LocalGGUFProvider(runtime=FakeLocalRuntime())
        request = ai_service_module.AIRequest(
            messages=[{'role': 'user', 'content': 'hello'}],
            task_id='local-task',
            must_be_local=True,
        )
        events = [event async for event in provider.stream_chat(request)]

        assert [event.event_type for event in events] == [
            ai_service_module.AIStreamEventType.STARTED,
            ai_service_module.AIStreamEventType.DELTA,
            ai_service_module.AIStreamEventType.DELTA,
            ai_service_module.AIStreamEventType.DONE,
        ]
        assert ''.join(event.content for event in events) == 'local'
        assert events[-1].response is not None
        assert events[-1].response.content == 'local'

    asyncio.run(scenario())


def test_ai_service_warmup_delegates_to_local_provider_runtime() -> None:
    async def scenario() -> None:
        runtime = FakeLocalRuntime()
        service = ai_service_module.AIService(ai_service_module.LocalGGUFProvider(runtime=runtime))

        await service.warmup()

        assert runtime.warmup_calls == 1

    asyncio.run(scenario())


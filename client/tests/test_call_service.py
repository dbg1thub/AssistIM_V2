from __future__ import annotations

import asyncio
import sys
import types


if 'aiohttp' not in sys.modules:
    aiohttp = types.ModuleType('aiohttp')

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

        async def close(self):
            self.closed = True

    class _DummyClientResponse:
        status = 200

        async def json(self):
            return {}

        async def text(self):
            return ''

    aiohttp.ClientError = _DummyClientError
    aiohttp.FormData = _DummyFormData
    aiohttp.ClientTimeout = _DummyClientTimeout
    aiohttp.ClientSession = _DummyClientSession
    aiohttp.ClientResponse = _DummyClientResponse
    sys.modules['aiohttp'] = aiohttp

from client.services import call_service as call_service_module


class FakeHTTPClient:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.get_calls: list[str] = []

    async def get(self, path: str):
        self.get_calls.append(path)
        return self.payload


def test_call_service_fetch_ice_servers_normalizes_backend_payload(monkeypatch) -> None:
    async def scenario() -> None:
        fake_http = FakeHTTPClient(
            {
                'ice_servers': [
                    {'urls': ['stun:stun.example.org:3478']},
                    {'urls': 'turn:turn.example.org:3478?transport=udp', 'username': 'alice', 'credential': 'secret'},
                    {'urls': []},
                    'ignored',
                ]
            }
        )
        monkeypatch.setattr(call_service_module, 'get_http_client', lambda: fake_http)

        service = call_service_module.CallService()
        payload = await service.fetch_ice_servers()

        assert fake_http.get_calls == ['/calls/ice-servers']
        assert payload == [
            {'urls': ['stun:stun.example.org:3478']},
            {'urls': ['turn:turn.example.org:3478?transport=udp'], 'username': 'alice', 'credential': 'secret'},
        ]

    asyncio.run(scenario())

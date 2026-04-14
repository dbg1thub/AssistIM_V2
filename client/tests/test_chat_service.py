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

from client.services import chat_service as chat_service_module

class FakeHTTPClient:
    def __init__(self) -> None:
        self.post_calls: list[dict] = []
        self.get_calls: list[dict] = []

    async def get(self, path: str, params=None):
        self.get_calls.append({"path": path, "params": params})
        return {"session": {"id": "session-1", "session_type": "direct"}, "messages": [{"message_id": "m-1"}]}

    async def post(self, path: str, json=None):
        self.post_calls.append({"path": path, "json": json})
        return {"success": True}


def test_chat_service_fetch_messages_uses_session_seq_cursor(monkeypatch) -> None:
    async def scenario() -> None:
        fake_http = FakeHTTPClient()
        monkeypatch.setattr(chat_service_module, "get_http_client", lambda: fake_http)

        service = chat_service_module.ChatService()
        messages = await service.fetch_messages("session-1", limit=25, before_seq=7)

        assert messages == [{"message_id": "m-1"}]
        assert fake_http.get_calls == [
            {
                "path": "/sessions/session-1/messages",
                "params": {"limit": 25, "before_seq": 7},
            }
        ]

    asyncio.run(scenario())

def test_chat_service_persist_read_receipt_uses_canonical_message_id(monkeypatch) -> None:
    async def scenario() -> None:
        fake_http = FakeHTTPClient()
        monkeypatch.setattr(chat_service_module, "get_http_client", lambda: fake_http)

        service = chat_service_module.ChatService()
        await service.persist_read_receipt("session-1", "message-1")

        assert fake_http.post_calls == [
            {
                "path": "/messages/read/batch",
                "json": {"session_id": "session-1", "message_id": "message-1"},
            }
        ]

    asyncio.run(scenario())

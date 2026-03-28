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
            return ""

    aiohttp.ClientError = _DummyClientError
    aiohttp.ClientTimeout = _DummyClientTimeout
    aiohttp.ClientSession = _DummyClientSession
    aiohttp.ClientResponse = _DummyClientResponse
    sys.modules["aiohttp"] = aiohttp

from client.services import session_service as session_service_module


class FakeHTTPClient:
    def __init__(self) -> None:
        self.post_calls: list[dict] = []

    async def post(self, path: str, json=None):
        self.post_calls.append({"path": path, "json": json})
        return {"id": "session-direct-1", "name": "Bob"}


def test_session_service_create_direct_session_uses_direct_endpoint(monkeypatch) -> None:
    async def scenario() -> None:
        fake_http = FakeHTTPClient()
        monkeypatch.setattr(session_service_module, "get_http_client", lambda: fake_http)

        service = session_service_module.SessionService()
        payload = await service.create_direct_session("bob", display_name="Bob")

        assert payload == {"id": "session-direct-1", "name": "Bob"}
        assert fake_http.post_calls == [
            {
                "path": "/sessions/direct",
                "json": {"participant_ids": ["bob"], "name": "Bob"},
            }
        ]

    asyncio.run(scenario())

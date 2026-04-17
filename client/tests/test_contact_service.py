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
            self.fields.append({"name": name, "value": value, **kwargs})

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
    aiohttp.FormData = _DummyFormData
    aiohttp.ClientTimeout = _DummyClientTimeout
    aiohttp.ClientSession = _DummyClientSession
    aiohttp.ClientResponse = _DummyClientResponse
    sys.modules["aiohttp"] = aiohttp

from client.services import contact_service as contact_service_module


class FakeHTTPClient:
    def __init__(self) -> None:
        self.post_calls: list[dict] = []

    async def post(self, path: str, json=None):
        self.post_calls.append({"path": path, "json": json})
        return {"group": {"id": "group-1", "name": "Core Team"}}


def test_contact_service_create_group_defaults_to_e2ee_group(monkeypatch) -> None:
    async def scenario() -> None:
        fake_http = FakeHTTPClient()
        monkeypatch.setattr(contact_service_module, "get_http_client", lambda: fake_http)

        service = contact_service_module.ContactService()
        payload = await service.create_group("Core Team", ["bob", "charlie"])

        assert payload == {"group": {"id": "group-1", "name": "Core Team"}}
        assert fake_http.post_calls == [
            {
                "path": "/groups",
                "json": {
                    "name": "Core Team",
                    "member_ids": ["bob", "charlie"],
                    "encryption_mode": "e2ee_group",
                },
            }
        ]

    asyncio.run(scenario())

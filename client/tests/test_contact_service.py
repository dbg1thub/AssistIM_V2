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
        self.delete_calls: list[str] = []

    async def post(self, path: str, json=None):
        self.post_calls.append({"path": path, "json": json})
        if path == "/blocks":
            return {"block": {"is_blocked": True, "blocked_user_id": str((json or {}).get("target_user_id") or "")}}
        return {"group": {"id": "group-1", "name": "Core Team"}}

    async def delete(self, path: str):
        self.delete_calls.append(path)
        return {"block": {"is_blocked": False}}


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


def test_contact_service_block_and_unblock_use_blocks_endpoint(monkeypatch) -> None:
    async def scenario() -> None:
        fake_http = FakeHTTPClient()
        monkeypatch.setattr(contact_service_module, "get_http_client", lambda: fake_http)

        service = contact_service_module.ContactService()
        block_payload = await service.block_user("user-2")
        unblock_payload = await service.unblock_user("user-2")

        assert block_payload == {"block": {"is_blocked": True, "blocked_user_id": "user-2"}}
        assert unblock_payload == {"block": {"is_blocked": False}}
        assert fake_http.post_calls == [
            {
                "path": "/blocks",
                "json": {
                    "target_user_id": "user-2",
                },
            }
        ]
        assert fake_http.delete_calls == ["/blocks/user-2"]

    asyncio.run(scenario())

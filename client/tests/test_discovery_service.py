from __future__ import annotations

import asyncio

from client.services import discovery_service as discovery_service_module


class FakeHttpClient:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.get_calls: list[tuple[str, dict | None]] = []

    async def get(self, path: str, params: dict | None = None):
        self.get_calls.append((path, params))
        return self.payload


def test_discovery_service_fetch_moments_requires_paged_envelope(monkeypatch) -> None:
    fake_http = FakeHttpClient(
        {
            "total": 1,
            "page": 1,
            "size": 20,
            "items": [{"id": "moment-1", "content": "hello"}],
        }
    )
    monkeypatch.setattr(discovery_service_module, "get_http_client", lambda: fake_http)

    async def scenario() -> None:
        service = discovery_service_module.DiscoveryService()
        payload = await service.fetch_moments(user_id="user-1")

        assert fake_http.get_calls == [("/moments", {"user_id": "user-1"})]
        assert payload == [{"id": "moment-1", "content": "hello"}]

    asyncio.run(scenario())


def test_discovery_service_fetch_moments_rejects_legacy_list_payload(monkeypatch) -> None:
    fake_http = FakeHttpClient([{"id": "legacy-moment"}])
    monkeypatch.setattr(discovery_service_module, "get_http_client", lambda: fake_http)

    async def scenario() -> None:
        service = discovery_service_module.DiscoveryService()
        payload = await service.fetch_moments()

        assert fake_http.get_calls == [("/moments", None)]
        assert payload == []

    asyncio.run(scenario())

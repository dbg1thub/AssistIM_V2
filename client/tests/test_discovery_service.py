from __future__ import annotations

import asyncio

from client.services import discovery_service as discovery_service_module


class FakeHttpClient:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.get_calls: list[tuple[str, dict | None]] = []
        self.post_calls: list[tuple[str, dict | None]] = []

    async def get(self, path: str, params: dict | None = None):
        self.get_calls.append((path, params))
        return self.payload

    async def post(self, path: str, json: dict | None = None):
        self.post_calls.append((path, json))
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


def test_discovery_service_create_moment_posts_media_items(monkeypatch) -> None:
    fake_http = FakeHttpClient({"id": "moment-1", "content": "caption"})
    monkeypatch.setattr(discovery_service_module, "get_http_client", lambda: fake_http)
    media = [
        {
            "type": "image",
            "url": "/uploads/moments/photo.png",
            "original_name": "photo.png",
            "mime_type": "image/png",
            "size_bytes": 123,
        },
        {
            "type": "video",
            "url": "/uploads/moments/clip.mp4",
            "original_name": "clip.mp4",
            "mime_type": "video/mp4",
            "size_bytes": 456,
        },
    ]

    async def scenario() -> None:
        service = discovery_service_module.DiscoveryService()
        payload = await service.create_moment("caption", media=media)

        assert fake_http.post_calls == [("/moments", {"content": "caption", "media": media})]
        assert payload == {"id": "moment-1", "content": "caption"}

    asyncio.run(scenario())


def test_discovery_service_add_comment_posts_optional_image(monkeypatch) -> None:
    fake_http = FakeHttpClient({"id": "comment-1", "content": "nice"})
    monkeypatch.setattr(discovery_service_module, "get_http_client", lambda: fake_http)
    image = {
        "type": "image",
        "url": "/uploads/moments/comment.png",
        "original_name": "comment.png",
        "mime_type": "image/png",
        "size_bytes": 789,
    }

    async def scenario() -> None:
        service = discovery_service_module.DiscoveryService()
        payload = await service.add_comment("moment-1", "nice", image=image)

        assert fake_http.post_calls == [
            ("/moments/moment-1/comments", {"content": "nice", "image": image})
        ]
        assert payload == {"id": "comment-1", "content": "nice"}

    asyncio.run(scenario())

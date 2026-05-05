from __future__ import annotations

import asyncio

from client.services import discovery_service as discovery_service_module


class FakeHttpClient:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.get_calls: list[tuple[str, dict | None]] = []
        self.post_calls: list[tuple[str, dict | None]] = []
        self.patch_calls: list[tuple[str, dict | None]] = []

    async def get(self, path: str, params: dict | None = None):
        self.get_calls.append((path, params))
        return self.payload

    async def post(self, path: str, json: dict | None = None):
        self.post_calls.append((path, json))
        return self.payload

    async def patch(self, path: str, json: dict | None = None):
        self.patch_calls.append((path, json))
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


def test_discovery_service_get_moment_fetches_detail(monkeypatch) -> None:
    fake_http = FakeHttpClient(
        {
            "id": "moment-1",
            "content": "full detail",
            "comments": [
                {"id": "comment-1", "content": "preview"},
                {"id": "comment-2", "content": "full"},
            ],
            "comments_truncated": False,
        }
    )
    monkeypatch.setattr(discovery_service_module, "get_http_client", lambda: fake_http)

    async def scenario() -> None:
        service = discovery_service_module.DiscoveryService()
        payload = await service.get_moment("moment-1")

        assert fake_http.get_calls == [("/moments/moment-1", None)]
        assert payload["id"] == "moment-1"
        assert len(payload["comments"]) == 2
        assert payload["comments_truncated"] is False

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
        payload = await service.create_moment(
            "caption",
            media=media,
            visibility_scope="include",
            visibility_user_ids=["user-2", "user-3"],
        )

        assert fake_http.post_calls == [
            (
                "/moments",
                {
                    "content": "caption",
                    "media": media,
                    "visibility_scope": "include",
                    "visibility_user_ids": ["user-2", "user-3"],
                },
            )
        ]
        assert payload == {"id": "moment-1", "content": "caption"}

    asyncio.run(scenario())


def test_discovery_service_fetches_and_updates_moment_privacy_settings(monkeypatch) -> None:
    fake_http = FakeHttpClient(
        {
            "hide_my_moments_user_ids": ["user-2"],
            "hide_their_moments_user_ids": ["user-3"],
            "visible_time_scope": "month",
        }
    )
    monkeypatch.setattr(discovery_service_module, "get_http_client", lambda: fake_http)

    async def scenario() -> None:
        service = discovery_service_module.DiscoveryService()
        loaded = await service.fetch_moment_privacy_settings()
        updated = await service.update_moment_privacy_settings(
            hide_my_moments_user_ids=["user-2"],
            hide_their_moments_user_ids=["user-3"],
            visible_time_scope="month",
        )

        assert fake_http.get_calls == [("/moments/privacy", None)]
        assert fake_http.patch_calls == [
            (
                "/moments/privacy",
                {
                    "hide_my_moments_user_ids": ["user-2"],
                    "hide_their_moments_user_ids": ["user-3"],
                    "visible_time_scope": "month",
                },
            )
        ]
        assert loaded["visible_time_scope"] == "month"
        assert updated["hide_my_moments_user_ids"] == ["user-2"]

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

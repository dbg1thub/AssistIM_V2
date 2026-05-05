"""Moment API contract tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.v1 import moments as moment_routes
from app.core.database import SessionLocal
from app.core.errors import ErrorCode
from app.models.moment import Moment
from app.schemas.moment import MAX_MOMENT_COMMENT_LENGTH, MAX_MOMENT_CONTENT_LENGTH, MAX_MOMENT_MEDIA_ITEMS


def _make_friends(client: TestClient, auth_header, requester: dict, receiver: dict) -> None:
    send_response = client.post(
        "/api/v1/friends/requests",
        json={"target_user_id": receiver["user"]["id"], "message": "moment visibility"},
        headers=auth_header(requester["access_token"]),
    )
    assert send_response.status_code == 200
    request_id = send_response.json()["data"]["request"]["request_id"]

    accept_response = client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=auth_header(receiver["access_token"]),
    )
    assert accept_response.status_code == 200


def test_moment_like_and_unlike_echo_state_changes(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_like_alice", "Moment Like Alice")

    create_response = client.post(
        "/api/v1/moments",
        json={"content": "hello moments"},
        headers=auth_header(alice["access_token"]),
    )
    assert create_response.status_code == 200
    moment_id = create_response.json()["data"]["id"]

    first_like = client.post(
        f"/api/v1/moments/{moment_id}/likes",
        headers=auth_header(alice["access_token"]),
    )
    assert first_like.status_code == 200
    assert first_like.json()["data"] == {"liked": True, "changed": True}

    second_like = client.post(
        f"/api/v1/moments/{moment_id}/likes",
        headers=auth_header(alice["access_token"]),
    )
    assert second_like.status_code == 200
    assert second_like.json()["data"] == {"liked": True, "changed": False}

    first_unlike = client.delete(
        f"/api/v1/moments/{moment_id}/likes",
        headers=auth_header(alice["access_token"]),
    )
    assert first_unlike.status_code == 200
    assert first_unlike.json()["data"] == {"liked": False, "changed": True}

    second_unlike = client.delete(
        f"/api/v1/moments/{moment_id}/likes",
        headers=auth_header(alice["access_token"]),
    )
    assert second_unlike.status_code == 200
    assert second_unlike.json()["data"] == {"liked": False, "changed": False}


def test_moment_mutations_broadcast_realtime_refresh_notifications(
    client: TestClient,
    user_factory,
    auth_header,
    monkeypatch,
) -> None:
    alice = user_factory("moment_refresh_alice", "Moment Refresh Alice")
    bob = user_factory("moment_refresh_bob", "Moment Refresh Bob")
    _make_friends(client, auth_header, alice, bob)
    alice_headers = auth_header(alice["access_token"])
    bob_headers = auth_header(bob["access_token"])
    send_json_to_users = AsyncMock(return_value=set())
    online_user_ids = [alice["user"]["id"], bob["user"]["id"]]

    monkeypatch.setattr(moment_routes.connection_manager, "online_user_ids", lambda: list(online_user_ids))
    monkeypatch.setattr(moment_routes.connection_manager, "send_json_to_users", send_json_to_users)

    create_response = client.post(
        "/api/v1/moments",
        json={"content": "realtime moment"},
        headers=alice_headers,
    )
    assert create_response.status_code == 200
    moment_id = create_response.json()["data"]["id"]
    assert send_json_to_users.await_count == 1
    assert send_json_to_users.await_args_list[-1].args[0] == online_user_ids
    create_payload = send_json_to_users.await_args_list[-1].args[1]
    assert create_payload["type"] == "moment_refresh"
    assert create_payload["data"] == {
        "reason": "moment_created",
        "action": "moment_created",
        "moment_id": moment_id,
        "actor_user_id": alice["user"]["id"],
        "owner_user_id": alice["user"]["id"],
        "changed": True,
    }

    like_response = client.post(
        f"/api/v1/moments/{moment_id}/likes",
        headers=bob_headers,
    )
    assert like_response.status_code == 200
    assert send_json_to_users.await_count == 2
    like_payload = send_json_to_users.await_args_list[-1].args[1]
    assert like_payload["data"]["action"] == "moment_liked"
    assert like_payload["data"]["actor_user_id"] == bob["user"]["id"]
    assert like_payload["data"]["owner_user_id"] == alice["user"]["id"]
    assert like_payload["data"]["changed"] is True

    duplicate_like = client.post(
        f"/api/v1/moments/{moment_id}/likes",
        headers=bob_headers,
    )
    assert duplicate_like.status_code == 200
    assert duplicate_like.json()["data"]["changed"] is False
    assert send_json_to_users.await_count == 2

    unlike_response = client.delete(
        f"/api/v1/moments/{moment_id}/likes",
        headers=bob_headers,
    )
    assert unlike_response.status_code == 200
    assert send_json_to_users.await_count == 3
    unlike_payload = send_json_to_users.await_args_list[-1].args[1]
    assert unlike_payload["data"]["action"] == "moment_unliked"
    assert unlike_payload["data"]["actor_user_id"] == bob["user"]["id"]
    assert unlike_payload["data"]["owner_user_id"] == alice["user"]["id"]
    assert unlike_payload["data"]["changed"] is True

    comment_response = client.post(
        f"/api/v1/moments/{moment_id}/comments",
        json={"content": "refresh comment"},
        headers=bob_headers,
    )
    assert comment_response.status_code == 200
    assert send_json_to_users.await_count == 4
    comment_payload = send_json_to_users.await_args_list[-1].args[1]
    assert comment_payload["data"]["action"] == "moment_commented"
    assert comment_payload["data"]["actor_user_id"] == bob["user"]["id"]
    assert comment_payload["data"]["owner_user_id"] == alice["user"]["id"]
    assert comment_payload["data"]["changed"] is True


def test_moment_and_comment_author_payloads_are_canonical(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_author_alice", "Moment Author Alice")
    bob = user_factory("moment_author_bob", "Moment Author Bob")
    _make_friends(client, auth_header, alice, bob)

    create_response = client.post(
        "/api/v1/moments",
        json={"content": "author contract"},
        headers=auth_header(alice["access_token"]),
    )
    assert create_response.status_code == 200
    created = create_response.json()["data"]
    moment_id = created["id"]

    assert "username" not in created
    assert "nickname" not in created
    assert "avatar" not in created
    assert created["author"]["id"] == alice["user"]["id"]
    assert created["author"]["username"] == alice["user"]["username"]

    comment_response = client.post(
        f"/api/v1/moments/{moment_id}/comments",
        json={"content": "comment contract"},
        headers=auth_header(bob["access_token"]),
    )
    assert comment_response.status_code == 200
    comment = comment_response.json()["data"]
    assert "username" not in comment
    assert "nickname" not in comment
    assert "avatar" not in comment
    assert comment["author"]["id"] == bob["user"]["id"]
    assert comment["author"]["username"] == bob["user"]["username"]

    list_response = client.get(
        "/api/v1/moments",
        headers=auth_header(bob["access_token"]),
    )
    assert list_response.status_code == 200
    listed = list_response.json()["data"]["items"][0]
    assert "username" not in listed
    assert "nickname" not in listed
    assert "avatar" not in listed
    assert listed["author"]["id"] == alice["user"]["id"]
    assert listed["comments"][0]["author"]["id"] == bob["user"]["id"]


def test_moment_feed_is_limited_to_self_and_friends(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_feed_alice", "Moment Feed Alice")
    bob = user_factory("moment_feed_bob", "Moment Feed Bob")
    charlie = user_factory("moment_feed_charlie", "Moment Feed Charlie")
    _make_friends(client, auth_header, alice, bob)

    alice_headers = auth_header(alice["access_token"])
    bob_headers = auth_header(bob["access_token"])
    charlie_headers = auth_header(charlie["access_token"])

    alice_moment = client.post(
        "/api/v1/moments",
        json={"content": "alice visible"},
        headers=alice_headers,
    ).json()["data"]
    bob_moment = client.post(
        "/api/v1/moments",
        json={"content": "bob visible"},
        headers=bob_headers,
    ).json()["data"]
    charlie_moment = client.post(
        "/api/v1/moments",
        json={"content": "charlie hidden"},
        headers=charlie_headers,
    ).json()["data"]

    alice_feed = client.get("/api/v1/moments", headers=alice_headers)
    assert alice_feed.status_code == 200
    alice_payload = alice_feed.json()["data"]
    assert alice_payload["total"] == 2
    assert {item["id"] for item in alice_payload["items"]} == {alice_moment["id"], bob_moment["id"]}

    charlie_feed = client.get("/api/v1/moments", headers=charlie_headers)
    assert charlie_feed.status_code == 200
    charlie_payload = charlie_feed.json()["data"]
    assert charlie_payload["total"] == 1
    assert {item["id"] for item in charlie_payload["items"]} == {charlie_moment["id"]}


def test_moment_user_feed_requires_self_or_friend(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_user_feed_alice", "Moment User Feed Alice")
    bob = user_factory("moment_user_feed_bob", "Moment User Feed Bob")
    charlie = user_factory("moment_user_feed_charlie", "Moment User Feed Charlie")
    _make_friends(client, auth_header, alice, bob)

    alice_headers = auth_header(alice["access_token"])
    bob_headers = auth_header(bob["access_token"])
    charlie_headers = auth_header(charlie["access_token"])

    bob_moment = client.post(
        "/api/v1/moments",
        json={"content": "bob friend feed"},
        headers=bob_headers,
    ).json()["data"]
    client.post(
        "/api/v1/moments",
        json={"content": "charlie non-friend feed"},
        headers=charlie_headers,
    )

    friend_feed = client.get(
        f"/api/v1/moments?user_id={bob['user']['id']}",
        headers=alice_headers,
    )
    assert friend_feed.status_code == 200
    friend_payload = friend_feed.json()["data"]
    assert friend_payload["total"] == 1
    assert [item["id"] for item in friend_payload["items"]] == [bob_moment["id"]]

    hidden_feed = client.get(
        f"/api/v1/moments?user_id={charlie['user']['id']}",
        headers=alice_headers,
    )
    assert hidden_feed.status_code == 403
    assert hidden_feed.json()["code"] == ErrorCode.FORBIDDEN


def test_moment_detail_and_interactions_require_visibility(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_private_alice", "Moment Private Alice")
    charlie = user_factory("moment_private_charlie", "Moment Private Charlie")
    alice_headers = auth_header(alice["access_token"])
    charlie_headers = auth_header(charlie["access_token"])

    create_response = client.post(
        "/api/v1/moments",
        json={"content": "charlie private moment"},
        headers=charlie_headers,
    )
    assert create_response.status_code == 200
    moment_id = create_response.json()["data"]["id"]

    detail_response = client.get(f"/api/v1/moments/{moment_id}", headers=alice_headers)
    assert detail_response.status_code == 403
    assert detail_response.json()["code"] == ErrorCode.FORBIDDEN

    like_response = client.post(f"/api/v1/moments/{moment_id}/likes", headers=alice_headers)
    assert like_response.status_code == 403
    assert like_response.json()["code"] == ErrorCode.FORBIDDEN

    unlike_response = client.delete(f"/api/v1/moments/{moment_id}/likes", headers=alice_headers)
    assert unlike_response.status_code == 403
    assert unlike_response.json()["code"] == ErrorCode.FORBIDDEN

    comment_response = client.post(
        f"/api/v1/moments/{moment_id}/comments",
        json={"content": "hidden comment"},
        headers=alice_headers,
    )
    assert comment_response.status_code == 403
    assert comment_response.json()["code"] == ErrorCode.FORBIDDEN


def test_moment_per_post_visibility_scopes_control_feed_detail_and_interactions(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_scope_alice", "Moment Scope Alice")
    bob = user_factory("moment_scope_bob", "Moment Scope Bob")
    charlie = user_factory("moment_scope_charlie", "Moment Scope Charlie")
    stranger = user_factory("moment_scope_stranger", "Moment Scope Stranger")
    _make_friends(client, auth_header, alice, bob)
    _make_friends(client, auth_header, alice, charlie)

    alice_headers = auth_header(alice["access_token"])
    bob_headers = auth_header(bob["access_token"])
    charlie_headers = auth_header(charlie["access_token"])

    private_response = client.post(
        "/api/v1/moments",
        json={"content": "only me", "visibility_scope": "private"},
        headers=alice_headers,
    )
    assert private_response.status_code == 200
    private_moment = private_response.json()["data"]
    assert private_moment["visibility_scope"] == "private"
    assert private_moment["visibility_user_ids"] == []

    include_response = client.post(
        "/api/v1/moments",
        json={
            "content": "bob only",
            "visibility_scope": "include",
            "visibility_user_ids": [bob["user"]["id"]],
        },
        headers=alice_headers,
    )
    assert include_response.status_code == 200
    include_moment = include_response.json()["data"]
    assert include_moment["visibility_scope"] == "include"
    assert include_moment["visibility_user_ids"] == [bob["user"]["id"]]

    exclude_response = client.post(
        "/api/v1/moments",
        json={
            "content": "not bob",
            "visibility_scope": "exclude",
            "visibility_user_ids": [bob["user"]["id"]],
        },
        headers=alice_headers,
    )
    assert exclude_response.status_code == 200
    exclude_moment = exclude_response.json()["data"]

    bob_feed = client.get("/api/v1/moments", headers=bob_headers)
    assert bob_feed.status_code == 200
    assert {item["id"] for item in bob_feed.json()["data"]["items"]} == {include_moment["id"]}

    charlie_feed = client.get("/api/v1/moments", headers=charlie_headers)
    assert charlie_feed.status_code == 200
    assert {item["id"] for item in charlie_feed.json()["data"]["items"]} == {exclude_moment["id"]}

    alice_feed = client.get("/api/v1/moments", headers=alice_headers)
    assert alice_feed.status_code == 200
    assert {item["id"] for item in alice_feed.json()["data"]["items"]} == {
        private_moment["id"],
        include_moment["id"],
        exclude_moment["id"],
    }

    visible_detail = client.get(f"/api/v1/moments/{include_moment['id']}", headers=bob_headers)
    assert visible_detail.status_code == 200
    assert visible_detail.json()["data"]["visibility_user_ids"] == []

    hidden_detail = client.get(f"/api/v1/moments/{exclude_moment['id']}", headers=bob_headers)
    assert hidden_detail.status_code == 403
    assert hidden_detail.json()["code"] == ErrorCode.FORBIDDEN

    hidden_like = client.post(f"/api/v1/moments/{exclude_moment['id']}/likes", headers=bob_headers)
    assert hidden_like.status_code == 403
    assert hidden_like.json()["code"] == ErrorCode.FORBIDDEN

    hidden_comment = client.post(
        f"/api/v1/moments/{exclude_moment['id']}/comments",
        json={"content": "hidden comment"},
        headers=bob_headers,
    )
    assert hidden_comment.status_code == 403
    assert hidden_comment.json()["code"] == ErrorCode.FORBIDDEN

    invalid_target = client.post(
        "/api/v1/moments",
        json={
            "content": "invalid target",
            "visibility_scope": "include",
            "visibility_user_ids": [stranger["user"]["id"]],
        },
        headers=alice_headers,
    )
    assert invalid_target.status_code == 400
    assert invalid_target.json()["code"] == ErrorCode.INVALID_REQUEST


def test_moment_privacy_settings_filter_feed_detail_interactions_and_time_scope(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_privacy_alice", "Moment Privacy Alice")
    bob = user_factory("moment_privacy_bob", "Moment Privacy Bob")
    _make_friends(client, auth_header, alice, bob)

    alice_headers = auth_header(alice["access_token"])
    bob_headers = auth_header(bob["access_token"])

    recent = client.post(
        "/api/v1/moments",
        json={"content": "recent public"},
        headers=alice_headers,
    ).json()["data"]
    old = client.post(
        "/api/v1/moments",
        json={"content": "old public"},
        headers=alice_headers,
    ).json()["data"]
    with SessionLocal() as db:
        old_moment = db.get(Moment, old["id"])
        assert old_moment is not None
        old_moment.created_at = datetime.now(timezone.utc) - timedelta(days=10)
        db.add(old_moment)
        db.commit()

    default_settings = client.get("/api/v1/moments/privacy", headers=alice_headers)
    assert default_settings.status_code == 200
    assert default_settings.json()["data"] == {
        "hide_my_moments_user_ids": [],
        "hide_their_moments_user_ids": [],
        "visible_time_scope": "all",
    }

    bob_initial_feed = client.get("/api/v1/moments", headers=bob_headers)
    assert bob_initial_feed.status_code == 200
    assert {item["id"] for item in bob_initial_feed.json()["data"]["items"]} == {recent["id"], old["id"]}

    time_update = client.patch(
        "/api/v1/moments/privacy",
        json={"visible_time_scope": "three_days"},
        headers=alice_headers,
    )
    assert time_update.status_code == 200
    assert time_update.json()["data"]["visible_time_scope"] == "three_days"

    bob_time_limited_feed = client.get("/api/v1/moments", headers=bob_headers)
    assert bob_time_limited_feed.status_code == 200
    assert {item["id"] for item in bob_time_limited_feed.json()["data"]["items"]} == {recent["id"]}

    old_detail = client.get(f"/api/v1/moments/{old['id']}", headers=bob_headers)
    assert old_detail.status_code == 403
    assert old_detail.json()["code"] == ErrorCode.FORBIDDEN

    alice_own_feed = client.get("/api/v1/moments", headers=alice_headers)
    assert alice_own_feed.status_code == 200
    assert {item["id"] for item in alice_own_feed.json()["data"]["items"]} == {recent["id"], old["id"]}

    hide_from_bob = client.patch(
        "/api/v1/moments/privacy",
        json={"hide_my_moments_user_ids": [bob["user"]["id"]], "visible_time_scope": "all"},
        headers=alice_headers,
    )
    assert hide_from_bob.status_code == 200
    assert hide_from_bob.json()["data"]["hide_my_moments_user_ids"] == [bob["user"]["id"]]

    bob_hidden_feed = client.get("/api/v1/moments", headers=bob_headers)
    assert bob_hidden_feed.status_code == 200
    assert bob_hidden_feed.json()["data"]["items"] == []

    recent_like = client.post(f"/api/v1/moments/{recent['id']}/likes", headers=bob_headers)
    assert recent_like.status_code == 403
    assert recent_like.json()["code"] == ErrorCode.FORBIDDEN

    reset_alice = client.patch(
        "/api/v1/moments/privacy",
        json={"hide_my_moments_user_ids": [], "visible_time_scope": "all"},
        headers=alice_headers,
    )
    assert reset_alice.status_code == 200

    bob_hides_alice = client.patch(
        "/api/v1/moments/privacy",
        json={"hide_their_moments_user_ids": [alice["user"]["id"]]},
        headers=bob_headers,
    )
    assert bob_hides_alice.status_code == 200
    assert bob_hides_alice.json()["data"]["hide_their_moments_user_ids"] == [alice["user"]["id"]]

    bob_filtered_feed = client.get("/api/v1/moments", headers=bob_headers)
    assert bob_filtered_feed.status_code == 200
    assert bob_filtered_feed.json()["data"]["items"] == []


def test_moment_create_schema_strips_content_and_rejects_invalid_payloads(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_schema_alice", "Moment Schema Alice")
    headers = auth_header(alice["access_token"])

    created_response = client.post(
        "/api/v1/moments",
        json={"content": "  stripped moment  "},
        headers=headers,
    )
    assert created_response.status_code == 200
    assert created_response.json()["data"]["content"] == "stripped moment"

    blank_response = client.post(
        "/api/v1/moments",
        json={"content": "   "},
        headers=headers,
    )
    assert blank_response.status_code == 422

    extra_response = client.post(
        "/api/v1/moments",
        json={"content": "valid", "extra": "ignored-before"},
        headers=headers,
    )
    assert extra_response.status_code == 422

    too_long_response = client.post(
        "/api/v1/moments",
        json={"content": "x" * (MAX_MOMENT_CONTENT_LENGTH + 1)},
        headers=headers,
    )
    assert too_long_response.status_code == 422


def test_moment_create_accepts_image_gallery_and_single_video_media(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_media_alice", "Moment Media Alice")
    headers = auth_header(alice["access_token"])
    image_media = [
        {
            "type": "image",
            "url": "/uploads/moments/photo.png",
            "original_name": "photo.png",
            "mime_type": "image/png",
            "size_bytes": 123,
        },
        {
            "type": "image",
            "url": "/uploads/moments/photo-2.png",
            "original_name": "photo-2.png",
            "mime_type": "image/png",
            "size_bytes": 234,
        },
    ]
    video_media = [
        {
            "type": "video",
            "url": "/uploads/moments/clip.mp4",
            "original_name": "clip.mp4",
            "mime_type": "video/mp4",
            "size_bytes": 456,
        },
    ]

    create_response = client.post(
        "/api/v1/moments",
        json={"content": "  media moment  ", "media": image_media},
        headers=headers,
    )
    assert create_response.status_code == 200
    created = create_response.json()["data"]
    moment_id = created["id"]
    assert created["content"] == "media moment"
    assert created["media"] == image_media
    assert created["images"] == ["/uploads/moments/photo.png", "/uploads/moments/photo-2.png"]
    assert created["videos"] == []

    video_response = client.post(
        "/api/v1/moments",
        json={"content": "", "media": video_media},
        headers=headers,
    )
    assert video_response.status_code == 200
    video_created = video_response.json()["data"]
    assert video_created["media"] == video_media
    assert video_created["images"] == []
    assert video_created["videos"] == ["/uploads/moments/clip.mp4"]

    list_response = client.get("/api/v1/moments", headers=headers)
    assert list_response.status_code == 200
    listed = next(item for item in list_response.json()["data"]["items"] if item["id"] == moment_id)
    assert listed["id"] == moment_id
    assert listed["media"] == image_media
    assert listed["images"] == ["/uploads/moments/photo.png", "/uploads/moments/photo-2.png"]
    assert listed["videos"] == []

    detail_response = client.get(f"/api/v1/moments/{moment_id}", headers=headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["media"] == image_media
    assert detail["images"] == ["/uploads/moments/photo.png", "/uploads/moments/photo-2.png"]
    assert detail["videos"] == []


def test_moment_create_requires_content_or_media_and_valid_media(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_media_schema_alice", "Moment Media Schema Alice")
    headers = auth_header(alice["access_token"])

    empty_response = client.post(
        "/api/v1/moments",
        json={"content": "   ", "media": []},
        headers=headers,
    )
    assert empty_response.status_code == 422

    media_only_response = client.post(
        "/api/v1/moments",
        json={"content": "   ", "media": [{"type": "image", "url": "/uploads/photo.png"}]},
        headers=headers,
    )
    assert media_only_response.status_code == 200
    assert media_only_response.json()["data"]["content"] == ""

    too_many_response = client.post(
        "/api/v1/moments",
        json={
            "content": "too many",
            "media": [
                {"type": "image", "url": f"/uploads/photo-{index}.png"}
                for index in range(MAX_MOMENT_MEDIA_ITEMS + 1)
            ],
        },
        headers=headers,
    )
    assert too_many_response.status_code == 422

    invalid_type_response = client.post(
        "/api/v1/moments",
        json={"content": "invalid", "media": [{"type": "audio", "url": "/uploads/audio.mp3"}]},
        headers=headers,
    )
    assert invalid_type_response.status_code == 422

    blank_url_response = client.post(
        "/api/v1/moments",
        json={"content": "invalid", "media": [{"type": "image", "url": "   "}]},
        headers=headers,
    )
    assert blank_url_response.status_code == 422

    mixed_media_response = client.post(
        "/api/v1/moments",
        json={
            "content": "mixed",
            "media": [
                {"type": "image", "url": "/uploads/photo.png"},
                {"type": "video", "url": "/uploads/video.mp4"},
            ],
        },
        headers=headers,
    )
    assert mixed_media_response.status_code == 422

    multiple_video_response = client.post(
        "/api/v1/moments",
        json={
            "content": "videos",
            "media": [
                {"type": "video", "url": "/uploads/video-1.mp4"},
                {"type": "video", "url": "/uploads/video-2.mp4"},
            ],
        },
        headers=headers,
    )
    assert multiple_video_response.status_code == 422


def test_moment_comment_schema_strips_content_and_rejects_invalid_payloads(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_comment_schema_alice", "Moment Comment Schema Alice")
    headers = auth_header(alice["access_token"])
    create_response = client.post(
        "/api/v1/moments",
        json={"content": "comment target"},
        headers=headers,
    )
    assert create_response.status_code == 200
    moment_id = create_response.json()["data"]["id"]

    comment_response = client.post(
        f"/api/v1/moments/{moment_id}/comments",
        json={"content": "  stripped comment  "},
        headers=headers,
    )
    assert comment_response.status_code == 200
    assert comment_response.json()["data"]["content"] == "stripped comment"

    blank_response = client.post(
        f"/api/v1/moments/{moment_id}/comments",
        json={"content": "   "},
        headers=headers,
    )
    assert blank_response.status_code == 422

    extra_response = client.post(
        f"/api/v1/moments/{moment_id}/comments",
        json={"content": "valid", "extra": "ignored-before"},
        headers=headers,
    )
    assert extra_response.status_code == 422

    too_long_response = client.post(
        f"/api/v1/moments/{moment_id}/comments",
        json={"content": "x" * (MAX_MOMENT_COMMENT_LENGTH + 1)},
        headers=headers,
    )
    assert too_long_response.status_code == 422


def test_moment_comment_accepts_one_image(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_comment_image_alice", "Moment Comment Image Alice")
    bob = user_factory("moment_comment_image_bob", "Moment Comment Image Bob")
    _make_friends(client, auth_header, alice, bob)
    alice_headers = auth_header(alice["access_token"])
    bob_headers = auth_header(bob["access_token"])
    create_response = client.post(
        "/api/v1/moments",
        json={"content": "comment image target"},
        headers=alice_headers,
    )
    assert create_response.status_code == 200
    moment_id = create_response.json()["data"]["id"]

    image = {
        "type": "image",
        "url": "/uploads/moments/comment.png",
        "original_name": "comment.png",
        "mime_type": "image/png",
        "size_bytes": 321,
    }
    comment_response = client.post(
        f"/api/v1/moments/{moment_id}/comments",
        json={"content": "  image comment  ", "image": image},
        headers=bob_headers,
    )
    assert comment_response.status_code == 200
    comment = comment_response.json()["data"]
    assert comment["content"] == "image comment"
    assert comment["image"] == image

    detail_response = client.get(
        f"/api/v1/moments/{moment_id}",
        headers=alice_headers,
    )
    assert detail_response.status_code == 200
    detail_comment = detail_response.json()["data"]["comments"][0]
    assert detail_comment["image"] == image


def test_moment_comment_rejects_empty_and_non_image_attachment(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_comment_img_schema", "Moment Comment Image Schema Alice")
    headers = auth_header(alice["access_token"])
    create_response = client.post(
        "/api/v1/moments",
        json={"content": "comment image schema target"},
        headers=headers,
    )
    assert create_response.status_code == 200
    moment_id = create_response.json()["data"]["id"]

    empty_response = client.post(
        f"/api/v1/moments/{moment_id}/comments",
        json={"content": "   "},
        headers=headers,
    )
    assert empty_response.status_code == 422

    image_only_response = client.post(
        f"/api/v1/moments/{moment_id}/comments",
        json={"content": "   ", "image": {"type": "image", "url": "/uploads/comment.png"}},
        headers=headers,
    )
    assert image_only_response.status_code == 200
    assert image_only_response.json()["data"]["content"] == ""

    video_response = client.post(
        f"/api/v1/moments/{moment_id}/comments",
        json={"content": "video", "image": {"type": "video", "url": "/uploads/comment.mp4"}},
        headers=headers,
    )
    assert video_response.status_code == 422


def test_moment_list_returns_paged_summary_without_liker_roster(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_paged_alice", "Moment Paged Alice")
    bob = user_factory("moment_paged_bob", "Moment Paged Bob")
    _make_friends(client, auth_header, alice, bob)
    alice_headers = auth_header(alice["access_token"])
    bob_headers = auth_header(bob["access_token"])

    first_response = client.post(
        "/api/v1/moments",
        json={"content": "older moment"},
        headers=alice_headers,
    )
    assert first_response.status_code == 200

    target_response = client.post(
        "/api/v1/moments",
        json={"content": "paged summary target"},
        headers=alice_headers,
    )
    assert target_response.status_code == 200
    moment_id = target_response.json()["data"]["id"]

    like_response = client.post(
        f"/api/v1/moments/{moment_id}/likes",
        headers=bob_headers,
    )
    assert like_response.status_code == 200

    for index in range(4):
        comment_response = client.post(
            f"/api/v1/moments/{moment_id}/comments",
            json={"content": f"comment {index}"},
            headers=bob_headers,
        )
        assert comment_response.status_code == 200

    list_response = client.get(
        "/api/v1/moments?page=1&size=1",
        headers=bob_headers,
    )
    assert list_response.status_code == 200
    payload = list_response.json()["data"]
    assert payload["page"] == 1
    assert payload["size"] == 1
    assert payload["total"] == 2
    assert len(payload["items"]) == 1
    listed = payload["items"][0]
    assert listed["id"] == moment_id
    assert listed["like_count"] == 1
    assert listed["is_liked"] is True
    assert listed["comment_count"] == 4
    assert listed["comments_truncated"] is True
    assert len(listed["comments"]) == 3
    assert "liked_user_ids" not in listed

    detail_response = client.get(
        f"/api/v1/moments/{moment_id}",
        headers=bob_headers,
    )
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["comment_count"] == 4
    assert detail["comments_truncated"] is False
    assert len(detail["comments"]) == 4
    assert "liked_user_ids" not in detail

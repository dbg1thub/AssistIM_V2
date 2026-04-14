"""Moment API contract tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.schemas.moment import MAX_MOMENT_COMMENT_LENGTH, MAX_MOMENT_CONTENT_LENGTH


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


def test_moment_and_comment_author_payloads_are_canonical(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_author_alice", "Moment Author Alice")
    bob = user_factory("moment_author_bob", "Moment Author Bob")

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


def test_moment_list_returns_paged_summary_without_liker_roster(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("moment_paged_alice", "Moment Paged Alice")
    bob = user_factory("moment_paged_bob", "Moment Paged Bob")
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

"""Moment API contract tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


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
    listed = list_response.json()["data"][0]
    assert "username" not in listed
    assert "nickname" not in listed
    assert "avatar" not in listed
    assert listed["author"]["id"] == alice["user"]["id"]
    assert listed["comments"][0]["author"]["id"] == bob["user"]["id"]
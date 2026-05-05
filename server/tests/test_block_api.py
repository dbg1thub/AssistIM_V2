"""User block API contract tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.v1 import blocks as block_routes
from app.core.errors import ErrorCode


def _make_friends(client: TestClient, auth_header, requester: dict, receiver: dict) -> None:
    request_response = client.post(
        "/api/v1/friends/requests",
        json={"target_user_id": receiver["user"]["id"], "message": "block contract"},
        headers=auth_header(requester["access_token"]),
    )
    assert request_response.status_code == 200
    request_id = request_response.json()["data"]["request"]["request_id"]

    accept_response = client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=auth_header(receiver["access_token"]),
    )
    assert accept_response.status_code == 200


def _create_direct_session(client: TestClient, auth_header, owner: dict, target: dict) -> str:
    response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [target["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    assert response.status_code == 200
    return response.json()["data"]["id"]


def test_block_user_removes_friendship_and_hides_private_session(
    client: TestClient,
    user_factory,
    auth_header,
    monkeypatch,
) -> None:
    alice = user_factory("block_hide_alice", "Block Hide Alice")
    bob = user_factory("block_hide_bob", "Block Hide Bob")
    _make_friends(client, auth_header, alice, bob)
    session_id = _create_direct_session(client, auth_header, alice, bob)

    send_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "12000000-0000-4000-8000-000000000001", "content": "before block", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert send_response.status_code == 200

    send_json_to_users = AsyncMock(return_value=set())
    monkeypatch.setattr(block_routes.connection_manager, "send_json_to_users", send_json_to_users)

    block_response = client.post(
        "/api/v1/blocks",
        json={"target_user_id": bob["user"]["id"]},
        headers=auth_header(alice["access_token"]),
    )
    assert block_response.status_code == 200
    block_payload = block_response.json()["data"]
    assert block_payload["mutation"] == {"action": "block_created", "changed": True, "created": True}
    assert block_payload["block"]["is_blocked"] is True
    assert block_payload["block"]["is_blocked_by"] is False
    assert send_json_to_users.await_count == 1
    assert send_json_to_users.await_args.args[0] == [alice["user"]["id"], bob["user"]["id"]]

    friends_response = client.get(
        "/api/v1/friends",
        headers=auth_header(alice["access_token"]),
    )
    assert friends_response.status_code == 200
    assert friends_response.json()["data"] == []

    alice_sessions = client.get("/api/v1/sessions", headers=auth_header(alice["access_token"]))
    bob_sessions = client.get("/api/v1/sessions", headers=auth_header(bob["access_token"]))
    assert alice_sessions.status_code == 200
    assert bob_sessions.status_code == 200
    assert session_id not in {item["id"] for item in alice_sessions.json()["data"]}
    assert session_id not in {item["id"] for item in bob_sessions.json()["data"]}

    detail_response = client.get(
        f"/api/v1/sessions/{session_id}",
        headers=auth_header(alice["access_token"]),
    )
    assert detail_response.status_code == 404
    assert detail_response.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND

    history_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(bob["access_token"]),
    )
    assert history_response.status_code == 404
    assert history_response.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND

    blocked_send_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "12000000-0000-4000-8000-000000000002", "content": "after block", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert blocked_send_response.status_code == 404
    assert blocked_send_response.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND


def test_blocked_relationship_rejects_friend_requests_and_direct_sessions(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("block_reject_alice", "Block Reject Alice")
    bob = user_factory("block_reject_bob", "Block Reject Bob")

    self_block_response = client.post(
        "/api/v1/blocks",
        json={"target_user_id": alice["user"]["id"]},
        headers=auth_header(alice["access_token"]),
    )
    assert self_block_response.status_code == 422
    assert self_block_response.json()["code"] == ErrorCode.INVALID_REQUEST

    block_response = client.post(
        "/api/v1/blocks",
        json={"target_user_id": bob["user"]["id"]},
        headers=auth_header(alice["access_token"]),
    )
    assert block_response.status_code == 200

    alice_check = client.get(
        f"/api/v1/blocks/check/{bob['user']['id']}",
        headers=auth_header(alice["access_token"]),
    )
    assert alice_check.status_code == 200
    assert alice_check.json()["data"]["block"]["is_blocked"] is True
    assert alice_check.json()["data"]["block"]["is_blocked_by"] is False

    bob_check = client.get(
        f"/api/v1/blocks/check/{alice['user']['id']}",
        headers=auth_header(bob["access_token"]),
    )
    assert bob_check.status_code == 200
    assert bob_check.json()["data"]["block"]["is_blocked"] is False
    assert bob_check.json()["data"]["block"]["is_blocked_by"] is True

    for actor, target in [(alice, bob), (bob, alice)]:
        friend_request_response = client.post(
            "/api/v1/friends/requests",
            json={"target_user_id": target["user"]["id"], "message": "should fail"},
            headers=auth_header(actor["access_token"]),
        )
        assert friend_request_response.status_code == 403
        assert friend_request_response.json()["code"] == ErrorCode.FORBIDDEN

        direct_response = client.post(
            "/api/v1/sessions/direct",
            json={"participant_ids": [target["user"]["id"]]},
            headers=auth_header(actor["access_token"]),
        )
        assert direct_response.status_code == 403
        assert direct_response.json()["code"] == ErrorCode.FORBIDDEN


def test_unblock_user_restores_existing_private_session_visibility_without_restoring_friendship(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("block_unblock_alice", "Block Unblock Alice")
    bob = user_factory("block_unblock_bob", "Block Unblock Bob")
    _make_friends(client, auth_header, alice, bob)
    session_id = _create_direct_session(client, auth_header, alice, bob)

    block_response = client.post(
        "/api/v1/blocks",
        json={"target_user_id": bob["user"]["id"]},
        headers=auth_header(alice["access_token"]),
    )
    assert block_response.status_code == 200

    list_blocks_response = client.get("/api/v1/blocks", headers=auth_header(alice["access_token"]))
    assert list_blocks_response.status_code == 200
    assert [item["user"]["id"] for item in list_blocks_response.json()["data"]] == [bob["user"]["id"]]

    hidden_sessions = client.get("/api/v1/sessions", headers=auth_header(alice["access_token"]))
    assert hidden_sessions.status_code == 200
    assert session_id not in {item["id"] for item in hidden_sessions.json()["data"]}

    unblock_response = client.delete(
        f"/api/v1/blocks/{bob['user']['id']}",
        headers=auth_header(alice["access_token"]),
    )
    assert unblock_response.status_code == 200
    unblock_payload = unblock_response.json()["data"]
    assert unblock_payload["mutation"] == {"action": "block_removed", "changed": True, "created": False}
    assert unblock_payload["block"]["is_blocked"] is False

    visible_sessions = client.get("/api/v1/sessions", headers=auth_header(alice["access_token"]))
    assert visible_sessions.status_code == 200
    assert session_id in {item["id"] for item in visible_sessions.json()["data"]}

    friendship_check = client.get(
        f"/api/v1/friends/check/{bob['user']['id']}",
        headers=auth_header(alice["access_token"]),
    )
    assert friendship_check.status_code == 200
    assert friendship_check.json()["data"]["friendship"]["is_friend"] is False

    friend_request_response = client.post(
        "/api/v1/friends/requests",
        json={"target_user_id": bob["user"]["id"], "message": "after unblock"},
        headers=auth_header(alice["access_token"]),
    )
    assert friend_request_response.status_code == 200
    assert friend_request_response.json()["data"]["mutation"]["action"] == "request_created"

    empty_blocks_response = client.get("/api/v1/blocks", headers=auth_header(alice["access_token"]))
    assert empty_blocks_response.status_code == 200
    assert empty_blocks_response.json()["data"] == []

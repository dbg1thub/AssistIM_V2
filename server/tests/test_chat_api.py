"""Chat and friendship API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_friend_request_private_session_and_message_flow(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    send_request_response = client.post(
        "/api/v1/friends/requests",
        json={"receiver_id": bob["user"]["id"], "message": "let's connect"},
        headers=auth_header(alice["access_token"]),
    )
    assert send_request_response.status_code == 200
    request_id = send_request_response.json()["data"]["id"]

    list_requests_response = client.get(
        "/api/v1/friends/requests",
        headers=auth_header(bob["access_token"]),
    )
    assert list_requests_response.status_code == 200
    requests_payload = list_requests_response.json()["data"]
    assert any(item["id"] == request_id for item in requests_payload)

    accept_response = client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=auth_header(bob["access_token"]),
    )
    assert accept_response.status_code == 200
    assert accept_response.json()["data"]["status"] == "accepted"

    friendship_check_response = client.get(
        f"/api/v1/friends/check/{bob['user']['id']}",
        headers=auth_header(alice["access_token"]),
    )
    assert friendship_check_response.status_code == 200
    assert friendship_check_response.json()["data"]["is_friend"] is True

    create_session_response = client.post(
        "/api/v1/sessions/private",
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_payload = create_session_response.json()["data"]
    session_id = session_payload["id"]
    assert bob["user"]["id"] in session_payload["participant_ids"]

    send_message_response = client.post(
        "/api/v1/messages",
        json={"session_id": session_id, "content": "hello bob", "type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert send_message_response.status_code == 200
    message_payload = send_message_response.json()["data"]
    assert message_payload["content"] == "hello bob"

    unread_response = client.get(
        "/api/v1/messages/unread",
        headers=auth_header(bob["access_token"]),
    )
    assert unread_response.status_code == 200
    assert unread_response.json()["data"]["total"] == 1

    history_response = client.get(
        "/api/v1/messages/history",
        params={"session_id": session_id},
        headers=auth_header(bob["access_token"]),
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()["data"]
    assert len(history_payload) == 1
    assert history_payload[0]["id"] == message_payload["id"]

    mark_read_response = client.post(
        "/api/v1/messages/read",
        json={"message_id": message_payload["id"]},
        headers=auth_header(bob["access_token"]),
    )
    assert mark_read_response.status_code == 200
    assert mark_read_response.json()["data"]["status"] == "read"

    unread_after_read_response = client.get(
        "/api/v1/messages/unread",
        headers=auth_header(bob["access_token"]),
    )
    assert unread_after_read_response.status_code == 200
    assert unread_after_read_response.json()["data"]["total"] == 0

    sessions_response = client.get(
        "/api/v1/sessions",
        headers=auth_header(alice["access_token"]),
    )
    assert sessions_response.status_code == 200
    assert sessions_response.json()["data"][0]["last_message"] == "hello bob"

"""Chat and friendship API tests."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocketDisconnect


def receive_until(ws, expected_type: str, *, unexpected_type: str | None = None):
    while True:
        payload = ws.receive_json()
        payload_type = payload.get("type")
        if unexpected_type and payload_type == unexpected_type:
            raise AssertionError(f"unexpected websocket payload: {payload}")
        if payload_type == expected_type:
            return payload


def authenticate_ws(ws, token: str, *, msg_id: str = "ws-auth") -> dict:
    ws.send_json(
        {
            "type": "auth",
            "msg_id": msg_id,
            "data": {"token": token},
        }
    )
    payload = receive_until(ws, "auth_ack")
    assert payload["data"]["success"] is True
    return payload


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
    send_request_payload = send_request_response.json()["data"]
    request_id = send_request_payload["request_id"]
    assert send_request_payload["action"] == "request_created"
    assert send_request_payload["created"] is True
    assert send_request_payload["changed"] is True
    assert "id" not in send_request_payload

    list_requests_response = client.get(
        "/api/v1/friends/requests",
        headers=auth_header(bob["access_token"]),
    )
    assert list_requests_response.status_code == 200
    requests_payload = list_requests_response.json()["data"]
    assert any(item["request_id"] == request_id for item in requests_payload)
    assert all("id" not in item for item in requests_payload)

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

    update_profile_response = client.put(
        "/api/v1/users/me",
        json={
            "email": "bob@example.com",
            "phone": "+82-10-0000-0002",
            "birthday": "1992-08-04",
            "region": "Busan",
            "signature": "Backend and integration tests.",
            "gender": "male",
            "status": "busy",
        },
        headers=auth_header(bob["access_token"]),
    )
    assert update_profile_response.status_code == 200

    friends_response = client.get(
        "/api/v1/friends",
        headers=auth_header(alice["access_token"]),
    )
    assert friends_response.status_code == 200
    friend_payload = friends_response.json()["data"]
    assert len(friend_payload) == 1
    assert friend_payload[0]["email"] == "bob@example.com"
    assert friend_payload[0]["phone"] == "+82-10-0000-0002"
    assert friend_payload[0]["birthday"] == "1992-08-04"
    assert friend_payload[0]["region"] == "Busan"
    assert friend_payload[0]["signature"] == "Backend and integration tests."
    assert friend_payload[0]["gender"] == "male"
    assert friend_payload[0]["status"] == "busy"

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_payload = create_session_response.json()["data"]
    session_id = session_payload["id"]
    assert session_payload["session_type"] == "direct"
    assert "type" not in session_payload
    assert bob["user"]["id"] in session_payload["participant_ids"]
    assert session_payload["counterpart_id"] == bob["user"]["id"]
    assert session_payload["counterpart_username"] == bob["user"]["username"]
    assert session_payload["counterpart_avatar"] == bob["user"]["avatar"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000001", "content": "hello bob", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert send_message_response.status_code == 200
    message_payload = send_message_response.json()["data"]
    assert message_payload["message_id"]
    assert message_payload["message_type"] == "text"
    assert "id" not in message_payload
    assert "msg_id" not in message_payload
    assert "type" not in message_payload
    assert datetime.fromisoformat(message_payload["created_at"])
    assert "timestamp" not in message_payload
    assert datetime.fromisoformat(message_payload["updated_at"])
    assert message_payload["session_type"] == "direct"
    assert sorted(message_payload["participant_ids"]) == sorted([alice["user"]["id"], bob["user"]["id"]])
    assert message_payload["session_name"] == "Private Chat"
    assert message_payload["sender_profile"]["id"] == alice["user"]["id"]
    assert message_payload["sender_profile"]["username"] == alice["user"]["username"]
    assert message_payload["sender_profile"]["avatar"] == alice["user"]["avatar"]

    history_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(alice["access_token"]),
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()["data"]
    assert history_payload[0]["message_id"] == message_payload["message_id"]
    assert history_payload[0]["message_type"] == "text"
    assert "id" not in history_payload[0]
    assert "msg_id" not in history_payload[0]
    assert "type" not in history_payload[0]
    assert datetime.fromisoformat(history_payload[0]["created_at"])
    assert "timestamp" not in history_payload[0]
    assert history_payload[0]["created_at"] == message_payload["created_at"]
    assert history_payload[0]["session_type"] == "direct"
    assert sorted(history_payload[0]["participant_ids"]) == sorted([alice["user"]["id"], bob["user"]["id"]])
    assert history_payload[0]["sender_profile"]["id"] == alice["user"]["id"]
    assert history_payload[0]["sender_profile"]["avatar"] == alice["user"]["avatar"]

    sessions_response = client.get(
        "/api/v1/sessions",
        headers=auth_header(alice["access_token"]),
    )
    assert sessions_response.status_code == 200
    session_payload = sessions_response.json()["data"]
    assert datetime.fromisoformat(session_payload[0]["last_message_time"])
    assert session_payload[0]["last_message_time"] == message_payload["created_at"]


def test_friend_request_create_echoes_reused_and_auto_accept_actions(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_friend_action", "Alice Friend Action")
    bob = user_factory("bob_friend_action", "Bob Friend Action")
    charlie = user_factory("charlie_friend_action", "Charlie Friend Action")

    first_request = client.post(
        "/api/v1/friends/requests",
        json={"receiver_id": bob["user"]["id"], "message": "hello"},
        headers=auth_header(alice["access_token"]),
    )
    assert first_request.status_code == 200
    first_payload = first_request.json()["data"]
    assert first_payload["action"] == "request_created"
    assert first_payload["created"] is True
    assert first_payload["changed"] is True

    reused_request = client.post(
        "/api/v1/friends/requests",
        json={"receiver_id": bob["user"]["id"], "message": "hello again"},
        headers=auth_header(alice["access_token"]),
    )
    assert reused_request.status_code == 200
    reused_payload = reused_request.json()["data"]
    assert reused_payload["request_id"] == first_payload["request_id"]
    assert reused_payload["action"] == "request_reused"
    assert reused_payload["created"] is False
    assert reused_payload["changed"] is False

    incoming_request = client.post(
        "/api/v1/friends/requests",
        json={"receiver_id": alice["user"]["id"], "message": "incoming"},
        headers=auth_header(charlie["access_token"]),
    )
    assert incoming_request.status_code == 200

    auto_accept = client.post(
        "/api/v1/friends/requests",
        json={"receiver_id": charlie["user"]["id"], "message": "accept by request"},
        headers=auth_header(alice["access_token"]),
    )
    assert auto_accept.status_code == 200
    auto_payload = auto_accept.json()["data"]
    assert auto_payload["status"] == "accepted"
    assert auto_payload["action"] == "friendship_created"
    assert auto_payload["changed"] is True
    assert auto_payload["friendship"] == {"is_friend": True, "friend_id": charlie["user"]["id"]}

    friendship_check = client.get(
        f"/api/v1/friends/check/{charlie['user']['id']}",
        headers=auth_header(alice["access_token"]),
    )
    assert friendship_check.status_code == 200
    assert friendship_check.json()["data"]["is_friend"] is True


def test_create_direct_session_is_idempotent_and_reuses_same_session(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.session import ChatSession

    alice = user_factory("alice_direct_unique", "Alice Direct Unique")
    bob = user_factory("bob_direct_unique", "Bob Direct Unique")

    first_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert first_response.status_code == 200
    first_payload = first_response.json()["data"]

    second_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert second_response.status_code == 200
    second_payload = second_response.json()["data"]

    assert second_payload["id"] == first_payload["id"]
    assert second_payload["participant_ids"] == first_payload["participant_ids"]

    with SessionLocal() as db:
        private_sessions = db.execute(select(ChatSession).where(ChatSession.type == "private")).scalars().all()
        assert len(private_sessions) == 1
        assert private_sessions[0].direct_key == ":".join(sorted([alice["user"]["id"], bob["user"]["id"]]))


def test_legacy_group_session_route_is_removed(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_group_route_removed", "Alice Group Route Removed")
    bob = user_factory("bob_group_route_removed", "Bob Group Route Removed")

    response = client.post(
        "/api/v1/sessions/group",
        json={"name": "Legacy Group", "participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )

    assert response.status_code == 405


def test_send_message_requires_canonical_message_type_field(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_http_message_type", "Alice Http Message Type")
    bob = user_factory("bob_http_message_type", "Bob Http Message Type")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000003", "content": "legacy http body", "type": "text"},
        headers=auth_header(alice["access_token"]),
    )

    assert response.status_code == 422
    assert "type" in response.json()["message"]


def test_http_send_message_requires_msg_id_and_rejects_system_type(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_http_formal_send", "Alice Http Formal Send")
    bob = user_factory("bob_http_formal_send", "Bob Http Formal Send")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    missing_msg_id = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "missing id", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert missing_msg_id.status_code == 422

    system_type = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "11000000-0000-4000-8000-000000000001",
            "content": "forged system",
            "message_type": "system",
        },
        headers=auth_header(alice["access_token"]),
    )
    assert system_type.status_code == 422

    blank_content = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "11000000-0000-4000-8000-000000000101", "content": "   ", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert blank_content.status_code == 422

    oversized_content = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "11000000-0000-4000-8000-000000000102",
            "content": "x" * 20001,
            "message_type": "text",
        },
        headers=auth_header(alice["access_token"]),
    )
    assert oversized_content.status_code == 422

    missing_attachment_payload = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "11000000-0000-4000-8000-000000000103",
            "content": "/uploads/missing-metadata.png",
            "message_type": "image",
        },
        headers=auth_header(alice["access_token"]),
    )
    assert missing_attachment_payload.status_code == 422

    incomplete_attachment_payload = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "11000000-0000-4000-8000-000000000104",
            "content": "/uploads/missing-size.png",
            "message_type": "image",
            "extra": {"url": "/uploads/missing-size.png", "name": "missing-size.png", "file_type": "image/png"},
        },
        headers=auth_header(alice["access_token"]),
    )
    assert incomplete_attachment_payload.status_code == 422


def test_http_send_message_uses_msg_id_and_realtime_broadcasts(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_http_realtime", "Alice Http Realtime")
    bob = user_factory("bob_http_realtime", "Bob Http Realtime")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]
    msg_id = "11000000-0000-4000-8000-000000000002"

    with client.websocket_connect("/ws") as bob_ws:
        authenticate_ws(bob_ws, bob["access_token"], msg_id="ws-auth-http-realtime-bob")
        send_response = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"msg_id": msg_id, "content": "hello over http", "message_type": "text"},
            headers=auth_header(alice["access_token"]),
        )
        assert send_response.status_code == 200
        send_payload = send_response.json()["data"]
        assert send_payload["message_id"] == msg_id

        realtime_payload = receive_until(bob_ws, "chat_message")
        assert realtime_payload["msg_id"] == msg_id
        assert realtime_payload["data"]["message_id"] == msg_id
        assert realtime_payload["data"]["content"] == "hello over http"
        assert realtime_payload["data"]["is_self"] is False

        duplicate_response = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"msg_id": msg_id, "content": "hello over http", "message_type": "text"},
            headers=auth_header(alice["access_token"]),
        )
        assert duplicate_response.status_code == 200
        assert duplicate_response.json()["data"]["message_id"] == msg_id


def test_websocket_chat_message_rejects_system_type(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_ws_system_type", "Alice Ws System Type")
    bob = user_factory("bob_ws_system_type", "Bob Ws System Type")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    with client.websocket_connect("/ws") as alice_ws:
        authenticate_ws(alice_ws, alice["access_token"], msg_id="ws-auth-system-type")
        alice_ws.send_json(
            {
                "type": "chat_message",
                "msg_id": "11000000-0000-4000-8000-000000000003",
                "data": {
                    "session_id": session_id,
                    "content": "forged system over ws",
                    "message_type": "system",
                },
            }
        )
        error_payload = receive_until(alice_ws, "error")
        assert error_payload["msg_id"] == "11000000-0000-4000-8000-000000000003"
        assert error_payload["data"]["message"] == "unsupported message type"

    history_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(alice["access_token"]),
    )
    assert history_response.status_code == 200
    assert history_response.json()["data"] == []


def test_websocket_chat_message_rejects_blank_content(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_ws_blank_content", "Alice Ws Blank Content")
    bob = user_factory("bob_ws_blank_content", "Bob Ws Blank Content")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    with client.websocket_connect("/ws") as alice_ws:
        authenticate_ws(alice_ws, alice["access_token"], msg_id="ws-auth-blank-content")
        alice_ws.send_json(
            {
                "type": "chat_message",
                "msg_id": "11000000-0000-4000-8000-000000000103",
                "data": {
                    "session_id": session_id,
                    "content": "   ",
                    "message_type": "text",
                },
            }
        )
        error_payload = receive_until(alice_ws, "error")
        assert error_payload["msg_id"] == "11000000-0000-4000-8000-000000000103"
        assert error_payload["data"]["message"] == "content cannot be blank"

    history_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(alice["access_token"]),
    )
    assert history_response.status_code == 200
    assert history_response.json()["data"] == []


def test_invalid_read_ack_does_not_disconnect_websocket(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    def receive_until(ws, expected_type: str):
        while True:
            payload = ws.receive_json()
            if payload.get("type") == expected_type:
                return payload

    with client.websocket_connect("/ws") as alice_ws, client.websocket_connect("/ws") as bob_ws:
        authenticate_ws(alice_ws, alice["access_token"], msg_id="ws-auth-invalid-read-alice")
        authenticate_ws(bob_ws, bob["access_token"], msg_id="ws-auth-invalid-read-bob")
        alice_ws.send_json(
            {
                "type": "chat_message",
                "msg_id": "33333333-3333-4333-8333-333333333333",
                "data": {
                    "session_id": session_id,
                    "content": "first",
                    "message_type": "text",
                },
            }
        )
        receive_until(alice_ws, "message_ack")
        first_received = receive_until(bob_ws, "chat_message")
        assert first_received["data"]["content"] == "first"

        bob_ws.send_json(
            {
                "type": "read_ack",
                "msg_id": "44444444-4444-4444-8444-444444444444",
                "data": {
                    "session_id": "not-a-real-session",
                    "message_id": first_received["msg_id"],
                },
            }
        )
        error_payload = receive_until(bob_ws, "error")
        assert error_payload["data"]["message"] == "unsupported message type: read_ack"

        alice_ws.send_json(
            {
                "type": "chat_message",
                "msg_id": "55555555-5555-4555-8555-555555555555",
                "data": {
                    "session_id": session_id,
                    "content": "second",
                    "message_type": "text",
                },
            }
        )
        receive_until(alice_ws, "message_ack")
        second_received = receive_until(bob_ws, "chat_message")
        assert second_received["data"]["content"] == "second"




def test_websocket_read_ack_requires_message_id_field(client: TestClient, user_factory) -> None:
    alice = user_factory("alice_read_ack_required", "Alice Read Ack Required")

    def receive_until(ws, expected_type: str):
        while True:
            payload = ws.receive_json()
            if payload.get("type") == expected_type:
                return payload

    with client.websocket_connect("/ws") as websocket:
        authenticate_ws(websocket, alice["access_token"], msg_id="ws-auth-read-ack-required")
        websocket.send_json(
            {
                "type": "read_ack",
                "msg_id": "44555555-5555-4555-8555-555555555555",
                "data": {
                    "session_id": "session-1",
                    "last_read_id": "message-1",
                },
            }
        )
        error_payload = receive_until(websocket, "error")
        assert error_payload["data"]["message"] == "unsupported message type: read_ack"


def test_websocket_chat_message_uses_recipient_is_self_view(client: TestClient, user_factory, auth_header) -> None:
    alice = user_factory("alice_ws_is_self", "Alice WS Is Self")
    bob = user_factory("bob_ws_is_self", "Bob WS Is Self")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    with client.websocket_connect("/ws") as alice_ws, client.websocket_connect("/ws") as bob_ws:
        authenticate_ws(alice_ws, alice["access_token"], msg_id="ws-auth-is-self-alice")
        authenticate_ws(bob_ws, bob["access_token"], msg_id="ws-auth-is-self-bob")

        alice_ws.send_json(
            {
                "type": "chat_message",
                "msg_id": "66666666-6666-4666-8666-666666666666",
                "data": {
                    "session_id": session_id,
                    "content": "hello bob",
                    "message_type": "text",
                },
            }
        )

        ack_payload = receive_until(alice_ws, "message_ack")
        received_payload = receive_until(bob_ws, "chat_message")

        assert ack_payload["data"]["message"]["sender_id"] == alice["user"]["id"]
        assert ack_payload["data"]["message"]["is_self"] is True
        assert received_payload["data"]["sender_id"] == alice["user"]["id"]
        assert received_payload["data"]["is_self"] is False


def test_websocket_rejects_legacy_message_alias(client: TestClient, user_factory) -> None:
    alice = user_factory("alice", "Alice")

    def receive_until(ws, expected_type: str):
        while True:
            payload = ws.receive_json()
            if payload.get("type") == expected_type:
                return payload

    with client.websocket_connect("/ws") as websocket:
        authenticate_ws(websocket, alice["access_token"], msg_id="ws-auth-legacy-alias")
        websocket.send_json(
            {
                "type": "message",
                "msg_id": "55666666-6666-4666-8666-666666666666",
                "data": {
                    "session_id": "legacy-session",
                    "content": "legacy hello",
                    "message_type": "text",
                },
            }
        )
        error_payload = receive_until(websocket, "error")
        assert error_payload["data"]["message"] == "unsupported message type: message"


def test_private_websocket_delivers_multiple_messages_after_explicit_auth(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    def receive_until(ws, expected_type: str):
        while True:
            payload = ws.receive_json()
            if payload.get("type") == expected_type:
                return payload

    with client.websocket_connect("/ws") as alice_ws, client.websocket_connect("/ws") as bob_ws:
        authenticate_ws(alice_ws, alice["access_token"], msg_id="ws-auth-private-alice")
        authenticate_ws(bob_ws, bob["access_token"], msg_id="ws-auth-private-bob")
        for index, content in enumerate(["one", "two", "three"], start=1):
            alice_ws.send_json(
                {
                    "type": "chat_message",
                    "msg_id": f"70000000-0000-4000-8000-00000000000{index}",
                    "data": {
                        "session_id": session_id,
                        "content": content,
                        "message_type": "text",
                    },
                }
            )
            receive_until(alice_ws, "message_ack")
            received = receive_until(bob_ws, "chat_message")
            assert received["data"]["content"] == content
            assert received["data"]["session_id"] == session_id
            assert received["data"]["session_type"] == "direct"
            assert received["data"]["session_name"] == "Private Chat"
            assert received["data"]["sender_profile"]["id"] == alice["user"]["id"]
            assert received["data"]["sender_profile"]["avatar"] == alice["user"]["avatar"]


def test_group_websocket_delivers_multiple_messages_after_explicit_auth(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    group_response = client.post(
        "/api/v1/groups",
        json={"name": "Team", "member_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert group_response.status_code == 201
    session_id = group_response.json()["data"]["group"]["session_id"]

    def receive_until(ws, expected_type: str):
        while True:
            payload = ws.receive_json()
            if payload.get("type") == expected_type:
                return payload

    with client.websocket_connect("/ws") as alice_ws, client.websocket_connect("/ws") as bob_ws:
        authenticate_ws(alice_ws, alice["access_token"], msg_id="ws-auth-group-alice")
        authenticate_ws(bob_ws, bob["access_token"], msg_id="ws-auth-group-bob")
        for index, content in enumerate(["g-one", "g-two", "g-three"], start=1):
            alice_ws.send_json(
                {
                    "type": "chat_message",
                    "msg_id": f"80000000-0000-4000-8000-00000000000{index}",
                    "data": {
                        "session_id": session_id,
                        "content": content,
                        "message_type": "text",
                    },
                }
            )
            receive_until(alice_ws, "message_ack")
            received = receive_until(bob_ws, "chat_message")
            assert received["data"]["content"] == content
            assert received["data"]["session_id"] == session_id
            assert received["data"]["session_type"] == "group"
            assert received["data"]["session_name"] == "Team"
            assert received["data"]["sender_profile"]["id"] == alice["user"]["id"]
            assert received["data"]["sender_profile"]["avatar"] == alice["user"]["avatar"]


def test_group_mention_all_requires_owner_or_admin(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    from app.core.database import SessionLocal
    from app.repositories.group_repo import GroupRepository

    owner = user_factory("mention_owner", "Mention Owner")
    admin = user_factory("mention_admin", "Mention Admin")
    member = user_factory("mention_member", "Mention Member")

    group_response = client.post(
        "/api/v1/groups",
        json={"name": "Mentions", "member_ids": [admin["user"]["id"], member["user"]["id"]]},
        headers=auth_header(owner["access_token"]),
    )
    assert group_response.status_code == 201
    group_payload = group_response.json()["data"]["group"]
    session_id = group_payload["session_id"]
    group_id = group_payload["id"]

    with SessionLocal() as db:
        GroupRepository(db).update_member_role(group_id, admin["user"]["id"], "admin")

    mention_extra = {
        "mentions": [
            {
                "start": 0,
                "end": 4,
                "display_name": "所有人",
                "mention_type": "all",
            }
        ]
    }

    member_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000004", "content": "@所有人 hi", "message_type": "text", "extra": mention_extra},
        headers=auth_header(member["access_token"]),
    )
    assert member_response.status_code == 403

    admin_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000005", "content": "@所有人 hi", "message_type": "text", "extra": mention_extra},
        headers=auth_header(admin["access_token"]),
    )
    assert admin_response.status_code == 200
    assert admin_response.json()["data"]["extra"]["mentions"][0]["mention_type"] == "all"

    owner_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000006", "content": "@所有人 hi", "message_type": "text", "extra": mention_extra},
        headers=auth_header(owner["access_token"]),
    )
    assert owner_response.status_code == 200


def test_member_mentions_require_session_members_and_non_overlapping_spans(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("mention_span_alice", "Alice")
    bob = user_factory("mention_span_bob", "Bob")
    charlie = user_factory("mention_span_charlie", "Charlie")

    group_response = client.post(
        "/api/v1/groups",
        json={"name": "Mention Spans", "member_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert group_response.status_code == 201
    session_id = group_response.json()["data"]["group"]["session_id"]

    non_member_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "10000000-0000-4000-8000-000000000007",
            "content": "@Charlie hi",
            "message_type": "text",
            "extra": {
                "mentions": [
                    {
                        "start": 0,
                        "end": 8,
                        "display_name": "Charlie",
                        "mention_type": "member",
                        "member_id": charlie["user"]["id"],
                    }
                ]
            },
        },
        headers=auth_header(alice["access_token"]),
    )
    assert non_member_response.status_code == 422
    assert non_member_response.json()["message"] == "mention member is not in session"

    overlapping_span_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "10000000-0000-4000-8000-000000000008",
            "content": "@Bob hi",
            "message_type": "text",
            "extra": {
                "mentions": [
                    {
                        "start": 0,
                        "end": 4,
                        "display_name": "Bob",
                        "mention_type": "member",
                        "member_id": bob["user"]["id"],
                    },
                    {
                        "start": 0,
                        "end": 4,
                        "display_name": "Bob",
                        "mention_type": "member",
                        "member_id": bob["user"]["id"],
                    },
                ]
            },
        },
        headers=auth_header(alice["access_token"]),
    )
    assert overlapping_span_response.status_code == 422
    assert overlapping_span_response.json()["message"] == "mention spans must not overlap"


def test_chat_websocket_rejects_user_id_only_auth_and_closes_socket(
    client: TestClient,
    user_factory,
) -> None:
    user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    def receive_until(ws, expected_type: str):
        while True:
            payload = ws.receive_json()
            if payload.get("type") == expected_type:
                return payload

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(
            {
                "type": "auth",
                "msg_id": "91000000-0000-4000-8000-000000000001",
                "data": {"user_id": bob["user"]["id"]},
            }
        )
        error_payload = receive_until(websocket, "error")
        assert error_payload["data"]["code"] == 1004
        assert "token required" in error_payload["data"]["message"]

        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_json()
        assert exc_info.value.code == 1008

def test_chat_websocket_ignores_query_token_until_explicit_auth(
    client: TestClient,
    user_factory,
) -> None:
    alice = user_factory("alice_query_token", "Alice Query Token")

    with client.websocket_connect(f"/ws?token={alice['access_token']}") as websocket:
        websocket.send_json(
            {
                "type": "sync_messages",
                "msg_id": "91000000-0000-4000-8000-000000000003",
                "data": {"session_cursors": {}, "event_cursors": {}},
            }
        )
        error_payload = receive_until(websocket, "error")
        assert error_payload["data"]["code"] == 1004
        assert error_payload["data"]["message"] == "websocket authentication required"

        authenticate_ws(websocket, alice["access_token"], msg_id="ws-auth-query-token")

def test_websocket_message_mutations_require_message_owner(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000007", "content": "hello bob", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert send_message_response.status_code == 200
    message_id = send_message_response.json()["data"]["message_id"]

    def receive_until(ws, expected_type: str):
        while True:
            payload = ws.receive_json()
            if payload.get("type") == expected_type:
                return payload

    with client.websocket_connect("/ws") as websocket:
        authenticate_ws(websocket, bob["access_token"], msg_id="ws-auth-owner-check")
        websocket.send_json(
            {
                "type": "message_recall",
                "msg_id": "92000000-0000-4000-8000-000000000001",
                "data": {"session_id": session_id, "message_id": message_id},
            }
        )
        recall_error = receive_until(websocket, "error")
        assert "cannot recall this message" in recall_error["data"]["message"]

        websocket.send_json(
            {
                "type": "message_edit",
                "msg_id": "92000000-0000-4000-8000-000000000002",
                "data": {
                    "session_id": session_id,
                    "message_id": message_id,
                    "content": "hacked by bob",
                },
            }
        )
        edit_error = receive_until(websocket, "error")
        assert "cannot edit this message" in edit_error["data"]["message"]

        websocket.send_json(
            {
                "type": "message_delete",
                "msg_id": "92000000-0000-4000-8000-000000000003",
                "data": {"session_id": session_id, "message_id": message_id},
            }
        )
        delete_error = receive_until(websocket, "error")
        assert "cannot delete this message" in delete_error["data"]["message"]

    history_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(bob["access_token"]),
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()["data"]
    assert len(history_payload) == 1
    assert history_payload[0]["message_id"] == message_id
    assert history_payload[0]["status"] == "sent"
    assert history_payload[0]["content"] == "hello bob"

def test_edit_message_rejects_messages_older_than_two_minutes(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    from datetime import timedelta

    from app.utils.time import utcnow

    from app.core.database import SessionLocal
    from app.models.message import Message

    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000009", "content": "original content", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert send_message_response.status_code == 200
    message_id = send_message_response.json()["data"]["message_id"]

    with SessionLocal() as db:
        message = db.get(Message, message_id)
        assert message is not None
        message.created_at = utcnow() - timedelta(minutes=3)
        db.add(message)
        db.commit()

    edit_response = client.put(
        f"/api/v1/messages/{message_id}",
        json={"content": "updated content"},
        headers=auth_header(alice["access_token"]),
    )
    assert edit_response.status_code == 403
    assert edit_response.json()["code"] == 1008
    assert edit_response.json()["message"] == "edit time limit exceeded"

    history_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(alice["access_token"]),
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()["data"]
    assert history_payload[0]["message_id"] == message_id
    assert history_payload[0]["content"] == "original content"
    assert history_payload[0]["status"] == "sent"


def test_edit_message_rejects_unknown_fields_and_blank_content(client: TestClient, user_factory, auth_header) -> None:
    alice = user_factory("alice_edit_schema", "Alice Edit Schema")

    extra_field = client.put(
        "/api/v1/messages/message-1",
        json={"content": "updated", "legacy": True},
        headers=auth_header(alice["access_token"]),
    )
    assert extra_field.status_code == 422

    blank_content = client.put(
        "/api/v1/messages/message-1",
        json={"content": "   "},
        headers=auth_header(alice["access_token"]),
    )
    assert blank_content.status_code == 422

    oversized_content = client.put(
        "/api/v1/messages/message-1",
        json={"content": "x" * 20001},
        headers=auth_header(alice["access_token"]),
    )

    assert oversized_content.status_code == 422



def test_message_mutations_reject_terminal_status_and_non_text_edits(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_mutation_gate", "Alice Mutation Gate")
    bob = user_factory("bob_mutation_gate", "Bob Mutation Gate")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    text_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "10000000-0000-4000-8000-000000000027",
            "content": "can be recalled",
            "message_type": "text",
        },
        headers=auth_header(alice["access_token"]),
    )
    assert text_response.status_code == 200
    text_message_id = text_response.json()["data"]["message_id"]

    recall_response = client.post(
        f"/api/v1/messages/{text_message_id}/recall",
        headers=auth_header(alice["access_token"]),
    )
    assert recall_response.status_code == 200

    recall_again = client.post(
        f"/api/v1/messages/{text_message_id}/recall",
        headers=auth_header(alice["access_token"]),
    )
    assert recall_again.status_code == 409
    assert recall_again.json()["message"] == "cannot recall recalled message"

    edit_recalled = client.put(
        f"/api/v1/messages/{text_message_id}",
        json={"content": "late edit"},
        headers=auth_header(alice["access_token"]),
    )
    assert edit_recalled.status_code == 409
    assert edit_recalled.json()["message"] == "cannot edit recalled message"

    delete_recalled = client.delete(
        f"/api/v1/messages/{text_message_id}",
        headers=auth_header(alice["access_token"]),
    )
    assert delete_recalled.status_code == 409
    assert delete_recalled.json()["message"] == "cannot delete recalled message"

    image_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "10000000-0000-4000-8000-000000000028",
            "content": "/uploads/demo.png",
            "message_type": "image",
            "extra": {
                "url": "/uploads/demo.png",
                "name": "demo.png",
                "file_type": "image/png",
                "size": 128,
            },
        },
        headers=auth_header(alice["access_token"]),
    )
    assert image_response.status_code == 200

    edit_image = client.put(
        f"/api/v1/messages/{image_response.json()['data']['message_id']}",
        json={"content": "caption"},
        headers=auth_header(alice["access_token"]),
    )
    assert edit_image.status_code == 422
    assert edit_image.json()["message"] == "message type does not support edit"


def test_group_read_receipts_are_tracked_per_member(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")
    charlie = user_factory("charlie", "Charlie")

    group_response = client.post(
        "/api/v1/groups",
        json={"name": "Team", "member_ids": [bob["user"]["id"], charlie["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert group_response.status_code == 201
    session_id = group_response.json()["data"]["group"]["session_id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000011", "content": "group hello", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert send_message_response.status_code == 200
    message_id = send_message_response.json()["data"]["message_id"]

    alice_history_before = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(alice["access_token"]),
    )
    assert alice_history_before.status_code == 200
    before_payload = alice_history_before.json()["data"][0]
    read_metadata_keys = {"session_seq", "read_count", "read_target_count", "read_by_user_ids", "is_read_by_me"}
    assert before_payload["status"] == "sent"
    assert "timestamp" not in before_payload
    assert before_payload["read_count"] == 0
    assert before_payload["read_target_count"] == 2
    assert before_payload["read_by_user_ids"] == []
    assert read_metadata_keys.isdisjoint(before_payload["extra"].keys())

    bob_read_response = client.post(
        "/api/v1/messages/read/batch",
        json={"session_id": session_id, "message_id": message_id},
        headers=auth_header(bob["access_token"]),
    )
    assert bob_read_response.status_code == 200
    bob_read_payload = bob_read_response.json()["data"]
    assert bob_read_payload["status"] == "read"
    assert bob_read_payload["advanced"] is True
    assert bob_read_payload["noop"] is False
    assert bob_read_payload["message_id"] == message_id
    assert "last_read_message_id" not in bob_read_payload
    assert bob_read_payload["last_read_seq"] == 1
    assert bob_read_payload["user_id"] == bob["user"]["id"]
    assert int(bob_read_payload["event_seq"]) > 0

    bob_unread_response = client.get(
        "/api/v1/messages/unread",
        headers=auth_header(bob["access_token"]),
    )
    assert bob_unread_response.status_code == 200
    assert bob_unread_response.json()["data"]["total"] == 0

    charlie_unread_response = client.get(
        "/api/v1/messages/unread",
        headers=auth_header(charlie["access_token"]),
    )
    assert charlie_unread_response.status_code == 200
    assert charlie_unread_response.json()["data"]["total"] == 1

    alice_history_after = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(alice["access_token"]),
    )
    assert alice_history_after.status_code == 200
    after_payload = alice_history_after.json()["data"][0]
    assert after_payload["message_id"] == message_id
    assert after_payload["status"] == "sent"
    assert "timestamp" not in after_payload
    assert after_payload["read_count"] == 1
    assert after_payload["read_target_count"] == 2
    assert after_payload["read_by_user_ids"] == [bob["user"]["id"]]
    assert read_metadata_keys.isdisjoint(after_payload["extra"].keys())

    charlie_history = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(charlie["access_token"]),
    )
    assert charlie_history.status_code == 200
    charlie_payload = charlie_history.json()["data"][0]
    assert charlie_payload["is_read_by_me"] is False


def test_read_batch_returns_stable_payload_for_noop(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.models.session import SessionEvent

    alice = user_factory("alice_read_noop", "Alice Read Noop")
    bob = user_factory("bob_read_noop", "Bob Read Noop")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000028", "content": "read once", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert send_message_response.status_code == 200
    message_id = send_message_response.json()["data"]["message_id"]

    expected_keys = {
        "status",
        "session_id",
        "message_id",
        "last_read_seq",
        "user_id",
        "read_at",
        "advanced",
        "noop",
        "event_seq",
    }

    first_response = client.post(
        "/api/v1/messages/read/batch",
        json={"session_id": session_id, "message_id": message_id},
        headers=auth_header(bob["access_token"]),
    )
    assert first_response.status_code == 200
    first_payload = first_response.json()["data"]
    assert set(first_payload) == expected_keys
    assert first_payload["status"] == "read"
    assert first_payload["session_id"] == session_id
    assert first_payload["message_id"] == message_id
    assert first_payload["last_read_seq"] == 1
    assert first_payload["user_id"] == bob["user"]["id"]
    assert first_payload["read_at"] is not None
    assert first_payload["advanced"] is True
    assert first_payload["noop"] is False
    assert int(first_payload["event_seq"]) > 0

    second_response = client.post(
        "/api/v1/messages/read/batch",
        json={"session_id": session_id, "message_id": message_id},
        headers=auth_header(bob["access_token"]),
    )
    assert second_response.status_code == 200
    second_payload = second_response.json()["data"]
    assert set(second_payload) == expected_keys
    assert second_payload["status"] == "read"
    assert second_payload["session_id"] == session_id
    assert second_payload["message_id"] == message_id
    assert second_payload["last_read_seq"] == 1
    assert second_payload["user_id"] == bob["user"]["id"]
    assert second_payload["read_at"] == first_payload["read_at"]
    assert second_payload["advanced"] is False
    assert second_payload["noop"] is True
    assert second_payload["event_seq"] == 0

    with SessionLocal() as db:
        read_event_count = db.execute(
            select(func.count(SessionEvent.id)).where(
                SessionEvent.session_id == session_id,
                SessionEvent.type == "read",
            )
        ).scalar_one()

    assert read_event_count == 1


def test_read_batch_requires_canonical_message_id_field(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_read_batch_alias", "Alice Read Batch Alias")

    response = client.post(
        "/api/v1/messages/read/batch",
        json={"session_id": "session-1", "last_read_id": "message-1"},
        headers=auth_header(alice["access_token"]),
    )

    assert response.status_code == 422
    assert "message_id" in response.json()["message"]

    extra_field = client.post(
        "/api/v1/messages/read/batch",
        json={"session_id": "session-1", "message_id": "message-1", "last_read_id": "message-1"},
        headers=auth_header(alice["access_token"]),
    )
    assert extra_field.status_code == 422

    blank_session = client.post(
        "/api/v1/messages/read/batch",
        json={"session_id": "   ", "message_id": "message-1"},
        headers=auth_header(alice["access_token"]),
    )
    assert blank_session.status_code == 422

    oversized_message_id = client.post(
        "/api/v1/messages/read/batch",
        json={"session_id": "session-1", "message_id": "m" * 129},
        headers=auth_header(alice["access_token"]),
    )
    assert oversized_message_id.status_code == 422


def test_http_read_batch_broadcasts_read_cursor(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000014", "content": "hello bob", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert send_message_response.status_code == 200
    message_id = send_message_response.json()["data"]["message_id"]

    def receive_until(ws, expected_type: str):
        while True:
            payload = ws.receive_json()
            if payload.get("type") == expected_type:
                return payload

    with client.websocket_connect("/ws") as alice_ws, client.websocket_connect("/ws") as bob_ws:
        authenticate_ws(alice_ws, alice["access_token"], msg_id="ws-auth-read-broadcast-alice")
        authenticate_ws(bob_ws, bob["access_token"], msg_id="ws-auth-read-broadcast-bob")
        read_response = client.post(
            "/api/v1/messages/read/batch",
            json={"session_id": session_id, "message_id": message_id},
            headers=auth_header(bob["access_token"]),
        )
        assert read_response.status_code == 200

        read_payload = receive_until(alice_ws, "read")
        assert read_payload["data"]["session_id"] == session_id
        assert read_payload["data"]["message_id"] == message_id
        assert "last_read_message_id" not in read_payload["data"]
        assert read_payload["data"]["last_read_seq"] == 1
        assert read_payload["data"]["user_id"] == bob["user"]["id"]

def test_websocket_duplicate_message_id_is_idempotent_and_ack_returns_canonical_message(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    def receive_until(ws, expected_type: str, *, unexpected_type: str | None = None):
        while True:
            payload = ws.receive_json()
            if unexpected_type and payload.get("type") == unexpected_type:
                raise AssertionError(f"unexpected websocket payload: {payload}")
            if payload.get("type") == expected_type:
                return payload

    payload = {
        "type": "chat_message",
        "msg_id": "94000000-0000-4000-8000-000000000001",
        "data": {
            "session_id": session_id,
            "content": "idempotent hello",
            "message_type": "text",
        },
    }

    with client.websocket_connect("/ws") as alice_ws, client.websocket_connect("/ws") as bob_ws:
        authenticate_ws(alice_ws, alice["access_token"], msg_id="ws-auth-idempotent-alice")
        authenticate_ws(bob_ws, bob["access_token"], msg_id="ws-auth-idempotent-bob")
        alice_ws.send_json(payload)
        first_ack = receive_until(alice_ws, "message_ack")
        assert first_ack["data"]["success"] is True
        assert first_ack["data"]["message"]["message_id"] == payload["msg_id"]
        assert first_ack["data"]["message"]["session_seq"] == 1

        first_message = receive_until(bob_ws, "chat_message")
        assert first_message["msg_id"] == payload["msg_id"]
        assert first_message["data"]["content"] == "idempotent hello"
        assert first_message["data"]["session_seq"] == 1

        alice_ws.send_json(payload)
        second_ack = receive_until(alice_ws, "message_ack")
        assert second_ack["data"]["success"] is True
        assert second_ack["data"]["message"]["message_id"] == payload["msg_id"]
        assert second_ack["data"]["message"]["session_seq"] == 1

        bob_ws.send_json({"type": "heartbeat", "msg_id": "94000000-0000-4000-8000-000000000099", "data": {}})
        heartbeat_error = receive_until(bob_ws, "error", unexpected_type="chat_message")
        assert heartbeat_error["msg_id"] == "94000000-0000-4000-8000-000000000099"
        assert heartbeat_error["data"]["message"] == "unsupported message type: heartbeat"

    history_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(alice["access_token"]),
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()["data"]
    assert len(history_payload) == 1
    assert history_payload[0]["message_id"] == payload["msg_id"]
    assert history_payload[0]["session_seq"] == 1

def test_list_messages_uses_session_seq_cursor(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    for index in range(1, 4):
        response = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={
                "msg_id": f"10000000-0000-4000-8000-00000000009{index}",
                "content": f"history seq {index}",
                "message_type": "text",
            },
            headers=auth_header(alice["access_token"]),
        )
        assert response.status_code == 200
        assert response.json()["data"]["session_seq"] == index

    page_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        params={"before_seq": 3, "limit": 2},
        headers=auth_header(alice["access_token"]),
    )
    assert page_response.status_code == 200
    page_payload = page_response.json()["data"]
    assert [message["session_seq"] for message in page_payload] == [1, 2]
    assert [message["content"] for message in page_payload] == ["history seq 1", "history seq 2"]

    oldest_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        params={"before_seq": 2, "limit": 2},
        headers=auth_header(alice["access_token"]),
    )
    assert oldest_response.status_code == 200
    oldest_payload = oldest_response.json()["data"]
    assert [message["session_seq"] for message in oldest_payload] == [1]


def test_websocket_rejects_conflicting_duplicate_message_id(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    def receive_until(ws, expected_type: str):
        while True:
            payload = ws.receive_json()
            if payload.get("type") == expected_type:
                return payload

    message_id = "95000000-0000-4000-8000-000000000001"

    with client.websocket_connect("/ws") as alice_ws:
        authenticate_ws(alice_ws, alice["access_token"], msg_id="ws-auth-conflict")
        alice_ws.send_json(
            {
                "type": "chat_message",
                "msg_id": message_id,
                "data": {
                    "session_id": session_id,
                    "content": "first body",
                    "message_type": "text",
                },
            }
        )
        receive_until(alice_ws, "message_ack")

        alice_ws.send_json(
            {
                "type": "chat_message",
                "msg_id": message_id,
                "data": {
                    "session_id": session_id,
                    "content": "tampered body",
                    "message_type": "text",
                },
            }
        )
        error_payload = receive_until(alice_ws, "error")
        assert error_payload["data"]["code"] == 1005
        assert "already used" in error_payload["data"]["message"]

    history_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(alice["access_token"]),
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()["data"]
    assert len(history_payload) == 1
    assert history_payload[0]["message_id"] == message_id
    assert history_payload[0]["content"] == "first body"



def test_websocket_sync_messages_uses_session_cursors(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    first_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000017", "content": "first sync message", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert first_response.status_code == 200
    assert first_response.json()["data"]["session_seq"] == 1

    second_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000018", "content": "second sync message", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert second_response.status_code == 200
    assert second_response.json()["data"]["session_seq"] == 2

    def receive_until(ws, expected_type: str):
        while True:
            payload = ws.receive_json()
            if payload.get("type") == expected_type:
                return payload

    with client.websocket_connect("/ws") as websocket:
        authenticate_ws(websocket, bob["access_token"], msg_id="ws-auth-sync-messages")
        websocket.send_json(
            {
                "type": "sync_messages",
                "msg_id": "96000000-0000-4000-8000-000000000001",
                "data": {
                    "session_cursors": {
                        session_id: 1,
                    },
                },
            }
        )

        history_payload = receive_until(websocket, "history_messages")
        messages = history_payload["data"]["messages"]
        assert len(messages) == 1
        assert messages[0]["session_id"] == session_id
        assert messages[0]["session_seq"] == 2
        assert messages[0]["content"] == "second sync message"


def test_websocket_sync_messages_replays_offline_read_and_edit_events(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000019", "content": "original sync payload", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert send_message_response.status_code == 200
    message_id = send_message_response.json()["data"]["message_id"]
    assert send_message_response.json()["data"]["session_seq"] == 1

    read_response = client.post(
        "/api/v1/messages/read/batch",
        json={"session_id": session_id, "message_id": message_id},
        headers=auth_header(bob["access_token"]),
    )
    assert read_response.status_code == 200
    assert read_response.json()["data"]["event_seq"] == 1

    edit_response = client.put(
        f"/api/v1/messages/{message_id}",
        json={"content": "edited sync payload"},
        headers=auth_header(alice["access_token"]),
    )
    assert edit_response.status_code == 200
    assert edit_response.json()["data"]["event_seq"] == 2

    def receive_until(ws, expected_type: str):
        while True:
            payload = ws.receive_json()
            if payload.get("type") == expected_type:
                return payload

    with client.websocket_connect("/ws") as websocket:
        authenticate_ws(websocket, alice["access_token"], msg_id="ws-auth-sync-events-read-edit")
        websocket.send_json(
            {
                "type": "sync_messages",
                "msg_id": "97000000-0000-4000-8000-000000000001",
                "data": {
                    "session_cursors": {session_id: 1},
                    "event_cursors": {session_id: 0},
                },
            }
        )

        history_payload = receive_until(websocket, "history_messages")
        assert history_payload["data"]["messages"] == []

        events_payload = receive_until(websocket, "history_events")
        events = events_payload["data"]["events"]
        assert [item["type"] for item in events] == ["read", "message_edit"]
        assert [item["seq"] for item in events] == [1, 2]
        assert events[0]["data"]["last_read_seq"] == 1
        assert events[0]["data"]["event_seq"] == 1
        assert events[1]["data"]["message_id"] == message_id
        assert "msg_id" not in events[1]["data"]
        assert events[1]["data"]["content"] == "edited sync payload"
        assert events[1]["data"]["event_seq"] == 2


def test_websocket_sync_messages_replays_offline_recall_and_delete_events(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    first_message = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000020", "content": "first message", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert first_message.status_code == 200
    first_message_id = first_message.json()["data"]["message_id"]
    assert first_message.json()["data"]["session_seq"] == 1

    second_message = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000021", "content": "second message", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert second_message.status_code == 200
    second_message_id = second_message.json()["data"]["message_id"]
    assert second_message.json()["data"]["session_seq"] == 2

    recall_response = client.post(
        f"/api/v1/messages/{first_message_id}/recall",
        headers=auth_header(alice["access_token"]),
    )
    assert recall_response.status_code == 200
    assert recall_response.json()["data"]["event_seq"] == 1

    delete_response = client.delete(
        f"/api/v1/messages/{second_message_id}",
        headers=auth_header(alice["access_token"]),
    )
    assert delete_response.status_code == 200
    delete_payload = delete_response.json()["data"]
    assert delete_payload["status"] == "deleted"
    assert delete_payload["message_id"] == second_message_id
    assert delete_payload["event_seq"] == 2

    def receive_until(ws, expected_type: str):
        while True:
            payload = ws.receive_json()
            if payload.get("type") == expected_type:
                return payload

    with client.websocket_connect("/ws") as websocket:
        authenticate_ws(websocket, bob["access_token"], msg_id="ws-auth-sync-events-recall-delete")
        websocket.send_json(
            {
                "type": "sync_messages",
                "msg_id": "97000000-0000-4000-8000-000000000002",
                "data": {
                    "session_cursors": {session_id: 2},
                    "event_cursors": {session_id: 0},
                },
            }
        )

        history_payload = receive_until(websocket, "history_messages")
        assert history_payload["data"]["messages"] == []

        events_payload = receive_until(websocket, "history_events")
        events = events_payload["data"]["events"]
        assert [item["type"] for item in events] == ["message_recall", "message_delete"]
        assert [item["seq"] for item in events] == [1, 2]
        assert events[0]["data"]["message_id"] == first_message_id
        assert "msg_id" not in events[0]["data"]
        assert events[0]["data"]["event_seq"] == 1
        assert events[1]["data"]["message_id"] == second_message_id
        assert "msg_id" not in events[1]["data"]
        assert events[1]["data"]["event_seq"] == 2


def test_file_upload_returns_normalized_media_metadata_and_list_roundtrips(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_upload", "Alice Upload")
    payload = b"assistim upload payload"

    upload_response = client.post(
        "/api/v1/files/upload",
        files={"file": ("demo-note.txt", payload, "application/x-msdownload")},
        headers=auth_header(alice["access_token"]),
    )
    assert upload_response.status_code == 200
    uploaded = upload_response.json()["data"]

    assert uploaded["url"].startswith("/uploads/")
    assert uploaded["mime_type"] == "text/plain"
    assert uploaded["original_name"] == "demo-note.txt"
    assert uploaded["size_bytes"] == len(payload)
    assert set(uploaded) == {"id", "url", "mime_type", "original_name", "size_bytes", "created_at"}

    unauthenticated_download = client.get(uploaded["url"])
    assert unauthenticated_download.status_code == 401

    authenticated_download = client.get(
        uploaded["url"],
        headers=auth_header(alice["access_token"]),
    )
    assert authenticated_download.status_code == 200
    assert authenticated_download.content == payload

    list_response = client.get(
        "/api/v1/files",
        headers=auth_header(alice["access_token"]),
    )
    assert list_response.status_code == 200
    listed = list_response.json()["data"]
    assert len(listed) == 1
    assert listed[0] == {key: uploaded[key] for key in ("id", "url", "mime_type", "original_name", "size_bytes")}

    second_upload_response = client.post(
        "/api/v1/files/upload",
        files={"file": ("second-note.txt", b"second payload", "text/plain")},
        headers=auth_header(alice["access_token"]),
    )
    assert second_upload_response.status_code == 200

    limited_response = client.get(
        "/api/v1/files?limit=1",
        headers=auth_header(alice["access_token"]),
    )
    assert limited_response.status_code == 200
    assert len(limited_response.json()["data"]) == 1

    invalid_limit_response = client.get(
        "/api/v1/files?limit=0",
        headers=auth_header(alice["access_token"]),
    )
    assert invalid_limit_response.status_code == 422


def test_attachment_message_extra_roundtrips_through_history_and_sync_messages(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_attachment_roundtrip", "Alice Attachment")
    bob = user_factory("bob_attachment_roundtrip", "Bob Attachment")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    attachment_extra = {
        "url": "/uploads/2026/03/24/demo-image.png",
        "file_type": "image/png",
        "size": 2048,
        "media": {
            "url": "/uploads/2026/03/24/demo-image.png",
            "original_name": "demo-image.png",
            "mime_type": "image/png",
            "storage_provider": "local",
            "storage_key": "2026/03/24/demo-image.png",
            "size_bytes": 2048,
            "checksum_sha256": "abc123",
        },
    }

    create_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "10000000-0000-4000-8000-000000000022",
            "content": "/uploads/2026/03/24/demo-image.png",
            "message_type": "image",
            "extra": attachment_extra,
        },
        headers=auth_header(alice["access_token"]),
    )
    assert create_message_response.status_code == 200
    created_payload = create_message_response.json()["data"]
    assert created_payload["extra"]["url"] == attachment_extra["url"]
    assert "storage_provider" not in created_payload["extra"]["media"]
    assert "storage_key" not in created_payload["extra"]["media"]

    history_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(bob["access_token"]),
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()["data"]
    assert len(history_payload) == 1
    assert history_payload[0]["message_id"] == created_payload["message_id"]
    assert history_payload[0]["extra"]["url"] == attachment_extra["url"]
    assert history_payload[0]["extra"]["media"]["mime_type"] == "image/png"
    assert "checksum_sha256" not in history_payload[0]["extra"]["media"]

    def receive_until(ws, expected_type: str):
        while True:
            payload = ws.receive_json()
            if payload.get("type") == expected_type:
                return payload

    with client.websocket_connect("/ws") as websocket:
        authenticate_ws(websocket, bob["access_token"], msg_id="ws-auth-attachment-sync")
        websocket.send_json(
            {
                "type": "sync_messages",
                "msg_id": "98000000-0000-4000-8000-000000000001",
                "data": {
                    "session_cursors": {session_id: 0},
                    "event_cursors": {session_id: 0},
                },
            }
        )

        sync_messages_payload = receive_until(websocket, "history_messages")
        assert len(sync_messages_payload["data"]["messages"]) == 1
        synced_message = sync_messages_payload["data"]["messages"][0]
        assert "storage_key" not in synced_message["extra"]["media"]
        assert synced_message["extra"]["media"]["size_bytes"] == 2048

        sync_events_payload = receive_until(websocket, "history_events")
        assert sync_events_payload["data"]["events"] == []


def test_file_upload_rejects_disallowed_file_types(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_disallowed_upload", "Alice Disallowed Upload")

    upload_response = client.post(
        "/api/v1/files/upload",
        files={"file": ("malware.exe", b"not-really-an-exe", "application/x-msdownload")},
        headers=auth_header(alice["access_token"]),
    )

    assert upload_response.status_code == 422
    assert upload_response.json()["message"] == "upload file type is not allowed"


def test_file_upload_removes_stored_object_when_database_insert_fails(
    client: TestClient,
    user_factory,
    auth_header,
    monkeypatch,
) -> None:
    from pathlib import Path

    from app.repositories.file_repo import FileRepository

    alice = user_factory("alice_orphan_upload", "Alice Orphan Upload")
    upload_dir = Path(client.app.state.settings.upload_dir)
    files_before = {path.relative_to(upload_dir) for path in upload_dir.rglob("*") if path.is_file()}

    def fail_create(self, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(FileRepository, "create", fail_create)

    with pytest.raises(RuntimeError, match="database unavailable"):
        client.post(
            "/api/v1/files/upload",
            files={"file": ("orphan.txt", b"orphan payload", "text/plain")},
            headers=auth_header(alice["access_token"]),
        )

    files_after = {path.relative_to(upload_dir) for path in upload_dir.rglob("*") if path.is_file()}
    assert files_after == files_before


def test_file_upload_canonicalizes_name_and_derives_content_type(
    client: TestClient,
) -> None:
    from io import BytesIO

    from fastapi import UploadFile

    from app.media.storage import LocalMediaStorage

    storage = LocalMediaStorage(client.app.state.settings)
    stored = storage.store_upload(
        UploadFile(
            BytesIO(b"plain text payload"),
            filename="..\\bad\r\nname-" + "x" * 160 + ".txt",
        )
    )

    assert stored.content_type == "text/plain"
    assert "\r" not in stored.original_name
    assert "\n" not in stored.original_name
    assert "\\" not in stored.original_name
    assert len(stored.original_name) <= 120
    assert stored.original_name.endswith(".txt")


def test_file_upload_rejects_empty_files(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_empty_upload", "Alice Empty Upload")

    upload_response = client.post(
        "/api/v1/files/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
        headers=auth_header(alice["access_token"]),
    )
    assert upload_response.status_code == 422
    assert upload_response.json()["message"] == "empty uploads are not allowed"


def test_delete_private_session_removes_messages_reads_members_and_events(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.message import Message, MessageRead
    from app.models.session import ChatSession, SessionEvent, SessionMember

    alice = user_factory("alice_delete_session", "Alice Delete Session")
    bob = user_factory("bob_delete_session", "Bob Delete Session")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000024", "content": "cleanup target", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert send_message_response.status_code == 200
    message_id = send_message_response.json()["data"]["message_id"]

    read_response = client.post(
        "/api/v1/messages/read/batch",
        json={"session_id": session_id, "message_id": message_id},
        headers=auth_header(bob["access_token"]),
    )
    assert read_response.status_code == 200
    assert read_response.json()["data"]["event_seq"] == 1

    delete_response = client.delete(
        f"/api/v1/sessions/{session_id}",
        headers=auth_header(alice["access_token"]),
    )
    assert delete_response.status_code == 204

    with SessionLocal() as db:
        assert db.get(ChatSession, session_id) is None
        assert db.execute(select(Message.id).where(Message.session_id == session_id)).scalars().all() == []
        assert db.execute(select(MessageRead.message_id).where(MessageRead.message_id == message_id)).scalars().all() == []
        assert db.execute(select(SessionMember.user_id).where(SessionMember.session_id == session_id)).scalars().all() == []
        assert db.execute(select(SessionEvent.id).where(SessionEvent.session_id == session_id)).scalars().all() == []


def test_delete_group_removes_group_session_messages_and_events(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.group import Group, GroupMember
    from app.models.message import Message, MessageRead
    from app.models.session import ChatSession, SessionEvent, SessionMember

    alice = user_factory("alice_delete_group", "Alice Delete Group")
    bob = user_factory("bob_delete_group", "Bob Delete Group")

    create_group_response = client.post(
        "/api/v1/groups",
        json={"name": "Delete Group", "member_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_group_response.status_code == 201
    group_payload = create_group_response.json()["data"]["group"]
    group_id = group_payload["id"]
    session_id = group_payload["session_id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"msg_id": "10000000-0000-4000-8000-000000000025", "content": "group cleanup target", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert send_message_response.status_code == 200
    message_id = send_message_response.json()["data"]["message_id"]

    read_response = client.post(
        "/api/v1/messages/read/batch",
        json={"session_id": session_id, "message_id": message_id},
        headers=auth_header(bob["access_token"]),
    )
    assert read_response.status_code == 200
    assert read_response.json()["data"]["event_seq"] == 1

    delete_response = client.delete(
        f"/api/v1/groups/{group_id}",
        headers=auth_header(alice["access_token"]),
    )
    assert delete_response.status_code == 200
    delete_payload = delete_response.json()["data"]
    assert delete_payload["group"] is None
    assert delete_payload["mutation"]["action"] == "deleted"

    with SessionLocal() as db:
        assert db.get(Group, group_id) is None
        assert db.get(ChatSession, session_id) is None
        assert db.execute(select(GroupMember.user_id).where(GroupMember.group_id == group_id)).scalars().all() == []
        assert db.execute(select(SessionMember.user_id).where(SessionMember.session_id == session_id)).scalars().all() == []
        assert db.execute(select(Message.id).where(Message.session_id == session_id)).scalars().all() == []
        assert db.execute(select(MessageRead.message_id).where(MessageRead.message_id == message_id)).scalars().all() == []
        assert db.execute(select(SessionEvent.id).where(SessionEvent.session_id == session_id)).scalars().all() == []








def test_websocket_receives_realtime_user_profile_update_events(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_profile_event_live", "Alice")
    bob = user_factory("bob_profile_event_live", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    with client.websocket_connect("/ws") as bob_ws:
        authenticate_ws(bob_ws, bob["access_token"], msg_id="ws-auth-profile-live")

        update_response = client.post(
            "/api/v1/users/me/avatar",
            headers=auth_header(alice["access_token"]),
            files={"file": ("avatar.png", b"profile-live-avatar", "image/png")},
        )
        assert update_response.status_code == 200
        updated_avatar = update_response.json()["data"]["avatar"]

        while True:
            payload = bob_ws.receive_json()
            if payload.get("type") == "user_profile_update":
                break

        assert payload["seq"] == 0
        assert "session_id" not in payload["data"]
        assert payload["data"]["user_id"] == alice["user"]["id"]
        assert "session_avatar" not in payload["data"]
        assert payload["data"]["profile_event_id"].startswith(f"user-profile:{alice['user']['id']}:")
        assert payload["data"]["profile"]["avatar"] == updated_avatar
        assert payload["data"]["profile"]["display_name"] == "Alice"
        assert payload["data"]["profile"]["avatar_kind"] == "custom"
        assert "event_seq" not in payload["data"]


def test_websocket_sync_messages_replays_offline_user_profile_update_events(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_profile_event_sync", "Alice")
    bob = user_factory("bob_profile_event_sync", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    update_response = client.put(
        "/api/v1/users/me",
        json={"nickname": "Alice Prime"},
        headers=auth_header(alice["access_token"]),
    )
    assert update_response.status_code == 200

    def receive_until(ws, expected_type: str):
        while True:
            payload = ws.receive_json()
            if payload.get("type") == expected_type:
                return payload

    with client.websocket_connect("/ws") as websocket:
        authenticate_ws(websocket, bob["access_token"], msg_id="ws-auth-profile-sync")
        websocket.send_json(
            {
                "type": "sync_messages",
                "msg_id": "97000000-0000-4000-8000-000000000099",
                "data": {
                    "session_cursors": {},
                    "event_cursors": {session_id: 0},
                },
            }
        )

        history_payload = receive_until(websocket, "history_messages")
        assert history_payload["data"]["messages"] == []

        events_payload = receive_until(websocket, "history_events")
        events = events_payload["data"]["events"]
        assert len(events) == 1
        assert events[0]["type"] == "user_profile_update"
        assert events[0]["seq"] == 1
        assert "session_id" not in events[0]["data"]
        assert events[0]["data"]["profile"]["nickname"] == "Alice Prime"
        assert "session_avatar" not in events[0]["data"]
        assert events[0]["data"]["profile_event_id"].startswith(f"user-profile:{alice['user']['id']}:")
        assert events[0]["data"]["profile"]["display_name"] == "Alice Prime"
        assert events[0]["data"]["event_seq"] == 1


def test_websocket_receives_realtime_group_profile_update_events(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    owner = user_factory('group_profile_ws_owner', 'Owner')
    member = user_factory('group_profile_ws_member', 'Member')

    create_group_response = client.post(
        '/api/v1/groups',
        json={'name': 'Before', 'member_ids': [member['user']['id']]},
        headers=auth_header(owner['access_token']),
    )
    assert create_group_response.status_code == 201
    group_payload = create_group_response.json()['data']['group']
    group_id = group_payload['id']
    session_id = group_payload['session_id']

    with client.websocket_connect('/ws') as member_ws:
        authenticate_ws(member_ws, member['access_token'], msg_id='ws-auth-group-profile-member')

        response = client.patch(
            f'/api/v1/groups/{group_id}',
            json={'name': 'After', 'announcement': 'Deploy tonight'},
            headers=auth_header(owner['access_token']),
        )
        assert response.status_code == 200

        payload = receive_until(member_ws, 'group_profile_update')
        assert payload['data']['session_id'] == session_id
        assert payload['data']['group_id'] == group_id
        assert payload['data']['name'] == 'After'
        assert payload['data']['announcement'] == 'Deploy tonight'
        assert int(payload['data']['event_seq']) > 0


def test_websocket_sync_messages_replays_offline_group_profile_update_events(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    owner = user_factory('group_profile_sync_owner', 'Owner')
    member = user_factory('group_profile_sync_member', 'Member')

    create_group_response = client.post(
        '/api/v1/groups',
        json={'name': 'Before', 'member_ids': [member['user']['id']]},
        headers=auth_header(owner['access_token']),
    )
    assert create_group_response.status_code == 201
    group_payload = create_group_response.json()['data']['group']
    group_id = group_payload['id']
    session_id = group_payload['session_id']

    response = client.patch(
        f'/api/v1/groups/{group_id}',
        json={'name': 'After', 'announcement': 'Deploy tonight'},
        headers=auth_header(owner['access_token']),
    )
    assert response.status_code == 200

    with client.websocket_connect('/ws') as websocket:
        authenticate_ws(websocket, member['access_token'], msg_id='ws-auth-group-profile-sync')
        websocket.send_json(
            {
                'type': 'sync_messages',
                'msg_id': 'sync-group-profile-update',
                'data': {
                    'session_cursors': {},
                    'event_cursors': {session_id: 0},
                },
            }
        )
        receive_until(websocket, 'history_messages')
        events_payload = receive_until(websocket, 'history_events')
        events = events_payload['data']['events']
        assert len(events) == 1
        assert events[0]['type'] == 'group_profile_update'
        assert events[0]['data']['session_id'] == session_id
        assert events[0]['data']['group_id'] == group_id
        assert events[0]['data']['name'] == 'After'
        assert events[0]['data']['announcement'] == 'Deploy tonight'


def test_websocket_sync_messages_replays_offline_group_self_profile_update_events(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    owner = user_factory('group_self_profile_sync_owner', 'Owner')
    member = user_factory('group_self_profile_sync_member', 'Member')

    create_group_response = client.post(
        '/api/v1/groups',
        json={'name': 'Ops', 'member_ids': [member['user']['id']]},
        headers=auth_header(owner['access_token']),
    )
    assert create_group_response.status_code == 201
    group_payload = create_group_response.json()['data']['group']
    group_id = group_payload['id']
    session_id = group_payload['session_id']

    response = client.patch(
        f'/api/v1/groups/{group_id}/me',
        json={'note': 'private note', 'my_group_nickname': 'oncall'},
        headers=auth_header(member['access_token']),
    )
    assert response.status_code == 200

    with client.websocket_connect('/ws') as websocket:
        authenticate_ws(websocket, member['access_token'], msg_id='ws-auth-group-self-profile-sync')
        websocket.send_json(
            {
                'type': 'sync_messages',
                'msg_id': 'sync-group-self-profile-update',
                'data': {
                    'session_cursors': {},
                    'event_cursors': {session_id: 0},
                },
            }
        )
        receive_until(websocket, 'history_messages')
        events_payload = receive_until(websocket, 'history_events')
        events = events_payload['data']['events']
        assert len(events) == 1
        assert events[0]['type'] == 'group_self_profile_update'
        assert events[0]['data']['session_id'] == session_id
        assert events[0]['data']['group_id'] == group_id
        assert events[0]['data']['group_note'] == 'private note'
        assert events[0]['data']['my_group_nickname'] == 'oncall'
        assert int(events[0]['data']['event_seq']) > 0

def test_private_call_signaling_invite_accept_and_hangup(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_call_signal", "Alice Call Signal")
    bob = user_factory("bob_call_signal", "Bob Call Signal")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    with client.websocket_connect("/ws") as alice_ws, client.websocket_connect("/ws") as bob_ws:
        authenticate_ws(alice_ws, alice["access_token"], msg_id="ws-auth-call-alice")
        authenticate_ws(bob_ws, bob["access_token"], msg_id="ws-auth-call-bob")

        alice_ws.send_json(
            {
                "type": "call_invite",
                "msg_id": "call-voice-001",
                "data": {
                    "call_id": "call-voice-001",
                    "session_id": session_id,
                    "media_type": "voice",
                },
            }
        )
        invite_payload = receive_until(bob_ws, "call_invite")
        assert invite_payload["data"]["call_id"] == "call-voice-001"
        assert invite_payload["data"]["session_id"] == session_id
        assert invite_payload["data"]["initiator_id"] == alice["user"]["id"]
        assert invite_payload["data"]["recipient_id"] == bob["user"]["id"]
        assert invite_payload["data"]["media_type"] == "voice"

        bob_ws.send_json(
            {
                "type": "call_ringing",
                "msg_id": "call-voice-001-ringing",
                "data": {"call_id": "call-voice-001"},
            }
        )
        ringing_payload = receive_until(alice_ws, "call_ringing")
        assert ringing_payload["data"]["call_id"] == "call-voice-001"
        assert ringing_payload["data"]["actor_id"] == bob["user"]["id"]

        bob_ws.send_json(
            {
                "type": "call_accept",
                "msg_id": "call-voice-001-accept",
                "data": {"call_id": "call-voice-001"},
            }
        )
        alice_accept_payload = receive_until(alice_ws, "call_accept")
        bob_accept_payload = receive_until(bob_ws, "call_accept")
        assert alice_accept_payload["data"]["status"] == "accepted"
        assert bob_accept_payload["data"]["status"] == "accepted"

        alice_ws.send_json(
            {
                "type": "call_hangup",
                "msg_id": "call-voice-001-hangup",
                "data": {"call_id": "call-voice-001"},
            }
        )
        alice_hangup_payload = receive_until(alice_ws, "call_hangup")
        bob_hangup_payload = receive_until(bob_ws, "call_hangup")
        assert alice_hangup_payload["data"]["reason"] == "hangup"
        assert bob_hangup_payload["data"]["reason"] == "hangup"
        assert bob_hangup_payload["data"]["actor_id"] == alice["user"]["id"]


def test_private_call_signaling_preserves_timeout_reason(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_call_timeout", "Alice Call Timeout")
    bob = user_factory("bob_call_timeout", "Bob Call Timeout")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    with client.websocket_connect("/ws") as alice_ws, client.websocket_connect("/ws") as bob_ws:
        authenticate_ws(alice_ws, alice["access_token"], msg_id="ws-auth-call-timeout-alice")
        authenticate_ws(bob_ws, bob["access_token"], msg_id="ws-auth-call-timeout-bob")

        alice_ws.send_json(
            {
                "type": "call_invite",
                "msg_id": "call-timeout-001",
                "data": {
                    "call_id": "call-timeout-001",
                    "session_id": session_id,
                    "media_type": "voice",
                },
            }
        )
        invite_payload = receive_until(bob_ws, "call_invite")
        assert invite_payload["data"]["call_id"] == "call-timeout-001"

        alice_ws.send_json(
            {
                "type": "call_hangup",
                "msg_id": "call-timeout-001-hangup",
                "data": {"call_id": "call-timeout-001", "reason": "timeout"},
            }
        )
        alice_hangup_payload = receive_until(alice_ws, "call_hangup")
        bob_hangup_payload = receive_until(bob_ws, "call_hangup")
        assert alice_hangup_payload["data"]["reason"] == "timeout"
        assert bob_hangup_payload["data"]["reason"] == "timeout"
        assert bob_hangup_payload["data"]["actor_id"] == alice["user"]["id"]


def test_private_call_signaling_reports_busy_for_second_invite(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_call_busy", "Alice Call Busy")
    bob = user_factory("bob_call_busy", "Bob Call Busy")
    charlie = user_factory("charlie_call_busy", "Charlie Call Busy")

    first_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert first_session_response.status_code == 200
    first_session_id = first_session_response.json()["data"]["id"]

    second_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(charlie["access_token"]),
    )
    assert second_session_response.status_code == 200
    second_session_id = second_session_response.json()["data"]["id"]

    with (
        client.websocket_connect("/ws") as alice_ws,
        client.websocket_connect("/ws") as bob_ws,
        client.websocket_connect("/ws") as charlie_ws,
    ):
        authenticate_ws(alice_ws, alice["access_token"], msg_id="ws-auth-call-busy-alice")
        authenticate_ws(bob_ws, bob["access_token"], msg_id="ws-auth-call-busy-bob")
        authenticate_ws(charlie_ws, charlie["access_token"], msg_id="ws-auth-call-busy-charlie")

        alice_ws.send_json(
            {
                "type": "call_invite",
                "msg_id": "call-busy-001",
                "data": {
                    "call_id": "call-busy-001",
                    "session_id": first_session_id,
                    "media_type": "voice",
                },
            }
        )
        first_invite_payload = receive_until(bob_ws, "call_invite")
        assert first_invite_payload["data"]["call_id"] == "call-busy-001"

        charlie_ws.send_json(
            {
                "type": "call_invite",
                "msg_id": "call-busy-002",
                "data": {
                    "call_id": "call-busy-002",
                    "session_id": second_session_id,
                    "media_type": "video",
                },
            }
        )
        busy_payload = receive_until(charlie_ws, "call_busy")
        assert busy_payload["data"]["call_id"] == "call-busy-002"
        assert busy_payload["data"]["active_call_id"] == "call-busy-001"
        assert busy_payload["data"]["busy_user_id"] == bob["user"]["id"]




def test_message_mutations_succeed_when_realtime_fanout_fails(
    client: TestClient,
    user_factory,
    auth_header,
    monkeypatch,
) -> None:
    from app.api.v1 import messages as message_routes

    alice = user_factory("alice_message_fanout", "Alice")
    bob = user_factory("bob_message_fanout", "Bob")

    session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    session_id = session_response.json()["data"]["id"]

    message_ids = []
    for index, content in enumerate(["before", "recall me", "delete me", "read me"], start=26):
        send_response = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={
                "msg_id": f"10000000-0000-4000-8000-0000000000{index}",
                "content": content,
                "message_type": "text",
            },
            headers=auth_header(alice["access_token"]),
        )
        assert send_response.status_code == 200
        message_ids.append(send_response.json()["data"]["message_id"])

    monkeypatch.setattr(
        message_routes.connection_manager,
        "send_json_to_users",
        AsyncMock(side_effect=RuntimeError("fanout failed")),
    )

    edit_response = client.put(
        f"/api/v1/messages/{message_ids[0]}",
        json={"content": "after"},
        headers=auth_header(alice["access_token"]),
    )
    assert edit_response.status_code == 200
    assert edit_response.json()["data"]["content"] == "after"

    recall_response = client.post(
        f"/api/v1/messages/{message_ids[1]}/recall",
        headers=auth_header(alice["access_token"]),
    )
    assert recall_response.status_code == 200
    assert recall_response.json()["data"]["status"] == "recalled"

    delete_response = client.delete(
        f"/api/v1/messages/{message_ids[2]}",
        headers=auth_header(alice["access_token"]),
    )
    assert delete_response.status_code == 200
    delete_payload = delete_response.json()["data"]
    assert delete_payload["status"] == "deleted"
    assert delete_payload["message_id"] == message_ids[2]
    assert int(delete_payload["event_seq"]) > 0

    read_response = client.post(
        "/api/v1/messages/read/batch",
        json={"session_id": session_id, "message_id": message_ids[3]},
        headers=auth_header(bob["access_token"]),
    )
    assert read_response.status_code == 200
    assert read_response.json()["data"]["advanced"] is True


def test_http_edit_and_recall_do_not_broadcast_back_to_actor_user(
    client: TestClient,
    user_factory,
    auth_header,
    monkeypatch,
) -> None:
    from app.api.v1 import messages as message_routes

    alice = user_factory("alice_message_actor_echo", "Alice")
    bob = user_factory("bob_message_actor_echo", "Bob")

    session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert session_response.status_code == 200
    session_id = session_response.json()["data"]["id"]

    message_ids = []
    for index, content in enumerate(["edit me", "recall me"], start=51):
        send_response = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={
                "msg_id": f"11000000-0000-4000-8000-0000000000{index}",
                "content": content,
                "message_type": "text",
            },
            headers=auth_header(alice["access_token"]),
        )
        assert send_response.status_code == 200
        message_ids.append(send_response.json()["data"]["message_id"])

    send_json_to_users = AsyncMock(return_value=set())
    monkeypatch.setattr(message_routes.connection_manager, "send_json_to_users", send_json_to_users)

    edit_response = client.put(
        f"/api/v1/messages/{message_ids[0]}",
        json={"content": "edited"},
        headers=auth_header(alice["access_token"]),
    )
    assert edit_response.status_code == 200

    recall_response = client.post(
        f"/api/v1/messages/{message_ids[1]}/recall",
        headers=auth_header(alice["access_token"]),
    )
    assert recall_response.status_code == 200

    called_user_lists = [call.args[0] for call in send_json_to_users.await_args_list]
    assert called_user_lists == [[bob["user"]["id"]], [bob["user"]["id"]]]


def test_accept_friend_request_succeeds_when_contact_refresh_fails(
    client: TestClient,
    user_factory,
    auth_header,
    monkeypatch,
) -> None:
    from app.api.v1 import friends as friend_routes

    alice = user_factory("alice_accept_fanout", "Alice")
    bob = user_factory("bob_accept_fanout", "Bob")

    request_response = client.post(
        "/api/v1/friends/requests",
        json={"receiver_id": bob["user"]["id"], "message": "ping"},
        headers=auth_header(alice["access_token"]),
    )
    request_id = request_response.json()["data"]["request_id"]

    monkeypatch.setattr(
        friend_routes.connection_manager,
        "send_json_to_users",
        AsyncMock(side_effect=RuntimeError("fanout failed")),
    )

    response = client.post(
        f"/api/v1/friends/requests/{request_id}/accept",
        headers=auth_header(bob["access_token"]),
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "accepted"


def test_create_direct_session_requires_exactly_one_normalized_participant(client: TestClient, user_factory, auth_header) -> None:
    alice = user_factory("alice_direct_schema", "Alice")
    bob = user_factory("bob_direct_schema", "Bob")
    charlie = user_factory("charlie_direct_schema", "Charlie")

    blank_participant = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": ["   "]},
        headers=auth_header(alice["access_token"]),
    )
    assert blank_participant.status_code == 422

    multiple_participants = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"], charlie["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert multiple_participants.status_code == 422

    oversized_participant = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": ["u" * 129]},
        headers=auth_header(alice["access_token"]),
    )
    assert oversized_participant.status_code == 422

    non_string_participant = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [123]},
        headers=auth_header(alice["access_token"]),
    )
    assert non_string_participant.status_code == 422

    extra_field = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]], "extra": True},
        headers=auth_header(alice["access_token"]),
    )
    assert extra_field.status_code == 422

    name_field = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
        headers=auth_header(alice["access_token"]),
    )
    assert name_field.status_code == 422

    normalized_participant = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [f"  {bob['user']['id']}  "]},
        headers=auth_header(alice["access_token"]),
    )
    assert normalized_participant.status_code == 200
    normalized_payload = normalized_participant.json()["data"]
    assert normalized_payload["counterpart_id"] == bob["user"]["id"]
    assert bob["user"]["id"] in normalized_payload["participant_ids"]

    duplicate_participant = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"], f"  {bob['user']['id']}  "]},
        headers=auth_header(alice["access_token"]),
    )
    assert duplicate_participant.status_code == 200
    duplicate_payload = duplicate_participant.json()["data"]
    assert duplicate_payload["counterpart_id"] == bob["user"]["id"]
    assert duplicate_payload["participant_ids"].count(bob["user"]["id"]) == 1


def test_friend_request_requires_one_consistent_target_field(client: TestClient, user_factory, auth_header) -> None:
    alice = user_factory("alice_friend_schema", "Alice")
    bob = user_factory("bob_friend_schema", "Bob")
    charlie = user_factory("charlie_friend_schema", "Charlie")

    missing_target = client.post(
        "/api/v1/friends/requests",
        json={"message": "hello"},
        headers=auth_header(alice["access_token"]),
    )
    assert missing_target.status_code == 422

    conflicting_target = client.post(
        "/api/v1/friends/requests",
        json={"receiver_id": bob["user"]["id"], "user_id": charlie["user"]["id"]},
        headers=auth_header(alice["access_token"]),
    )
    assert conflicting_target.status_code == 422

    extra_field = client.post(
        "/api/v1/friends/requests",
        json={"receiver_id": bob["user"]["id"], "extra": True},
        headers=auth_header(alice["access_token"]),
    )
    assert extra_field.status_code == 422

    oversized_message = client.post(
        "/api/v1/friends/requests",
        json={"receiver_id": bob["user"]["id"], "message": "x" * 501},
        headers=auth_header(alice["access_token"]),
    )
    assert oversized_message.status_code == 422

    normalized_target = client.post(
        "/api/v1/friends/requests",
        json={"user_id": f"  {bob['user']['id']}  ", "message": "  hi  "},
        headers=auth_header(alice["access_token"]),
    )
    assert normalized_target.status_code == 200
    request_payload = normalized_target.json()["data"]
    assert request_payload["receiver"]["id"] == bob["user"]["id"]
    assert request_payload["sender"]["id"] == alice["user"]["id"]
    assert "sender_id" not in request_payload
    assert "receiver_id" not in request_payload
    assert "from_user" not in request_payload
    assert "to_user" not in request_payload

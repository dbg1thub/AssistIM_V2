"""Chat and friendship API tests."""

from __future__ import annotations

from datetime import datetime
import hashlib
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
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
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
        json={"content": "hello bob", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert send_message_response.status_code == 200
    message_payload = send_message_response.json()["data"]
    assert message_payload["message_id"]
    assert message_payload["message_type"] == "text"
    assert "id" not in message_payload
    assert "msg_id" not in message_payload
    assert "type" not in message_payload
    assert datetime.fromisoformat(message_payload["timestamp"])
    assert datetime.fromisoformat(message_payload["created_at"])
    assert datetime.fromisoformat(message_payload["updated_at"])
    assert message_payload["timestamp"] == message_payload["created_at"]
    assert message_payload["session_type"] == "direct"
    assert sorted(message_payload["participant_ids"]) == sorted([alice["user"]["id"], bob["user"]["id"]])
    assert message_payload["session_name"] == "Alice & Bob"
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
    assert datetime.fromisoformat(history_payload[0]["timestamp"])
    assert history_payload[0]["timestamp"] == message_payload["timestamp"]
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
    assert session_payload[0]["last_message_time"] == message_payload["timestamp"]

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
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
        headers=auth_header(alice["access_token"]),
    )
    assert first_response.status_code == 200
    first_payload = first_response.json()["data"]

    second_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]], "name": "Renamed Private Chat"},
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
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "legacy http body", "type": "text"},
        headers=auth_header(alice["access_token"]),
    )

    assert response.status_code == 422
    assert "type" in response.json()["message"]

def test_invalid_read_ack_does_not_disconnect_websocket(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
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
        assert "not a session member" in error_payload["data"]["message"]

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
        assert error_payload["data"]["message"] == "message_id is required"


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
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
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
            assert received["data"]["session_name"] == "Alice & Bob"
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
    session_id = group_response.json()["data"]["session_id"]

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
    group_payload = group_response.json()["data"]
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
        json={"content": "@所有人 hi", "message_type": "text", "extra": mention_extra},
        headers=auth_header(member["access_token"]),
    )
    assert member_response.status_code == 403

    admin_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "@所有人 hi", "message_type": "text", "extra": mention_extra},
        headers=auth_header(admin["access_token"]),
    )
    assert admin_response.status_code == 200
    assert admin_response.json()["data"]["extra"]["mentions"][0]["mention_type"] == "all"

    owner_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "@所有人 hi", "message_type": "text", "extra": mention_extra},
        headers=auth_header(owner["access_token"]),
    )
    assert owner_response.status_code == 200


def test_presence_websocket_requires_valid_token(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/presence") as websocket:
            websocket.receive_json()
    assert exc_info.value.code == 1008


def test_chat_websocket_rejects_user_id_only_auth_and_keeps_socket_open(
    client: TestClient,
    user_factory,
) -> None:
    alice = user_factory("alice", "Alice")
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

        websocket.send_json(
            {
                "type": "auth",
                "msg_id": "91000000-0000-4000-8000-000000000002",
                "data": {"token": alice["access_token"]},
            }
        )
        auth_payload = receive_until(websocket, "auth_ack")
        assert auth_payload["data"]["success"] is True
        assert auth_payload["data"]["user_id"] == alice["user"]["id"]


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
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "hello bob", "message_type": "text"},
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
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "original content", "message_type": "text"},
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
    session_id = group_response.json()["data"]["session_id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "group hello", "message_type": "text"},
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
    assert before_payload["status"] == "sent"
    assert before_payload["read_count"] == 0
    assert before_payload["read_target_count"] == 2
    assert before_payload["read_by_user_ids"] == []

    bob_read_response = client.post(
        "/api/v1/messages/read/batch",
        json={"session_id": session_id, "message_id": message_id},
        headers=auth_header(bob["access_token"]),
    )
    assert bob_read_response.status_code == 200
    bob_read_payload = bob_read_response.json()["data"]
    assert bob_read_payload["success"] is True
    assert bob_read_payload["message_id"] == message_id
    assert "last_read_message_id" not in bob_read_payload
    assert bob_read_payload["last_read_seq"] == 1
    assert bob_read_payload["user_id"] == bob["user"]["id"]

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
    assert after_payload["read_count"] == 1
    assert after_payload["read_target_count"] == 2
    assert after_payload["read_by_user_ids"] == [bob["user"]["id"]]

    charlie_history = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(charlie["access_token"]),
    )
    assert charlie_history.status_code == 200
    charlie_payload = charlie_history.json()["data"][0]
    assert charlie_payload["is_read_by_me"] is False



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


def test_read_ack_websocket_broadcasts_read_cursor(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "hello bob", "message_type": "text"},
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
        bob_ws.send_json(
            {
                "type": "read_ack",
                "msg_id": "93000000-0000-4000-8000-000000000001",
                "data": {
                    "session_id": session_id,
                    "message_id": message_id,
                },
            }
        )

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
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
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
        receive_until(bob_ws, "pong", unexpected_type="chat_message")

    history_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(alice["access_token"]),
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()["data"]
    assert len(history_payload) == 1
    assert history_payload[0]["message_id"] == payload["msg_id"]
    assert history_payload[0]["session_seq"] == 1


def test_websocket_rejects_conflicting_duplicate_message_id(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
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
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    first_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "first sync message", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert first_response.status_code == 200
    assert first_response.json()["data"]["session_seq"] == 1

    second_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "second sync message", "message_type": "text"},
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
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "original sync payload", "message_type": "text"},
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
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    first_message = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "first message", "message_type": "text"},
        headers=auth_header(alice["access_token"]),
    )
    assert first_message.status_code == 200
    first_message_id = first_message.json()["data"]["message_id"]
    assert first_message.json()["data"]["session_seq"] == 1

    second_message = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "second message", "message_type": "text"},
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
    assert delete_response.status_code == 204

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
        files={"file": ("demo-note.txt", payload, "text/plain")},
        headers=auth_header(alice["access_token"]),
    )
    assert upload_response.status_code == 200
    uploaded = upload_response.json()["data"]

    assert uploaded["url"].startswith("/uploads/")
    assert uploaded["file_url"] == uploaded["url"]
    assert uploaded["storage_provider"] == "local"
    assert uploaded["storage_key"]
    assert uploaded["mime_type"] == "text/plain"
    assert uploaded["file_type"] == "text/plain"
    assert uploaded["original_name"] == "demo-note.txt"
    assert uploaded["file_name"] == "demo-note.txt"
    assert uploaded["size_bytes"] == len(payload)
    assert uploaded["checksum_sha256"] == hashlib.sha256(payload).hexdigest()
    assert uploaded["media"]["url"] == uploaded["url"]
    assert uploaded["media"]["storage_key"] == uploaded["storage_key"]
    assert uploaded["media"]["original_name"] == "demo-note.txt"

    list_response = client.get(
        "/api/v1/files",
        headers=auth_header(alice["access_token"]),
    )
    assert list_response.status_code == 200
    listed = list_response.json()["data"]
    assert len(listed) == 1
    assert listed[0]["id"] == uploaded["id"]
    assert listed[0]["storage_provider"] == "local"
    assert listed[0]["storage_key"] == uploaded["storage_key"]
    assert listed[0]["checksum_sha256"] == uploaded["checksum_sha256"]


def test_attachment_message_extra_roundtrips_through_history_and_sync_messages(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_attachment_roundtrip", "Alice Attachment")
    bob = user_factory("bob_attachment_roundtrip", "Bob Attachment")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    attachment_extra = {
        "url": "/uploads/2026/03/24/demo-image.png",
        "name": "demo-image.png",
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
            "session_id": session_id,
            "content": "/uploads/2026/03/24/demo-image.png",
            "message_type": "image",
            "extra": attachment_extra,
        },
        headers=auth_header(alice["access_token"]),
    )
    assert create_message_response.status_code == 200
    created_payload = create_message_response.json()["data"]
    assert created_payload["extra"]["url"] == attachment_extra["url"]
    assert created_payload["extra"]["media"]["storage_provider"] == "local"
    assert created_payload["extra"]["media"]["storage_key"] == "2026/03/24/demo-image.png"

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
    assert history_payload[0]["extra"]["media"]["checksum_sha256"] == "abc123"

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
        assert synced_message["extra"]["media"]["storage_key"] == "2026/03/24/demo-image.png"
        assert synced_message["extra"]["media"]["size_bytes"] == 2048

        sync_events_payload = receive_until(websocket, "history_events")
        assert sync_events_payload["data"]["events"] == []

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
        json={"participant_ids": [bob["user"]["id"]], "name": "Delete Me"},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "cleanup target", "message_type": "text"},
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
    group_payload = create_group_response.json()["data"]
    group_id = group_payload["id"]
    session_id = group_payload["session_id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "group cleanup target", "message_type": "text"},
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
    assert delete_response.status_code == 204

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
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
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

        assert payload["seq"] == 1
        assert payload["data"]["session_id"] == session_id
        assert payload["data"]["user_id"] == alice["user"]["id"]
        assert payload["data"]["profile"]["avatar"] == updated_avatar
        assert payload["data"]["event_seq"] == 1


def test_websocket_sync_messages_replays_offline_user_profile_update_events(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_profile_event_sync", "Alice")
    bob = user_factory("bob_profile_event_sync", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
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
        assert events[0]["data"]["session_id"] == session_id
        assert events[0]["data"]["profile"]["nickname"] == "Alice Prime"
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
    group_payload = create_group_response.json()['data']
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
    group_payload = create_group_response.json()['data']
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
    group_payload = create_group_response.json()['data']
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
        assert len(events) == 2
        assert events[0]['type'] == 'group_profile_update'
        assert events[1]['type'] == 'group_self_profile_update'
        assert events[1]['data']['session_id'] == session_id
        assert events[1]['data']['group_id'] == group_id
        assert events[1]['data']['group_note'] == 'private note'
        assert events[1]['data']['my_group_nickname'] == 'oncall'
        assert int(events[1]['data']['event_seq']) > int(events[0]['data']['event_seq'])

def test_private_call_signaling_invite_accept_and_hangup(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_call_signal", "Alice Call Signal")
    bob = user_factory("bob_call_signal", "Bob Call Signal")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
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
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob Timeout"},
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
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
        headers=auth_header(alice["access_token"]),
    )
    assert first_session_response.status_code == 200
    first_session_id = first_session_response.json()["data"]["id"]

    second_session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]], "name": "Charlie & Bob"},
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


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



def test_private_session_reuses_existing_and_rejects_self_chat(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    first_response = client.post(
        "/api/v1/sessions/private",
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
        headers=auth_header(alice["access_token"]),
    )
    assert first_response.status_code == 200
    first_payload = first_response.json()["data"]

    second_response = client.post(
        "/api/v1/sessions/private",
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob Again"},
        headers=auth_header(alice["access_token"]),
    )
    assert second_response.status_code == 200
    second_payload = second_response.json()["data"]
    assert second_payload["id"] == first_payload["id"]

    sessions_response = client.get(
        "/api/v1/sessions",
        headers=auth_header(alice["access_token"]),
    )
    assert sessions_response.status_code == 200
    session_ids = [item["id"] for item in sessions_response.json()["data"]]
    assert session_ids.count(first_payload["id"]) == 1

    self_chat_response = client.post(
        "/api/v1/sessions/private",
        json={"participant_ids": [alice["user"]["id"]], "name": "Me"},
        headers=auth_header(alice["access_token"]),
    )
    assert self_chat_response.status_code == 422


def test_invalid_private_sessions_are_hidden_from_session_list(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")

    from app.core.database import SessionLocal
    from app.repositories.session_repo import SessionRepository

    with SessionLocal() as db:
        repo = SessionRepository(db)
        broken = repo.create("Broken", "private")
        repo.add_member(broken.id, alice["user"]["id"])

    sessions_response = client.get(
        "/api/v1/sessions",
        headers=auth_header(alice["access_token"]),
    )
    assert sessions_response.status_code == 200
    session_ids = [item["id"] for item in sessions_response.json()["data"]]
    assert broken.id not in session_ids

    detail_response = client.get(
        f"/api/v1/sessions/{broken.id}",
        headers=auth_header(alice["access_token"]),
    )
    assert detail_response.status_code == 404


def test_group_session_membership_is_repaired_for_legacy_groups(
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
    group_payload = group_response.json()["data"]
    session_id = group_payload["session_id"]

    from app.core.database import SessionLocal
    from app.repositories.session_repo import SessionRepository

    with SessionLocal() as db:
        sessions = SessionRepository(db)
        sessions.remove_member(session_id, bob["user"]["id"])

    sessions_response = client.get(
        "/api/v1/sessions",
        headers=auth_header(bob["access_token"]),
    )
    assert sessions_response.status_code == 200
    session_ids = [item["id"] for item in sessions_response.json()["data"]]
    assert session_id in session_ids

    def receive_until(ws, expected_type: str):
        while True:
            payload = ws.receive_json()
            if payload.get("type") == expected_type:
                return payload

    with client.websocket_connect("/ws/chat") as alice_ws, client.websocket_connect("/ws/chat") as bob_ws:
        alice_ws.send_json({"type": "auth", "data": {"token": alice["access_token"]}})
        bob_ws.send_json({"type": "auth", "data": {"token": bob["access_token"]}})
        receive_until(alice_ws, "auth_ack")
        receive_until(bob_ws, "auth_ack")

        alice_ws.send_json(
            {
                "type": "chat_message",
                "msg_id": "22222222-2222-4222-8222-222222222222",
                "data": {
                    "session_id": session_id,
                    "content": "hello group",
                    "message_type": "text",
                },
            }
        )

        ack = receive_until(alice_ws, "message_ack")
        assert ack["type"] == "message_ack"
        received = receive_until(bob_ws, "chat_message")
        assert received["data"]["content"] == "hello group"
        assert received["data"]["session_id"] == session_id


def test_duplicate_private_sessions_are_collapsed_in_session_list(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    from app.core.database import SessionLocal
    from app.repositories.session_repo import SessionRepository

    with SessionLocal() as db:
        sessions = SessionRepository(db)
        first = sessions.create("Alice & Bob", "private")
        sessions.add_member(first.id, alice["user"]["id"])
        sessions.add_member(first.id, bob["user"]["id"])

        second = sessions.create("Alice & Bob Old", "private")
        sessions.add_member(second.id, alice["user"]["id"])
        sessions.add_member(second.id, bob["user"]["id"])

    sessions_response = client.get(
        "/api/v1/sessions",
        headers=auth_header(alice["access_token"]),
    )
    assert sessions_response.status_code == 200
    payload = sessions_response.json()["data"]
    private_sessions = [item for item in payload if item["session_type"] == "private"]
    assert len(private_sessions) == 1



def test_recalled_messages_are_sanitized_in_history_and_session_preview(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/private",
        json={"participant_ids": [bob["user"]["id"]], "name": "Alice & Bob"},
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    send_message_response = client.post(
        "/api/v1/messages",
        json={"session_id": session_id, "content": "/uploads/demo.png", "type": "image"},
        headers=auth_header(alice["access_token"]),
    )
    assert send_message_response.status_code == 200
    message_id = send_message_response.json()["data"]["id"]

    recall_response = client.post(
        f"/api/v1/messages/{message_id}/recall",
        headers=auth_header(alice["access_token"]),
    )
    assert recall_response.status_code == 200

    history_response = client.get(
        "/api/v1/messages/history",
        params={"session_id": session_id},
        headers=auth_header(bob["access_token"]),
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()["data"]
    assert history_payload[0]["status"] == "recalled"
    assert history_payload[0]["content"] == ""

    sessions_response = client.get(
        "/api/v1/sessions",
        headers=auth_header(bob["access_token"]),
    )
    assert sessions_response.status_code == 200
    session_payload = sessions_response.json()["data"]
    assert session_payload[0]["id"] == session_id
    assert session_payload[0]["last_message"] == ""
    assert session_payload[0]["last_message_status"] == "recalled"


def test_invalid_read_ack_does_not_disconnect_websocket(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/private",
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

    with client.websocket_connect(f"/ws?token={alice['access_token']}") as alice_ws, client.websocket_connect(
        f"/ws?token={bob['access_token']}"
    ) as bob_ws:
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


def test_private_websocket_delivers_multiple_messages_with_token_query(
    client: TestClient,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/private",
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

    with client.websocket_connect(f"/ws?token={alice['access_token']}") as alice_ws, client.websocket_connect(
        f"/ws?token={bob['access_token']}"
    ) as bob_ws:
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


def test_group_websocket_delivers_multiple_messages_with_token_query(
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

    with client.websocket_connect(f"/ws?token={alice['access_token']}") as alice_ws, client.websocket_connect(
        f"/ws?token={bob['access_token']}"
    ) as bob_ws:
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

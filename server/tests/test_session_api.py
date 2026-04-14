"""Session API tests."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

def test_create_direct_session_echoes_created_or_reused(client: TestClient, user_factory, auth_header) -> None:
    alice = user_factory("alice_direct_created", "Alice Direct Created")
    bob = user_factory("bob_direct_created", "Bob Direct Created")

    first_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert first_response.status_code == 200
    first_payload = first_response.json()["data"]
    assert first_payload["created"] is True
    assert first_payload["reused"] is False

    second_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    assert second_response.status_code == 200
    second_payload = second_response.json()["data"]
    assert second_payload["id"] == first_payload["id"]
    assert second_payload["created"] is False
    assert second_payload["reused"] is True


def test_create_direct_session_emits_lifecycle_refresh_once(
    client: TestClient,
    user_factory,
    auth_header,
    monkeypatch,
) -> None:
    from app.api.v1 import sessions as session_routes

    alice = user_factory("alice_direct_event", "Alice Direct Event")
    bob = user_factory("bob_direct_event", "Bob Direct Event")
    send_mock = AsyncMock(return_value={"delivered"})
    monkeypatch.setattr(session_routes.connection_manager, "send_json_to_users", send_mock)

    first_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )

    assert first_response.status_code == 200
    recipients, message = send_mock.await_args.args[:2]
    assert set(recipients) == {alice["user"]["id"], bob["user"]["id"]}
    assert message["type"] == "contact_refresh"
    assert message["data"]["reason"] == "session_lifecycle_changed"
    assert message["data"]["session_id"] == first_response.json()["data"]["session_id"]

    send_mock.reset_mock()
    second_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )

    assert second_response.status_code == 200
    send_mock.assert_not_awaited()

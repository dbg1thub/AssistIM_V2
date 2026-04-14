"""Session API tests."""

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

"""Authentication API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_auth_register_login_refresh_and_me(client: TestClient, auth_header) -> None:
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "alice",
            "password": "secret123",
            "nickname": "Alice",
        },
    )
    assert register_response.status_code == 200
    register_payload = register_response.json()
    assert register_payload["code"] == 0
    assert register_payload["data"]["user"]["username"] == "alice"
    assert register_payload["data"]["token_type"] == "Bearer"

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "alice",
            "password": "secret123",
        },
    )
    assert login_response.status_code == 200
    login_payload = login_response.json()["data"]
    assert login_payload["user"]["nickname"] == "Alice"

    refresh_response = client.post(
        "/api/v1/auth/token",
        json={"refresh_token": login_payload["refresh_token"]},
    )
    assert refresh_response.status_code == 200
    assert refresh_response.json()["data"]["access_token"]

    me_response = client.get(
        "/api/v1/auth/me",
        headers=auth_header(login_payload["access_token"]),
    )
    assert me_response.status_code == 200
    me_payload = me_response.json()["data"]
    assert me_payload["username"] == "alice"
    assert me_payload["nickname"] == "Alice"

    logout_response = client.delete(
        "/api/v1/auth/session",
        headers=auth_header(login_payload["access_token"]),
    )
    assert logout_response.status_code == 204

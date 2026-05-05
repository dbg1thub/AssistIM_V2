"""Shared auth helpers for backend tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def issue_register_email_code(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/email-verification/send",
        json={"email": email, "purpose": "register"},
    )
    assert response.status_code == 200, response.text
    code = str(response.json()["data"].get("debug_code") or "").strip()
    assert code, response.text
    return code


def register_user(
    client: TestClient,
    username: str,
    *,
    nickname: str | None = None,
    password: str = "secret123",
    email: str | None = None,
) -> dict:
    normalized_email = email or f"{username}@example.test"
    code = issue_register_email_code(client, normalized_email)
    response = register_user_response(
        client,
        username,
        nickname=nickname,
        password=password,
        email=normalized_email,
        email_code=code,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def register_user_response(
    client: TestClient,
    username: str,
    *,
    nickname: str | None = None,
    password: str = "secret123",
    email: str | None = None,
    email_code: str | None = None,
):
    normalized_email = email or f"{username}@example.test"
    code = email_code if email_code is not None else issue_register_email_code(client, normalized_email)
    return client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": password,
            "nickname": nickname or username,
            "email": normalized_email,
            "email_code": code,
        },
    )

"""Session API tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.errors import AppError, ErrorCode
from app.api.v1 import sessions as session_routes


def test_typing_session_rejects_hidden_private_session_before_broadcast(monkeypatch) -> None:
    send_mock = AsyncMock()

    class _FakeSessionService:
        def __init__(self, db) -> None:
            pass

        def get_session(self, current_user, session_id: str):
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)

    class _FakeMessageService:
        def __init__(self, db) -> None:
            raise AssertionError("message service should not be reached for hidden sessions")

    monkeypatch.setattr(session_routes, "SessionService", _FakeSessionService)
    monkeypatch.setattr(session_routes, "MessageService", _FakeMessageService)
    monkeypatch.setattr(session_routes.connection_manager, "send_json_to_users", send_mock)

    async def scenario() -> None:
        with pytest.raises(AppError) as exc_info:
            await session_routes.typing_session(
                "session-hidden",
                {"typing": True},
                current_user=SimpleNamespace(id="alice"),
                db=None,
            )
        assert exc_info.value.status_code == 404
        send_mock.assert_not_awaited()

    asyncio.run(scenario())



def test_typing_session_broadcasts_only_to_other_members(monkeypatch) -> None:
    send_mock = AsyncMock()

    class _FakeSessionService:
        def __init__(self, db) -> None:
            pass

        def get_session(self, current_user, session_id: str):
            return {"id": session_id}

    class _FakeMessageService:
        def __init__(self, db) -> None:
            pass

        def get_session_member_ids(self, session_id: str, current_user_id: str) -> list[str]:
            assert session_id == "session-1"
            assert current_user_id == "alice"
            return ["alice", "bob", "carol"]

    monkeypatch.setattr(session_routes, "SessionService", _FakeSessionService)
    monkeypatch.setattr(session_routes, "MessageService", _FakeMessageService)
    monkeypatch.setattr(session_routes.connection_manager, "send_json_to_users", send_mock)

    async def scenario() -> None:
        response = await session_routes.typing_session(
            "session-1",
            SimpleNamespace(typing=False),
            current_user=SimpleNamespace(id="alice"),
            db=None,
        )

        assert response["data"]["type"] == "typing"
        assert response["data"]["data"] == {
            "session_id": "session-1",
            "user_id": "alice",
            "typing": False,
        }
        send_mock.assert_awaited_once()
        recipient_ids, payload = send_mock.await_args.args
        assert recipient_ids == ["bob", "carol"]
        assert payload["type"] == "typing"
        assert payload["data"] == {
            "session_id": "session-1",
            "user_id": "alice",
            "typing": False,
        }

    asyncio.run(scenario())


def test_typing_session_requires_strict_boolean_payload(client: TestClient, user_factory, auth_header) -> None:
    alice = user_factory("alice_typing_schema", "Alice")
    bob = user_factory("bob_typing_schema", "Bob")

    session_response = client.post(
        "/api/v1/sessions/direct",
        json={"participant_ids": [bob["user"]["id"]]},
        headers=auth_header(alice["access_token"]),
    )
    session_id = session_response.json()["data"]["id"]

    invalid_type = client.post(
        f"/api/v1/sessions/{session_id}/typing",
        json={"typing": "true"},
        headers=auth_header(alice["access_token"]),
    )
    assert invalid_type.status_code == 422

    invalid_extra = client.post(
        f"/api/v1/sessions/{session_id}/typing",
        json={"typing": True, "extra": 1},
        headers=auth_header(alice["access_token"]),
    )
    assert invalid_extra.status_code == 422

    valid_false = client.post(
        f"/api/v1/sessions/{session_id}/typing",
        json={"typing": False},
        headers=auth_header(alice["access_token"]),
    )
    assert valid_false.status_code == 200
    valid_payload = valid_false.json()["data"]
    assert valid_payload["type"] == "typing"
    assert valid_payload["data"] == {
        "session_id": session_id,
        "user_id": alice["user"]["id"],
        "typing": False,
    }


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
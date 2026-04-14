"""Call-related API tests."""

from __future__ import annotations

import base64
import hashlib
import hmac
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.core.config import reload_settings


def _register_user(client: TestClient, username: str) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "nickname": username},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def test_calls_ice_servers_returns_static_runtime_config(monkeypatch) -> None:
    monkeypatch.setenv("WEBRTC_STUN_URLS", "stun:stun1.example.org:3478,stun:stun2.example.org:3478")
    monkeypatch.setenv("WEBRTC_TURN_URLS", "turn:turn.example.org:3478?transport=udp,turns:turn.example.org:5349")
    monkeypatch.setenv("WEBRTC_TURN_USERNAME", "assistim")
    monkeypatch.setenv("WEBRTC_TURN_CREDENTIAL", "secret")
    monkeypatch.delenv("WEBRTC_TURN_SHARED_SECRET", raising=False)

    with TestClient(create_app(reload_settings())) as client:
        user = _register_user(client, "alice_call_ice_static")

        response = client.get(
            "/api/v1/calls/ice-servers",
            headers=_auth_header(user["access_token"]),
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["credential_mode"] == "static"
    assert payload["ttl_seconds"] is None
    assert payload["expires_at"] is None
    assert payload["ice_servers"] == [
        {"urls": ["stun:stun1.example.org:3478", "stun:stun2.example.org:3478"]},
        {
            "urls": ["turn:turn.example.org:3478?transport=udp", "turns:turn.example.org:5349"],
            "username": "assistim",
            "credential": "secret",
        },
    ]


def test_calls_ice_servers_signs_short_lived_turn_credentials(monkeypatch) -> None:
    monkeypatch.setenv("WEBRTC_TURN_URLS", "turn:turn.example.org:3478?transport=udp")
    monkeypatch.setenv("WEBRTC_TURN_SHARED_SECRET", "turn-shared-secret")
    monkeypatch.setenv("WEBRTC_TURN_CREDENTIAL_TTL_SECONDS", "600")
    monkeypatch.delenv("WEBRTC_TURN_USERNAME", raising=False)
    monkeypatch.delenv("WEBRTC_TURN_CREDENTIAL", raising=False)

    with TestClient(create_app(reload_settings())) as client:
        user = _register_user(client, "alice_call_ice_ephemeral")

        response = client.get(
            "/api/v1/calls/ice-servers",
            headers=_auth_header(user["access_token"]),
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["credential_mode"] == "shared_secret"
    assert payload["ttl_seconds"] == 600
    assert payload["expires_at"] > 0
    turn_server = payload["ice_servers"][0]
    assert turn_server["urls"] == ["turn:turn.example.org:3478?transport=udp"]
    assert turn_server["username"].endswith(f":{user['user']['id']}")
    expected_credential = base64.b64encode(
        hmac.new(
            b"turn-shared-secret",
            turn_server["username"].encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("ascii")
    assert turn_server["credential"] == expected_credential



def test_call_service_rejects_hidden_private_session_before_entering_call_state_machine() -> None:
    from app.core.errors import AppError
    from app.services.call_service import CallService

    class _FakeSessionRepo:
        def get_by_id(self, session_id: str):
            return SimpleNamespace(id=session_id, type="private", is_ai_session=False)

        def has_member(self, session_id: str, user_id: str) -> bool:
            return True

        def list_member_ids(self, session_id: str) -> list[str]:
            return ["alice", "alice"]

    service = CallService(db=None)
    service.sessions = _FakeSessionRepo()

    with pytest.raises(AppError) as exc_info:
        service.invite(
            session_id="session-1",
            call_id="call-1",
            initiator_id="alice",
            media_type="voice",
        )

    assert exc_info.value.status_code == 404


def test_call_service_rejects_private_session_with_more_than_two_members() -> None:
    from app.core.errors import AppError
    from app.services.call_service import CallService

    class _FakeSessionRepo:
        def get_by_id(self, session_id: str):
            return SimpleNamespace(id=session_id, type="private", is_ai_session=False)

        def has_member(self, session_id: str, user_id: str) -> bool:
            return True

        def list_member_ids(self, session_id: str) -> list[str]:
            return ["alice", "bob", "charlie"]

    service = CallService(db=None)
    service.sessions = _FakeSessionRepo()

    with pytest.raises(AppError) as exc_info:
        service.invite(
            session_id="session-1",
            call_id="call-1",
            initiator_id="alice",
            media_type="voice",
        )

    assert exc_info.value.status_code == 409


class _FakePrivateSessionRepo:
    def __init__(self, member_ids: list[str] | None = None) -> None:
        self.member_ids = list(member_ids or ["alice", "bob"])

    def get_by_id(self, session_id: str):
        return SimpleNamespace(id=session_id, type="private", is_ai_session=False)

    def has_member(self, session_id: str, user_id: str) -> bool:
        return user_id in self.member_ids

    def list_member_ids(self, session_id: str) -> list[str]:
        return list(self.member_ids)


def test_call_service_requires_accept_before_signaling_and_validates_payload() -> None:
    from app.core.errors import AppError
    from app.realtime.call_registry import InMemoryCallRegistry
    from app.services.call_service import CallService

    registry = InMemoryCallRegistry()
    service = CallService(db=None, registry=registry)
    service.sessions = _FakePrivateSessionRepo()

    event_type, target_user_ids, invite = service.invite(
        session_id="session-1",
        call_id="call-1",
        initiator_id="alice",
        media_type="voice",
    )

    assert event_type == "call_invite"
    assert target_user_ids == ["alice", "bob"]
    assert invite["status"] == "invited"

    with pytest.raises(AppError) as pre_accept_exc:
        service.relay_offer(call_id="call-1", user_id="alice", sdp={"type": "offer", "sdp": "v=0"})
    assert pre_accept_exc.value.status_code == 409

    service.ringing(call_id="call-1", user_id="bob")
    service.accept(call_id="call-1", user_id="bob")

    with pytest.raises(AppError) as bad_sdp_exc:
        service.relay_offer(call_id="call-1", user_id="alice", sdp={"type": "answer", "sdp": "v=0"})
    assert bad_sdp_exc.value.status_code == 422

    event_type, target_user_ids, offer = service.relay_offer(
        call_id="call-1",
        user_id="alice",
        sdp={"type": "offer", "sdp": "v=0"},
    )

    assert event_type == "call_offer"
    assert target_user_ids == ["alice", "bob"]
    assert offer["actor_id"] == "alice"
    assert "from_user_id" not in offer
    assert "to_user_id" not in offer


def test_call_service_rejects_duplicate_accept_and_post_accept_reject() -> None:
    from app.core.errors import AppError
    from app.realtime.call_registry import InMemoryCallRegistry
    from app.services.call_service import CallService

    registry = InMemoryCallRegistry()
    service = CallService(db=None, registry=registry)
    service.sessions = _FakePrivateSessionRepo()

    service.invite(
        session_id="session-1",
        call_id="call-1",
        initiator_id="alice",
        media_type="voice",
    )
    service.accept(call_id="call-1", user_id="bob")

    with pytest.raises(AppError) as second_accept_exc:
        service.accept(call_id="call-1", user_id="bob")
    assert second_accept_exc.value.status_code == 409

    with pytest.raises(AppError) as reject_exc:
        service.reject(call_id="call-1", user_id="bob")
    assert reject_exc.value.status_code == 409


def test_call_service_rejects_reused_call_id_before_registry_overwrite() -> None:
    from app.core.errors import AppError
    from app.realtime.call_registry import InMemoryCallRegistry
    from app.services.call_service import CallService

    registry = InMemoryCallRegistry()
    registry.create(
        call_id="call-1",
        session_id="other-session",
        initiator_id="carol",
        recipient_id="dave",
        media_type="voice",
    )
    service = CallService(db=None, registry=registry)
    service.sessions = _FakePrivateSessionRepo()

    with pytest.raises(AppError) as exc_info:
        service.invite(
            session_id="session-1",
            call_id="call-1",
            initiator_id="alice",
            media_type="voice",
        )

    assert exc_info.value.status_code == 409

"""Development admin dashboard API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import reload_settings
from app.core.database import SessionLocal
from app.core.errors import ErrorCode
from app.core.logging import logger
from app.main import create_app
from app.models.base import generate_id
from app.models.device import UserDevice, UserPreKey, UserSignedPreKey
from app.models.file import StoredFile
from app.models.group import Group, GroupMember
from app.models.message import Message, MessageRead
from app.models.moment import Moment, MomentComment, MomentLike
from app.models.session import ChatSession, SessionEvent, SessionMember
from app.models.user import FriendRequest, Friendship
from app.realtime.call_registry import get_call_registry
from app.websocket.manager import connection_manager


def _client_with_dashboard(monkeypatch, *, enabled: bool) -> TestClient:
    monkeypatch.setenv("ADMIN_DASHBOARD_ENABLED", "true" if enabled else "false")
    monkeypatch.setenv("WEBRTC_STUN_URLS", "stun:stun.example.test:3478")
    monkeypatch.setenv("WEBRTC_TURN_URLS", "")
    return TestClient(create_app(reload_settings()))


def _register(client: TestClient, username: str, nickname: str) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "nickname": nickname},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_admin_dashboard_is_disabled_by_default(monkeypatch) -> None:
    with _client_with_dashboard(monkeypatch, enabled=False) as client:
        auth_payload = _register(client, "dashboard-disabled", "Dashboard Disabled")

        response = client.get(
            "/api/v1/admin/dashboard",
            headers=_auth_header(auth_payload["access_token"]),
        )

    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.FORBIDDEN


def test_admin_dashboard_requires_authentication_when_enabled(monkeypatch) -> None:
    with _client_with_dashboard(monkeypatch, enabled=True) as client:
        response = client.get("/api/v1/admin/dashboard")

    assert response.status_code == 401
    assert response.json()["code"] == ErrorCode.UNAUTHORIZED


def test_admin_dashboard_reports_runtime_business_and_diagnostic_counts(monkeypatch) -> None:
    from app.core.runtime_diagnostics import reset_runtime_diagnostics

    reset_runtime_diagnostics()
    with _client_with_dashboard(monkeypatch, enabled=True) as client:
        alice_auth = _register(client, "dashboard-alice", "Alice")
        bob_auth = _register(client, "dashboard-bob", "Bob")
        alice = alice_auth["user"]
        bob = bob_auth["user"]
        _seed_dashboard_records(alice["id"], bob["id"])

        connection_manager.bind_user("dashboard-conn-1", alice["id"])
        get_call_registry().create(
            call_id="dashboard-call-1",
            session_id="dashboard-call-session",
            initiator_id=alice["id"],
            recipient_id=bob["id"],
            media_type="audio",
        )

        root_response = client.get("/")
        assert root_response.status_code == 200
        missing_response = client.get("/api/v1/dashboard-missing")
        assert missing_response.status_code == 404
        logger.warning("dashboard-test-warning")

        response = client.get(
            "/api/v1/admin/dashboard",
            headers=_auth_header(alice_auth["access_token"]),
        )

    assert response.status_code == 200
    payload = response.json()["data"]

    assert payload["system"]["app_name"] == "AssistIM Test API"
    assert payload["system"]["api_v1_prefix"] == "/api/v1"
    assert payload["database"]["status"] == "ok"
    assert payload["database"]["required_tables"]["users"] is True
    assert payload["database"]["required_tables"]["messages"] is True

    assert payload["users"]["total"] == 2
    assert payload["users"]["online"] == 1
    assert payload["users"]["devices"]["total"] == 2
    assert payload["users"]["devices"]["active"] == 1
    assert payload["contacts"]["friendships"] == 2
    assert payload["contacts"]["pending_friend_requests"] == 1

    assert payload["chat"]["sessions"]["total"] == 3
    assert payload["chat"]["sessions"]["private"] == 1
    assert payload["chat"]["sessions"]["group"] == 1
    assert payload["chat"]["sessions"]["ai"] == 1
    assert payload["chat"]["messages"]["total"] == 2
    assert payload["chat"]["messages"]["by_type"] == {"image": 1, "text": 1}
    assert payload["chat"]["events"] == 1
    assert payload["chat"]["read_records"] == 1

    assert payload["groups"]["total"] == 1
    assert payload["groups"]["members"] == 2
    assert payload["groups"]["with_announcements"] == 1
    assert payload["moments"] == {"total": 1, "likes": 1, "comments": 1}
    assert payload["files"]["total"] == 2
    assert payload["files"]["total_size_bytes"] == 1536
    assert payload["files"]["by_type"] == {"image/png": 1, "text/markdown": 1}
    assert payload["files"]["upload_dir"]["exists"] is True

    assert payload["realtime"]["hub"] == "InMemoryRealtimeHub"
    assert payload["realtime"]["online_users"] == 1
    assert payload["realtime"]["bound_connections"] == 1
    assert payload["calls"]["active"] == 1
    assert payload["calls"]["by_media_type"] == {"audio": 1}
    assert payload["calls"]["ice_servers_configured"] is True
    assert payload["calls"]["turn_configured"] is False

    assert payload["e2ee"]["encrypted_sessions"] == 2
    assert payload["e2ee"]["private_sessions"] == 1
    assert payload["e2ee"]["group_sessions"] == 1
    assert payload["e2ee"]["one_time_prekeys"]["total"] == 2
    assert payload["e2ee"]["one_time_prekeys"]["available"] == 1
    assert payload["e2ee"]["one_time_prekeys"]["consumed"] == 1
    assert payload["e2ee"]["signed_prekeys"]["total"] == 2
    assert payload["e2ee"]["signed_prekeys"]["active"] == 1

    assert payload["http"]["total_requests"] >= 2
    assert payload["http"]["error_requests"] >= 1
    assert any(item["path"] == "/api/v1/dashboard-missing" for item in payload["http"]["recent"])
    assert any("dashboard-test-warning" in item["message"] for item in payload["logs"]["recent_warnings_errors"])


def test_realtime_hub_snapshot_reports_bound_connections() -> None:
    from app.realtime.hub import InMemoryRealtimeHub

    hub = InMemoryRealtimeHub()
    hub.bind_user("conn-1", "user-1")
    hub.bind_user("conn-2", "user-1")
    hub.bind_user("conn-3", "user-2")

    snapshot = hub.snapshot()

    assert snapshot == {
        "hub": "InMemoryRealtimeHub",
        "raw_connections": 0,
        "bound_connections": 3,
        "online_users": 2,
    }


def test_call_registry_snapshot_reports_active_call_distribution() -> None:
    from app.realtime.call_registry import InMemoryCallRegistry

    registry = InMemoryCallRegistry()
    registry.create(
        call_id="call-1",
        session_id="session-1",
        initiator_id="user-1",
        recipient_id="user-2",
        media_type="audio",
    )
    registry.create(
        call_id="call-2",
        session_id="session-2",
        initiator_id="user-3",
        recipient_id="user-4",
        media_type="video",
    )

    snapshot = registry.snapshot()

    assert snapshot == {
        "active": 2,
        "by_media_type": {"audio": 1, "video": 1},
    }


def _seed_dashboard_records(alice_id: str, bob_id: str) -> None:
    private_session_id = generate_id()
    group_session_id = generate_id()
    ai_session_id = generate_id()
    text_message_id = generate_id()
    image_message_id = generate_id()
    group_id = generate_id()
    file_one_id = generate_id()
    file_two_id = generate_id()
    moment_id = generate_id()

    with SessionLocal() as db:
        db.add_all(
            [
                Friendship(id=generate_id(), user_id=alice_id, friend_id=bob_id),
                Friendship(id=generate_id(), user_id=bob_id, friend_id=alice_id),
                FriendRequest(id=generate_id(), sender_id=bob_id, receiver_id=alice_id, status="pending"),
                ChatSession(
                    id=private_session_id,
                    type="private",
                    name="Alice/Bob",
                    encryption_mode="e2ee_private",
                    is_ai_session=False,
                ),
                ChatSession(
                    id=group_session_id,
                    type="group",
                    name="Ops",
                    encryption_mode="e2ee_group",
                    is_ai_session=False,
                ),
                ChatSession(
                    id=ai_session_id,
                    type="private",
                    name="AI",
                    encryption_mode="plain",
                    is_ai_session=True,
                ),
                SessionMember(session_id=private_session_id, user_id=alice_id),
                SessionMember(session_id=private_session_id, user_id=bob_id),
                SessionMember(session_id=group_session_id, user_id=alice_id),
                SessionMember(session_id=group_session_id, user_id=bob_id),
                Message(
                    id=text_message_id,
                    session_id=private_session_id,
                    sender_id=alice_id,
                    session_seq=1,
                    type="text",
                    content="hello",
                ),
                Message(
                    id=image_message_id,
                    session_id=group_session_id,
                    sender_id=bob_id,
                    session_seq=1,
                    type="image",
                    content="/uploads/image.png",
                ),
                MessageRead(message_id=text_message_id, user_id=bob_id),
                SessionEvent(
                    id=generate_id(),
                    session_id=private_session_id,
                    event_seq=1,
                    type="message_edit",
                    message_id=text_message_id,
                    actor_user_id=alice_id,
                    payload="{}",
                ),
                Group(
                    id=group_id,
                    name="Ops",
                    owner_id=alice_id,
                    session_id=group_session_id,
                    announcement="Deploy at 6",
                    announcement_message_id=image_message_id,
                    announcement_author_id=alice_id,
                ),
                GroupMember(group_id=group_id, user_id=alice_id, role="owner"),
                GroupMember(group_id=group_id, user_id=bob_id, role="member"),
                StoredFile(
                    id=file_one_id,
                    user_id=alice_id,
                    storage_provider="local",
                    storage_key="files/readme.md",
                    file_url="/uploads/files/readme.md",
                    file_type="text/markdown",
                    file_name="README.md",
                    size_bytes=512,
                    checksum_sha256="sha-one",
                ),
                StoredFile(
                    id=file_two_id,
                    user_id=bob_id,
                    storage_provider="local",
                    storage_key="files/image.png",
                    file_url="/uploads/files/image.png",
                    file_type="image/png",
                    file_name="image.png",
                    size_bytes=1024,
                    checksum_sha256="sha-two",
                ),
                Moment(id=moment_id, user_id=alice_id, content="hello moment"),
                MomentLike(moment_id=moment_id, user_id=bob_id),
                MomentComment(id=generate_id(), moment_id=moment_id, user_id=bob_id, content="ok"),
                UserDevice(
                    device_id="alice-device",
                    user_id=alice_id,
                    identity_key_public="identity-a",
                    signing_key_public="signing-a",
                    device_name="Alice PC",
                    is_active=True,
                ),
                UserDevice(
                    device_id="bob-device",
                    user_id=bob_id,
                    identity_key_public="identity-b",
                    signing_key_public="signing-b",
                    device_name="Bob PC",
                    is_active=False,
                ),
                UserSignedPreKey(
                    id=generate_id(),
                    device_id="alice-device",
                    key_id=1,
                    public_key="signed-a",
                    signature="sig-a",
                    is_active=True,
                ),
                UserSignedPreKey(
                    id=generate_id(),
                    device_id="bob-device",
                    key_id=1,
                    public_key="signed-b",
                    signature="sig-b",
                    is_active=False,
                ),
                UserPreKey(
                    id=generate_id(),
                    device_id="alice-device",
                    prekey_id=1,
                    public_key="prekey-a",
                    is_consumed=False,
                ),
                UserPreKey(
                    id=generate_id(),
                    device_id="bob-device",
                    prekey_id=1,
                    public_key="prekey-b",
                    is_consumed=True,
                ),
            ]
        )
        db.commit()

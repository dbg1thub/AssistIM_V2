"""Admin realtime and call inspection API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from auth_test_helpers import register_user
from app.core.database import SessionLocal
from app.core.errors import ErrorCode
from app.models.admin import AdminAuditLog
from app.models.session import ChatSession, SessionMember
from app.models.user import User
from app.realtime.call_registry import get_call_registry
from app.websocket.manager import connection_manager


MISSING_CONNECTION_USER_ID = "00000000-0000-0000-0000-000000000031"
MISSING_CALL_SESSION_ID = "00000000-0000-0000-0000-000000000032"
MISSING_CALL_USER_ID = "00000000-0000-0000-0000-000000000033"


def _register(client: TestClient, username: str, nickname: str) -> dict:
    return register_user(client, username, nickname=nickname)


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _set_role(user_id: str, role: str) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.role = role
        db.add(user)
        db.commit()


def _seed_private_session(member_ids: list[str], *, name: str = "Call Session") -> str:
    with SessionLocal() as db:
        session = ChatSession(type="private", name=name, is_ai_session=False, encryption_mode="plain")
        db.add(session)
        db.flush()
        for user_id in member_ids:
            db.add(SessionMember(session_id=session.id, user_id=user_id))
        db.commit()
        return str(session.id)


def _seed_group_session(member_ids: list[str], *, name: str = "Group Call Session") -> str:
    with SessionLocal() as db:
        session = ChatSession(type="group", name=name, is_ai_session=False, encryption_mode="plain")
        db.add(session)
        db.flush()
        for user_id in member_ids:
            db.add(SessionMember(session_id=session.id, user_id=user_id))
        db.commit()
        return str(session.id)


def test_admin_realtime_and_calls_forbid_non_admin(client: TestClient) -> None:
    auth_payload = _register(client, "realtime-normal", "Realtime Normal")
    headers = _auth_header(auth_payload["access_token"])

    responses = [
        client.get("/api/v1/admin/realtime/connections", headers=headers),
        client.get("/api/v1/admin/realtime/health", headers=headers),
        client.get("/api/v1/admin/calls/active", headers=headers),
        client.get("/api/v1/admin/calls/health", headers=headers),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]
    assert all(response.json()["code"] == ErrorCode.FORBIDDEN for response in responses)


def test_admin_realtime_connections_list_online_users_and_audit(client: TestClient) -> None:
    admin_auth = _register(client, "realtime-list-admin", "Realtime List Admin")
    alice = _register(client, "realtime-list-alice", "Realtime List Alice")
    bob = _register(client, "realtime-list-bob", "Realtime List Bob")
    _set_role(admin_auth["user"]["id"], "admin")
    connection_manager.bind_user("alice-conn-1", alice["user"]["id"])
    connection_manager.bind_user("alice-conn-2", alice["user"]["id"])
    connection_manager.bind_user("bob-conn-1", bob["user"]["id"])

    response = client.get(
        "/api/v1/admin/realtime/connections",
        headers=_auth_header(admin_auth["access_token"]),
        params={"user_id": alice["user"]["id"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total_users"] == 1
    assert payload["total_connections"] == 2
    assert payload["snapshot"]["online_users"] == 2
    assert payload["items"][0]["user_id"] == alice["user"]["id"]
    assert payload["items"][0]["user"]["username"] == "realtime-list-alice"
    assert payload["items"][0]["connection_count"] == 2
    connection_ids = {item["connection_id"] for item in payload["items"][0]["connections"]}
    assert connection_ids == {"alice-conn-1", "alice-conn-2"}
    assert all(item["bound"] is True for item in payload["items"][0]["connections"])

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.realtime.connections.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True


def test_admin_realtime_health_reports_connection_integrity_issues(client: TestClient) -> None:
    admin_auth = _register(client, "realtime-health-admin", "Realtime Health Admin")
    alice = _register(client, "realtime-health-alice", "Realtime Health Alice")
    _set_role(admin_auth["user"]["id"], "admin")
    connection_manager.bind_user("missing-user-conn", MISSING_CONNECTION_USER_ID)
    connection_manager.bind_user("bound-without-socket", alice["user"]["id"])

    response = client.get(
        "/api/v1/admin/realtime/health",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "warning"
    issue_types = {item["issue_type"] for item in payload["issues"]}
    assert "realtime_connection_user_missing" in issue_types
    assert "realtime_bound_connection_missing_socket" in issue_types
    assert any(
        item["issue_type"] == "realtime_connection_user_missing"
        and item["user_id"] == MISSING_CONNECTION_USER_ID
        for item in payload["issues"]
    )

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.realtime.health.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True


def test_admin_calls_active_lists_calls_with_users_sessions_and_audit(client: TestClient) -> None:
    admin_auth = _register(client, "calls-active-admin", "Calls Active Admin")
    alice = _register(client, "calls-active-alice", "Calls Active Alice")
    bob = _register(client, "calls-active-bob", "Calls Active Bob")
    _set_role(admin_auth["user"]["id"], "admin")
    session_id = _seed_private_session([alice["user"]["id"], bob["user"]["id"]])
    get_call_registry().create(
        call_id="active-call-1",
        session_id=session_id,
        initiator_id=alice["user"]["id"],
        recipient_id=bob["user"]["id"],
        media_type="voice",
    )
    connection_manager.bind_user("bob-online-conn", bob["user"]["id"])

    response = client.get(
        "/api/v1/admin/calls/active",
        headers=_auth_header(admin_auth["access_token"]),
        params={"user_id": bob["user"]["id"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 1
    assert payload["items"][0]["call_id"] == "active-call-1"
    assert payload["items"][0]["session"]["id"] == session_id
    assert payload["items"][0]["session"]["type"] == "private"
    assert payload["items"][0]["initiator"]["username"] == "calls-active-alice"
    assert payload["items"][0]["recipient"]["username"] == "calls-active-bob"
    assert payload["items"][0]["participants"][1]["online"] is True
    assert payload["items"][0]["status"] == "invited"
    assert payload["items"][0]["media_type"] == "voice"

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.calls.active.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True


def test_admin_calls_health_reports_runtime_integrity_issues(client: TestClient) -> None:
    admin_auth = _register(client, "calls-health-admin", "Calls Health Admin")
    alice = _register(client, "calls-health-alice", "Calls Health Alice")
    bob = _register(client, "calls-health-bob", "Calls Health Bob")
    charlie = _register(client, "calls-health-charlie", "Calls Health Charlie")
    _set_role(admin_auth["user"]["id"], "admin")
    private_session_id = _seed_private_session([alice["user"]["id"], bob["user"]["id"]])
    group_session_id = _seed_group_session([alice["user"]["id"], bob["user"]["id"]])
    registry = get_call_registry()
    registry.create(
        call_id="missing-session-call",
        session_id=MISSING_CALL_SESSION_ID,
        initiator_id=alice["user"]["id"],
        recipient_id=bob["user"]["id"],
        media_type="voice",
    )
    registry.create(
        call_id="missing-user-call",
        session_id=private_session_id,
        initiator_id=MISSING_CALL_USER_ID,
        recipient_id=bob["user"]["id"],
        media_type="voice",
    )
    registry.create(
        call_id="not-member-call",
        session_id=private_session_id,
        initiator_id=alice["user"]["id"],
        recipient_id=charlie["user"]["id"],
        media_type="video",
    )
    registry.create(
        call_id="group-session-call",
        session_id=group_session_id,
        initiator_id=alice["user"]["id"],
        recipient_id=bob["user"]["id"],
        media_type="voice",
    )
    invalid_status_call = registry.create(
        call_id="invalid-status-call",
        session_id=private_session_id,
        initiator_id=alice["user"]["id"],
        recipient_id=bob["user"]["id"],
        media_type="voice",
    )
    invalid_status_call.status = "paused"
    registry._call_id_by_user_id.pop(alice["user"]["id"], None)

    response = client.get(
        "/api/v1/admin/calls/health",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "warning"
    issue_types = {item["issue_type"] for item in payload["issues"]}
    assert "call_session_missing" in issue_types
    assert "call_participant_user_missing" in issue_types
    assert "call_participant_not_session_member" in issue_types
    assert "call_session_type_invalid" in issue_types
    assert "call_status_invalid" in issue_types
    assert "call_user_mapping_missing" in issue_types
    assert any(
        item["issue_type"] == "call_session_missing"
        and item["call_id"] == "missing-session-call"
        for item in payload["issues"]
    )
    assert any(
        item["issue_type"] == "call_participant_user_missing"
        and item["user_id"] == MISSING_CALL_USER_ID
        for item in payload["issues"]
    )

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.calls.health.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True

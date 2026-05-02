"""Admin user-management API tests."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.errors import ErrorCode
from app.models.admin import AdminAuditLog
from app.models.device import UserDevice
from app.models.file import StoredFile
from app.models.session import ChatSession, SessionMember
from app.models.user import Friendship, User
from app.websocket.manager import connection_manager


def _register(client: TestClient, username: str, nickname: str) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "nickname": nickname},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _set_role(user_id: str, role: str) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.role = role
        db.add(user)
        db.commit()


def test_admin_users_forbid_non_admin(client: TestClient) -> None:
    auth_payload = _register(client, "admin-users-normal", "Normal User")

    response = client.get(
        "/api/v1/admin/users",
        headers=_auth_header(auth_payload["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.FORBIDDEN


def test_admin_users_list_supports_search_filters_and_hides_sensitive_fields(client: TestClient) -> None:
    admin_auth = _register(client, "admin-users-admin", "Admin User")
    alice_auth = _register(client, "admin-users-alice", "Alice Target")
    bob_auth = _register(client, "admin-users-bob", "Bob Target")
    _set_role(admin_auth["user"]["id"], "admin")
    _disable_user_directly(bob_auth["user"]["id"], reason="manual seed")

    response = client.get(
        "/api/v1/admin/users",
        params={"keyword": "target", "role": "user", "disabled": "false", "page": 1, "size": 10},
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["size"] == 10
    assert [item["id"] for item in payload["items"]] == [alice_auth["user"]["id"]]

    item = payload["items"][0]
    assert item["username"] == "admin-users-alice"
    assert item["role"] == "user"
    assert item["is_disabled"] is False
    assert "password_hash" not in item
    assert "access_token" not in item
    assert "refresh_token" not in item


def test_admin_user_detail_reports_counts_and_hides_keys(client: TestClient) -> None:
    admin_auth = _register(client, "admin-users-detail-admin", "Admin User")
    target_auth = _register(client, "admin-users-detail-target", "Target User")
    _set_role(admin_auth["user"]["id"], "admin")
    _seed_detail_records(target_auth["user"]["id"], admin_auth["user"]["id"])

    response = client.get(
        f"/api/v1/admin/users/{target_auth['user']['id']}",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["id"] == target_auth["user"]["id"]
    assert payload["username"] == "admin-users-detail-target"
    assert payload["role"] == "user"
    assert payload["is_disabled"] is False
    assert payload["counts"] == {
        "devices": 1,
        "sessions": 1,
        "friends": 1,
        "files": 1,
    }
    assert len(payload["devices"]) == 1
    assert payload["devices"][0]["device_id"] == "target-device"
    assert payload["devices"][0]["device_name"] == "Target PC"
    assert payload["devices"][0]["is_active"] is True
    assert payload["devices"][0]["last_seen_at"]
    assert payload["devices"][0]["created_at"]
    assert payload["devices"][0]["updated_at"]
    assert "password_hash" not in payload
    assert "identity_key_public" not in json.dumps(payload)
    assert "signing_key_public" not in json.dumps(payload)


def test_admin_disable_user_blocks_login_existing_token_and_records_audit(client: TestClient) -> None:
    admin_auth = _register(client, "admin-users-disable-admin", "Admin User")
    target_auth = _register(client, "admin-users-disable-target", "Target User")
    _set_role(admin_auth["user"]["id"], "admin")
    connection_manager.bind_user("disabled-user-conn", target_auth["user"]["id"])

    response = client.post(
        f"/api/v1/admin/users/{target_auth['user']['id']}/disable",
        json={"reason": "risk review"},
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["id"] == target_auth["user"]["id"]
    assert payload["is_disabled"] is True
    assert payload["disabled_reason"] == "risk review"
    assert connection_manager.has_user_connections(target_auth["user"]["id"]) is False

    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin-users-disable-target", "password": "secret123"},
    )
    assert login_response.status_code == 403
    assert login_response.json()["code"] == ErrorCode.FORBIDDEN

    me_response = client.get("/api/v1/auth/me", headers=_auth_header(target_auth["access_token"]))
    assert me_response.status_code == 403
    assert me_response.json()["code"] == ErrorCode.FORBIDDEN

    audit = _latest_audit("admin.user.disable")
    assert audit.actor_user_id == admin_auth["user"]["id"]
    assert audit.target_id == target_auth["user"]["id"]
    assert audit.success is True
    assert "risk review" in audit.detail_json
    assert "secret123" not in audit.detail_json


def test_admin_enable_user_allows_login_and_records_audit(client: TestClient) -> None:
    admin_auth = _register(client, "admin-users-enable-admin", "Admin User")
    target_auth = _register(client, "admin-users-enable-target", "Target User")
    _set_role(admin_auth["user"]["id"], "admin")
    _disable_user_directly(target_auth["user"]["id"], reason="manual seed")

    response = client.post(
        f"/api/v1/admin/users/{target_auth['user']['id']}/enable",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["is_disabled"] is False
    assert response.json()["data"]["disabled_reason"] == ""

    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin-users-enable-target", "password": "secret123"},
    )
    assert login_response.status_code == 200, login_response.text

    audit = _latest_audit("admin.user.enable")
    assert audit.actor_user_id == admin_auth["user"]["id"]
    assert audit.target_id == target_auth["user"]["id"]
    assert audit.success is True


def test_admin_force_logout_invalidates_existing_token_disconnects_and_records_audit(client: TestClient) -> None:
    admin_auth = _register(client, "admin-users-logout-admin", "Admin User")
    target_auth = _register(client, "admin-users-logout-target", "Target User")
    _set_role(admin_auth["user"]["id"], "admin")
    connection_manager.bind_user("force-logout-conn", target_auth["user"]["id"])

    response = client.post(
        f"/api/v1/admin/users/{target_auth['user']['id']}/force-logout",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "user_id": target_auth["user"]["id"],
        "username": "admin-users-logout-target",
        "disconnected": True,
    }
    assert connection_manager.has_user_connections(target_auth["user"]["id"]) is False

    me_response = client.get("/api/v1/auth/me", headers=_auth_header(target_auth["access_token"]))
    assert me_response.status_code == 401
    assert me_response.json()["code"] == ErrorCode.UNAUTHORIZED

    audit = _latest_audit("admin.user.force_logout")
    assert audit.actor_user_id == admin_auth["user"]["id"]
    assert audit.target_id == target_auth["user"]["id"]
    assert audit.success is True


def test_admin_set_user_role_by_id_records_audit_and_protects_self_demote(client: TestClient) -> None:
    admin_auth = _register(client, "admin-users-role-admin", "Admin User")
    target_auth = _register(client, "admin-users-role-target", "Target User")
    _set_role(admin_auth["user"]["id"], "admin")

    response = client.patch(
        f"/api/v1/admin/users/{target_auth['user']['id']}/role",
        json={"role": "admin"},
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["id"] == target_auth["user"]["id"]
    assert response.json()["data"]["role"] == "admin"

    self_response = client.patch(
        f"/api/v1/admin/users/{admin_auth['user']['id']}/role",
        json={"role": "user"},
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert self_response.status_code == 403
    assert self_response.json()["code"] == ErrorCode.FORBIDDEN

    audit = _latest_audit("admin.user.role.set")
    assert audit.actor_user_id == admin_auth["user"]["id"]
    assert audit.target_id == target_auth["user"]["id"]
    assert '"new_role": "admin"' in audit.detail_json


def test_admin_disable_self_is_forbidden(client: TestClient) -> None:
    admin_auth = _register(client, "admin-users-self-disable", "Admin User")
    _set_role(admin_auth["user"]["id"], "admin")

    response = client.post(
        f"/api/v1/admin/users/{admin_auth['user']['id']}/disable",
        json={"reason": "mistake"},
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.FORBIDDEN


def _disable_user_directly(user_id: str, *, reason: str) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.is_disabled = True
        user.disabled_reason = reason
        db.add(user)
        db.commit()


def _seed_detail_records(target_user_id: str, friend_user_id: str) -> None:
    with SessionLocal() as db:
        session = ChatSession(type="private", name="detail-session")
        db.add(session)
        db.flush()
        db.add_all(
            [
                SessionMember(session_id=session.id, user_id=target_user_id),
                UserDevice(
                    device_id="target-device",
                    user_id=target_user_id,
                    identity_key_public="identity-secret",
                    signing_key_public="signing-secret",
                    device_name="Target PC",
                    is_active=True,
                ),
                Friendship(user_id=target_user_id, friend_id=friend_user_id),
                StoredFile(
                    user_id=target_user_id,
                    storage_provider="local",
                    storage_key="files/admin-detail.txt",
                    file_url="/uploads/files/admin-detail.txt",
                    file_type="text/plain",
                    file_name="admin-detail.txt",
                    size_bytes=12,
                    checksum_sha256="detail-sha",
                ),
            ]
        )
        db.commit()


def _latest_audit(action: str) -> AdminAuditLog:
    with SessionLocal() as db:
        audit = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.action == action)
            .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
            .first()
        )
        assert audit is not None
        return audit

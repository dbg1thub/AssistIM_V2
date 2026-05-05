"""Admin authentication and account-security inspection API tests."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from auth_test_helpers import register_user
from app.core.database import SessionLocal
from app.core.errors import ErrorCode
from app.models.admin import AdminAuditLog
from app.models.user import User
from app.websocket.manager import connection_manager


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


def test_admin_auth_inspection_forbids_non_admin(client: TestClient) -> None:
    auth_payload = _register(client, "auth-inspection-normal", "Auth Inspection Normal")
    headers = _auth_header(auth_payload["access_token"])

    responses = [
        client.get("/api/v1/admin/auth/status", headers=headers),
        client.get("/api/v1/admin/auth/health", headers=headers),
    ]

    assert [response.status_code for response in responses] == [403, 403]
    assert all(response.json()["code"] == ErrorCode.FORBIDDEN for response in responses)


def test_admin_auth_status_reports_runtime_config_counts_and_redacts_secrets(client: TestClient) -> None:
    admin_auth = _register(client, "auth-status-admin", "Auth Status Admin")
    user_auth = _register(client, "auth-status-user", "Auth Status User")
    _set_role(admin_auth["user"]["id"], "admin")
    _seed_admin_audit(
        actor_id=admin_auth["user"]["id"],
        actor_username="auth-status-admin",
        action="admin.user.force_logout",
        target_id=user_auth["user"]["id"],
    )
    connection_manager.bind_user("auth-status-online-admin", admin_auth["user"]["id"])
    connection_manager.bind_user("auth-status-online-user", user_auth["user"]["id"])

    response = client.get(
        "/api/v1/admin/auth/status",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["token"]["access_token_expire_minutes"] == 60
    assert payload["token"]["refresh_token_expire_days"] == 7
    assert payload["token"]["token_storage"] == "stateless_jwt"
    assert payload["session"]["invalidation_strategy"] == "auth_session_version"
    assert payload["session"]["server_persisted_sessions"] is False
    assert payload["users"]["total"] == 2
    assert payload["users"]["admins"] == 1
    assert payload["users"]["enabled_admins"] == 1
    assert payload["users"]["disabled"] == 0
    assert payload["runtime"]["online_users"] == 2
    assert payload["runtime"]["bound_connections"] == 2
    assert payload["audit"]["recent_auth_audit_logs"] == 1
    assert payload["audit"]["recent_auth_actions"] == {"admin.user.force_logout": 1}

    serialized = json.dumps(payload, ensure_ascii=False).lower()
    assert admin_auth["access_token"].lower() not in serialized
    assert admin_auth["refresh_token"].lower() not in serialized
    assert user_auth["access_token"].lower() not in serialized
    assert user_auth["refresh_token"].lower() not in serialized
    assert "password_hash" not in serialized
    assert "secret123" not in serialized

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.auth.status.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True
        assert "access_token" not in audit.detail_json.lower()
        assert "password" not in audit.detail_json.lower()


def test_admin_auth_health_reports_account_and_session_integrity_issues(client: TestClient) -> None:
    admin_auth = _register(client, "auth-health-admin", "Auth Health Admin")
    disabled_auth = _register(client, "auth-health-disabled", "Disabled User")
    _set_role(admin_auth["user"]["id"], "admin")
    _mutate_user(disabled_auth["user"]["id"], is_disabled=True)
    invalid_role_id = _create_user_directly(
        username="auth-health-invalid-role",
        role="owner",
        password_hash="hash-value",
    )
    empty_hash_id = _create_user_directly(
        username="auth-health-empty-hash",
        role="user",
        password_hash="",
    )
    negative_session_id = _create_user_directly(
        username="auth-health-negative-session",
        role="user",
        password_hash="hash-value",
        auth_session_version=-1,
    )
    connection_manager.bind_user("auth-health-disabled-conn", disabled_auth["user"]["id"])

    response = client.get(
        "/api/v1/admin/auth/health",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "warning"
    assert payload["checks"]["users"] == 5
    assert payload["checks"]["admins"] == 1
    assert payload["checks"]["disabled_users_online"] == 1
    issue_types = {item["issue_type"] for item in payload["issues"]}
    assert "auth_disabled_user_online" in issue_types
    assert "auth_invalid_user_role" in issue_types
    assert "auth_empty_password_credential" in issue_types
    assert "auth_invalid_session_version" in issue_types
    assert any(item["user_id"] == disabled_auth["user"]["id"] for item in payload["issues"])
    assert any(item["user_id"] == invalid_role_id for item in payload["issues"])
    assert any(item["user_id"] == empty_hash_id for item in payload["issues"])
    assert any(item["user_id"] == negative_session_id for item in payload["issues"])

    serialized = json.dumps(payload, ensure_ascii=False).lower()
    assert "password_hash" not in serialized
    assert "hash-value" not in serialized
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.auth.health.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True


def _seed_admin_audit(*, actor_id: str, actor_username: str, action: str, target_id: str) -> None:
    with SessionLocal() as db:
        db.add(
            AdminAuditLog(
                actor_user_id=actor_id,
                actor_username=actor_username,
                action=action,
                target_type="user",
                target_id=target_id,
                request_path="/api/v1/admin/users/target/force-logout",
                request_method="POST",
                success=True,
                detail_json="{}",
            )
        )
        db.commit()


def _mutate_user(user_id: str, **changes: object) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        for key, value in changes.items():
            setattr(user, key, value)
        db.add(user)
        db.commit()


def _create_user_directly(
    *,
    username: str,
    role: str,
    password_hash: str,
    auth_session_version: int = 0,
) -> str:
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=password_hash,
            nickname=username,
            role=role,
            auth_session_version=auth_session_version,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return str(user.id or "")

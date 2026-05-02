"""Admin audit-log query API tests."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.errors import ErrorCode
from app.models.admin import AdminAuditLog
from app.models.user import User
from app.services.admin_audit_service import AdminAuditService


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


def test_admin_audit_logs_forbid_non_admin(client: TestClient) -> None:
    auth_payload = _register(client, "audit-normal", "Audit Normal")

    response = client.get(
        "/api/v1/admin/audit-logs",
        headers=_auth_header(auth_payload["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.FORBIDDEN


def test_admin_audit_logs_list_supports_filters_pagination_and_redaction(client: TestClient) -> None:
    admin_auth = _register(client, "audit-admin", "Audit Admin")
    target_auth = _register(client, "audit-target", "Audit Target")
    _set_role(admin_auth["user"]["id"], "admin")
    _seed_audit_logs(admin_auth["user"]["id"], target_auth["user"]["id"])

    response = client.get(
        "/api/v1/admin/audit-logs",
        params={
            "actor_username": "audit-admin",
            "action": "admin.user.disable",
            "target_type": "user",
            "target_id": target_auth["user"]["id"],
            "success": "true",
            "created_from": "2026-01-01T00:00:00Z",
            "created_to": "2026-12-31T23:59:59Z",
            "page": 1,
            "size": 10,
        },
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["size"] == 10
    assert len(payload["items"]) == 1

    item = payload["items"][0]
    assert item["actor_user_id"] == admin_auth["user"]["id"]
    assert item["actor_username"] == "audit-admin"
    assert item["action"] == "admin.user.disable"
    assert item["target_type"] == "user"
    assert item["target_id"] == target_auth["user"]["id"]
    assert item["success"] is True
    assert item["detail"]["reason"] == "risk review"
    assert item["detail"]["password"] == "[redacted]"
    assert item["detail"]["nested"]["token"] == "[redacted]"
    assert item["detail"]["nested"]["safe"] == "visible"
    assert "secret123" not in json.dumps(item, ensure_ascii=False)
    assert "raw-token" not in json.dumps(item, ensure_ascii=False)


def test_admin_audit_log_detail_returns_one_log_and_redacts_legacy_raw_detail(client: TestClient) -> None:
    admin_auth = _register(client, "audit-detail-admin", "Audit Detail Admin")
    target_auth = _register(client, "audit-detail-target", "Audit Detail Target")
    _set_role(admin_auth["user"]["id"], "admin")
    log_id = _insert_legacy_raw_audit_log(admin_auth["user"]["id"], target_auth["user"]["id"])

    response = client.get(
        f"/api/v1/admin/audit-logs/{log_id}",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["id"] == log_id
    assert payload["actor_username"] == "audit-detail-admin"
    assert payload["action"] == "admin.user.force_logout"
    assert payload["target_id"] == target_auth["user"]["id"]
    assert payload["detail"]["authorization"] == "[redacted]"
    assert payload["detail"]["nested"]["secret"] == "[redacted]"
    assert payload["detail"]["nested"]["safe"] == "visible"
    assert "Bearer raw-token" not in json.dumps(payload, ensure_ascii=False)
    assert "raw-secret" not in json.dumps(payload, ensure_ascii=False)


def test_admin_audit_log_detail_returns_404_for_missing_log(client: TestClient) -> None:
    admin_auth = _register(client, "audit-missing-admin", "Audit Missing Admin")
    _set_role(admin_auth["user"]["id"], "admin")

    response = client.get(
        "/api/v1/admin/audit-logs/00000000-0000-0000-0000-000000000000",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 404
    assert response.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND


def test_admin_user_management_audit_can_be_queried_after_operation(client: TestClient) -> None:
    admin_auth = _register(client, "audit-operation-admin", "Audit Operation Admin")
    target_auth = _register(client, "audit-operation-target", "Audit Operation Target")
    _set_role(admin_auth["user"]["id"], "admin")

    disable_response = client.post(
        f"/api/v1/admin/users/{target_auth['user']['id']}/disable",
        json={"reason": "audit query"},
        headers=_auth_header(admin_auth["access_token"]),
    )
    assert disable_response.status_code == 200, disable_response.text

    response = client.get(
        "/api/v1/admin/audit-logs",
        params={"action": "admin.user.disable", "target_id": target_auth["user"]["id"]},
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["actor_user_id"] == admin_auth["user"]["id"]
    assert item["target_id"] == target_auth["user"]["id"]
    assert item["detail"]["reason"] == "audit query"


def _seed_audit_logs(actor_user_id: str, target_user_id: str) -> None:
    with SessionLocal() as db:
        service = AdminAuditService(db)
        service.record(
            actor_user_id=actor_user_id,
            actor_username="audit-admin",
            action="admin.user.disable",
            target_type="user",
            target_id=target_user_id,
            request_path=f"/api/v1/admin/users/{target_user_id}/disable",
            request_method="POST",
            client_ip="127.0.0.1",
            success=True,
            detail={
                "reason": "risk review",
                "password": "secret123",
                "nested": {"token": "raw-token", "safe": "visible"},
            },
        )
        service.record(
            actor_user_id=actor_user_id,
            actor_username="audit-admin",
            action="admin.user.enable",
            target_type="user",
            target_id=target_user_id,
            request_path=f"/api/v1/admin/users/{target_user_id}/enable",
            request_method="POST",
            client_ip="127.0.0.1",
            success=True,
            detail={"reason": "restored"},
        )
        service.record(
            actor_user_id=actor_user_id,
            actor_username="audit-admin",
            action="admin.dashboard.read",
            target_type="admin_dashboard",
            target_id="dashboard",
            request_path="/api/v1/admin/dashboard",
            request_method="GET",
            client_ip="127.0.0.1",
            success=True,
            detail={"section": "system"},
        )


def _insert_legacy_raw_audit_log(actor_user_id: str, target_user_id: str) -> str:
    with SessionLocal() as db:
        log = AdminAuditLog(
            actor_user_id=actor_user_id,
            actor_username="audit-detail-admin",
            action="admin.user.force_logout",
            target_type="user",
            target_id=target_user_id,
            request_path=f"/api/v1/admin/users/{target_user_id}/force-logout",
            request_method="POST",
            client_ip="127.0.0.1",
            success=True,
            detail_json=json.dumps(
                {
                    "authorization": "Bearer raw-token",
                    "nested": {"secret": "raw-secret", "safe": "visible"},
                },
                ensure_ascii=False,
            ),
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return str(log.id)

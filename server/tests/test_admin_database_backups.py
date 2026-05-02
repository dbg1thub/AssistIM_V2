"""Admin database backup API tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import SessionLocal
from app.core.errors import AppError, ErrorCode
from app.models.admin import AdminAuditLog, AdminDatabaseBackup
from app.models.user import User
from app.services import admin_database_backup_service as backup_service_module
from app.services.admin_database_backup_service import AdminDatabaseBackupService


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


def test_admin_database_backup_forbids_non_admin(client: TestClient) -> None:
    auth_payload = _register(client, "backup-normal", "Backup Normal")

    create_response = client.post(
        "/api/v1/admin/database/backups",
        headers=_auth_header(auth_payload["access_token"]),
    )
    list_response = client.get(
        "/api/v1/admin/database/backups",
        headers=_auth_header(auth_payload["access_token"]),
    )

    assert create_response.status_code == 403
    assert create_response.json()["code"] == ErrorCode.FORBIDDEN
    assert list_response.status_code == 403
    assert list_response.json()["code"] == ErrorCode.FORBIDDEN


def test_admin_database_backup_creates_real_sqlite_backup_and_audit(client: TestClient) -> None:
    admin_auth = _register(client, "backup-admin", "Backup Admin")
    _register(client, "backup-data", "Backup Data")
    _set_role(admin_auth["user"]["id"], "admin")

    response = client.post(
        "/api/v1/admin/database/backups",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "completed"
    assert payload["database_dialect"] == "sqlite"
    assert payload["backup_format"] == "sqlite"
    assert payload["created_by_user_id"] == admin_auth["user"]["id"]
    assert payload["created_by_username"] == "backup-admin"
    assert payload["size_bytes"] > 0
    assert len(payload["checksum_sha256"]) == 64
    assert payload["storage_key"].startswith("database_backups/")
    assert payload["file_name"].endswith(".sqlite3")
    assert "file_path" not in payload
    assert "public_url" not in payload
    assert "secret" not in str(payload).lower()
    assert "password" not in str(payload).lower()

    with SessionLocal() as db:
        backup = db.get(AdminDatabaseBackup, payload["id"])
        assert backup is not None
        assert Path(backup.file_path).is_file()
        assert Path(backup.file_path).stat().st_size == payload["size_bytes"]
        audit = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin.database.backup.create")
            .one()
        )
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.target_id == payload["id"]
        assert audit.success is True
        assert "secret123" not in audit.detail_json


def test_admin_database_backups_list_and_detail(client: TestClient) -> None:
    admin_auth = _register(client, "backup-list-admin", "Backup List Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    create_response = client.post(
        "/api/v1/admin/database/backups",
        headers=_auth_header(admin_auth["access_token"]),
    )
    assert create_response.status_code == 200, create_response.text
    backup_id = create_response.json()["data"]["id"]

    list_response = client.get(
        "/api/v1/admin/database/backups",
        headers=_auth_header(admin_auth["access_token"]),
    )
    detail_response = client.get(
        f"/api/v1/admin/database/backups/{backup_id}",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert list_response.status_code == 200, list_response.text
    list_payload = list_response.json()["data"]
    assert list_payload["total"] == 1
    assert list_payload["items"][0]["id"] == backup_id
    assert list_payload["items"][0]["status"] == "completed"
    assert "file_path" not in list_payload["items"][0]

    assert detail_response.status_code == 200, detail_response.text
    detail_payload = detail_response.json()["data"]
    assert detail_payload["id"] == backup_id
    assert detail_payload["status"] == "completed"
    assert detail_payload["storage_key"].startswith("database_backups/")
    assert "file_path" not in detail_payload


def test_admin_database_backup_detail_returns_404_for_missing_backup(client: TestClient) -> None:
    admin_auth = _register(client, "backup-missing-admin", "Backup Missing Admin")
    _set_role(admin_auth["user"]["id"], "admin")

    response = client.get(
        "/api/v1/admin/database/backups/00000000-0000-0000-0000-000000000000",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 404
    assert response.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND


def test_admin_database_backup_failure_records_error_and_redacts_password(monkeypatch) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://assistim:super-secret@db.example:5432/assistim",
    )
    with SessionLocal() as db:
        actor = User(username="backup-fail-admin", password_hash="hash", nickname="Backup Fail Admin", role="admin")
        db.add(actor)
        db.commit()
        db.refresh(actor)

        monkeypatch.setattr(backup_service_module.shutil, "which", lambda name: None)
        with pytest.raises(AppError) as exc_info:
            AdminDatabaseBackupService(db, settings).create_backup(actor=actor)

        assert exc_info.value.status_code == 500
        assert "pg_dump" in exc_info.value.message

        backup = db.query(AdminDatabaseBackup).one()
        assert backup.status == "failed"
        assert backup.database_dialect == "postgresql"
        assert "pg_dump" in backup.error_message
        assert "super-secret" not in backup.error_message

        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.database.backup.create").one()
        assert audit.success is False
        assert audit.target_id == str(backup.id)
        assert "super-secret" not in audit.detail_json

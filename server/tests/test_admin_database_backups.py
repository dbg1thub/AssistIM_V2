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


def test_admin_database_backup_download_forbids_non_admin(client: TestClient) -> None:
    admin_auth = _register(client, "backup-download-owner", "Backup Download Owner")
    normal_auth = _register(client, "backup-download-normal", "Backup Download Normal")
    _set_role(admin_auth["user"]["id"], "admin")
    create_response = client.post(
        "/api/v1/admin/database/backups",
        headers=_auth_header(admin_auth["access_token"]),
    )
    assert create_response.status_code == 200, create_response.text
    backup_id = create_response.json()["data"]["id"]

    response = client.get(
        f"/api/v1/admin/database/backups/{backup_id}/download",
        headers=_auth_header(normal_auth["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.FORBIDDEN


def test_admin_database_backup_delete_forbids_non_admin(client: TestClient) -> None:
    admin_auth = _register(client, "backup-delete-owner", "Backup Delete Owner")
    normal_auth = _register(client, "backup-delete-normal", "Backup Delete Normal")
    _set_role(admin_auth["user"]["id"], "admin")
    create_response = client.post(
        "/api/v1/admin/database/backups",
        headers=_auth_header(admin_auth["access_token"]),
    )
    assert create_response.status_code == 200, create_response.text
    backup_id = create_response.json()["data"]["id"]

    response = client.delete(
        f"/api/v1/admin/database/backups/{backup_id}",
        headers=_auth_header(normal_auth["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.FORBIDDEN
    with SessionLocal() as db:
        backup = db.get(AdminDatabaseBackup, backup_id)
        assert backup is not None
        assert backup.status == "completed"
        assert Path(backup.file_path).is_file()


def test_admin_database_backup_verify_forbids_non_admin(client: TestClient) -> None:
    admin_auth = _register(client, "backup-verify-owner", "Backup Verify Owner")
    normal_auth = _register(client, "backup-verify-normal", "Backup Verify Normal")
    _set_role(admin_auth["user"]["id"], "admin")
    create_response = client.post(
        "/api/v1/admin/database/backups",
        headers=_auth_header(admin_auth["access_token"]),
    )
    assert create_response.status_code == 200, create_response.text
    backup_id = create_response.json()["data"]["id"]

    response = client.post(
        f"/api/v1/admin/database/backups/{backup_id}/verify",
        headers=_auth_header(normal_auth["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.FORBIDDEN


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


def test_admin_database_backup_download_returns_attachment_and_records_audit(client: TestClient) -> None:
    admin_auth = _register(client, "backup-download-admin", "Backup Download Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    create_response = client.post(
        "/api/v1/admin/database/backups",
        headers=_auth_header(admin_auth["access_token"]),
    )
    assert create_response.status_code == 200, create_response.text
    backup_payload = create_response.json()["data"]

    response = client.get(
        f"/api/v1/admin/database/backups/{backup_payload['id']}/download",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/octet-stream")
    assert f'filename="{backup_payload["file_name"]}"' in response.headers["content-disposition"]
    assert len(response.content) == backup_payload["size_bytes"]
    assert len(response.content) > 0
    assert "file_path" not in response.headers["content-disposition"]

    with SessionLocal() as db:
        audit = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin.database.backup.download")
            .one()
        )
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.target_id == backup_payload["id"]
        assert audit.success is True
        assert "file_path" not in audit.detail_json


def test_admin_database_backup_verify_sqlite_success_records_fields_and_audit(client: TestClient) -> None:
    admin_auth = _register(client, "backup-verify-admin", "Backup Verify Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    create_response = client.post(
        "/api/v1/admin/database/backups",
        headers=_auth_header(admin_auth["access_token"]),
    )
    assert create_response.status_code == 200, create_response.text
    backup_payload = create_response.json()["data"]

    response = client.post(
        f"/api/v1/admin/database/backups/{backup_payload['id']}/verify",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["id"] == backup_payload["id"]
    assert payload["verification_status"] == "passed"
    assert payload["verification_message"]
    assert payload["verified_at"]
    assert payload["size_matched"] is True
    assert payload["checksum_matched"] is True
    assert payload["integrity_check"] == "ok"
    assert "file_path" not in payload

    detail_response = client.get(
        f"/api/v1/admin/database/backups/{backup_payload['id']}",
        headers=_auth_header(admin_auth["access_token"]),
    )
    assert detail_response.status_code == 200, detail_response.text
    detail_payload = detail_response.json()["data"]
    assert detail_payload["verification_status"] == "passed"
    assert detail_payload["verification_message"] == payload["verification_message"]
    assert detail_payload["verified_at"] == payload["verified_at"]
    assert "file_path" not in detail_payload

    with SessionLocal() as db:
        backup = db.get(AdminDatabaseBackup, backup_payload["id"])
        assert backup is not None
        assert backup.verification_status == "passed"
        assert backup.verified_at is not None
        audit = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin.database.backup.verify")
            .one()
        )
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.target_id == backup_payload["id"]
        assert audit.success is True
        assert "file_path" not in audit.detail_json


def test_admin_database_backup_verify_missing_file_marks_failed_and_records_audit(
    client: TestClient,
) -> None:
    admin_auth = _register(client, "backup-verify-missing-admin", "Backup Verify Missing Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    missing_path = _backup_root_for_client(client) / "verify-missing.sqlite3"
    missing_path.unlink(missing_ok=True)
    backup_id = _insert_backup_record(
        created_by_user_id=admin_auth["user"]["id"],
        created_by_username="backup-verify-missing-admin",
        status="completed",
        file_path=str(missing_path),
        file_name="verify-missing.sqlite3",
        size_bytes=128,
        checksum_sha256="4" * 64,
    )

    response = client.post(
        f"/api/v1/admin/database/backups/{backup_id}/verify",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 404
    assert response.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND
    assert "file" in response.json()["message"]

    with SessionLocal() as db:
        backup = db.get(AdminDatabaseBackup, backup_id)
        assert backup is not None
        assert backup.status == "completed"
        assert backup.verification_status == "failed"
        assert "file" in backup.verification_message
        assert backup.verified_at is not None
        audit = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin.database.backup.verify")
            .one()
        )
        assert audit.target_id == backup_id
        assert audit.success is False
        assert "file_path" not in audit.detail_json


def test_admin_database_backup_verify_rejects_checksum_mismatch_and_records_audit(
    client: TestClient,
) -> None:
    admin_auth = _register(client, "backup-verify-checksum-admin", "Backup Verify Checksum Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    create_response = client.post(
        "/api/v1/admin/database/backups",
        headers=_auth_header(admin_auth["access_token"]),
    )
    assert create_response.status_code == 200, create_response.text
    backup_payload = create_response.json()["data"]
    with SessionLocal() as db:
        backup = db.get(AdminDatabaseBackup, backup_payload["id"])
        assert backup is not None
        backup_file = Path(backup.file_path)
    with backup_file.open("ab") as handle:
        handle.write(b"tampered")

    response = client.post(
        f"/api/v1/admin/database/backups/{backup_payload['id']}/verify",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 409
    assert response.json()["code"] == ErrorCode.INVALID_REQUEST
    assert "checksum" in response.json()["message"]

    with SessionLocal() as db:
        backup = db.get(AdminDatabaseBackup, backup_payload["id"])
        assert backup is not None
        assert backup.verification_status == "failed"
        assert "checksum" in backup.verification_message
        audit = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin.database.backup.verify")
            .one()
        )
        assert audit.target_id == backup_payload["id"]
        assert audit.success is False
        assert "file_path" not in audit.detail_json


def test_admin_database_backup_verify_rejects_path_outside_backup_root(client: TestClient) -> None:
    admin_auth = _register(client, "backup-verify-path-admin", "Backup Verify Path Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    outside_file = _testdata_path("outside-verify-backup.sqlite3")
    outside_file.write_bytes(b"outside")
    backup_id = _insert_backup_record(
        created_by_user_id=admin_auth["user"]["id"],
        created_by_username="backup-verify-path-admin",
        status="completed",
        file_path=str(outside_file),
        file_name="outside-verify-backup.sqlite3",
        size_bytes=outside_file.stat().st_size,
        checksum_sha256=_sha256_file(outside_file),
    )

    response = client.post(
        f"/api/v1/admin/database/backups/{backup_id}/verify",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.FORBIDDEN
    assert "backup directory" in response.json()["message"]
    assert outside_file.is_file()

    with SessionLocal() as db:
        backup = db.get(AdminDatabaseBackup, backup_id)
        assert backup is not None
        assert backup.status == "completed"
        audit = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin.database.backup.verify")
            .one()
        )
        assert audit.target_id == backup_id
        assert audit.success is False
        assert "outside-verify-backup" not in audit.detail_json


def test_admin_database_backup_verify_rejects_failed_and_deleted_backups(client: TestClient) -> None:
    admin_auth = _register(client, "backup-verify-state-admin", "Backup Verify State Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    failed_backup_id = _insert_backup_record(
        created_by_user_id=admin_auth["user"]["id"],
        created_by_username="backup-verify-state-admin",
        status="failed",
        file_path="",
        file_name="verify-failed.dump",
        error_message="pg_dump not found",
    )
    create_response = client.post(
        "/api/v1/admin/database/backups",
        headers=_auth_header(admin_auth["access_token"]),
    )
    assert create_response.status_code == 200, create_response.text
    deleted_backup_id = create_response.json()["data"]["id"]
    delete_response = client.delete(
        f"/api/v1/admin/database/backups/{deleted_backup_id}",
        headers=_auth_header(admin_auth["access_token"]),
    )
    assert delete_response.status_code == 200, delete_response.text

    failed_response = client.post(
        f"/api/v1/admin/database/backups/{failed_backup_id}/verify",
        headers=_auth_header(admin_auth["access_token"]),
    )
    deleted_response = client.post(
        f"/api/v1/admin/database/backups/{deleted_backup_id}/verify",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert failed_response.status_code == 409
    assert failed_response.json()["code"] == ErrorCode.INVALID_REQUEST
    assert "completed" in failed_response.json()["message"]
    assert deleted_response.status_code == 409
    assert deleted_response.json()["code"] == ErrorCode.INVALID_REQUEST
    assert "completed" in deleted_response.json()["message"]


def test_admin_database_backup_verify_postgresql_requires_pg_restore(monkeypatch) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://assistim:super-secret@db.example:5432/assistim",
        upload_dir=_testdata_path("postgres-uploads").as_posix(),
    )
    backup_root = Path(settings.upload_dir).resolve().parent / "database_backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    dump_path = backup_root / "verify-postgres.dump"
    dump_path.write_bytes(b"pg custom dump placeholder")
    with SessionLocal() as db:
        actor = User(
            username="backup-verify-pg-admin",
            password_hash="hash",
            nickname="Backup Verify Pg Admin",
            role="admin",
        )
        db.add(actor)
        db.commit()
        db.refresh(actor)
        backup = AdminDatabaseBackup(
            created_by_user_id=str(actor.id),
            created_by_username=actor.username,
            status="completed",
            database_dialect="postgresql",
            backup_format="pg_dump_custom",
            storage_key=f"database_backups/{dump_path.name}",
            file_name=dump_path.name,
            file_path=str(dump_path),
            size_bytes=dump_path.stat().st_size,
            checksum_sha256=_sha256_file(dump_path),
        )
        db.add(backup)
        db.commit()
        db.refresh(backup)

        monkeypatch.setattr(backup_service_module.shutil, "which", lambda name: None)
        with pytest.raises(AppError) as exc_info:
            AdminDatabaseBackupService(db, settings).verify_backup(str(backup.id), actor=actor)

        assert exc_info.value.status_code == 500
        assert "pg_restore" in exc_info.value.message
        db.refresh(backup)
        assert backup.verification_status == "failed"
        assert "pg_restore" in backup.verification_message
        assert "super-secret" not in backup.verification_message
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.database.backup.verify").one()
        assert audit.success is False
        assert audit.target_id == str(backup.id)
        assert "super-secret" not in audit.detail_json
        assert "file_path" not in audit.detail_json


def test_admin_database_backup_delete_marks_record_deleted_and_removes_file(client: TestClient) -> None:
    admin_auth = _register(client, "backup-delete-admin", "Backup Delete Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    create_response = client.post(
        "/api/v1/admin/database/backups",
        headers=_auth_header(admin_auth["access_token"]),
    )
    assert create_response.status_code == 200, create_response.text
    backup_payload = create_response.json()["data"]
    with SessionLocal() as db:
        backup = db.get(AdminDatabaseBackup, backup_payload["id"])
        assert backup is not None
        backup_file = Path(backup.file_path)
        assert backup_file.is_file()

    response = client.delete(
        f"/api/v1/admin/database/backups/{backup_payload['id']}",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["id"] == backup_payload["id"]
    assert payload["status"] == "deleted"
    assert payload["file_deleted"] is True
    assert payload["file_missing"] is False
    assert "file_path" not in payload
    assert not backup_file.exists()

    detail_response = client.get(
        f"/api/v1/admin/database/backups/{backup_payload['id']}",
        headers=_auth_header(admin_auth["access_token"]),
    )
    assert detail_response.status_code == 200, detail_response.text
    assert detail_response.json()["data"]["status"] == "deleted"

    with SessionLocal() as db:
        backup = db.get(AdminDatabaseBackup, backup_payload["id"])
        assert backup is not None
        assert backup.status == "deleted"
        audit = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin.database.backup.delete")
            .one()
        )
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.target_id == backup_payload["id"]
        assert audit.success is True
        assert "file_path" not in audit.detail_json


def test_admin_database_backup_delete_marks_failed_backup_without_file_deleted(
    client: TestClient,
) -> None:
    admin_auth = _register(client, "backup-delete-failed-admin", "Backup Delete Failed Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    backup_id = _insert_backup_record(
        created_by_user_id=admin_auth["user"]["id"],
        created_by_username="backup-delete-failed-admin",
        status="failed",
        file_path="",
        file_name="failed-delete.dump",
        error_message="pg_dump not found",
    )

    response = client.delete(
        f"/api/v1/admin/database/backups/{backup_id}",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "deleted"
    assert payload["file_deleted"] is False
    assert payload["file_missing"] is True
    assert "file_path" not in payload

    with SessionLocal() as db:
        backup = db.get(AdminDatabaseBackup, backup_id)
        assert backup is not None
        assert backup.status == "deleted"
        audit = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin.database.backup.delete")
            .one()
        )
        assert audit.target_id == backup_id
        assert audit.success is True
        assert '"status_before": "failed"' in audit.detail_json
        assert "file_path" not in audit.detail_json


def test_admin_database_backup_delete_marks_missing_file_deleted_and_records_audit(
    client: TestClient,
) -> None:
    admin_auth = _register(client, "backup-delete-missing-admin", "Backup Delete Missing Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    missing_path = _backup_root_for_client(client) / "missing-delete.sqlite3"
    missing_path.unlink(missing_ok=True)
    backup_id = _insert_backup_record(
        created_by_user_id=admin_auth["user"]["id"],
        created_by_username="backup-delete-missing-admin",
        status="completed",
        file_path=str(missing_path),
        file_name="missing-delete.sqlite3",
        size_bytes=128,
        checksum_sha256="2" * 64,
    )

    response = client.delete(
        f"/api/v1/admin/database/backups/{backup_id}",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "deleted"
    assert payload["file_deleted"] is False
    assert payload["file_missing"] is True

    with SessionLocal() as db:
        audit = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin.database.backup.delete")
            .one()
        )
        assert audit.target_id == backup_id
        assert audit.success is True
        assert '"file_missing": true' in audit.detail_json
        assert "file_path" not in audit.detail_json


def test_admin_database_backup_delete_rejects_path_outside_backup_root(client: TestClient) -> None:
    admin_auth = _register(client, "backup-delete-path-admin", "Backup Delete Path Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    outside_file = _testdata_path("outside-delete-backup.sqlite3")
    outside_file.write_bytes(b"outside")
    backup_id = _insert_backup_record(
        created_by_user_id=admin_auth["user"]["id"],
        created_by_username="backup-delete-path-admin",
        status="completed",
        file_path=str(outside_file),
        file_name="outside-delete-backup.sqlite3",
        size_bytes=outside_file.stat().st_size,
        checksum_sha256="3" * 64,
    )

    response = client.delete(
        f"/api/v1/admin/database/backups/{backup_id}",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.FORBIDDEN
    assert "backup directory" in response.json()["message"]
    assert outside_file.is_file()

    with SessionLocal() as db:
        backup = db.get(AdminDatabaseBackup, backup_id)
        assert backup is not None
        assert backup.status == "completed"
        audit = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin.database.backup.delete")
            .one()
        )
        assert audit.target_id == backup_id
        assert audit.success is False
        assert "outside-delete-backup" not in audit.detail_json


def test_admin_database_backup_detail_returns_404_for_missing_backup(client: TestClient) -> None:
    admin_auth = _register(client, "backup-missing-admin", "Backup Missing Admin")
    _set_role(admin_auth["user"]["id"], "admin")

    response = client.get(
        "/api/v1/admin/database/backups/00000000-0000-0000-0000-000000000000",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 404
    assert response.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND


def test_admin_database_backup_download_rejects_failed_backup_and_records_audit(client: TestClient) -> None:
    admin_auth = _register(client, "backup-download-failed-admin", "Backup Download Failed Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    backup_id = _insert_backup_record(
        created_by_user_id=admin_auth["user"]["id"],
        created_by_username="backup-download-failed-admin",
        status="failed",
        file_path="",
        file_name="failed.dump",
        error_message="pg_dump not found",
    )

    response = client.get(
        f"/api/v1/admin/database/backups/{backup_id}/download",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 409
    assert response.json()["code"] == ErrorCode.INVALID_REQUEST
    assert "completed" in response.json()["message"]

    with SessionLocal() as db:
        audit = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin.database.backup.download")
            .one()
        )
        assert audit.target_id == backup_id
        assert audit.success is False
        assert "failed" in audit.detail_json


def test_admin_database_backup_download_returns_404_when_file_missing_and_records_audit(
    client: TestClient,
) -> None:
    admin_auth = _register(client, "backup-download-missing-admin", "Backup Download Missing Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    backup_id = _insert_backup_record(
        created_by_user_id=admin_auth["user"]["id"],
        created_by_username="backup-download-missing-admin",
        status="completed",
        file_path=str(_testdata_path("missing-backup.sqlite3")),
        file_name="missing-backup.sqlite3",
        size_bytes=128,
        checksum_sha256="0" * 64,
    )

    response = client.get(
        f"/api/v1/admin/database/backups/{backup_id}/download",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 404
    assert response.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND
    assert "file" in response.json()["message"]

    with SessionLocal() as db:
        audit = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin.database.backup.download")
            .one()
        )
        assert audit.target_id == backup_id
        assert audit.success is False
        assert "file_path" not in audit.detail_json


def test_admin_database_backup_download_rejects_path_outside_backup_root(client: TestClient) -> None:
    admin_auth = _register(client, "backup-download-path-admin", "Backup Download Path Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    outside_file = _testdata_path("outside-backup.sqlite3")
    outside_file.write_bytes(b"outside")
    backup_id = _insert_backup_record(
        created_by_user_id=admin_auth["user"]["id"],
        created_by_username="backup-download-path-admin",
        status="completed",
        file_path=str(outside_file),
        file_name="outside-backup.sqlite3",
        size_bytes=outside_file.stat().st_size,
        checksum_sha256="1" * 64,
    )

    response = client.get(
        f"/api/v1/admin/database/backups/{backup_id}/download",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.FORBIDDEN
    assert "backup directory" in response.json()["message"]

    with SessionLocal() as db:
        audit = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin.database.backup.download")
            .one()
        )
        assert audit.target_id == backup_id
        assert audit.success is False
        assert "outside-backup" not in audit.detail_json


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


def _insert_backup_record(
    *,
    created_by_user_id: str,
    created_by_username: str,
    status: str,
    file_path: str,
    file_name: str,
    database_dialect: str = "sqlite",
    backup_format: str = "sqlite",
    size_bytes: int = 0,
    checksum_sha256: str = "",
    error_message: str = "",
) -> str:
    with SessionLocal() as db:
        backup = AdminDatabaseBackup(
            created_by_user_id=created_by_user_id,
            created_by_username=created_by_username,
            status=status,
            database_dialect=database_dialect,
            backup_format=backup_format,
            storage_key=f"database_backups/{file_name}",
            file_name=file_name,
            file_path=file_path,
            size_bytes=size_bytes,
            checksum_sha256=checksum_sha256,
            error_message=error_message,
        )
        db.add(backup)
        db.commit()
        db.refresh(backup)
        return str(backup.id)


def _backup_root_for_client(client: TestClient) -> Path:
    settings = client.app.state.settings
    configured = str(getattr(settings, "admin_backup_dir", "") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(settings.upload_dir).expanduser().resolve().parent / "database_backups").resolve()


def _testdata_path(file_name: str) -> Path:
    return (Path(__file__).resolve().parents[1] / ".testdata" / file_name).resolve()


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

"""Admin file storage inspection API tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.errors import ErrorCode
from app.models.admin import AdminAuditLog
from app.models.file import StoredFile
from app.models.user import User


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


def _upload_root(client: TestClient) -> Path:
    return Path(client.app.state.settings.upload_dir).resolve()


def _write_upload(client: TestClient, storage_key: str, content: bytes) -> str:
    path = _upload_root(client) / Path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _seed_file_record(
    *,
    user_id: str,
    storage_key: str,
    file_name: str,
    size_bytes: int,
    checksum_sha256: str,
    file_type: str = "text/plain",
    storage_provider: str = "local",
) -> str:
    with SessionLocal() as db:
        stored = StoredFile(
            user_id=user_id,
            storage_provider=storage_provider,
            storage_key=storage_key,
            file_url=f"/uploads/{storage_key}",
            file_type=file_type,
            file_name=file_name,
            size_bytes=size_bytes,
            checksum_sha256=checksum_sha256,
        )
        db.add(stored)
        db.commit()
        return str(stored.id)


def test_admin_file_storage_forbids_non_admin(client: TestClient) -> None:
    auth_payload = _register(client, "files-normal", "Files Normal")

    status_response = client.get(
        "/api/v1/admin/files/storage/status",
        headers=_auth_header(auth_payload["access_token"]),
    )
    issues_response = client.get(
        "/api/v1/admin/files/storage/issues",
        headers=_auth_header(auth_payload["access_token"]),
    )

    assert status_response.status_code == 403
    assert status_response.json()["code"] == ErrorCode.FORBIDDEN
    assert issues_response.status_code == 403
    assert issues_response.json()["code"] == ErrorCode.FORBIDDEN


def test_admin_file_storage_status_reports_database_and_disk_without_paths(client: TestClient) -> None:
    admin_auth = _register(client, "files-status-admin", "Files Status Admin")
    target_auth = _register(client, "files-status-user", "Files Status User")
    _set_role(admin_auth["user"]["id"], "admin")
    upload_root = _upload_root(client)

    content = b"readme content"
    checksum = _write_upload(client, "files/readme.txt", content)
    _seed_file_record(
        user_id=target_auth["user"]["id"],
        storage_key="files/readme.txt",
        file_name="readme.txt",
        size_bytes=len(content),
        checksum_sha256=checksum,
    )

    response = client.get(
        "/api/v1/admin/files/storage/status",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "ok"
    assert payload["storage_provider"] == "local"
    assert payload["upload_dir"]["exists"] is True
    assert payload["upload_dir"]["is_dir"] is True
    assert payload["database"]["local_records"] == 1
    assert payload["database"]["non_local_records"] == 0
    assert payload["database"]["local_size_bytes"] == len(content)
    assert payload["disk"]["managed_files"] == 1
    assert payload["disk"]["managed_size_bytes"] == len(content)
    assert payload["issues"] == {
        "total": 0,
        "invalid_storage_keys": 0,
        "missing_disk_files": 0,
        "metadata_mismatches": 0,
        "orphan_disk_files": 0,
    }
    assert "file_path" not in str(payload)
    assert str(upload_root) not in str(payload)

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.files.storage.status.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True
        assert "file_path" not in audit.detail_json
        assert str(upload_root) not in audit.detail_json


def test_admin_file_storage_issues_reports_missing_and_orphan_files_without_paths(client: TestClient) -> None:
    admin_auth = _register(client, "files-issues-admin", "Files Issues Admin")
    target_auth = _register(client, "files-issues-user", "Files Issues User")
    _set_role(admin_auth["user"]["id"], "admin")
    upload_root = _upload_root(client)

    missing_id = _seed_file_record(
        user_id=target_auth["user"]["id"],
        storage_key="files/missing.txt",
        file_name="missing.txt",
        size_bytes=7,
        checksum_sha256="missing-checksum",
    )
    _write_upload(client, "files/orphan.txt", b"orphan")

    response = client.get(
        "/api/v1/admin/files/storage/issues",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 2
    issues = {item["issue_type"]: item for item in payload["items"]}
    assert issues["missing_disk_file"]["file_id"] == missing_id
    assert issues["missing_disk_file"]["file_name"] == "missing.txt"
    assert issues["missing_disk_file"]["storage_key"] == "files/missing.txt"
    assert issues["orphan_disk_file"]["storage_key"] == "files/orphan.txt"
    assert issues["orphan_disk_file"]["actual_size_bytes"] == len(b"orphan")
    assert "file_path" not in str(payload)
    assert str(upload_root) not in str(payload)

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.files.storage.issues.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True
        assert "file_path" not in audit.detail_json
        assert str(upload_root) not in audit.detail_json


def test_admin_file_storage_issues_reports_metadata_mismatch(client: TestClient) -> None:
    admin_auth = _register(client, "files-mismatch-admin", "Files Mismatch Admin")
    target_auth = _register(client, "files-mismatch-user", "Files Mismatch User")
    _set_role(admin_auth["user"]["id"], "admin")

    actual_checksum = _write_upload(client, "files/mismatch.txt", b"actual")
    _seed_file_record(
        user_id=target_auth["user"]["id"],
        storage_key="files/mismatch.txt",
        file_name="mismatch.txt",
        size_bytes=100,
        checksum_sha256="recorded-checksum",
    )

    response = client.get(
        "/api/v1/admin/files/storage/issues",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 1
    issue = payload["items"][0]
    assert issue["issue_type"] == "metadata_mismatch"
    assert issue["storage_key"] == "files/mismatch.txt"
    assert issue["size_mismatch"] is True
    assert issue["checksum_mismatch"] is True
    assert issue["expected_size_bytes"] == 100
    assert issue["actual_size_bytes"] == len(b"actual")
    assert issue["expected_checksum_sha256"] == "recorded-checksum"
    assert issue["actual_checksum_sha256"] == actual_checksum

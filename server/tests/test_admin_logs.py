"""Admin server log API tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import reload_settings
from app.core.database import SessionLocal
from app.core.errors import ErrorCode
from app.main import create_app
from app.models.admin import AdminAuditLog
from app.models.user import User


def _client_with_log_dir(monkeypatch, log_dir: Path) -> TestClient:
    monkeypatch.setenv("LOG_DIR", log_dir.as_posix())
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


def _set_role(user_id: str, role: str) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.role = role
        db.add(user)
        db.commit()


def _write_log(log_dir: Path, file_name: str, lines: list[str]) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / file_name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_admin_logs_forbid_non_admin(monkeypatch) -> None:
    log_dir = _test_log_dir("non-admin")
    with _client_with_log_dir(monkeypatch, log_dir) as client:
        auth_payload = _register(client, "logs-normal", "Logs Normal")
        _write_log(log_dir, "assistim.log", ["2026-05-03 10:00:00,000 level=INFO logger=assistim message=hello"])

        list_response = client.get(
            "/api/v1/admin/logs/files",
            headers=_auth_header(auth_payload["access_token"]),
        )
        query_response = client.get(
            "/api/v1/admin/logs",
            headers=_auth_header(auth_payload["access_token"]),
        )
        download_response = client.get(
            "/api/v1/admin/logs/files/assistim.log/download",
            headers=_auth_header(auth_payload["access_token"]),
        )

    assert list_response.status_code == 403
    assert list_response.json()["code"] == ErrorCode.FORBIDDEN
    assert query_response.status_code == 403
    assert query_response.json()["code"] == ErrorCode.FORBIDDEN
    assert download_response.status_code == 403
    assert download_response.json()["code"] == ErrorCode.FORBIDDEN


def test_admin_logs_list_files_and_records_audit(monkeypatch) -> None:
    log_dir = _test_log_dir("list")
    with _client_with_log_dir(monkeypatch, log_dir) as client:
        admin_auth = _register(client, "logs-list-admin", "Logs List Admin")
        _set_role(admin_auth["user"]["id"], "admin")
        log_file = _write_log(log_dir, "assistim.log", ["2026-05-03 10:00:00,000 level=INFO logger=assistim message=hello"])
        _write_log(log_dir, "assistim.log.1", ["2026-05-03 09:00:00,000 level=WARNING logger=assistim message=old"])

        response = client.get(
            "/api/v1/admin/logs/files",
            headers=_auth_header(admin_auth["access_token"]),
        )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 2
    file_names = {item["file_name"] for item in payload["items"]}
    assert file_names == {"assistim.log", "assistim.log.1"}
    assert all("file_path" not in item for item in payload["items"])
    assert any(item["size_bytes"] == log_file.stat().st_size for item in payload["items"])

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.logs.files.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True
        assert "file_path" not in audit.detail_json


def test_admin_logs_query_supports_filters_limit_and_redaction(monkeypatch) -> None:
    log_dir = _test_log_dir("query")
    with _client_with_log_dir(monkeypatch, log_dir) as client:
        admin_auth = _register(client, "logs-query-admin", "Logs Query Admin")
        _set_role(admin_auth["user"]["id"], "admin")
        _write_log(
            log_dir,
            "assistim.log",
            [
                "2026-05-03 10:00:00,000 level=INFO logger=assistim message=login ok token=plain-token",
                "2026-05-03 10:00:01,000 level=ERROR logger=assistim message=database failed password=super-secret authorization=Bearer abc",
                "2026-05-03 10:00:02,000 level=WARNING logger=assistim message=cache warning secret=hidden",
            ],
        )

        response = client.get(
            "/api/v1/admin/logs",
            headers=_auth_header(admin_auth["access_token"]),
            params={
                "file_name": "assistim.log",
                "level": "ERROR",
                "keyword": "database",
                "created_from": "2026-05-03T10:00:00+00:00",
                "created_to": "2026-05-03T10:00:01+00:00",
                "limit": 1,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 1
    assert payload["items"][0]["level"] == "ERROR"
    assert payload["items"][0]["logger"] == "assistim"
    assert "database failed" in payload["items"][0]["message"]
    assert "super-secret" not in str(payload)
    assert "plain-token" not in str(payload)
    assert "Bearer abc" not in str(payload)
    assert "[redacted]" in payload["items"][0]["message"]
    assert "file_path" not in payload["items"][0]

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.logs.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True
        assert "super-secret" not in audit.detail_json
        assert "file_path" not in audit.detail_json


def test_admin_logs_download_returns_sanitized_attachment(monkeypatch) -> None:
    log_dir = _test_log_dir("download")
    with _client_with_log_dir(monkeypatch, log_dir) as client:
        admin_auth = _register(client, "logs-download-admin", "Logs Download Admin")
        _set_role(admin_auth["user"]["id"], "admin")
        _write_log(
            log_dir,
            "assistim.log",
            ["2026-05-03 10:00:00,000 level=ERROR logger=assistim message=password=super-secret token=abc"],
        )

        response = client.get(
            "/api/v1/admin/logs/files/assistim.log/download",
            headers=_auth_header(admin_auth["access_token"]),
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/plain")
    assert 'filename="assistim.log"' in response.headers["content-disposition"]
    assert "super-secret" not in response.text
    assert "token=abc" not in response.text
    assert "[redacted]" in response.text

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.logs.download").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True
        assert "file_path" not in audit.detail_json


def test_admin_logs_reject_path_traversal_and_records_audit(monkeypatch) -> None:
    log_dir = _test_log_dir("path")
    outside_file = log_dir.parent / "outside.log"
    outside_file.parent.mkdir(parents=True, exist_ok=True)
    outside_file.write_text("outside", encoding="utf-8")
    with _client_with_log_dir(monkeypatch, log_dir) as client:
        admin_auth = _register(client, "logs-path-admin", "Logs Path Admin")
        _set_role(admin_auth["user"]["id"], "admin")

        response = client.get(
            "/api/v1/admin/logs/files/..%5Coutside.log/download",
            headers=_auth_header(admin_auth["access_token"]),
        )

    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.FORBIDDEN
    assert outside_file.is_file()

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.logs.download").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is False
        assert "outside.log" not in audit.detail_json
        assert "file_path" not in audit.detail_json


def _test_log_dir(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / ".testdata" / "logs" / name

"""Admin database inspection API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import RUNTIME_SCHEMA_REQUIRED_TABLES, SessionLocal
from app.core.errors import ErrorCode
from app.core.schema_compat import RUNTIME_SCHEMA_ALEMBIC_REVISION
from app.models.admin import AdminAuditLog
from app.models.file import StoredFile
from app.models.message import Message
from app.models.session import ChatSession, SessionMember
from app.models.user import User
from app.services.admin_database_service import AdminDatabaseService


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


def test_admin_database_status_forbids_non_admin(client: TestClient) -> None:
    auth_payload = _register(client, "db-normal", "DB Normal")

    response = client.get(
        "/api/v1/admin/database/status",
        headers=_auth_header(auth_payload["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.FORBIDDEN


def test_admin_database_status_reports_schema_and_migration_without_password(client: TestClient) -> None:
    admin_auth = _register(client, "db-status-admin", "DB Status Admin")
    _set_role(admin_auth["user"]["id"], "admin")

    response = client.get(
        "/api/v1/admin/database/status",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "ok"
    assert payload["dialect"] == "sqlite"
    assert payload["runtime_schema_revision"] == RUNTIME_SCHEMA_ALEMBIC_REVISION
    assert payload["runtime_schema_complete"] is True
    assert payload["alembic"]["current_versions"] == []
    assert payload["alembic"]["runtime_revision_applied"] is False
    assert set(payload["required_tables"]) == set(RUNTIME_SCHEMA_REQUIRED_TABLES)
    assert all(payload["required_tables"].values())
    assert "secret" not in str(payload).lower()
    assert "password" not in str(payload).lower()


def test_admin_database_tables_reports_row_counts_and_indexes(client: TestClient) -> None:
    admin_auth = _register(client, "db-tables-admin", "DB Tables Admin")
    target_auth = _register(client, "db-tables-target", "DB Tables Target")
    _set_role(admin_auth["user"]["id"], "admin")
    _seed_database_records(target_auth["user"]["id"])

    response = client.get(
        "/api/v1/admin/database/tables",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total_tables"] >= len(RUNTIME_SCHEMA_REQUIRED_TABLES)
    tables = {item["name"]: item for item in payload["tables"]}

    assert tables["users"]["row_count"] == 2
    assert tables["messages"]["row_count"] == 1
    assert tables["files"]["row_count"] == 1
    assert "idx_messages_session_seq" in tables["messages"]["indexes"]
    assert tables["messages"]["required_indexes"]["idx_messages_session_seq"] is True


def test_admin_database_health_reports_ok_when_runtime_schema_is_complete(client: TestClient) -> None:
    admin_auth = _register(client, "db-health-admin", "DB Health Admin")
    _set_role(admin_auth["user"]["id"], "admin")

    response = client.get(
        "/api/v1/admin/database/health",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "ok"
    assert payload["issue_count"] == 0
    assert payload["issues"] == []
    assert payload["checks"]["required_tables_missing"] == []
    assert payload["checks"]["required_indexes_missing"] == {}
    assert payload["checks"]["runtime_schema_complete"] is True


def test_admin_database_service_redacts_database_url_password() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://assistim:super-secret@db.example:5432/assistim",
    )
    with SessionLocal() as db:
        payload = AdminDatabaseService(db, settings).build_status()

    assert payload["database_url"] == "postgresql+psycopg://assistim:***@db.example:5432/assistim"
    assert "super-secret" not in str(payload)


def _seed_database_records(user_id: str) -> None:
    with SessionLocal() as db:
        session = ChatSession(type="private", name="db-inspection-session")
        db.add(session)
        db.flush()
        message = Message(
            session_id=session.id,
            sender_id=user_id,
            session_seq=1,
            type="text",
            content="hello",
        )
        db.add_all(
            [
                SessionMember(session_id=session.id, user_id=user_id),
                message,
                StoredFile(
                    user_id=user_id,
                    storage_provider="local",
                    storage_key="files/db-inspection.txt",
                    file_url="/uploads/files/db-inspection.txt",
                    file_type="text/plain",
                    file_name="db-inspection.txt",
                    size_bytes=12,
                    checksum_sha256="db-inspection-sha",
                ),
                AdminAuditLog(
                    actor_user_id=user_id,
                    actor_username="db-tables-target",
                    action="admin.database.test_seed",
                    target_type="database",
                    target_id="test",
                    request_path="/api/v1/admin/database/tables",
                    request_method="GET",
                    client_ip="127.0.0.1",
                    success=True,
                    detail_json="{}",
                ),
            ]
        )
        db.commit()

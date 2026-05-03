"""Admin HTTP diagnostics and rate-limit inspection API tests."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.core.config import reload_settings
from app.core.database import SessionLocal
from app.core.errors import ErrorCode
from app.core.runtime_diagnostics import record_http_request, reset_runtime_diagnostics
from app.main import create_app
from app.models.admin import AdminAuditLog
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


def _client_with_rate_limit_backend(monkeypatch, backend: str) -> TestClient:
    monkeypatch.setenv("RATE_LIMIT_STORE_BACKEND", backend)
    return TestClient(create_app(reload_settings()))


def test_admin_http_and_rate_limit_endpoints_forbid_non_admin(client: TestClient) -> None:
    auth_payload = _register(client, "http-rate-normal", "HTTP Rate Normal")
    headers = _auth_header(auth_payload["access_token"])

    responses = [
        client.get("/api/v1/admin/http/requests", headers=headers),
        client.get("/api/v1/admin/http/health", headers=headers),
        client.get("/api/v1/admin/rate-limits/status", headers=headers),
        client.get("/api/v1/admin/rate-limits/health", headers=headers),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]
    assert all(response.json()["code"] == ErrorCode.FORBIDDEN for response in responses)


def test_admin_http_requests_list_filters_records_and_redacts_request_data(client: TestClient) -> None:
    admin_auth = _register(client, "http-requests-admin", "HTTP Requests Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    reset_runtime_diagnostics()
    record_http_request(
        method="GET",
        path="/api/v1/visible",
        status_code=200,
        duration_ms=12.5,
        user_id=admin_auth["user"]["id"],
        timestamp=1000.0,
        slow_request_ms=1000,
    )
    record_http_request(
        method="POST",
        path="/api/v1/auth/login",
        status_code=401,
        duration_ms=34.0,
        user_id="anonymous",
        timestamp=1001.0,
        slow_request_ms=1000,
    )

    response = client.get(
        "/api/v1/admin/http/requests",
        headers=_auth_header(admin_auth["access_token"]),
        params={"status_code": 401, "limit": 10},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["total"] == 1
    assert payload["limit"] == 10
    assert payload["filters"]["status_code"] == 401
    assert payload["counters"]["total_requests"] == 2
    assert payload["counters"]["error_requests"] == 1
    assert payload["items"] == [
        {
            "method": "POST",
            "path": "/api/v1/auth/login",
            "status_code": 401,
            "duration_ms": 34.0,
            "user_id": "anonymous",
            "timestamp": "1970-01-01T00:16:41+00:00",
        }
    ]
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    assert "authorization" not in serialized
    assert "access_token" not in serialized
    assert "password" not in serialized
    assert "headers" not in serialized
    assert "body" not in serialized

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.http.requests.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True
        assert "authorization" not in audit.detail_json.lower()
        assert "password" not in audit.detail_json.lower()


def test_admin_http_health_reports_error_and_slow_request_issues(client: TestClient) -> None:
    admin_auth = _register(client, "http-health-admin", "HTTP Health Admin")
    _set_role(admin_auth["user"]["id"], "admin")
    reset_runtime_diagnostics()
    record_http_request(
        method="GET",
        path="/api/v1/ok",
        status_code=200,
        duration_ms=20.0,
        user_id="anonymous",
        timestamp=1000.0,
        slow_request_ms=1000,
    )
    record_http_request(
        method="GET",
        path="/api/v1/missing",
        status_code=404,
        duration_ms=45.0,
        user_id="anonymous",
        timestamp=1001.0,
        slow_request_ms=1000,
    )
    record_http_request(
        method="POST",
        path="/api/v1/broken",
        status_code=503,
        duration_ms=1500.0,
        user_id=admin_auth["user"]["id"],
        timestamp=1002.0,
        slow_request_ms=1000,
    )

    response = client.get(
        "/api/v1/admin/http/health",
        headers=_auth_header(admin_auth["access_token"]),
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "warning"
    issue_types = {item["issue_type"] for item in payload["issues"]}
    assert "http_error_responses_observed" in issue_types
    assert "http_5xx_responses_observed" in issue_types
    assert "http_slow_requests_observed" in issue_types
    assert payload["checks"]["total_requests"] == 3
    assert payload["checks"]["retained_requests"] == 3
    assert payload["checks"]["error_requests"] == 2
    assert payload["checks"]["slow_requests"] == 1
    assert payload["recent_error_requests"][0]["path"] == "/api/v1/broken"
    assert payload["slowest_requests"][0]["duration_ms"] == 1500.0

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.http.health.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True


def test_admin_rate_limit_status_reports_active_store_and_buckets(monkeypatch) -> None:
    with _client_with_rate_limit_backend(monkeypatch, "memory") as client:
        admin_auth = _register(client, "rate-status-admin", "Rate Status Admin")
        _set_role(admin_auth["user"]["id"], "admin")
        failed_login = client.post(
            "/api/v1/auth/login",
            json={"username": "rate-status-admin", "password": "wrong-password"},
        )
        assert failed_login.status_code == 401

        response = client.get(
            "/api/v1/admin/rate-limits/status",
            headers=_auth_header(admin_auth["access_token"]),
            params={"key_prefix": "login", "limit": 10},
        )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["backend"]["configured"] == "memory"
    assert payload["backend"]["active_store"] == "InMemoryRateLimitStore"
    assert payload["limits"]["login"] == {"limit": 5, "window_seconds": 60}
    assert payload["filters"] == {"key_prefix": "login", "limit": 10}
    assert payload["store"]["supported"] is True
    assert payload["store"]["bucket_count"] >= 1
    assert payload["store"]["active_hit_count"] >= 1
    assert payload["by_key_prefix"]["login"]["bucket_count"] >= 1
    assert payload["items"][0]["key_prefix"] == "login"
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    assert "authorization" not in serialized
    assert "access_token" not in serialized
    assert "password" not in serialized

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.rate_limits.status.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True


def test_admin_rate_limit_status_reports_database_store(client: TestClient) -> None:
    admin_auth = _register(client, "rate-db-admin", "Rate DB Admin")
    _set_role(admin_auth["user"]["id"], "admin")

    response = client.get(
        "/api/v1/admin/rate-limits/status",
        headers=_auth_header(admin_auth["access_token"]),
        params={"key_prefix": "register", "limit": 10},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["backend"]["configured"] == "database"
    assert payload["backend"]["active_store"] == "DatabaseRateLimitStore"
    assert payload["store"]["supported"] is True
    assert payload["store"]["status"] == "ok"
    assert payload["store"]["scope"] == "database"
    assert payload["store"]["table_exists"] is True
    assert payload["by_key_prefix"]["register"]["bucket_count"] >= 1


def test_admin_rate_limit_health_reports_store_pressure(monkeypatch) -> None:
    with _client_with_rate_limit_backend(monkeypatch, "memory") as client:
        admin_auth = _register(client, "rate-health-admin", "Rate Health Admin")
        _set_role(admin_auth["user"]["id"], "admin")

        response = client.get(
            "/api/v1/admin/rate-limits/health",
            headers=_auth_header(admin_auth["access_token"]),
            params={"max_bucket_count": 0},
        )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "warning"
    assert payload["checks"]["store_supported"] is True
    assert payload["checks"]["bucket_count"] >= 1
    issue_types = {item["issue_type"] for item in payload["issues"]}
    assert "rate_limit_bucket_count_exceeded" in issue_types

    with SessionLocal() as db:
        audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "admin.rate_limits.health.read").one()
        assert audit.actor_user_id == admin_auth["user"]["id"]
        assert audit.success is True

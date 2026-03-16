"""Pytest fixtures for backend integration tests."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = ROOT / "server"
TEST_STATE_DIR = SERVER_ROOT / ".testdata"
TEST_DB_PATH = TEST_STATE_DIR / "test.db"
TEST_UPLOAD_DIR = TEST_STATE_DIR / "uploads"

TEST_STATE_DIR.mkdir(parents=True, exist_ok=True)
os.environ["APP_NAME"] = "AssistIM Test API"
os.environ["APP_VERSION"] = "test"
os.environ["DEBUG"] = "false"
os.environ["SECRET_KEY"] = "assistim-test-secret"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["UPLOAD_DIR"] = TEST_UPLOAD_DIR.as_posix()
os.environ["API_V1_PREFIX"] = "/api/v1"
os.environ["API_COMPAT_PREFIX"] = "/api"
os.environ["CORS_ORIGINS"] = "*"

if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.core.database import Base, engine
from app.core.rate_limit import rate_limiter
from app.main import app
from app.websocket.manager import connection_manager


@pytest.fixture(autouse=True)
def reset_test_state() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    rate_limiter._buckets.clear()
    connection_manager._connections.clear()
    connection_manager._user_by_connection.clear()
    connection_manager._connection_by_socket.clear()
    connection_manager._connections_by_user.clear()

    if TEST_UPLOAD_DIR.exists():
        shutil.rmtree(TEST_UPLOAD_DIR)
    TEST_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def user_factory(client: TestClient) -> Callable[..., dict]:
    def create_user(username: str, nickname: str | None = None, password: str = "secret123") -> dict:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": username,
                "password": password,
                "nickname": nickname or username,
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()["data"]
        payload["password"] = password
        return payload

    return create_user


@pytest.fixture
def auth_header() -> Callable[[str], dict[str, str]]:
    def build(access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    return build

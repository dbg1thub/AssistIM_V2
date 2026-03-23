"""Infrastructure boundary tests."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute
from starlette.routing import WebSocketRoute

from app.core.config import Settings, reload_settings
from app.core.database import SessionLocal, configure_database, get_engine
from app.core.errors import ErrorCode
from app.core.rate_limit import InMemoryRateLimitStore, RateLimiter, RateLimitStore
from app.core.security import create_access_token, decode_access_token
from app.dependencies.settings_dependency import get_request_settings, get_websocket_settings
from app.main import create_app
from app.realtime.hub import InMemoryRealtimeHub
from app.websocket import presence_ws


class FakeRateLimitStore(RateLimitStore):
    def __init__(self, *, allow_result: bool) -> None:
        self.allow_result = allow_result
        self.calls: list[dict] = []
        self.reset_calls = 0

    def allow(self, key: str, *, limit: int, window_seconds: int, now: float) -> bool:
        self.calls.append(
            {
                "key": key,
                "limit": limit,
                "window_seconds": window_seconds,
                "now": now,
            }
        )
        return self.allow_result

    def reset(self) -> None:
        self.reset_calls += 1


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.sent_payloads: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.sent_payloads.append(dict(payload))


def test_reload_settings_rebuilds_from_current_environment() -> None:
    original_app_name = os.environ.get("APP_NAME")
    original_legacy_ws = os.environ.get("ENABLE_LEGACY_CHAT_WS")

    try:
        os.environ["APP_NAME"] = "AssistIM Runtime One"
        os.environ["ENABLE_LEGACY_CHAT_WS"] = "false"
        first = reload_settings()
        assert first.app_name == "AssistIM Runtime One"
        assert first.enable_legacy_chat_ws is False

        os.environ["APP_NAME"] = "AssistIM Runtime Two"
        os.environ["ENABLE_LEGACY_CHAT_WS"] = "true"
        second = reload_settings()
        assert second.app_name == "AssistIM Runtime Two"
        assert second.enable_legacy_chat_ws is True
    finally:
        if original_app_name is None:
            os.environ.pop("APP_NAME", None)
        else:
            os.environ["APP_NAME"] = original_app_name

        if original_legacy_ws is None:
            os.environ.pop("ENABLE_LEGACY_CHAT_WS", None)
        else:
            os.environ["ENABLE_LEGACY_CHAT_WS"] = original_legacy_ws

        reload_settings()



def test_security_helpers_use_explicit_settings_snapshot() -> None:
    custom_settings = Settings(secret_key="runtime-boundary-secret")
    token = create_access_token("user-1", "alice", settings=custom_settings)

    payload = decode_access_token(token, settings=custom_settings)
    assert payload["sub"] == "user-1"
    assert payload["username"] == "alice"

    with pytest.raises(Exception) as exc_info:
        decode_access_token(token, settings=reload_settings())
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED



def test_request_and_websocket_settings_resolve_app_snapshot() -> None:
    custom_settings = Settings(app_name="AssistIM Snapshot")
    app = SimpleNamespace(state=SimpleNamespace(settings=custom_settings))

    assert get_request_settings(SimpleNamespace(app=app)) is custom_settings
    assert get_websocket_settings(SimpleNamespace(app=app)) is custom_settings



def test_bind_websocket_user_uses_websocket_app_settings_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    custom_settings = Settings(secret_key="runtime-ws-secret")
    token = create_access_token("user-42", "alice", settings=custom_settings)
    websocket = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=custom_settings)),
        query_params={"token": token},
    )
    bindings: list[tuple[str, str]] = []

    monkeypatch.setattr(
        presence_ws.connection_manager,
        "bind_user",
        lambda connection_id, user_id: bindings.append((connection_id, user_id)),
    )

    user_id = presence_ws.bind_websocket_user(websocket, "conn-1")

    assert user_id == "user-42"
    assert bindings == [("conn-1", "user-42")]



def test_configure_database_rebinds_engine_and_session_factory() -> None:
    baseline_engine = get_engine()
    custom_db_path = Path("server/.testdata/runtime-boundary.db")
    custom_db_path.parent.mkdir(parents=True, exist_ok=True)
    custom_db_path.unlink(missing_ok=True)
    custom_settings = Settings(database_url=f"sqlite:///{custom_db_path.as_posix()}", debug=True)

    try:
        custom_engine = configure_database(custom_settings)
        assert custom_engine is configure_database(custom_settings)
        assert str(custom_engine.url).endswith("runtime-boundary.db")

        with SessionLocal() as db:
            assert db.bind is custom_engine
    finally:
        restored_settings = reload_settings()
        restored_engine = configure_database(restored_settings)
        assert restored_engine is get_engine()
        assert restored_engine is not None
        assert baseline_engine is not None
        custom_db_path.unlink(missing_ok=True)


def test_rate_limiter_delegates_to_store_and_reset() -> None:
    store = FakeRateLimitStore(allow_result=False)
    limiter = RateLimiter(store=store)
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))

    async def scenario() -> None:
        with pytest.raises(Exception) as exc_info:
            await limiter.dependency("login", 3, window_seconds=30)(request)

        assert exc_info.value.code == ErrorCode.RATE_LIMITED
        assert store.calls[0]["key"] == "login:127.0.0.1"
        assert store.calls[0]["limit"] == 3
        assert store.calls[0]["window_seconds"] == 30

    asyncio.run(scenario())
    limiter.reset()
    assert store.reset_calls == 1



def test_rate_limiter_dynamic_dependency_reads_current_limit_factory() -> None:
    limiter = RateLimiter(store=InMemoryRateLimitStore())
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    limit_state = {"value": 1}
    dependency = limiter.dynamic_dependency("login", lambda: limit_state["value"], window_seconds=30)

    async def scenario() -> None:
        await dependency(request)
        with pytest.raises(Exception) as exc_info:
            await dependency(request)
        assert exc_info.value.code == ErrorCode.RATE_LIMITED

        limiter.reset()
        limit_state["value"] = 2

        await dependency(request)
        await dependency(request)
        with pytest.raises(Exception) as exc_info:
            await dependency(request)
        assert exc_info.value.code == ErrorCode.RATE_LIMITED

    asyncio.run(scenario())



def test_rate_limiter_dynamic_dependency_accepts_request_aware_limit_factory() -> None:
    limiter = RateLimiter(store=InMemoryRateLimitStore())
    custom_settings = Settings(rate_limit_login=1)
    request = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        app=SimpleNamespace(state=SimpleNamespace(settings=custom_settings)),
    )
    dependency = limiter.dynamic_dependency(
        "login",
        lambda current_request: get_request_settings(current_request).rate_limit_login,
        window_seconds=30,
    )

    async def scenario() -> None:
        await dependency(request)
        with pytest.raises(Exception) as exc_info:
            await dependency(request)
        assert exc_info.value.code == ErrorCode.RATE_LIMITED

    asyncio.run(scenario())



def test_in_memory_rate_limit_store_is_resettable() -> None:
    store = InMemoryRateLimitStore()
    now = 100.0

    assert store.allow("login:127.0.0.1", limit=2, window_seconds=60, now=now) is True
    assert store.allow("login:127.0.0.1", limit=2, window_seconds=60, now=now + 1) is True
    assert store.allow("login:127.0.0.1", limit=2, window_seconds=60, now=now + 2) is False

    store.reset()

    assert store.allow("login:127.0.0.1", limit=2, window_seconds=60, now=now + 3) is True



def test_create_app_can_disable_legacy_chat_aliases() -> None:
    custom_db_path = Path("server/.testdata/runtime-aliases.db")
    custom_db_path.parent.mkdir(parents=True, exist_ok=True)
    custom_db_path.unlink(missing_ok=True)
    settings = Settings(
        database_url=f"sqlite:///{custom_db_path.as_posix()}",
        enable_legacy_chat_http=False,
        enable_legacy_chat_ws=False,
    )

    try:
        app = create_app(settings)
        http_paths = [route.path for route in app.routes if isinstance(route, APIRoute)]
        websocket_paths = [route.path for route in app.routes if isinstance(route, WebSocketRoute)]

        assert app.state.settings is settings
        assert "/ws" in websocket_paths
        assert "/ws/chat" not in websocket_paths
        assert "/ws/presence" in websocket_paths
        assert not any(path.startswith("/api/chat") for path in http_paths)
    finally:
        restored_settings = reload_settings()
        configure_database(restored_settings)
        custom_db_path.unlink(missing_ok=True)


def test_auth_routes_and_dependencies_use_app_settings_snapshot() -> None:
    custom_db_path = Path("server/.testdata/runtime-auth-boundary.db")
    upload_dir = Path("server/.testdata/runtime-auth-uploads")
    custom_db_path.parent.mkdir(parents=True, exist_ok=True)
    custom_db_path.unlink(missing_ok=True)
    shutil.rmtree(upload_dir, ignore_errors=True)
    custom_settings = Settings(
        database_url=f"sqlite:///{custom_db_path.as_posix()}",
        secret_key="runtime-auth-boundary-secret",
        upload_dir=upload_dir.as_posix(),
        enable_legacy_chat_http=False,
        enable_legacy_chat_ws=False,
    )

    try:
        app = create_app(custom_settings)
        assert app.state.settings is custom_settings

        with TestClient(app) as client:
            register_response = client.post(
                "/api/v1/auth/register",
                json={
                    "username": "boundary_user",
                    "password": "secret123",
                    "nickname": "Boundary User",
                },
            )
            assert register_response.status_code == 200
            access_token = register_response.json()["data"]["access_token"]

            me_response = client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert me_response.status_code == 200
            assert me_response.json()["data"]["username"] == "boundary_user"
    finally:
        restored_settings = reload_settings()
        configure_database(restored_settings)
        custom_db_path.unlink(missing_ok=True)
        shutil.rmtree(upload_dir, ignore_errors=True)


def test_in_memory_realtime_hub_tracks_presence_and_reset() -> None:
    async def scenario() -> None:
        hub = InMemoryRealtimeHub()
        websocket_a = FakeWebSocket()
        websocket_b = FakeWebSocket()

        connection_a = await hub.connect(websocket_a)
        connection_b = await hub.connect(websocket_b)
        hub.bind_user(connection_a, "alice")
        hub.bind_user(connection_b, "alice")

        assert websocket_a.accepted is True
        assert websocket_b.accepted is True
        assert hub.online_user_ids() == ["alice"]
        assert hub.has_user_connections("alice") is True

        delivered = await hub.send_json_to_users(["alice"], {"type": "ping"})
        assert delivered == {"alice"}
        assert websocket_a.sent_payloads == [{"type": "ping"}]
        assert websocket_b.sent_payloads == [{"type": "ping"}]

        user_id, became_offline = hub.disconnect_by_connection_id(connection_a)
        assert user_id == "alice"
        assert became_offline is False
        assert hub.has_user_connections("alice") is True

        user_id, became_offline = hub.disconnect_by_connection_id(connection_b)
        assert user_id == "alice"
        assert became_offline is True
        assert hub.online_user_ids() == []

        hub.reset()
        assert hub.online_user_ids() == []

    asyncio.run(scenario())

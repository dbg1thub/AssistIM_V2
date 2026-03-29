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
from app.core.database import Base, SessionLocal, configure_database, get_engine, init_db
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
    original_api_v1_prefix = os.environ.get("API_V1_PREFIX")

    try:
        os.environ["APP_NAME"] = "AssistIM Runtime One"
        os.environ["API_V1_PREFIX"] = "/api/v1"
        first = reload_settings()
        assert first.app_name == "AssistIM Runtime One"
        assert first.api_v1_prefix == "/api/v1"

        os.environ["APP_NAME"] = "AssistIM Runtime Two"
        os.environ["API_V1_PREFIX"] = "/runtime/v2"
        second = reload_settings()
        assert second.app_name == "AssistIM Runtime Two"
        assert second.api_v1_prefix == "/runtime/v2"
    finally:
        if original_app_name is None:
            os.environ.pop("APP_NAME", None)
        else:
            os.environ["APP_NAME"] = original_app_name

        if original_api_v1_prefix is None:
            os.environ.pop("API_V1_PREFIX", None)
        else:
            os.environ["API_V1_PREFIX"] = original_api_v1_prefix

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
    captured: dict[str, object] = {}

    def fake_require(token_value: str | None, *, settings: Settings) -> str:
        captured["token"] = token_value
        captured["settings"] = settings
        return "user-42"

    monkeypatch.setattr(
        presence_ws.connection_manager,
        "bind_user",
        lambda connection_id, user_id: bindings.append((connection_id, user_id)),
    )
    monkeypatch.setattr(presence_ws, "require_websocket_user_id", fake_require)

    user_id = presence_ws.bind_websocket_user(websocket, "conn-1")

    assert user_id == "user-42"
    assert captured == {"token": token, "settings": custom_settings}
    assert bindings == [("conn-1", "user-42")]



def test_presence_event_payload_uses_type_only() -> None:
    payload = presence_ws.event_payload("online", {"user_id": "alice"}, msg_id="msg-1")

    assert payload == {
        "type": "online",
        "seq": 0,
        "msg_id": "msg-1",
        "data": {"user_id": "alice"},
        "timestamp": payload["timestamp"],
    }
    assert "event" not in payload



def test_shared_ws_message_uses_type_only() -> None:
    from app.websocket.payloads import ws_message

    payload = ws_message("message_ack", {"ok": True}, msg_id="msg-2", seq=7)

    assert payload == {
        "type": "message_ack",
        "seq": 7,
        "msg_id": "msg-2",
        "timestamp": payload["timestamp"],
        "data": {"ok": True},
    }
    assert "event" not in payload




def test_message_service_event_message_id_uses_canonical_field_only() -> None:
    from app.services.message_service import MessageService

    assert MessageService._event_message_id("message_edit", {"message_id": "message-1", "msg_id": "legacy-1"}) == "message-1"
    assert MessageService._event_message_id("message_edit", {"msg_id": "legacy-1"}) == ""
    assert MessageService._event_message_id("read", {"message_id": "message-1", "last_read_message_id": "message-2"}) == "message-1"

def test_api_schema_models_use_canonical_session_and_friend_request_fields() -> None:
    from app.schemas.friend import FriendRequestOut
    from app.schemas.message import MessageOut
    from app.schemas.session import SessionOut

    assert "request_id" in FriendRequestOut.model_fields
    assert "id" not in FriendRequestOut.model_fields
    assert "session_type" in SessionOut.model_fields
    assert "type" not in SessionOut.model_fields
    assert "session_type" in MessageOut.model_fields
    assert "participant_ids" in MessageOut.model_fields
    assert "sender_profile" in MessageOut.model_fields
    assert "counterpart_avatar" in SessionOut.model_fields
    assert "counterpart_id" in SessionOut.model_fields
    assert "msg_id" not in MessageOut.model_fields
    assert "type" not in MessageOut.model_fields

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



def test_create_app_only_mounts_canonical_chat_endpoints() -> None:
    custom_db_path = Path("server/.testdata/runtime-aliases.db")
    custom_db_path.parent.mkdir(parents=True, exist_ok=True)
    custom_db_path.unlink(missing_ok=True)
    settings = Settings(database_url=f"sqlite:///{custom_db_path.as_posix()}")

    try:
        app = create_app(settings)
        http_routes = [route for route in app.routes if isinstance(route, APIRoute)]
        http_paths = [route.path for route in http_routes]
        http_route_methods = {
            (route.path, method)
            for route in http_routes
            for method in (route.methods or set())
        }
        websocket_paths = [route.path for route in app.routes if isinstance(route, WebSocketRoute)]

        assert app.state.settings is settings
        assert "/api/v1/auth/register" in http_paths
        assert "/api/v1/files/upload" in http_paths
        assert ("/api/v1/sessions", "GET") in http_route_methods
        assert ("/api/v1/sessions/direct", "POST") in http_route_methods
        assert ("/api/v1/sessions/group", "POST") not in http_route_methods
        assert "/api/v1/sessions/{session_id}/messages" in http_paths
        assert ("/api/v1/sessions", "POST") not in http_route_methods
        assert ("/api/v1/messages", "POST") not in http_route_methods
        assert ("/api/v1/messages/history", "GET") not in http_route_methods
        assert ("/api/v1/messages/read", "POST") not in http_route_methods
        assert ("/api/v1/messages/{message_id}/read", "POST") not in http_route_methods
        assert "/api/auth/register" not in http_paths
        assert "/api/v1/upload" not in http_paths
        assert "/api/upload" not in http_paths
        assert "/ws" in websocket_paths
        assert "/ws/chat" not in websocket_paths
        assert "/ws/presence" in websocket_paths
        assert not any(path.startswith("/api/chat") for path in http_paths)
    finally:
        restored_settings = reload_settings()
        configure_database(restored_settings)
        custom_db_path.unlink(missing_ok=True)
    settings = Settings(database_url=f"sqlite:///{custom_db_path.as_posix()}")

    try:
        app = create_app(settings)
        http_paths = [route.path for route in app.routes if isinstance(route, APIRoute)]
        websocket_paths = [route.path for route in app.routes if isinstance(route, WebSocketRoute)]

        assert app.state.settings is settings
        assert "/api/v1/auth/register" in http_paths
        assert "/api/v1/files/upload" in http_paths
        assert "/api/auth/register" not in http_paths
        assert "/api/v1/upload" not in http_paths
        assert "/api/upload" not in http_paths
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
    )

    try:
        engine = configure_database(custom_settings)
        Base.metadata.create_all(bind=engine)
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


def test_init_db_requires_existing_runtime_schema() -> None:
    custom_db_path = Path("server/.testdata/runtime-init-db-empty.db")
    custom_db_path.parent.mkdir(parents=True, exist_ok=True)
    custom_db_path.unlink(missing_ok=True)
    custom_settings = Settings(database_url=f"sqlite:///{custom_db_path.as_posix()}", debug=True)

    try:
        with pytest.raises(RuntimeError, match="alembic upgrade head"):
            init_db(custom_settings)
    finally:
        restored_settings = reload_settings()
        configure_database(restored_settings)
        custom_db_path.unlink(missing_ok=True)



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
def test_schema_compatibility_is_noop_for_current_runtime_schema() -> None:
    from app.core.database import Base
    from app.core.schema_compat import ensure_schema_compatibility
    from app.models import file, group, message, moment, session, user  # noqa: F401

    custom_db_path = Path("server/.testdata/runtime-schema-compat.db")
    custom_db_path.parent.mkdir(parents=True, exist_ok=True)
    custom_db_path.unlink(missing_ok=True)
    custom_settings = Settings(database_url=f"sqlite:///{custom_db_path.as_posix()}", debug=True)

    try:
        engine = configure_database(custom_settings)
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        assert ensure_schema_compatibility(engine) == []
    finally:
        restored_settings = reload_settings()
        configure_database(restored_settings)
        custom_db_path.unlink(missing_ok=True)



def test_sqlite_alembic_upgrade_head_succeeds() -> None:
    import subprocess
    import sys

    custom_db_path = Path("server/.testdata/runtime-alembic-upgrade.db")
    custom_db_path.parent.mkdir(parents=True, exist_ok=True)
    custom_db_path.unlink(missing_ok=True)
    server_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{custom_db_path.resolve().as_posix()}"

    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=server_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        custom_db_path.unlink(missing_ok=True)





def test_schema_compatibility_skips_runtime_checks_when_runtime_migration_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy import create_engine, text

    from app.core import schema_compat as schema_compat_module

    def _unexpected_runtime_schema_check(*_args, **_kwargs):
        raise AssertionError("runtime schema inspection should be skipped for migrated databases")

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": schema_compat_module.RUNTIME_SCHEMA_ALEMBIC_REVISION},
        )

    monkeypatch.setattr(schema_compat_module, "_has_current_runtime_schema", _unexpected_runtime_schema_check)

    try:
        assert schema_compat_module.ensure_schema_compatibility(engine) == []
    finally:
        engine.dispose()


def test_private_session_direct_key_backfill_uses_boolean_safe_coalesce() -> None:
    schema_compat = Path('server/app/core/schema_compat.py').read_text(encoding='utf-8')
    migration = Path('server/alembic/versions/20260329_0005_private_session_direct_key.py').read_text(encoding='utf-8')

    assert 'COALESCE(is_ai_session, 0)' not in schema_compat
    assert 'COALESCE(is_ai_session, 0)' not in migration
    assert 'COALESCE(is_ai_session, FALSE)' in schema_compat
    assert 'COALESCE(is_ai_session, FALSE)' in migration


def test_svg_rasterizer_converts_default_avatar_to_png() -> None:
    from app.media.svg_rasterizer import ensure_rasterized_svg

    cache_dir = Path("server/.testdata/svg-raster-cache")
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    svg_path = Path("client/resources/avatars/avatar_default_female_01.svg").resolve()
    raster_path = ensure_rasterized_svg(svg_path, cache_dir, size=128)

    assert raster_path is not None
    assert raster_path.is_file()
    assert raster_path.suffix == ".png"
    assert raster_path.read_bytes().startswith(b"\x89PNG")





def test_schema_compatibility_backfills_avatar_columns_for_legacy_runtime_schema() -> None:
    from sqlalchemy import create_engine, inspect, text

    from app.core import schema_compat as schema_compat_module

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, username VARCHAR(255), password_hash VARCHAR(255), nickname VARCHAR(255), avatar VARCHAR(255), status VARCHAR(32), created_at TIMESTAMP, updated_at TIMESTAMP)"))
        connection.execute(text("CREATE TABLE messages (id VARCHAR(36) PRIMARY KEY, session_id VARCHAR(36), sender_id VARCHAR(36), content TEXT, type VARCHAR(32), status VARCHAR(32), created_at TIMESTAMP, updated_at TIMESTAMP)"))
        connection.execute(text("CREATE TABLE sessions (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255), type VARCHAR(32), avatar VARCHAR(255), is_ai_session BOOLEAN, created_at TIMESTAMP, updated_at TIMESTAMP)"))
        connection.execute(text("CREATE TABLE session_members (session_id VARCHAR(36), user_id VARCHAR(36), joined_at TIMESTAMP)"))
        connection.execute(text("CREATE TABLE files (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36), file_url VARCHAR(255), file_name VARCHAR(255), file_type VARCHAR(255), created_at TIMESTAMP, updated_at TIMESTAMP)"))
        connection.execute(text("CREATE TABLE session_events (id VARCHAR(36) PRIMARY KEY, session_id VARCHAR(36), type VARCHAR(32), payload TEXT, event_seq INTEGER, created_at TIMESTAMP, updated_at TIMESTAMP)"))
        connection.execute(text("CREATE TABLE groups (id VARCHAR(36) PRIMARY KEY, session_id VARCHAR(36), owner_id VARCHAR(36), name VARCHAR(255), created_at TIMESTAMP, updated_at TIMESTAMP)"))
        connection.execute(text("INSERT INTO users (id, username, password_hash, nickname, avatar, status) VALUES ('user-1', 'legacy', 'hash', 'Legacy', NULL, 'offline')"))

    applied = schema_compat_module.ensure_schema_compatibility(engine)
    columns_by_table = {
        table_name: {column["name"] for column in inspect(engine).get_columns(table_name)}
        for table_name in ["users", "groups"]
    }

    assert "users.avatar_kind" in applied
    assert "users.avatar_default_key" in applied
    assert "users.avatar_file_id" in applied
    assert "groups.avatar_kind" in applied
    assert "groups.avatar_file_id" in applied
    assert "groups.avatar_version" in applied
    assert {"avatar_kind", "avatar_default_key", "avatar_file_id"}.issubset(columns_by_table["users"])
    assert {"avatar_kind", "avatar_file_id", "avatar_version"}.issubset(columns_by_table["groups"])

    with engine.begin() as connection:
        user_row = connection.execute(text("SELECT avatar_kind, avatar_default_key FROM users WHERE id = 'user-1'")) .mappings().one()
    assert user_row["avatar_kind"] == "default"
    assert str(user_row["avatar_default_key"] or "") != ""

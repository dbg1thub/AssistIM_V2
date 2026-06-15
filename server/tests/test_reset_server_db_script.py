"""Reset-server database script boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.database import SessionLocal
from app.core.security import verify_password
from app.models.user import User
from app.repositories.user_repo import UserRepository


def test_seed_test_users_creates_expected_initial_users() -> None:
    from app.ops.seed_test_users import DEFAULT_TEST_PASSWORD, TEST_USER_SPECS, seed_test_users

    with SessionLocal() as db:
        result = seed_test_users(db)
        users = UserRepository(db)

        assert [item["username"] for item in result] == [item.username for item in TEST_USER_SPECS]
        assert [item["nickname"] for item in result] == [item.nickname for item in TEST_USER_SPECS]

        for spec in TEST_USER_SPECS:
            user = users.get_by_username(spec.username)
            assert user is not None
            assert user.nickname == spec.nickname
            assert user.email == spec.email
            assert user.email_verified is True
            assert user.avatar_kind == "generated"
            assert str(user.avatar or "").startswith("/uploads/generated_avatars/")
            assert user.auth_session_version == 1
            assert verify_password(DEFAULT_TEST_PASSWORD, user.password_hash)


def test_seed_test_users_fails_when_database_is_not_fresh() -> None:
    from app.ops.seed_test_users import seed_test_users

    with SessionLocal() as db:
        seed_test_users(db)

    with SessionLocal() as db:
        with pytest.raises(RuntimeError, match="already exists"):
            seed_test_users(db)


def test_regenerate_generated_avatars_rewrites_existing_generated_avatar_url() -> None:
    from app.ops.regenerate_generated_avatars import regenerate_generated_user_avatars

    old_avatar = "/uploads/generated_avatars/user-1_legacy.png"
    with SessionLocal() as db:
        user = User(
            username="regen-avatar",
            password_hash="hash",
            nickname="邓斌",
            avatar_kind="generated",
            avatar=old_avatar,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = str(user.id)

        result = regenerate_generated_user_avatars(db)
        db.refresh(user)

        assert result == [
            {
                "id": user_id,
                "username": "regen-avatar",
                "nickname": "邓斌",
                "old_avatar": old_avatar,
                "new_avatar": user.avatar,
            }
        ]
        assert user.avatar_kind == "generated"
        assert str(user.avatar or "").startswith("/uploads/generated_avatars/")
        assert user.avatar != old_avatar


def test_reset_server_db_script_is_ubuntu_bash_with_explicit_confirmation() -> None:
    script = Path("server/scripts/reset-server-db.sh").read_text(encoding="utf-8")

    assert script.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in script
    assert "--confirm-reset" in script
    assert "CONFIRM_RESET" in script
    assert "APP_ROOT=" in script
    assert "select_default_env_file" in script
    assert '"${SERVER_ROOT}/.env" "${APP_ROOT}/deploy/docker/server.env"' in script
    assert "resolve_file_path" in script
    assert '"${PWD}/${raw_path}" "${APP_ROOT}/${raw_path}" "${SERVER_ROOT}/${raw_path}"' in script
    assert "alembic upgrade head" in script
    assert "app.ops.seed_test_users" in script
    assert "DROP DATABASE IF EXISTS" in script
    assert "pg_terminate_backend" in script
    assert "--compose-file PATH" in script
    assert "has_docker_compose_database_config" in script
    assert "run_docker_compose_reset" in script
    assert "local -a dc" in script
    assert 'docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE"' in script
    assert '"${dc[@]}" up -d postgres' in script
    assert 'DATABASE_URL is not set and Docker Compose database settings were not found' in script


def test_reset_local_db_script_is_powershell_with_local_guard() -> None:
    script = Path("server/scripts/reset-local-db.ps1").read_text(encoding="utf-8")

    assert "param(" in script
    assert "[switch]$ConfirmReset" in script
    assert "Assert-LocalDatabaseHost" in script
    assert "localhost" in script
    assert "127.0.0.1" in script
    assert "::1" in script
    assert "Resolve-PythonPath" in script
    assert "Get-PsqlPath" in script
    assert "'alembic', 'upgrade', 'head'" in script
    assert "app.ops.seed_test_users" in script
    assert "DROP DATABASE IF EXISTS" in script
    assert "pg_terminate_backend" in script

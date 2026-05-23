from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.errors import AppError, ErrorCode
from app.services.avatar_service import AvatarService


class _MissingFileRepo:
    def get_by_id(self, file_id: str):
        assert file_id == "missing-file"
        return None


class _RecordingUserRepo:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def update_avatar_state(self, user, **kwargs):
        self.calls.append({"user": user, **kwargs})
        return user


def test_backfill_user_avatar_state_keeps_missing_custom_avatar_stable() -> None:
    service = AvatarService(db=None)
    service.files = _MissingFileRepo()
    service.users = _RecordingUserRepo()

    user = SimpleNamespace(
        id="user-1",
        username="alice",
        avatar_kind="custom",
        avatar_file_id="missing-file",
        avatar="/uploads/missing.png",
        gender="female",
    )

    result = service.backfill_user_avatar_state(user, commit=False)

    assert result is user
    assert service.users.calls == []


def test_assign_generated_user_avatar_raises_internal_error_when_avatar_write_fails(monkeypatch) -> None:
    service = AvatarService(db=None)
    user = SimpleNamespace(id="user-1", username="alice", nickname="Alice")

    monkeypatch.setattr("app.services.avatar_service.build_generated_user_avatar", lambda *args, **kwargs: "")

    with pytest.raises(AppError) as exc_info:
        service.assign_generated_user_avatar(user, nickname="Alice", commit=False)

    assert exc_info.value.code == ErrorCode.INTERNAL_ERROR
    assert exc_info.value.status_code == 500
    assert exc_info.value.message == "generated avatar write failed"


def test_assign_generated_user_avatar_propagates_commit_flag(monkeypatch) -> None:
    service = AvatarService(db=None)
    user = SimpleNamespace(id="user-1", username="alice", nickname="Alice")
    recorded: dict[str, object] = {}

    monkeypatch.setattr("app.services.avatar_service.build_generated_user_avatar", lambda *args, **kwargs: "/uploads/generated_avatars/user-1.png")

    def fake_set_user_generated_avatar(target_user, *, avatar_url: str, commit: bool = True):
        recorded["user"] = target_user
        recorded["avatar_url"] = avatar_url
        recorded["commit"] = commit
        return target_user

    monkeypatch.setattr(service, "set_user_generated_avatar", fake_set_user_generated_avatar)

    result = service.assign_generated_user_avatar(user, nickname="Alice", commit=False)

    assert result is user
    assert recorded == {
        "user": user,
        "avatar_url": "/uploads/generated_avatars/user-1.png",
        "commit": False,
    }

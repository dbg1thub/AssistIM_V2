from __future__ import annotations

from types import SimpleNamespace

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
        avatar_default_key="",
        avatar_file_id="missing-file",
        avatar="/uploads/missing.png",
        gender="female",
    )

    result = service.backfill_user_avatar_state(user, commit=False)

    assert result is user
    assert service.users.calls == []

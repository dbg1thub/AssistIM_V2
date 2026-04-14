"""Avatar domain service."""

from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.media.default_avatars import (
    choose_random_default_avatar_key,
    choose_seeded_default_avatar_key,
    default_avatar_key_from_url,
    default_avatar_url,
)
from app.media.group_avatars import build_group_avatar, group_avatar_public_url, group_avatar_storage_key
from app.models.file import StoredFile
from app.models.group import Group
from app.models.user import User
from app.repositories.file_repo import FileRepository
from app.repositories.group_repo import GroupRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.user_repo import UserRepository
from app.services.file_service import FileService


class AvatarService:
    """Own default-avatar assignment, custom avatar uploads, and generated group avatars."""

    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.files = FileRepository(db)
        self.users = UserRepository(db)
        self.groups = GroupRepository(db)
        self.sessions = SessionRepository(db)

    def assign_default_user_avatar(self, user: User, *, seed: object = "", gender: object = "", commit: bool = True) -> User:
        """Assign one persisted formal default avatar to a user."""
        default_key = choose_seeded_default_avatar_key(seed, gender=gender) or choose_random_default_avatar_key(gender)
        if not default_key:
            raise AppError(ErrorCode.SERVER_ERROR, "default avatar assets unavailable", 500)
        return self.set_user_default_avatar(user, default_key=default_key)

    def backfill_user_avatar_state(self, user: User, *, commit: bool = True) -> User:
        """Normalize one legacy user row into the new avatar state model."""
        avatar_kind = str(getattr(user, "avatar_kind", "") or "").strip().lower()
        avatar_default_key = str(getattr(user, "avatar_default_key", "") or "").strip()
        avatar_file_id = str(getattr(user, "avatar_file_id", "") or "").strip()
        avatar_value = str(getattr(user, "avatar", "") or "").strip()

        if avatar_kind == "custom" and avatar_file_id:
            stored = self.files.get_by_id(avatar_file_id)
            if stored is not None:
                return self.users.update_avatar_state(
                    user,
                    avatar_kind="custom",
                    avatar_default_key=avatar_default_key or None,
                    avatar_file_id=stored.id,
                    avatar=stored.file_url,
                    commit=commit,
                )

        inferred_default_key = avatar_default_key or default_avatar_key_from_url(avatar_value)
        if inferred_default_key:
            return self.users.update_avatar_state(
                user,
                avatar_kind="default",
                avatar_default_key=inferred_default_key,
                avatar_file_id=None,
                avatar=default_avatar_url(self.settings, inferred_default_key),
            )

        if avatar_value:
            return self.users.update_avatar_state(
                user,
                avatar_kind="custom",
                avatar_default_key=avatar_default_key or None,
                avatar_file_id=avatar_file_id or None,
                avatar=avatar_value,
            )

        return self.assign_default_user_avatar(
            user,
            seed=getattr(user, "id", "") or getattr(user, "username", ""),
            gender=getattr(user, "gender", ""),
            commit=commit,
        )

    def set_user_default_avatar(self, user: User, *, default_key: str, commit: bool = True) -> User:
        """Switch one user back to the assigned default avatar."""
        avatar_url = default_avatar_url(self.settings, default_key)
        if not avatar_url:
            raise AppError(ErrorCode.INVALID_REQUEST, "invalid default avatar key", 422)
        updated = self.users.update_avatar_state(
            user,
            avatar_kind="default",
            avatar_default_key=default_key,
            avatar_file_id=None,
            avatar=avatar_url,
            commit=commit,
        )
        self._refresh_generated_group_avatars_for_user(updated.id)
        return updated

    def reset_user_avatar(self, user: User) -> User:
        """Reset one user to the persisted formal default avatar."""
        default_key = str(getattr(user, "avatar_default_key", "") or "").strip()
        if not default_key:
            return self.assign_default_user_avatar(
                user,
                seed=getattr(user, "id", "") or getattr(user, "username", ""),
                gender=getattr(user, "gender", ""),
            )
        return self.set_user_default_avatar(user, default_key=default_key)

    def upload_user_avatar(self, user: User, file: UploadFile) -> User:
        """Persist one custom profile avatar and bind it to the user."""
        self._validate_avatar_upload(file)
        stored = FileService(self.db, self.settings).save_upload_record(user, file)
        updated = self.users.update_avatar_state(
            user,
            avatar_kind="custom",
            avatar_default_key=str(getattr(user, "avatar_default_key", "") or "") or None,
            avatar_file_id=stored.id,
            avatar=stored.file_url,
        )
        self._refresh_generated_group_avatars_for_user(updated.id)
        return updated

    def resolve_user_avatar_url(self, user: User) -> str | None:
        """Return the effective public avatar URL for one user."""
        avatar_kind = str(getattr(user, "avatar_kind", "default") or "default").strip().lower()
        avatar_default_key = str(getattr(user, "avatar_default_key", "") or "").strip()
        avatar_value = str(getattr(user, "avatar", "") or "").strip()
        avatar_file_id = str(getattr(user, "avatar_file_id", "") or "").strip()

        if avatar_kind == "custom" and avatar_file_id:
            stored = self.files.get_by_id(avatar_file_id)
            if stored is not None:
                return stored.file_url
        if avatar_kind == "default" and avatar_default_key:
            return default_avatar_url(self.settings, avatar_default_key)
        return avatar_value or None

    def ensure_group_avatar(self, group: Group) -> str | None:
        """Ensure one group has a generated avatar and mirror it to the session."""
        avatar_kind = str(getattr(group, "avatar_kind", "generated") or "generated").strip().lower()
        if avatar_kind == "custom":
            stored = self.files.get_by_id(str(getattr(group, "avatar_file_id", "") or ""))
            avatar_url = stored.file_url if stored is not None else None
        else:
            members = self._group_member_avatar_payload(group)
            avatar_url = build_group_avatar(
                self.settings,
                group_id=group.id,
                version=int(getattr(group, "avatar_version", 1) or 1),
                group_name=group.name,
                members=members,
            )
        self.sessions.update_avatar(group.session_id, avatar_url, commit=False)
        if avatar_kind != "custom":
            self._prune_generated_group_avatar_versions(group)
        return avatar_url

    def resolve_group_avatar_url(self, group: Group) -> str | None:
        """Return the current group avatar URL without file I/O or DB writes."""
        avatar_kind = str(getattr(group, "avatar_kind", "generated") or "generated").strip().lower()
        if avatar_kind == "custom":
            stored = self.files.get_by_id(str(getattr(group, "avatar_file_id", "") or ""))
            return stored.file_url if stored is not None else None
        return group_avatar_public_url(
            self.settings,
            str(getattr(group, "id", "") or ""),
            int(getattr(group, "avatar_version", 1) or 1),
        )

    def bump_group_avatar_version(self, group: Group) -> Group:
        """Bump one generated group avatar version after membership changes."""
        avatar_kind = str(getattr(group, "avatar_kind", "generated") or "generated").strip().lower()
        if avatar_kind != "generated":
            return group
        return self.groups.update_avatar_state(
            group,
            avatar_kind="generated",
            avatar_file_id=str(getattr(group, "avatar_file_id", "") or "") or None,
            avatar_version=max(1, int(getattr(group, "avatar_version", 1) or 1)) + 1,
            commit=False,
        )

    def _group_member_avatar_payload(self, group: Group) -> list[dict[str, str]]:
        session_members = self.sessions.list_members(group.session_id)
        user_ids = [str(item.user_id or "") for item in session_members if str(item.user_id or "")]
        users_by_id = self.users.list_users_by_ids(user_ids)
        members: list[dict[str, str]] = []
        for session_member in session_members:
            user = users_by_id.get(str(session_member.user_id or ""))
            if user is None:
                continue
            members.append(
                {
                    "id": user.id,
                    "nickname": user.nickname,
                    "username": user.username,
                    "avatar": self.resolve_user_avatar_url(user) or "",
                    "gender": str(user.gender or ""),
                }
            )
        return members

    def _refresh_generated_group_avatars_for_user(self, user_id: str, *, commit: bool = True) -> None:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return

        touched = False
        for group in self.groups.list_user_groups(normalized_user_id):
            avatar_kind = str(getattr(group, "avatar_kind", "generated") or "generated").strip().lower()
            if avatar_kind != "generated":
                continue
            self.bump_group_avatar_version(group)
            self.ensure_group_avatar(group)
            touched = True

        if touched and commit:
            self.db.commit()

    def cleanup_group_avatar_assets(self, group: Group) -> None:
        """Remove generated group avatar files owned by a deleted group."""
        self._prune_generated_group_avatar_versions(group, keep_current=False)

    def _prune_generated_group_avatar_versions(self, group: Group, *, keep_current: bool = True) -> None:
        avatar_kind = str(getattr(group, "avatar_kind", "generated") or "generated").strip().lower()
        if avatar_kind != "generated":
            return
        group_id = str(getattr(group, "id", "") or "").strip()
        if not group_id:
            return
        current_version = max(1, int(getattr(group, "avatar_version", 1) or 1))
        avatar_dir = Path(self.settings.upload_dir) / "group_avatars"
        if not avatar_dir.exists():
            return
        keep_name = Path(group_avatar_storage_key(group_id, current_version)).name if keep_current else ""
        for path in avatar_dir.glob(f"{group_id}_v*.png"):
            if keep_name and path.name == keep_name:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue

    @staticmethod
    def _validate_avatar_upload(file: UploadFile) -> None:
        content_type = str(getattr(file, "content_type", "") or "").strip().lower()
        filename = Path(str(getattr(file, "filename", "") or "upload.bin"))
        extension = filename.suffix.lower()
        if not content_type.startswith("image/"):
            raise AppError(ErrorCode.INVALID_REQUEST, "avatar upload must be an image", 422)
        if extension not in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}:
            raise AppError(ErrorCode.INVALID_REQUEST, "unsupported avatar image format", 422)

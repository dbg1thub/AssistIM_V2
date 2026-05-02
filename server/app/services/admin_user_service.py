"""Admin user-management service primitives."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.dependencies.admin_dependency import ROLE_ADMIN, validate_user_role
from app.models.device import UserDevice
from app.models.file import StoredFile
from app.models.session import SessionMember
from app.models.user import Friendship, User
from app.repositories.user_repo import UserRepository
from app.services.admin_audit_service import AdminAuditService
from app.services.avatar_service import AvatarService
from app.utils.time import isoformat_utc, utcnow


class AdminUserService:
    """Controlled user-management operations for admin tooling."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.audit = AdminAuditService(db)
        self.avatars = AvatarService(db)

    def list_users(
        self,
        *,
        keyword: str = "",
        role: str = "",
        disabled: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        normalized_page = max(1, int(page or 1))
        normalized_size = min(100, max(1, int(size or 20)))
        filters = self._user_filters(keyword=keyword, role=role, disabled=disabled)

        total = self.db.execute(select(func.count()).select_from(User).where(*filters)).scalar_one()
        statement = (
            select(User)
            .where(*filters)
            .order_by(User.created_at.desc(), User.id.desc())
            .offset((normalized_page - 1) * normalized_size)
            .limit(normalized_size)
        )
        users = list(self.db.execute(statement).scalars().all())
        return {
            "total": int(total or 0),
            "page": normalized_page,
            "size": normalized_size,
            "items": [self.serialize_admin_user(user) for user in users],
        }

    def get_user_detail(self, user_id: str) -> dict:
        user = self._get_target_user(user_id)
        payload = self.serialize_admin_user(user)
        payload["counts"] = {
            "devices": self._count(UserDevice, UserDevice.user_id == user.id),
            "sessions": self._count(SessionMember, SessionMember.user_id == user.id),
            "friends": self._count(
                Friendship,
                or_(Friendship.user_id == user.id, Friendship.friend_id == user.id),
            ),
            "files": self._count(StoredFile, StoredFile.user_id == user.id),
        }
        payload["devices"] = [self._serialize_device(device) for device in self._list_user_devices(str(user.id or ""))]
        return payload

    def set_user_role_by_id(
        self,
        user_id: str,
        role: str,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict:
        normalized_role = validate_user_role(role)
        user = self._get_target_user(user_id)
        if str(actor.id or "") == str(user.id or "") and normalized_role != ROLE_ADMIN:
            raise AppError(ErrorCode.FORBIDDEN, "cannot remove your own admin role", 403)

        old_role = self._normalize_role(getattr(user, "role", "user"))
        self.users.update(user, role=normalized_role, commit=False)
        self.audit.record(
            actor=actor,
            action="admin.user.role.set",
            target_type="user",
            target_id=str(user.id or ""),
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "username": str(user.username or ""),
                "old_role": old_role,
                "new_role": normalized_role,
            },
            commit=False,
        )
        self.db.commit()
        self.db.refresh(user)
        return self.serialize_admin_user(user)

    def disable_user(
        self,
        user_id: str,
        *,
        actor: User,
        reason: str = "",
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict:
        user = self._get_target_user(user_id)
        if str(actor.id or "") == str(user.id or ""):
            raise AppError(ErrorCode.FORBIDDEN, "cannot disable your own account", 403)

        normalized_reason = str(reason or "").strip()
        self.users.update(
            user,
            is_disabled=True,
            disabled_at=utcnow(),
            disabled_reason=normalized_reason,
            commit=False,
        )
        self.users.advance_auth_session_version(user, commit=False)
        self.audit.record(
            actor=actor,
            action="admin.user.disable",
            target_type="user",
            target_id=str(user.id or ""),
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "username": str(user.username or ""),
                "reason": normalized_reason,
            },
            commit=False,
        )
        self.db.commit()
        self.db.refresh(user)
        return self.serialize_admin_user(user)

    def enable_user(
        self,
        user_id: str,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict:
        user = self._get_target_user(user_id)
        self.users.update(
            user,
            is_disabled=False,
            disabled_at=None,
            disabled_reason="",
            commit=False,
        )
        self.audit.record(
            actor=actor,
            action="admin.user.enable",
            target_type="user",
            target_id=str(user.id or ""),
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"username": str(user.username or "")},
            commit=False,
        )
        self.db.commit()
        self.db.refresh(user)
        return self.serialize_admin_user(user)

    def force_logout_user(
        self,
        user_id: str,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict:
        user = self._get_target_user(user_id)
        self.users.advance_auth_session_version(user, commit=False)
        self.audit.record(
            actor=actor,
            action="admin.user.force_logout",
            target_type="user",
            target_id=str(user.id or ""),
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"username": str(user.username or "")},
            commit=False,
        )
        self.db.commit()
        self.db.refresh(user)
        return {
            "user_id": str(user.id or ""),
            "username": str(user.username or ""),
        }

    def set_user_role_by_username(
        self,
        username: str,
        role: str,
        *,
        actor_user_id: str | None = None,
        actor_username: str,
    ) -> dict:
        normalized_role = validate_user_role(role)
        user = self.users.get_by_username(username)
        if user is None:
            raise AppError(ErrorCode.USER_NOT_FOUND, "user not found", 404)

        old_role = str(getattr(user, "role", "user") or "user").strip().lower() or "user"
        self.users.update(user, role=normalized_role, commit=False)
        self.audit.record(
            actor_user_id=actor_user_id,
            actor_username=actor_username,
            action="admin.user.role.set",
            target_type="user",
            target_id=str(user.id or ""),
            success=True,
            detail={
                "username": str(user.username or ""),
                "old_role": old_role,
                "new_role": normalized_role,
            },
            commit=False,
        )
        self.db.commit()
        self.db.refresh(user)
        return {
            "user_id": str(user.id or ""),
            "username": str(user.username or ""),
            "old_role": old_role,
            "new_role": normalized_role,
        }

    def serialize_admin_user(self, user: User) -> dict:
        nickname = str(user.nickname or "")
        username = str(user.username or "")
        return {
            "id": str(user.id or ""),
            "username": username,
            "nickname": nickname,
            "display_name": nickname or username or str(user.id or ""),
            "avatar": self.avatars.resolve_user_avatar_url(user),
            "avatar_kind": str(getattr(user, "avatar_kind", "default") or "default"),
            "email": user.email,
            "phone": user.phone,
            "birthday": user.birthday.isoformat() if user.birthday else None,
            "region": user.region,
            "signature": user.signature,
            "gender": user.gender,
            "status": user.status,
            "role": self._normalize_role(getattr(user, "role", "user")),
            "is_disabled": bool(getattr(user, "is_disabled", False)),
            "disabled_at": isoformat_utc(getattr(user, "disabled_at", None)),
            "disabled_reason": str(getattr(user, "disabled_reason", "") or ""),
            "created_at": isoformat_utc(user.created_at),
            "updated_at": isoformat_utc(user.updated_at),
        }

    def _user_filters(self, *, keyword: str, role: str, disabled: bool | None) -> list:
        filters = []
        normalized_keyword = str(keyword or "").strip().lower()
        if normalized_keyword:
            pattern = f"%{normalized_keyword}%"
            filters.append(
                or_(
                    func.lower(User.username).like(pattern),
                    func.lower(func.coalesce(User.nickname, "")).like(pattern),
                    func.lower(func.coalesce(User.email, "")).like(pattern),
                    func.lower(func.coalesce(User.phone, "")).like(pattern),
                )
            )

        normalized_role = str(role or "").strip().lower()
        if normalized_role:
            try:
                normalized_role = validate_user_role(normalized_role)
            except ValueError as exc:
                raise AppError(ErrorCode.INVALID_REQUEST, str(exc), 422) from exc
            filters.append(User.role == normalized_role)

        if disabled is not None:
            filters.append(User.is_disabled.is_(bool(disabled)))

        return filters

    def _get_target_user(self, user_id: str) -> User:
        normalized_user_id = str(user_id or "").strip()
        user = self.users.get_by_id(normalized_user_id)
        if user is None:
            raise AppError(ErrorCode.USER_NOT_FOUND, "user not found", 404)
        return user

    def _count(self, model, *criteria) -> int:
        statement = select(func.count()).select_from(model)
        for condition in criteria:
            statement = statement.where(condition)
        return int(self.db.execute(statement).scalar_one() or 0)

    def _list_user_devices(self, user_id: str) -> list[UserDevice]:
        statement = (
            select(UserDevice)
            .where(UserDevice.user_id == user_id)
            .order_by(UserDevice.created_at.desc(), UserDevice.device_id.asc())
        )
        return list(self.db.execute(statement).scalars().all())

    def _serialize_device(self, device: UserDevice) -> dict:
        return {
            "device_id": str(device.device_id or ""),
            "device_name": str(device.device_name or ""),
            "is_active": bool(device.is_active),
            "last_seen_at": isoformat_utc(device.last_seen_at),
            "created_at": isoformat_utc(device.created_at),
            "updated_at": isoformat_utc(device.updated_at),
        }

    def _normalize_role(self, role: object) -> str:
        value = str(role or "user").strip().lower()
        return value or "user"

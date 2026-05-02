"""Admin user-management service primitives."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.dependencies.admin_dependency import validate_user_role
from app.repositories.user_repo import UserRepository
from app.services.admin_audit_service import AdminAuditService


class AdminUserService:
    """Controlled user-management operations for admin tooling."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.audit = AdminAuditService(db)

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

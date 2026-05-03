"""Admin authentication and account-security inspection service."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.dependencies.admin_dependency import VALID_USER_ROLES, normalize_user_role
from app.models.admin import AdminAuditLog
from app.models.user import User
from app.services.admin_audit_service import AdminAuditService
from app.websocket.manager import connection_manager


AUTH_RELATED_AUDIT_ACTIONS = (
    "admin.user.disable",
    "admin.user.enable",
    "admin.user.force_logout",
    "admin.user.role.set",
    "admin.auth.status.read",
    "admin.auth.health.read",
)


class AdminAuthInspectionService:
    """Read-only auth configuration and account integrity checks for admin tooling."""

    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.audit = AdminAuditService(db)

    def build_status(
        self,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        users = list(self.db.execute(select(User)).scalars().all())
        realtime = connection_manager.snapshot()
        recent_auth_actions = self._recent_auth_action_counts()
        payload = {
            "token": {
                "token_storage": "stateless_jwt",
                "access_token_expire_minutes": int(self.settings.access_token_expire_minutes or 0),
                "refresh_token_expire_days": int(self.settings.refresh_token_expire_days or 0),
            },
            "session": {
                "invalidation_strategy": "auth_session_version",
                "server_persisted_sessions": False,
                "refresh_tokens_persisted": False,
            },
            "users": self._user_counts(users),
            "runtime": {
                "online_users": int(realtime.get("online_users", 0) or 0),
                "bound_connections": int(realtime.get("bound_connections", 0) or 0),
                "raw_connections": int(realtime.get("raw_connections", 0) or 0),
            },
            "audit": {
                "tracked_actions": list(AUTH_RELATED_AUDIT_ACTIONS),
                "recent_auth_audit_logs": sum(recent_auth_actions.values()),
                "recent_auth_actions": dict(sorted(recent_auth_actions.items())),
            },
        }
        self.audit.record(
            actor=actor,
            action="admin.auth.status.read",
            target_type="auth_status",
            target_id="status",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "users": payload["users"]["total"],
                "admins": payload["users"]["admins"],
                "online_users": payload["runtime"]["online_users"],
            },
        )
        return payload

    def build_health(
        self,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        users = list(self.db.execute(select(User)).scalars().all())
        online_user_ids = self._online_user_ids()
        issues = self._health_issues(users=users, online_user_ids=online_user_ids)
        counts = self._user_counts(users)
        payload = {
            "status": "ok" if not issues else "warning",
            "issue_count": len(issues),
            "issues": issues,
            "checks": {
                "users": counts["total"],
                "admins": counts["admins"],
                "enabled_admins": counts["enabled_admins"],
                "disabled_users": counts["disabled"],
                "online_users": len(online_user_ids),
                "disabled_users_online": sum(
                    1
                    for user in users
                    if bool(getattr(user, "is_disabled", False)) and str(user.id or "") in online_user_ids
                ),
                "invalid_roles": sum(
                    1
                    for user in users
                    if normalize_user_role(getattr(user, "role", "user")) not in VALID_USER_ROLES
                ),
                "empty_password_credentials": sum(
                    1 for user in users if not str(getattr(user, "password_hash", "") or "").strip()
                ),
                "invalid_session_versions": sum(
                    1 for user in users if self._session_version(user) < 0
                ),
            },
        }
        self.audit.record(
            actor=actor,
            action="admin.auth.health.read",
            target_type="auth_health",
            target_id="health",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"status": payload["status"], "issue_count": len(issues)},
        )
        return payload

    def _user_counts(self, users: list[User]) -> dict[str, int]:
        admins = [
            user
            for user in users
            if normalize_user_role(getattr(user, "role", "user")) == "admin"
        ]
        return {
            "total": len(users),
            "admins": len(admins),
            "enabled_admins": sum(1 for user in admins if not bool(getattr(user, "is_disabled", False))),
            "disabled_admins": sum(1 for user in admins if bool(getattr(user, "is_disabled", False))),
            "disabled": sum(1 for user in users if bool(getattr(user, "is_disabled", False))),
        }

    def _recent_auth_action_counts(self) -> Counter[str]:
        rows = (
            self.db.execute(
                select(AdminAuditLog.action)
                .where(AdminAuditLog.action.in_(AUTH_RELATED_AUDIT_ACTIONS))
                .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
                .limit(50)
            )
            .scalars()
            .all()
        )
        return Counter(str(action or "") for action in rows if str(action or ""))

    def _health_issues(self, *, users: list[User], online_user_ids: set[str]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        admins = [
            user
            for user in users
            if normalize_user_role(getattr(user, "role", "user")) == "admin"
        ]
        if not admins:
            issues.append(self._issue("auth_no_admin_user", severity="error"))
        elif not any(not bool(getattr(user, "is_disabled", False)) for user in admins):
            issues.append(self._issue("auth_all_admins_disabled", severity="error"))

        for user in users:
            user_id = str(user.id or "")
            username = str(user.username or "")
            role = normalize_user_role(getattr(user, "role", "user"))
            if role not in VALID_USER_ROLES:
                issues.append(
                    self._issue(
                        "auth_invalid_user_role",
                        severity="error",
                        user_id=user_id,
                        username=username,
                        role=role,
                    )
                )
            if bool(getattr(user, "is_disabled", False)) and user_id in online_user_ids:
                issues.append(
                    self._issue(
                        "auth_disabled_user_online",
                        severity="error",
                        user_id=user_id,
                        username=username,
                    )
                )
            if not str(getattr(user, "password_hash", "") or "").strip():
                issues.append(
                    self._issue(
                        "auth_empty_password_credential",
                        severity="error",
                        user_id=user_id,
                        username=username,
                    )
                )
            session_version = self._session_version(user)
            if session_version < 0:
                issues.append(
                    self._issue(
                        "auth_invalid_session_version",
                        severity="error",
                        user_id=user_id,
                        username=username,
                        auth_session_version=session_version,
                    )
                )
        return sorted(issues, key=self._issue_sort_key)

    def _online_user_ids(self) -> set[str]:
        diagnostics = connection_manager.connection_diagnostics()
        return {
            str(user_id or "")
            for user_id in diagnostics.get("connections_by_user", {})
            if str(user_id or "")
        }

    def _session_version(self, user: User) -> int:
        try:
            return int(getattr(user, "auth_session_version", 0) or 0)
        except (TypeError, ValueError):
            return -1

    def _issue(self, issue_type: str, *, severity: str, **extra: Any) -> dict[str, Any]:
        payload = {"issue_type": issue_type, "severity": severity}
        payload.update(extra)
        return payload

    def _issue_sort_key(self, issue: dict[str, Any]) -> tuple[str, str]:
        return (
            str(issue.get("issue_type") or ""),
            str(issue.get("user_id") or ""),
        )

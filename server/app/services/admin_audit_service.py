"""Admin operation audit logging."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.admin import AdminAuditLog
from app.models.user import User


SENSITIVE_DETAIL_KEYS = {
    "access_token",
    "authorization",
    "credential",
    "password",
    "refresh_token",
    "secret",
    "token",
}


def _sanitize_detail(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key or "").strip()
            if normalized_key.lower() in SENSITIVE_DETAIL_KEYS:
                sanitized[normalized_key] = "[redacted]"
            else:
                sanitized[normalized_key] = _sanitize_detail(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_detail(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_detail(item) for item in value]
    return value


def _detail_json(detail: dict[str, Any] | None) -> str:
    sanitized = _sanitize_detail(detail or {})
    return json.dumps(sanitized, ensure_ascii=False, sort_keys=True, default=str)


class AdminAuditService:
    """Persist immutable admin operation audit entries."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        *,
        actor: User | None = None,
        actor_user_id: str | None = None,
        actor_username: str = "",
        action: str,
        target_type: str = "",
        target_id: str = "",
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
        success: bool = True,
        error_code: str = "",
        detail: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> AdminAuditLog:
        if actor is not None:
            actor_user_id = str(getattr(actor, "id", "") or "") or actor_user_id
            actor_username = str(getattr(actor, "username", "") or "") or actor_username

        log = AdminAuditLog(
            actor_user_id=str(actor_user_id or "") or None,
            actor_username=str(actor_username or ""),
            action=str(action or "").strip(),
            target_type=str(target_type or ""),
            target_id=str(target_id or ""),
            request_path=str(request_path or ""),
            request_method=str(request_method or "").upper(),
            client_ip=str(client_ip or ""),
            success=bool(success),
            error_code=str(error_code or ""),
            detail_json=_detail_json(detail),
        )
        self.db.add(log)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(log)
        return log

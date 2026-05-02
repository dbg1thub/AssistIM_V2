"""Admin operation audit logging."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.admin import AdminAuditLog
from app.models.user import User
from app.utils.time import isoformat_utc


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

    def list_logs(
        self,
        *,
        actor_username: str = "",
        action: str = "",
        target_type: str = "",
        target_id: str = "",
        success: bool | None = None,
        created_from: str = "",
        created_to: str = "",
        page: int = 1,
        size: int = 20,
    ) -> dict:
        normalized_page = max(1, int(page or 1))
        normalized_size = min(100, max(1, int(size or 20)))
        filters = self._query_filters(
            actor_username=actor_username,
            action=action,
            target_type=target_type,
            target_id=target_id,
            success=success,
            created_from=created_from,
            created_to=created_to,
        )

        count_statement = select(func.count()).select_from(AdminAuditLog)
        list_statement = select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
        for condition in filters:
            count_statement = count_statement.where(condition)
            list_statement = list_statement.where(condition)

        total = self.db.execute(count_statement).scalar_one()
        logs = list(
            self.db.execute(
                list_statement.offset((normalized_page - 1) * normalized_size).limit(normalized_size)
            )
            .scalars()
            .all()
        )
        return {
            "total": int(total or 0),
            "page": normalized_page,
            "size": normalized_size,
            "items": [self.serialize_log(log) for log in logs],
        }

    def get_log(self, log_id: str) -> dict:
        log = self.db.get(AdminAuditLog, str(log_id or "").strip())
        if log is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "audit log not found", 404)
        return self.serialize_log(log)

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

    def serialize_log(self, log: AdminAuditLog) -> dict[str, Any]:
        return {
            "id": str(log.id or ""),
            "actor_user_id": str(log.actor_user_id or ""),
            "actor_username": str(log.actor_username or ""),
            "action": str(log.action or ""),
            "target_type": str(log.target_type or ""),
            "target_id": str(log.target_id or ""),
            "request_path": str(log.request_path or ""),
            "request_method": str(log.request_method or ""),
            "client_ip": str(log.client_ip or ""),
            "success": bool(log.success),
            "error_code": str(log.error_code or ""),
            "detail": self._detail_payload(log.detail_json),
            "created_at": isoformat_utc(log.created_at),
        }

    def _query_filters(
        self,
        *,
        actor_username: str,
        action: str,
        target_type: str,
        target_id: str,
        success: bool | None,
        created_from: str,
        created_to: str,
    ) -> list:
        filters = []
        normalized_actor = str(actor_username or "").strip()
        if normalized_actor:
            filters.append(AdminAuditLog.actor_username == normalized_actor)

        normalized_action = str(action or "").strip()
        if normalized_action:
            filters.append(AdminAuditLog.action == normalized_action)

        normalized_target_type = str(target_type or "").strip()
        if normalized_target_type:
            filters.append(AdminAuditLog.target_type == normalized_target_type)

        normalized_target_id = str(target_id or "").strip()
        if normalized_target_id:
            filters.append(AdminAuditLog.target_id == normalized_target_id)

        if success is not None:
            filters.append(AdminAuditLog.success.is_(bool(success)))

        lower_bound = self._parse_datetime_filter(created_from, field_name="created_from")
        if lower_bound is not None:
            filters.append(AdminAuditLog.created_at >= lower_bound)

        upper_bound = self._parse_datetime_filter(created_to, field_name="created_to")
        if upper_bound is not None:
            filters.append(AdminAuditLog.created_at <= upper_bound)

        return filters

    def _parse_datetime_filter(self, value: str, *, field_name: str) -> datetime | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        try:
            return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AppError(ErrorCode.INVALID_REQUEST, f"invalid {field_name}", 422) from exc

    def _detail_payload(self, detail_json: str) -> Any:
        try:
            raw_payload = json.loads(str(detail_json or "{}"))
        except json.JSONDecodeError:
            return {}
        return _sanitize_detail(raw_payload)

"""Admin server log inspection service."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.services.admin_audit_service import AdminAuditService
from app.utils.time import ensure_utc, isoformat_utc


LOG_LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
    r"level=(?P<level>[A-Z]+) logger=(?P<logger>\S+) message=(?P<message>.*)$"
)

SENSITIVE_VALUE_RE = re.compile(
    r"(?i)\b(access_token|authorization|credential|password|refresh_token|secret|token)\b\s*[:=]\s*"
    r"(Bearer\s+)?(\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)"
)


def _redact_text(value: str) -> str:
    return SENSITIVE_VALUE_RE.sub(lambda match: f"{match.group(1)}=[redacted]", str(value or ""))


class AdminLogService:
    """Read server-controlled log files for admin diagnostics."""

    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.audit = AdminAuditService(db)

    def list_files(
        self,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        files = [self._serialize_file(path) for path in self._iter_log_files()]
        payload = {"total": len(files), "items": files}
        self.audit.record(
            actor=actor,
            action="admin.logs.files.read",
            target_type="server_logs",
            target_id="files",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"total": len(files), "file_names": [item["file_name"] for item in files]},
        )
        return payload

    def query_logs(
        self,
        *,
        actor: User,
        file_name: str = "",
        level: str = "",
        keyword: str = "",
        created_from: str = "",
        created_to: str = "",
        limit: int = 100,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        normalized_level = str(level or "").strip().upper()
        if normalized_level and normalized_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise AppError(ErrorCode.INVALID_REQUEST, "invalid log level", 422)

        lower_bound = self._parse_datetime_filter(created_from, "created_from")
        upper_bound = self._parse_datetime_filter(created_to, "created_to")
        normalized_limit = min(1000, max(1, int(limit or 100)))
        files = [self._safe_log_file(file_name)] if str(file_name or "").strip() else self._iter_log_files()

        items: list[dict[str, Any]] = []
        for path in files:
            for entry in self._read_log_entries(path):
                if normalized_level and entry["level"] != normalized_level:
                    continue
                if keyword and str(keyword).lower() not in entry["message"].lower():
                    continue
                entry_timestamp = entry.pop("_timestamp_dt", None)
                if lower_bound is not None and (entry_timestamp is None or entry_timestamp < lower_bound):
                    continue
                if upper_bound is not None and (entry_timestamp is None or entry_timestamp > upper_bound):
                    continue
                items.append(entry)
                if len(items) >= normalized_limit:
                    break
            if len(items) >= normalized_limit:
                break

        payload = {
            "total": len(items),
            "limit": normalized_limit,
            "items": items,
        }
        self.audit.record(
            actor=actor,
            action="admin.logs.read",
            target_type="server_logs",
            target_id="query",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "file_name": self._safe_audit_file_name(file_name),
                "level": normalized_level,
                "keyword": _redact_text(keyword),
                "created_from": created_from,
                "created_to": created_to,
                "limit": normalized_limit,
                "total": len(items),
            },
        )
        return payload

    def download_file(
        self,
        file_name: str,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        try:
            path = self._safe_log_file(file_name)
            content = _redact_text(path.read_text(encoding="utf-8", errors="replace"))
            self.audit.record(
                actor=actor,
                action="admin.logs.download",
                target_type="server_logs",
                target_id="download",
                request_path=request_path,
                request_method=request_method,
                client_ip=client_ip,
                success=True,
                detail={"file_name": path.name, "size_bytes": path.stat().st_size},
                commit=False,
            )
            self.db.commit()
            return {"file_name": path.name, "content": content}
        except AppError as exc:
            self.audit.record(
                actor=actor,
                action="admin.logs.download",
                target_type="server_logs",
                target_id="download",
                request_path=request_path,
                request_method=request_method,
                client_ip=client_ip,
                success=False,
                error_code=str(exc.code),
                detail={"error": exc.message},
                commit=False,
            )
            self.db.commit()
            raise

    def _iter_log_files(self) -> list[Path]:
        root = self._log_root()
        if not root.exists():
            return []
        files = [path for path in root.iterdir() if path.is_file() and self._is_log_file(path.name)]
        return sorted(files, key=lambda path: (path.stat().st_mtime, path.name), reverse=True)

    def _serialize_file(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "file_name": path.name,
            "size_bytes": int(stat.st_size),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        }

    def _read_log_entries(self, path: Path) -> list[dict[str, Any]]:
        entries = [self._parse_log_line(path.name, line) for line in path.read_text(encoding="utf-8", errors="replace").splitlines()]
        return list(reversed(entries))

    def _parse_log_line(self, file_name: str, line: str) -> dict[str, Any]:
        match = LOG_LINE_RE.match(str(line or ""))
        if not match:
            return {
                "file_name": file_name,
                "timestamp": None,
                "_timestamp_dt": None,
                "level": "",
                "logger": "",
                "message": _redact_text(line),
            }

        timestamp_dt = datetime.strptime(match.group("timestamp"), "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=UTC)
        return {
            "file_name": file_name,
            "timestamp": timestamp_dt.isoformat(),
            "_timestamp_dt": timestamp_dt,
            "level": match.group("level"),
            "logger": match.group("logger"),
            "message": _redact_text(match.group("message")),
        }

    def _safe_log_file(self, file_name: str) -> Path:
        normalized = str(file_name or "").strip()
        if not normalized or "/" in normalized or "\\" in normalized or Path(normalized).name != normalized:
            raise AppError(ErrorCode.FORBIDDEN, "invalid log file name", 403)
        if not self._is_log_file(normalized):
            raise AppError(ErrorCode.FORBIDDEN, "invalid log file name", 403)

        root = self._log_root()
        target = (root / normalized).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise AppError(ErrorCode.FORBIDDEN, "log file is outside the log directory", 403) from exc
        if not target.is_file():
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "log file not found", 404)
        return target

    def _safe_audit_file_name(self, file_name: str) -> str:
        normalized = str(file_name or "").strip()
        return normalized if normalized and "/" not in normalized and "\\" not in normalized else ""

    def _log_root(self) -> Path:
        return Path(self.settings.log_dir).expanduser().resolve()

    def _is_log_file(self, file_name: str) -> bool:
        normalized = str(file_name or "").strip()
        return normalized.endswith(".log") or ".log." in normalized

    def _parse_datetime_filter(self, value: str, field_name: str) -> datetime | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        try:
            return ensure_utc(datetime.fromisoformat(normalized.replace("Z", "+00:00")))
        except ValueError as exc:
            raise AppError(ErrorCode.INVALID_REQUEST, f"invalid {field_name}", 422) from exc

"""Admin database backup service."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.models.admin import AdminDatabaseBackup
from app.models.user import User
from app.services.admin_audit_service import AdminAuditService
from app.utils.time import isoformat_utc, utcnow


class AdminDatabaseBackupError(RuntimeError):
    """Raised when one database backup cannot be completed."""


class AdminDatabaseBackupService:
    """Create and inspect server-local database backups."""

    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.audit = AdminAuditService(db)

    def create_backup(
        self,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        started_at = utcnow()
        started_perf = time.perf_counter()
        database_dialect = self._database_dialect()
        backup = AdminDatabaseBackup(
            created_by_user_id=str(actor.id or "") or None,
            created_by_username=str(actor.username or ""),
            status="running",
            database_dialect=database_dialect,
            backup_format=self._backup_format_for_dialect(database_dialect),
            started_at=started_at,
            created_at=started_at,
        )
        self.db.add(backup)
        self.db.flush()

        try:
            if database_dialect == "sqlite":
                self._create_sqlite_backup(backup)
            elif database_dialect in {"postgresql", "postgres"}:
                self._create_postgresql_backup(backup)
            else:
                raise AdminDatabaseBackupError(f"unsupported database dialect: {database_dialect}")

            finished_at = utcnow()
            backup.status = "completed"
            backup.finished_at = finished_at
            backup.duration_ms = self._duration_ms(started_perf)
            backup.size_bytes = self._file_size(backup.file_path)
            backup.checksum_sha256 = self._sha256(backup.file_path)
            self.audit.record(
                actor=actor,
                action="admin.database.backup.create",
                target_type="database_backup",
                target_id=str(backup.id or ""),
                request_path=request_path,
                request_method=request_method,
                client_ip=client_ip,
                success=True,
                detail={
                    "backup_id": str(backup.id or ""),
                    "database_dialect": backup.database_dialect,
                    "backup_format": backup.backup_format,
                    "status": backup.status,
                    "size_bytes": backup.size_bytes,
                    "storage_key": backup.storage_key,
                },
                commit=False,
            )
            self.db.commit()
            self.db.refresh(backup)
            return self.serialize_backup(backup)
        except Exception as exc:
            error_message = self._sanitize_error_message(str(exc) or type(exc).__name__)
            finished_at = utcnow()
            backup.status = "failed"
            backup.error_message = error_message
            backup.finished_at = finished_at
            backup.duration_ms = self._duration_ms(started_perf)
            self.audit.record(
                actor=actor,
                action="admin.database.backup.create",
                target_type="database_backup",
                target_id=str(backup.id or ""),
                request_path=request_path,
                request_method=request_method,
                client_ip=client_ip,
                success=False,
                error_code=str(ErrorCode.INTERNAL_ERROR),
                detail={
                    "backup_id": str(backup.id or ""),
                    "database_dialect": backup.database_dialect,
                    "backup_format": backup.backup_format,
                    "status": backup.status,
                    "error": error_message,
                },
                commit=False,
            )
            self.db.commit()
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                f"database backup failed: {error_message}",
                500,
            ) from exc

    def list_backups(self, *, page: int = 1, size: int = 20) -> dict[str, Any]:
        normalized_page = max(1, int(page or 1))
        normalized_size = min(100, max(1, int(size or 20)))
        total = self.db.execute(select(func.count()).select_from(AdminDatabaseBackup)).scalar_one()
        statement = (
            select(AdminDatabaseBackup)
            .order_by(AdminDatabaseBackup.created_at.desc(), AdminDatabaseBackup.id.desc())
            .offset((normalized_page - 1) * normalized_size)
            .limit(normalized_size)
        )
        backups = list(self.db.execute(statement).scalars().all())
        return {
            "total": int(total or 0),
            "page": normalized_page,
            "size": normalized_size,
            "items": [self.serialize_backup(backup) for backup in backups],
        }

    def get_backup(self, backup_id: str) -> dict[str, Any]:
        backup = self.db.get(AdminDatabaseBackup, str(backup_id or "").strip())
        if backup is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "database backup not found", 404)
        return self.serialize_backup(backup)

    def serialize_backup(self, backup: AdminDatabaseBackup) -> dict[str, Any]:
        return {
            "id": str(backup.id or ""),
            "created_by_user_id": str(backup.created_by_user_id or ""),
            "created_by_username": str(backup.created_by_username or ""),
            "status": str(backup.status or ""),
            "database_dialect": str(backup.database_dialect or ""),
            "backup_format": str(backup.backup_format or ""),
            "storage_key": str(backup.storage_key or ""),
            "file_name": str(backup.file_name or ""),
            "size_bytes": int(backup.size_bytes or 0),
            "checksum_sha256": str(backup.checksum_sha256 or ""),
            "error_message": str(backup.error_message or ""),
            "started_at": isoformat_utc(backup.started_at),
            "finished_at": isoformat_utc(backup.finished_at),
            "duration_ms": int(backup.duration_ms or 0),
            "created_at": isoformat_utc(backup.created_at),
        }

    def _create_sqlite_backup(self, backup: AdminDatabaseBackup) -> None:
        source_path = self._sqlite_database_path()
        if not source_path.is_file():
            raise AdminDatabaseBackupError("sqlite database file not found")

        target_path, storage_key, file_name = self._target_file(backup, suffix=".sqlite3")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(str(source_path))) as source:
            with closing(sqlite3.connect(str(target_path))) as target:
                source.backup(target)
        backup.file_path = str(target_path)
        backup.storage_key = storage_key
        backup.file_name = file_name

    def _create_postgresql_backup(self, backup: AdminDatabaseBackup) -> None:
        pg_dump = shutil.which("pg_dump")
        if not pg_dump:
            raise AdminDatabaseBackupError("pg_dump not found; install PostgreSQL client tools on the server")

        target_path, storage_key, file_name = self._target_file(backup, suffix=".dump")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        args = self._pg_dump_args(pg_dump, target_path, env)
        result = subprocess.run(args, env=env, capture_output=True, text=True, check=False, timeout=600)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "pg_dump failed").strip()
            raise AdminDatabaseBackupError(self._sanitize_error_message(detail[:500]))
        backup.file_path = str(target_path)
        backup.storage_key = storage_key
        backup.file_name = file_name

    def _pg_dump_args(self, pg_dump: str, target_path: Path, env: dict[str, str]) -> list[str]:
        url = make_url(self.settings.database_url)
        args = [pg_dump, "--format=custom", "--file", str(target_path)]
        if url.host:
            args.extend(["--host", str(url.host)])
        if url.port:
            args.extend(["--port", str(url.port)])
        if url.username:
            args.extend(["--username", str(url.username)])
        if url.database:
            args.extend(["--dbname", str(url.database)])
        if url.password:
            env["PGPASSWORD"] = str(url.password)
        return args

    def _target_file(self, backup: AdminDatabaseBackup, *, suffix: str) -> tuple[Path, str, str]:
        timestamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
        file_name = f"{timestamp}-{backup.id}{suffix}"
        storage_key = f"database_backups/{file_name}"
        return self._backup_root() / file_name, storage_key, file_name

    def _backup_root(self) -> Path:
        configured = str(getattr(self.settings, "admin_backup_dir", "") or "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
        return (Path(self.settings.upload_dir).expanduser().resolve().parent / "database_backups").resolve()

    def _sqlite_database_path(self) -> Path:
        database = self.db.get_bind().url.database or make_url(self.settings.database_url).database
        if not database:
            raise AdminDatabaseBackupError("sqlite database path is empty")
        return Path(str(database)).expanduser().resolve()

    def _database_dialect(self) -> str:
        try:
            return make_url(self.settings.database_url).get_backend_name()
        except Exception:
            return str(self.db.get_bind().dialect.name or "")

    def _backup_format_for_dialect(self, dialect: str) -> str:
        if dialect == "sqlite":
            return "sqlite"
        if dialect in {"postgresql", "postgres"}:
            return "pg_dump_custom"
        return ""

    def _duration_ms(self, started_perf: float) -> int:
        return max(0, int(round((time.perf_counter() - started_perf) * 1000)))

    def _file_size(self, file_path: str) -> int:
        return int(Path(file_path).stat().st_size)

    def _sha256(self, file_path: str) -> str:
        digest = hashlib.sha256()
        with Path(file_path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _sanitize_error_message(self, message: str) -> str:
        sanitized = str(message or "")
        raw_url = str(self.settings.database_url or "")
        try:
            url = make_url(raw_url)
            if url.password:
                sanitized = sanitized.replace(str(url.password), "***")
            if raw_url:
                sanitized = sanitized.replace(raw_url, str(url.set(password="***")))
        except Exception:
            pass
        return sanitized

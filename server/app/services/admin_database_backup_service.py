"""Admin database backup service."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import time
from contextlib import closing
from datetime import timedelta
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
from app.utils.time import ensure_utc, isoformat_utc, utcnow


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

    def prune_backups(
        self,
        *,
        keep_last: int | None,
        older_than_days: int | None,
        include_failed: bool,
        include_deleted: bool,
        dry_run: bool,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        criteria = {
            "keep_last": keep_last,
            "older_than_days": older_than_days,
            "include_failed": bool(include_failed),
            "include_deleted": bool(include_deleted),
            "dry_run": bool(dry_run),
        }
        if keep_last is None and older_than_days is None:
            raise AppError(ErrorCode.INVALID_REQUEST, "keep_last or older_than_days is required", 422)

        candidates = self._select_prune_candidates(
            keep_last=keep_last,
            older_than_days=older_than_days,
            include_failed=include_failed,
            include_deleted=include_deleted,
        )

        try:
            for backup in candidates:
                self._validate_backup_path_for_cleanup(backup)

            items: list[dict[str, Any]] = []
            file_deleted_count = 0
            file_missing_count = 0
            processed_count = 0

            if dry_run:
                items = [self._serialize_prune_item(backup, dry_run=True) for backup in candidates]
            else:
                for backup in candidates:
                    status_before = str(backup.status or "")
                    file_result = self._delete_backup_file(backup)
                    backup.status = "deleted"
                    processed_count += 1
                    if file_result["file_deleted"]:
                        file_deleted_count += 1
                    if file_result["file_missing"]:
                        file_missing_count += 1
                    items.append(
                        self._serialize_prune_item(
                            backup,
                            dry_run=False,
                            status_before=status_before,
                            file_deleted=bool(file_result["file_deleted"]),
                            file_missing=bool(file_result["file_missing"]),
                        )
                    )

            payload = {
                **criteria,
                "candidate_count": len(candidates),
                "processed_count": processed_count,
                "file_deleted_count": file_deleted_count,
                "file_missing_count": file_missing_count,
                "items": items,
            }
            self.audit.record(
                actor=actor,
                action="admin.database.backup.prune",
                target_type="database_backup",
                target_id="prune",
                request_path=request_path,
                request_method=request_method,
                client_ip=client_ip,
                success=True,
                detail={
                    **criteria,
                    "candidate_count": payload["candidate_count"],
                    "processed_count": payload["processed_count"],
                    "file_deleted_count": payload["file_deleted_count"],
                    "file_missing_count": payload["file_missing_count"],
                    "backup_ids": [str(backup.id or "") for backup in candidates],
                },
                commit=False,
            )
            self.db.commit()
            return payload
        except AppError as exc:
            self.audit.record(
                actor=actor,
                action="admin.database.backup.prune",
                target_type="database_backup",
                target_id="prune",
                request_path=request_path,
                request_method=request_method,
                client_ip=client_ip,
                success=False,
                error_code=str(exc.code),
                detail={
                    **criteria,
                    "candidate_count": len(candidates),
                    "error": exc.message,
                    "backup_ids": [str(backup.id or "") for backup in candidates],
                },
                commit=False,
            )
            self.db.commit()
            raise

    def delete_backup(
        self,
        backup_id: str,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        backup = self.db.get(AdminDatabaseBackup, str(backup_id or "").strip())
        if backup is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "database backup not found", 404)

        status_before = str(backup.status or "")
        try:
            file_result = self._delete_backup_file(backup)
            backup.status = "deleted"
            self.audit.record(
                actor=actor,
                action="admin.database.backup.delete",
                target_type="database_backup",
                target_id=str(backup.id or ""),
                request_path=request_path,
                request_method=request_method,
                client_ip=client_ip,
                success=True,
                detail={
                    "backup_id": str(backup.id or ""),
                    "status_before": status_before,
                    "status_after": backup.status,
                    "storage_key": str(backup.storage_key or ""),
                    "file_name": str(backup.file_name or ""),
                    "file_deleted": bool(file_result["file_deleted"]),
                    "file_missing": bool(file_result["file_missing"]),
                },
                commit=False,
            )
            self.db.commit()
            self.db.refresh(backup)
            payload = self.serialize_backup(backup)
            payload.update(file_result)
            return payload
        except AppError as exc:
            self.audit.record(
                actor=actor,
                action="admin.database.backup.delete",
                target_type="database_backup",
                target_id=str(backup.id or ""),
                request_path=request_path,
                request_method=request_method,
                client_ip=client_ip,
                success=False,
                error_code=str(exc.code),
                detail={
                    "backup_id": str(backup.id or ""),
                    "status": status_before,
                    "error": exc.message,
                },
                commit=False,
            )
            self.db.commit()
            raise

    def verify_backup(
        self,
        backup_id: str,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        backup = self.db.get(AdminDatabaseBackup, str(backup_id or "").strip())
        if backup is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "database backup not found", 404)

        try:
            result = self._verify_backup_file(backup)
            verified_at = utcnow()
            backup.verification_status = "passed"
            backup.verification_message = str(result["verification_message"])
            backup.verified_at = verified_at
            self.audit.record(
                actor=actor,
                action="admin.database.backup.verify",
                target_type="database_backup",
                target_id=str(backup.id or ""),
                request_path=request_path,
                request_method=request_method,
                client_ip=client_ip,
                success=True,
                detail={
                    "backup_id": str(backup.id or ""),
                    "status": str(backup.status or ""),
                    "database_dialect": str(backup.database_dialect or ""),
                    "backup_format": str(backup.backup_format or ""),
                    "storage_key": str(backup.storage_key or ""),
                    "file_name": str(backup.file_name or ""),
                    "verification_status": backup.verification_status,
                    "verification_message": backup.verification_message,
                    "checksum_matched": bool(result["checksum_matched"]),
                    "size_matched": bool(result["size_matched"]),
                    "integrity_check": str(result["integrity_check"]),
                },
                commit=False,
            )
            self.db.commit()
            self.db.refresh(backup)
            payload = self.serialize_backup(backup)
            payload.update(result)
            return payload
        except AppError as exc:
            verified_at = utcnow()
            backup.verification_status = "failed"
            backup.verification_message = self._verification_message(exc.message)
            backup.verified_at = verified_at
            self.audit.record(
                actor=actor,
                action="admin.database.backup.verify",
                target_type="database_backup",
                target_id=str(backup.id or ""),
                request_path=request_path,
                request_method=request_method,
                client_ip=client_ip,
                success=False,
                error_code=str(exc.code),
                detail={
                    "backup_id": str(backup.id or ""),
                    "status": str(backup.status or ""),
                    "database_dialect": str(backup.database_dialect or ""),
                    "backup_format": str(backup.backup_format or ""),
                    "verification_status": backup.verification_status,
                    "error": backup.verification_message,
                },
                commit=False,
            )
            self.db.commit()
            raise

    def prepare_download(
        self,
        backup_id: str,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        backup = self.db.get(AdminDatabaseBackup, str(backup_id or "").strip())
        if backup is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "database backup not found", 404)

        try:
            file_path = self._validate_downloadable_backup(backup)
            self.audit.record(
                actor=actor,
                action="admin.database.backup.download",
                target_type="database_backup",
                target_id=str(backup.id or ""),
                request_path=request_path,
                request_method=request_method,
                client_ip=client_ip,
                success=True,
                detail={
                    "backup_id": str(backup.id or ""),
                    "status": str(backup.status or ""),
                    "storage_key": str(backup.storage_key or ""),
                    "file_name": str(backup.file_name or ""),
                    "size_bytes": int(backup.size_bytes or 0),
                    "checksum_sha256": str(backup.checksum_sha256 or ""),
                },
                commit=False,
            )
            self.db.commit()
            return {
                "path": file_path,
                "file_name": str(backup.file_name or file_path.name),
                "media_type": "application/octet-stream",
            }
        except AppError as exc:
            self.audit.record(
                actor=actor,
                action="admin.database.backup.download",
                target_type="database_backup",
                target_id=str(backup.id or ""),
                request_path=request_path,
                request_method=request_method,
                client_ip=client_ip,
                success=False,
                error_code=str(exc.code),
                detail={
                    "backup_id": str(backup.id or ""),
                    "status": str(backup.status or ""),
                    "error": exc.message,
                },
                commit=False,
            )
            self.db.commit()
            raise

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
            "verification_status": str(backup.verification_status or ""),
            "verification_message": str(backup.verification_message or ""),
            "verified_at": isoformat_utc(backup.verified_at),
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

    def _validate_downloadable_backup(self, backup: AdminDatabaseBackup) -> Path:
        status = str(backup.status or "").strip().lower()
        if status != "completed":
            raise AppError(ErrorCode.INVALID_REQUEST, "only completed backups can be downloaded", 409)

        raw_path = str(backup.file_path or "").strip()
        if not raw_path:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "database backup file is missing", 404)

        file_path = Path(raw_path).expanduser().resolve()
        if not file_path.is_file():
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "database backup file is missing", 404)

        backup_root = self._backup_root()
        try:
            file_path.relative_to(backup_root)
        except ValueError as exc:
            raise AppError(ErrorCode.FORBIDDEN, "database backup file is outside the backup directory", 403) from exc
        return file_path

    def _delete_backup_file(self, backup: AdminDatabaseBackup) -> dict[str, bool]:
        raw_path = str(backup.file_path or "").strip()
        if not raw_path:
            return {"file_deleted": False, "file_missing": True}

        file_path = Path(raw_path).expanduser().resolve()
        backup_root = self._backup_root()
        try:
            file_path.relative_to(backup_root)
        except ValueError as exc:
            raise AppError(ErrorCode.FORBIDDEN, "database backup file is outside the backup directory", 403) from exc

        if not file_path.exists():
            return {"file_deleted": False, "file_missing": True}
        if not file_path.is_file():
            raise AppError(ErrorCode.INVALID_REQUEST, "database backup path is not a file", 409)

        try:
            file_path.unlink()
        except OSError as exc:
            raise AppError(ErrorCode.INTERNAL_ERROR, "database backup file delete failed", 500) from exc
        return {"file_deleted": True, "file_missing": False}

    def _select_prune_candidates(
        self,
        *,
        keep_last: int | None,
        older_than_days: int | None,
        include_failed: bool,
        include_deleted: bool,
    ) -> list[AdminDatabaseBackup]:
        statuses = {"completed"}
        if include_failed:
            statuses.add("failed")
        if include_deleted:
            statuses.add("deleted")

        statement = (
            select(AdminDatabaseBackup)
            .where(AdminDatabaseBackup.status.in_(sorted(statuses)))
            .order_by(AdminDatabaseBackup.created_at.desc(), AdminDatabaseBackup.id.desc())
        )
        backups = list(self.db.execute(statement).scalars().all())
        protected_ids: set[str] = set()
        if keep_last is not None and keep_last > 0:
            protected_ids = {str(backup.id or "") for backup in backups[:keep_last]}

        cutoff = None
        if older_than_days is not None:
            cutoff = utcnow() - timedelta(days=int(older_than_days))

        candidates: list[AdminDatabaseBackup] = []
        for backup in backups:
            backup_id = str(backup.id or "")
            if backup_id in protected_ids:
                continue

            matches_retention = keep_last is not None
            matches_age = cutoff is not None and backup.created_at is not None and ensure_utc(backup.created_at) < cutoff
            if matches_retention or matches_age:
                candidates.append(backup)
        return candidates

    def _validate_backup_path_for_cleanup(self, backup: AdminDatabaseBackup) -> None:
        raw_path = str(backup.file_path or "").strip()
        if not raw_path:
            return

        file_path = Path(raw_path).expanduser().resolve()
        backup_root = self._backup_root()
        try:
            file_path.relative_to(backup_root)
        except ValueError as exc:
            raise AppError(ErrorCode.FORBIDDEN, "database backup file is outside the backup directory", 403) from exc

    def _serialize_prune_item(
        self,
        backup: AdminDatabaseBackup,
        *,
        dry_run: bool,
        status_before: str | None = None,
        file_deleted: bool = False,
        file_missing: bool = False,
    ) -> dict[str, Any]:
        before = str(status_before if status_before is not None else backup.status or "")
        after = before if dry_run else "deleted"
        return {
            "id": str(backup.id or ""),
            "status_before": before,
            "status_after": after,
            "action": "would_delete" if dry_run else "deleted",
            "storage_key": str(backup.storage_key or ""),
            "file_name": str(backup.file_name or ""),
            "size_bytes": int(backup.size_bytes or 0),
            "created_at": isoformat_utc(backup.created_at),
            "file_deleted": bool(file_deleted),
            "file_missing": bool(file_missing),
        }

    def _verify_backup_file(self, backup: AdminDatabaseBackup) -> dict[str, Any]:
        file_path = self._validate_verifiable_backup(backup)
        expected_checksum = str(backup.checksum_sha256 or "").strip()
        if not expected_checksum:
            raise AppError(ErrorCode.INVALID_REQUEST, "database backup checksum is missing", 409)

        actual_checksum = self._sha256(str(file_path))
        if actual_checksum != expected_checksum:
            raise AppError(ErrorCode.INVALID_REQUEST, "database backup checksum mismatch", 409)

        expected_size = int(backup.size_bytes or 0)
        actual_size = int(file_path.stat().st_size)
        if expected_size != actual_size:
            raise AppError(ErrorCode.INVALID_REQUEST, "database backup size mismatch", 409)

        dialect = str(backup.database_dialect or "").strip().lower()
        backup_format = str(backup.backup_format or "").strip().lower()
        if dialect == "sqlite" or backup_format == "sqlite":
            integrity_check = self._verify_sqlite_backup(file_path)
            verification_message = "sqlite integrity_check ok"
        elif dialect in {"postgresql", "postgres"} or backup_format == "pg_dump_custom":
            integrity_check = self._verify_postgresql_backup(file_path)
            verification_message = "pg_restore --list ok"
        else:
            raise AppError(ErrorCode.INVALID_REQUEST, "unsupported database backup format", 409)

        return {
            "verification_message": verification_message,
            "size_matched": True,
            "checksum_matched": True,
            "integrity_check": integrity_check,
        }

    def _validate_verifiable_backup(self, backup: AdminDatabaseBackup) -> Path:
        status = str(backup.status or "").strip().lower()
        if status != "completed":
            raise AppError(ErrorCode.INVALID_REQUEST, "only completed backups can be verified", 409)

        raw_path = str(backup.file_path or "").strip()
        if not raw_path:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "database backup file is missing", 404)

        file_path = Path(raw_path).expanduser().resolve()
        backup_root = self._backup_root()
        try:
            file_path.relative_to(backup_root)
        except ValueError as exc:
            raise AppError(ErrorCode.FORBIDDEN, "database backup file is outside the backup directory", 403) from exc

        if not file_path.is_file():
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "database backup file is missing", 404)
        return file_path

    def _verify_sqlite_backup(self, file_path: Path) -> str:
        try:
            with closing(sqlite3.connect(f"{file_path.as_uri()}?mode=ro", uri=True)) as connection:
                rows = connection.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError as exc:
            message = self._verification_message(str(exc) or "sqlite integrity_check failed")
            raise AppError(ErrorCode.INVALID_REQUEST, f"sqlite backup integrity check failed: {message}", 409) from exc

        messages = [str(row[0] if row else "") for row in rows]
        if messages != ["ok"]:
            detail = "; ".join(item for item in messages if item) or "unknown integrity_check failure"
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"sqlite backup integrity check failed: {self._verification_message(detail)}",
                409,
            )
        return "ok"

    def _verify_postgresql_backup(self, file_path: Path) -> str:
        pg_restore = shutil.which("pg_restore")
        if not pg_restore:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "pg_restore not found; install PostgreSQL client tools on the server",
                500,
            )

        try:
            result = subprocess.run(
                [pg_restore, "--list", str(file_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
        except OSError as exc:
            raise AppError(ErrorCode.INTERNAL_ERROR, "pg_restore execution failed", 500) from exc
        except subprocess.TimeoutExpired as exc:
            raise AppError(ErrorCode.INTERNAL_ERROR, "pg_restore verification timed out", 500) from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "pg_restore --list failed").strip()
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"postgresql backup verification failed: {self._verification_message(detail)}",
                409,
            )
        return "pg_restore_list_ok"

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

    def _verification_message(self, message: str) -> str:
        return self._sanitize_error_message(str(message or "")).strip()[:500]

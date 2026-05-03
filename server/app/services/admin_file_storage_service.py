"""Admin file storage inspection service."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.file import StoredFile
from app.models.user import User
from app.services.admin_audit_service import AdminAuditService


SERVER_GENERATED_MEDIA_PREFIXES = ("default_avatars/", "group_avatars/")


@dataclass(slots=True)
class _ResolvedStoredFile:
    record: StoredFile
    storage_key: str
    path: Path | None
    invalid: bool = False


class AdminFileStorageService:
    """Inspect local file records and upload-dir consistency."""

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
        scan = self._scan()
        payload = scan["status_payload"]
        self.audit.record(
            actor=actor,
            action="admin.files.storage.status.read",
            target_type="file_storage",
            target_id="status",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "status": payload["status"],
                "local_records": payload["database"]["local_records"],
                "managed_files": payload["disk"]["managed_files"],
                "issue_count": payload["issues"]["total"],
            },
        )
        return payload

    def list_issues(
        self,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        scan = self._scan()
        issues = scan["issues"]
        payload = {"total": len(issues), "items": issues}
        self.audit.record(
            actor=actor,
            action="admin.files.storage.issues.read",
            target_type="file_storage",
            target_id="issues",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "total": len(issues),
                "issue_types": self._issue_counts(issues),
            },
        )
        return payload

    def _scan(self) -> dict[str, Any]:
        root = self._upload_root()
        upload_dir = self._upload_dir_snapshot(root)
        records = list(self.db.execute(select(StoredFile)).scalars().all())
        local_records = [record for record in records if str(record.storage_provider or "") == "local"]
        disk_files = self._scan_disk_files(root)
        issues: list[dict[str, Any]] = []
        referenced_storage_keys: set[str] = set()

        for resolved in (self._resolve_record(record, root) for record in local_records):
            if resolved.invalid:
                issues.append(self._invalid_storage_key_issue(resolved.record))
                continue

            referenced_storage_keys.add(resolved.storage_key)
            assert resolved.path is not None
            if not resolved.path.is_file():
                issues.append(self._missing_disk_file_issue(resolved.record, resolved.storage_key))
                continue

            mismatch_issue = self._metadata_mismatch_issue(resolved.record, resolved.storage_key, resolved.path)
            if mismatch_issue is not None:
                issues.append(mismatch_issue)

        for storage_key in sorted(set(disk_files["managed_files"]) - referenced_storage_keys):
            path = disk_files["managed_files"][storage_key]
            issues.append(
                {
                    "issue_type": "orphan_disk_file",
                    "severity": "warning",
                    "storage_provider": "local",
                    "storage_key": storage_key,
                    "actual_size_bytes": self._safe_file_size(path),
                }
            )

        issue_counts = self._status_issue_counts(issues)
        status_payload = {
            "status": "ok" if upload_dir["exists"] and upload_dir["is_dir"] and issue_counts["total"] == 0 else "warning",
            "storage_provider": "local",
            "upload_dir": upload_dir,
            "database": {
                "total_records": len(records),
                "local_records": len(local_records),
                "non_local_records": max(0, len(records) - len(local_records)),
                "local_size_bytes": sum(max(0, int(record.size_bytes or 0)) for record in local_records),
            },
            "disk": {
                "total_files": disk_files["total_files"],
                "managed_files": len(disk_files["managed_files"]),
                "ignored_server_generated_files": disk_files["ignored_server_generated_files"],
                "total_size_bytes": disk_files["total_size_bytes"],
                "managed_size_bytes": disk_files["managed_size_bytes"],
            },
            "issues": issue_counts,
        }
        return {"status_payload": status_payload, "issues": sorted(issues, key=self._issue_sort_key)}

    def _scan_disk_files(self, root: Path) -> dict[str, Any]:
        managed_files: dict[str, Path] = {}
        total_files = 0
        total_size_bytes = 0
        managed_size_bytes = 0
        ignored_server_generated_files = 0
        if not root.is_dir():
            return {
                "managed_files": managed_files,
                "total_files": 0,
                "total_size_bytes": 0,
                "managed_size_bytes": 0,
                "ignored_server_generated_files": 0,
            }

        for path in root.rglob("*"):
            if not path.is_file():
                continue
            storage_key = path.relative_to(root).as_posix()
            file_size = self._safe_file_size(path)
            total_files += 1
            total_size_bytes += file_size
            if self._is_server_generated_storage_key(storage_key):
                ignored_server_generated_files += 1
                continue
            managed_files[storage_key] = path
            managed_size_bytes += file_size

        return {
            "managed_files": managed_files,
            "total_files": total_files,
            "total_size_bytes": total_size_bytes,
            "managed_size_bytes": managed_size_bytes,
            "ignored_server_generated_files": ignored_server_generated_files,
        }

    def _resolve_record(self, record: StoredFile, root: Path) -> _ResolvedStoredFile:
        storage_key = self._normalize_storage_key(record.storage_key)
        if not storage_key:
            return _ResolvedStoredFile(record=record, storage_key="", path=None, invalid=True)
        target_path = (root / Path(storage_key)).resolve()
        try:
            target_path.relative_to(root)
        except ValueError:
            return _ResolvedStoredFile(record=record, storage_key="", path=None, invalid=True)
        return _ResolvedStoredFile(record=record, storage_key=storage_key, path=target_path)

    def _invalid_storage_key_issue(self, record: StoredFile) -> dict[str, Any]:
        return {
            "issue_type": "invalid_storage_key",
            "severity": "error",
            "file_id": str(record.id or ""),
            "file_name": str(record.file_name or ""),
            "storage_provider": str(record.storage_provider or ""),
            "storage_key": "",
        }

    def _missing_disk_file_issue(self, record: StoredFile, storage_key: str) -> dict[str, Any]:
        return {
            "issue_type": "missing_disk_file",
            "severity": "error",
            "file_id": str(record.id or ""),
            "file_name": str(record.file_name or ""),
            "storage_provider": str(record.storage_provider or ""),
            "storage_key": storage_key,
            "expected_size_bytes": max(0, int(record.size_bytes or 0)),
            "actual_size_bytes": None,
            "expected_checksum_sha256": str(record.checksum_sha256 or ""),
            "actual_checksum_sha256": "",
        }

    def _metadata_mismatch_issue(self, record: StoredFile, storage_key: str, path: Path) -> dict[str, Any] | None:
        expected_size = max(0, int(record.size_bytes or 0))
        actual_size = self._safe_file_size(path)
        expected_checksum = str(record.checksum_sha256 or "")
        actual_checksum = self._sha256(path) if expected_checksum else ""
        size_mismatch = expected_size != actual_size
        checksum_mismatch = bool(expected_checksum and expected_checksum != actual_checksum)
        if not size_mismatch and not checksum_mismatch:
            return None
        return {
            "issue_type": "metadata_mismatch",
            "severity": "warning",
            "file_id": str(record.id or ""),
            "file_name": str(record.file_name or ""),
            "storage_provider": str(record.storage_provider or ""),
            "storage_key": storage_key,
            "size_mismatch": size_mismatch,
            "checksum_mismatch": checksum_mismatch,
            "expected_size_bytes": expected_size,
            "actual_size_bytes": actual_size,
            "expected_checksum_sha256": expected_checksum,
            "actual_checksum_sha256": actual_checksum,
        }

    def _upload_dir_snapshot(self, root: Path) -> dict[str, bool]:
        exists = root.exists()
        is_dir = root.is_dir() if exists else False
        return {
            "exists": exists,
            "is_dir": is_dir,
            "readable": bool(os.access(root, os.R_OK)) if exists else False,
            "writable": bool(os.access(root, os.W_OK)) if exists else False,
        }

    def _upload_root(self) -> Path:
        return Path(self.settings.upload_dir).expanduser().resolve()

    def _normalize_storage_key(self, storage_key: str | None) -> str:
        normalized = str(storage_key or "").strip().replace("\\", "/").lstrip("/")
        parts = [part for part in normalized.split("/") if part]
        if not parts or any(part in {".", ".."} for part in parts):
            return ""
        return "/".join(parts)

    def _status_issue_counts(self, issues: list[dict[str, Any]]) -> dict[str, int]:
        counts = self._issue_counts(issues)
        return {
            "total": len(issues),
            "invalid_storage_keys": counts.get("invalid_storage_key", 0),
            "missing_disk_files": counts.get("missing_disk_file", 0),
            "metadata_mismatches": counts.get("metadata_mismatch", 0),
            "orphan_disk_files": counts.get("orphan_disk_file", 0),
        }

    def _issue_counts(self, issues: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in issues:
            issue_type = str(issue.get("issue_type") or "")
            counts[issue_type] = counts.get(issue_type, 0) + 1
        return dict(sorted(counts.items()))

    def _issue_sort_key(self, issue: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(issue.get("issue_type") or ""),
            str(issue.get("storage_key") or ""),
            str(issue.get("file_id") or ""),
        )

    def _is_server_generated_storage_key(self, storage_key: str) -> bool:
        normalized = str(storage_key or "").replace("\\", "/").lstrip("/")
        return normalized.startswith(SERVER_GENERATED_MEDIA_PREFIXES)

    def _safe_file_size(self, path: Path) -> int:
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0

    def _sha256(self, path: Path) -> str:
        checksum = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                checksum.update(chunk)
        return checksum.hexdigest()

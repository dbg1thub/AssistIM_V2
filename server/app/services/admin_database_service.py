"""Read-only admin database inspection service."""

from __future__ import annotations

import warnings

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError, SAWarning
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import RUNTIME_SCHEMA_REQUIRED_TABLES
from app.core.schema_compat import (
    ADMIN_AUDIT_INDEX_DDL,
    ADMIN_DATABASE_BACKUP_INDEX_DDL,
    CHAT_INDEX_DDL,
    FILE_INDEX_DDL,
    RUNTIME_SCHEMA_ALEMBIC_REVISION,
    SESSION_EVENT_INDEX_DDL,
    SESSION_INDEX_DDL,
    USER_PROFILE_INDEX_DDL,
    USER_SESSION_EVENT_INDEX_DDL,
    USERNAME_INDEX_DDL,
    has_current_runtime_schema,
)


REQUIRED_INDEXES_BY_TABLE: dict[str, tuple[str, ...]] = {
    "users": tuple(USER_PROFILE_INDEX_DDL) + tuple(USERNAME_INDEX_DDL),
    "messages": tuple(CHAT_INDEX_DDL),
    "sessions": tuple(SESSION_INDEX_DDL),
    "files": tuple(FILE_INDEX_DDL),
    "session_events": tuple(SESSION_EVENT_INDEX_DDL),
    "user_session_events": tuple(USER_SESSION_EVENT_INDEX_DDL),
    "user_blocks": ("idx_user_blocks_user_id", "idx_user_blocks_blocked_user_id"),
    "admin_audit_logs": tuple(ADMIN_AUDIT_INDEX_DDL),
    "admin_database_backups": tuple(ADMIN_DATABASE_BACKUP_INDEX_DDL),
}


class AdminDatabaseService:
    """Build read-only database inspection snapshots for admin tooling."""

    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def build_status(self) -> dict:
        bind = self.db.get_bind()
        table_names = self._table_names()
        return {
            "status": "ok",
            "dialect": bind.dialect.name,
            "database_url": self._redact_database_url(self.settings.database_url),
            "runtime_schema_revision": RUNTIME_SCHEMA_ALEMBIC_REVISION,
            "runtime_schema_complete": self._runtime_schema_complete(),
            "alembic": self._alembic_snapshot(table_names),
            "required_tables": {
                table_name: table_name in table_names
                for table_name in sorted(RUNTIME_SCHEMA_REQUIRED_TABLES)
            },
        }

    def build_tables(self) -> dict:
        table_names = sorted(self._table_names())
        return {
            "total_tables": len(table_names),
            "tables": [self._table_snapshot(table_name) for table_name in table_names],
        }

    def build_health(self) -> dict:
        table_names = self._table_names()
        required_tables_missing = sorted(set(RUNTIME_SCHEMA_REQUIRED_TABLES) - table_names)
        required_indexes_missing = self._missing_required_indexes(table_names)
        runtime_schema_complete = self._runtime_schema_complete()

        issues: list[dict[str, object]] = []
        if required_tables_missing:
            issues.append(
                {
                    "code": "required_tables_missing",
                    "severity": "error",
                    "message": "required runtime tables are missing",
                    "items": required_tables_missing,
                }
            )
        if required_indexes_missing:
            issues.append(
                {
                    "code": "required_indexes_missing",
                    "severity": "warning",
                    "message": "required runtime indexes are missing",
                    "items": required_indexes_missing,
                }
            )
        if not runtime_schema_complete:
            issues.append(
                {
                    "code": "runtime_schema_incomplete",
                    "severity": "error",
                    "message": "runtime schema is incomplete",
                    "items": [],
                }
            )

        return {
            "status": "ok" if not issues else "warning",
            "issue_count": len(issues),
            "issues": issues,
            "checks": {
                "runtime_schema_complete": runtime_schema_complete,
                "required_tables_missing": required_tables_missing,
                "required_indexes_missing": required_indexes_missing,
                "alembic": self._alembic_snapshot(table_names),
            },
        }

    def _table_snapshot(self, table_name: str) -> dict:
        indexes = self._index_names(table_name)
        required_indexes = {
            index_name: index_name in indexes
            for index_name in REQUIRED_INDEXES_BY_TABLE.get(table_name, ())
        }
        return {
            "name": table_name,
            "row_count": self._row_count(table_name),
            "indexes": sorted(indexes),
            "required_indexes": required_indexes,
        }

    def _alembic_snapshot(self, table_names: set[str]) -> dict:
        versions: list[str] = []
        if "alembic_version" in table_names:
            try:
                versions = [
                    str(version or "")
                    for version in self.db.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
                    if str(version or "").strip()
                ]
            except SQLAlchemyError:
                versions = []
        return {
            "current_versions": sorted(versions),
            "runtime_required_revision": RUNTIME_SCHEMA_ALEMBIC_REVISION,
            "runtime_revision_applied": RUNTIME_SCHEMA_ALEMBIC_REVISION in versions,
        }

    def _missing_required_indexes(self, table_names: set[str]) -> dict[str, list[str]]:
        missing: dict[str, list[str]] = {}
        for table_name, required_indexes in REQUIRED_INDEXES_BY_TABLE.items():
            if table_name not in table_names:
                continue
            indexes = self._index_names(table_name)
            missing_indexes = sorted(index_name for index_name in required_indexes if index_name not in indexes)
            if missing_indexes:
                missing[table_name] = missing_indexes
        return missing

    def _runtime_schema_complete(self) -> bool:
        try:
            return bool(has_current_runtime_schema(self.db.connection()))
        except SQLAlchemyError:
            return False

    def _table_names(self) -> set[str]:
        return set(inspect(self.db.get_bind()).get_table_names())

    def _index_names(self, table_name: str) -> set[str]:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", "Skipped unsupported reflection of expression-based index", SAWarning)
            indexes = {index["name"] for index in inspect(self.db.get_bind()).get_indexes(table_name)}
        if table_name == "users" and self.db.get_bind().dialect.name == "sqlite":
            row = self.db.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'index' AND tbl_name = 'users' AND name = 'uq_users_username_lower'"
                )
            ).first()
            if row is not None:
                indexes.add("uq_users_username_lower")
        return indexes

    def _row_count(self, table_name: str) -> int:
        quoted_table_name = self.db.get_bind().dialect.identifier_preparer.quote(table_name)
        return int(self.db.execute(text(f"SELECT COUNT(*) FROM {quoted_table_name}")).scalar_one() or 0)

    def _redact_database_url(self, database_url: str) -> str:
        try:
            rendered = str(self.db.get_bind().url.set(password="***"))
            if str(self.db.get_bind().url) == str(database_url):
                return rendered
        except Exception:
            pass

        raw_url = str(database_url or "")
        if "://" not in raw_url or "@" not in raw_url:
            return raw_url
        prefix, rest = raw_url.split("://", 1)
        credentials, host = rest.split("@", 1)
        if ":" not in credentials:
            return raw_url
        username, _password = credentials.split(":", 1)
        return f"{prefix}://{username}:***@{host}"

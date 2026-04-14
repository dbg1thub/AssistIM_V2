"""
Database Module

SQLite database using aiosqlite for async operations.
"""
import aiosqlite
import base64
import hashlib
import importlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from client.core import logging
from client.core.config_backend import get_config
from client.core.logging import setup_logging
from client.core.secure_storage import SecureStorage
from client.models.message import ChatMessage, Session, merge_sender_profile_extra


setup_logging()
logger = logging.get_logger(__name__)

ENCRYPTED_MESSAGE_PLACEHOLDER = "[Encrypted message]"

class Database:
    AUTH_USER_ID_STATE_KEY = "auth.user_id"
    APP_STATE_DB_ENCRYPTION_MODE = "storage.db_encryption_mode"
    APP_STATE_DB_ENCRYPTION_KEY = "storage.db_encryption_key"
    APP_STATE_DB_ENCRYPTION_KEY_ID = "storage.db_encryption_key_id"
    DB_ENCRYPTION_MODE_PLAIN = "plain"
    DB_ENCRYPTION_MODE_SQLCIPHER = "sqlcipher"
    DB_ENCRYPTION_MODE_SQLCIPHER_PENDING = "sqlcipher_pending"
    DB_ENCRYPTION_PROVIDER_AUTO = "auto"
    DB_ENCRYPTION_PROVIDER_SQLITE_DEFAULT = "sqlite-default"
    DB_ENCRYPTION_PROVIDER_SQLCIPHER_COMPAT = "sqlcipher-compatible"
    DB_ENCRYPTION_PROVIDER_SQLITE_MODULE = "sqlite3"
    DB_ENCRYPTION_PROVIDER_SQLCIPHER_MODULES = (
        "sqlcipher3",
        "pysqlcipher3.dbapi2",
        "pysqlcipher3",
    )

    """
    SQLite database for local storage.
    
    Manages chat messages, sessions, and user data.
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize database.
        
        Args:
            db_path: Path to SQLite database file
        """
        if db_path is None:
            config = get_config()
            db_path = config.storage.db_path
        else:
            config = get_config()
        
        self._db_path = str(Path(db_path).expanduser().resolve())
        self._db_crypto_metadata_path = str(Path(f"{self._db_path}.crypto.json"))
        self._db: Optional[aiosqlite.Connection] = None
        self._search_fts_tokenizer: Optional[str] = None
        self._active_dbapi_module_name = self.DB_ENCRYPTION_PROVIDER_SQLITE_MODULE
        self._requested_db_encryption_mode = self._normalize_db_encryption_mode(
            getattr(config.storage, "db_encryption_mode", self.DB_ENCRYPTION_MODE_PLAIN)
        )
        self._requested_db_encryption_provider = self._normalize_db_encryption_provider(
            getattr(config.storage, "db_encryption_provider", self.DB_ENCRYPTION_PROVIDER_AUTO)
        )
        self._db_encryption_status: dict[str, Any] = {
            "requested_mode": self._requested_db_encryption_mode,
            "requested_provider": self._requested_db_encryption_provider,
            "effective_mode": self.DB_ENCRYPTION_MODE_PLAIN,
            "runtime_provider": self.DB_ENCRYPTION_PROVIDER_SQLITE_DEFAULT,
            "runtime_module": self.DB_ENCRYPTION_PROVIDER_SQLITE_MODULE,
            "provider_match": self._requested_db_encryption_provider == self.DB_ENCRYPTION_PROVIDER_AUTO,
            "driver_available": False,
            "driver_version": "",
            "has_key_material": False,
            "key_id": "",
            "ready_for_sqlcipher": False,
            "migration_required": False,
            "fts_available": False,
            "fts_tokenizer": "",
            "supported_sqlcipher_modules": list(self.DB_ENCRYPTION_PROVIDER_SQLCIPHER_MODULES),
            "install_hint": "",
        }
    
    @property
    def is_connected(self) -> bool:
        """Check if database is connected."""
        return self._db is not None

    @staticmethod
    def _sql_literal(value: str) -> str:
        return "'" + str(value or "").replace("'", "''") + "'"

    async def _open_connection(self) -> aiosqlite.Connection:
        metadata = self._load_db_crypto_metadata()
        encryption_mode = self._normalize_db_encryption_mode(metadata.get("db_encryption_mode"))
        requires_sqlcipher = (
            encryption_mode == self.DB_ENCRYPTION_MODE_SQLCIPHER
            or self._requested_db_encryption_mode == self.DB_ENCRYPTION_MODE_SQLCIPHER
            or self._requested_db_encryption_provider == self.DB_ENCRYPTION_PROVIDER_SQLCIPHER_COMPAT
        )
        dbapi_module, runtime_module = self._resolve_dbapi_module(requires_sqlcipher=requires_sqlcipher)
        connection = await self._open_connection_with_dbapi_module(dbapi_module)
        try:
            self._db_encryption_status["runtime_module"] = self._active_dbapi_module_name or runtime_module
            if encryption_mode == self.DB_ENCRYPTION_MODE_SQLCIPHER:
                key_cipher = str(metadata.get("db_encryption_key") or "").strip()
                if not key_cipher:
                    raise RuntimeError("SQLCipher database key material is unavailable")
                driver_available, _, runtime_provider = await self._detect_sqlcipher_runtime_on_connection(connection)
                self._ensure_requested_db_provider_matches(runtime_provider, requires_sqlcipher=True)
                if not driver_available:
                    raise RuntimeError(
                        "SQLCipher database requires SQLCipher runtime support, "
                        "but the current sqlite driver does not provide it"
                    )
                await self._apply_sqlcipher_key(connection, key_cipher)
                await self._verify_sqlcipher_connection(connection)
            row_factory = aiosqlite.Row
            if self._active_dbapi_module_name == runtime_module:
                row_factory = getattr(dbapi_module, "Row", aiosqlite.Row)
            connection.row_factory = row_factory
            return connection
        except Exception:
            await connection.close()
            raise

    async def _open_connection_with_dbapi_module(self, dbapi_module: Any) -> aiosqlite.Connection:
        module_name = str(getattr(dbapi_module, "__name__", "") or "")
        if module_name in {"sqlite3", "_sqlite3"}:
            self._active_dbapi_module_name = self.DB_ENCRYPTION_PROVIDER_SQLITE_MODULE
            return await aiosqlite.connect(self._db_path)
        original_aiosqlite_sqlite3 = getattr(aiosqlite, "sqlite3", None)
        core_module = getattr(aiosqlite, "core", None)
        original_core_sqlite3 = getattr(core_module, "sqlite3", None) if core_module is not None else None
        if core_module is None or original_core_sqlite3 is None:
            self._active_dbapi_module_name = self.DB_ENCRYPTION_PROVIDER_SQLITE_MODULE
            return await aiosqlite.connect(self._db_path)
        try:
            if original_aiosqlite_sqlite3 is not None:
                setattr(aiosqlite, "sqlite3", dbapi_module)
            if core_module is not None and original_core_sqlite3 is not None:
                setattr(core_module, "sqlite3", dbapi_module)
            self._active_dbapi_module_name = module_name
            return await aiosqlite.connect(self._db_path)
        finally:
            if original_aiosqlite_sqlite3 is not None:
                setattr(aiosqlite, "sqlite3", original_aiosqlite_sqlite3)
            if core_module is not None and original_core_sqlite3 is not None:
                setattr(core_module, "sqlite3", original_core_sqlite3)

    async def _apply_sqlcipher_key(self, connection: aiosqlite.Connection, key_cipher: str) -> None:
        raw_key = SecureStorage.decrypt_text(str(key_cipher or "").strip())
        await connection.execute(f"PRAGMA key = {self._sql_literal(raw_key)}")

    async def _verify_sqlcipher_connection(self, connection: aiosqlite.Connection) -> None:
        try:
            cursor = await connection.execute("SELECT count(*) FROM sqlite_master")
            await cursor.fetchone()
        except Exception as exc:
            raise RuntimeError("Failed to open SQLCipher database with the configured key") from exc

    async def connect(self) -> None:
        """Connect to database and create tables."""
        if self._db is not None:
            return
        
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._db = await self._open_connection()
        
        await self._create_tables()
        await self._ensure_db_encryption_state()
        if await self._auto_migrate_sqlcipher_if_needed():
            await self._create_tables()
            await self._ensure_db_encryption_state()
        await self._ensure_directory_cache_scope_schema()
        await self._ensure_local_search_cache_schema()
        await self._ensure_directory_cache_owner_indexes()
        await self._ensure_message_crypto_schema()
        await self._ensure_search_fts_schema()
        await self._normalize_cached_session_types()
        logger.info(f"Database connected: {self._db_path}")
    
    async def _create_tables(self) -> None:
        """Create database tables."""
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                session_type TEXT NOT NULL DEFAULT 'direct',
                participant_ids TEXT NOT NULL DEFAULT '[]',
                last_message TEXT,
                last_message_time INTEGER,
                unread_count INTEGER NOT NULL DEFAULT 0,
                avatar TEXT,
                is_ai_session INTEGER NOT NULL DEFAULT 0,
                extra TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                content TEXT NOT NULL,
                message_type TEXT NOT NULL DEFAULT 'text',
                status TEXT NOT NULL DEFAULT 'pending',
                timestamp INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                is_self INTEGER NOT NULL DEFAULT 0,
                is_ai INTEGER NOT NULL DEFAULT 0,
                is_encrypted INTEGER NOT NULL DEFAULT 0,
                encryption_scheme TEXT NOT NULL DEFAULT '',
                extra TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE TABLE IF NOT EXISTS session_read_cursors (
                session_id TEXT NOT NULL,
                reader_id TEXT NOT NULL,
                last_read_seq INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (session_id, reader_id)
            );
            
            CREATE TABLE IF NOT EXISTS contacts_cache (
                owner_user_id TEXT NOT NULL,
                contact_id TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                nickname TEXT NOT NULL DEFAULT '',
                remark TEXT NOT NULL DEFAULT '',
                assistim_id TEXT NOT NULL DEFAULT '',
                region TEXT NOT NULL DEFAULT '',
                avatar TEXT NOT NULL DEFAULT '',
                signature TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'friend',
                status TEXT NOT NULL DEFAULT '',
                extra TEXT NOT NULL DEFAULT '{}',
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (owner_user_id, contact_id)
            );

            CREATE TABLE IF NOT EXISTS groups_cache (
                owner_user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                avatar TEXT NOT NULL DEFAULT '',
                owner_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                member_count INTEGER NOT NULL DEFAULT 0,
                member_search_text TEXT NOT NULL DEFAULT '',
                extra TEXT NOT NULL DEFAULT '{}',
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (owner_user_id, group_id)
            );
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_messages_session 
                ON messages(session_id, timestamp DESC);

            CREATE INDEX IF NOT EXISTS idx_session_read_cursors_session
                ON session_read_cursors(session_id, last_read_seq DESC);
            
            CREATE INDEX IF NOT EXISTS idx_sessions_updated 
                ON sessions(updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_contacts_cache_updated
                ON contacts_cache(updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_groups_cache_updated
                ON groups_cache(updated_at DESC);
        """)
        await self._db.commit()

    async def _ensure_directory_cache_scope_schema(self) -> None:
        """Rebuild directory cache tables when one older global-cache schema is detected."""
        contacts_requires_rebuild = await self._directory_cache_table_requires_rebuild(
            "contacts_cache",
            ("owner_user_id", "contact_id"),
        )
        groups_requires_rebuild = await self._directory_cache_table_requires_rebuild(
            "groups_cache",
            ("owner_user_id", "group_id"),
        )
        if not contacts_requires_rebuild and not groups_requires_rebuild:
            return

        await self._drop_search_fts_schema()
        await self._db.executescript(
            """
            DROP TABLE IF EXISTS contacts_cache;
            DROP TABLE IF EXISTS groups_cache;

            CREATE TABLE contacts_cache (
                owner_user_id TEXT NOT NULL,
                contact_id TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                nickname TEXT NOT NULL DEFAULT '',
                remark TEXT NOT NULL DEFAULT '',
                assistim_id TEXT NOT NULL DEFAULT '',
                region TEXT NOT NULL DEFAULT '',
                avatar TEXT NOT NULL DEFAULT '',
                signature TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'friend',
                status TEXT NOT NULL DEFAULT '',
                extra TEXT NOT NULL DEFAULT '{}',
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (owner_user_id, contact_id)
            );

            CREATE TABLE groups_cache (
                owner_user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                avatar TEXT NOT NULL DEFAULT '',
                owner_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                member_count INTEGER NOT NULL DEFAULT 0,
                member_search_text TEXT NOT NULL DEFAULT '',
                extra TEXT NOT NULL DEFAULT '{}',
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (owner_user_id, group_id)
            );

            CREATE INDEX idx_contacts_cache_updated
                ON contacts_cache(updated_at DESC);
            CREATE INDEX idx_contacts_cache_owner_updated
                ON contacts_cache(owner_user_id, updated_at DESC);

            CREATE INDEX idx_groups_cache_updated
                ON groups_cache(updated_at DESC);
            CREATE INDEX idx_groups_cache_owner_updated
                ON groups_cache(owner_user_id, updated_at DESC);
            """
        )
        await self._db.commit()

    async def _directory_cache_table_requires_rebuild(
        self,
        table_name: str,
        expected_primary_key: tuple[str, ...],
    ) -> bool:
        """Return whether one directory cache table still uses one legacy global schema."""
        cursor = await self._db.execute(f"PRAGMA table_info({table_name})")
        rows = await cursor.fetchall()
        if not rows:
            return True

        existing_columns = {str(row["name"]) for row in rows}
        if any(column not in existing_columns for column in expected_primary_key):
            return True

        actual_primary_key = [
            str(item["name"])
            for item in sorted(rows, key=lambda row: int(row["pk"] or 0))
            if int(item["pk"] or 0) > 0
        ]
        return tuple(actual_primary_key) != tuple(expected_primary_key)

    async def _ensure_local_search_cache_schema(self) -> None:
        """Add newly introduced cache columns to existing local databases."""
        await self._ensure_table_columns(
            "contacts_cache",
            {
                "owner_user_id": "TEXT NOT NULL DEFAULT ''",
                "region": "TEXT NOT NULL DEFAULT ''",
            },
        )
        await self._ensure_table_columns(
            "groups_cache",
            {
                "owner_user_id": "TEXT NOT NULL DEFAULT ''",
                "member_search_text": "TEXT NOT NULL DEFAULT ''",
            },
        )

    async def _ensure_directory_cache_owner_indexes(self) -> None:
        """Create owner-scoped cache indexes after one schema rebuild or upgrade completes."""
        await self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_contacts_cache_owner_updated
            ON contacts_cache(owner_user_id, updated_at DESC)
            """
        )
        await self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_groups_cache_owner_updated
            ON groups_cache(owner_user_id, updated_at DESC)
            """
        )
        await self._db.commit()

    async def _ensure_message_crypto_schema(self) -> None:
        """Add explicit encryption markers for cached messages and backfill existing rows."""
        await self._ensure_table_columns(
            "messages",
            {
                "is_encrypted": "INTEGER NOT NULL DEFAULT 0",
                "encryption_scheme": "TEXT NOT NULL DEFAULT ''",
            },
        )
        await self._db.execute(
            """
            UPDATE messages
            SET
                is_encrypted = CASE
                    WHEN COALESCE(json_extract(extra, '$.encryption.enabled'), 0) = 1 THEN 1
                    WHEN COALESCE(json_extract(extra, '$.attachment_encryption.enabled'), 0) = 1 THEN 1
                    ELSE 0
                END,
                encryption_scheme = CASE
                    WHEN LENGTH(COALESCE(json_extract(extra, '$.encryption.scheme'), '')) > 0
                        THEN json_extract(extra, '$.encryption.scheme')
                    WHEN LENGTH(COALESCE(json_extract(extra, '$.attachment_encryption.scheme'), '')) > 0
                        THEN json_extract(extra, '$.attachment_encryption.scheme')
                    ELSE ''
                END
            """
        )
        await self._db.commit()

    async def _ensure_table_columns(self, table_name: str, columns: dict[str, str]) -> None:
        """Ensure one table exposes every required column for lightweight upgrades."""
        cursor = await self._db.execute(f"PRAGMA table_info({table_name})")
        rows = await cursor.fetchall()
        existing_columns = {str(row["name"]) for row in rows}
        missing_columns = {name: ddl for name, ddl in columns.items() if name not in existing_columns}
        for column_name, ddl in missing_columns.items():
            await self._db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")
        if missing_columns:
            await self._db.commit()

    @classmethod
    def _normalize_db_encryption_mode(cls, value: object) -> str:
        normalized = str(value or "").strip().lower()
        if normalized == cls.DB_ENCRYPTION_MODE_SQLCIPHER_PENDING:
            return cls.DB_ENCRYPTION_MODE_SQLCIPHER_PENDING
        if normalized == cls.DB_ENCRYPTION_MODE_SQLCIPHER:
            return cls.DB_ENCRYPTION_MODE_SQLCIPHER
        return cls.DB_ENCRYPTION_MODE_PLAIN

    @classmethod
    def _normalize_db_encryption_provider(cls, value: object) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {
            cls.DB_ENCRYPTION_PROVIDER_SQLITE_DEFAULT,
            "sqlite",
            "default",
            "stdlib",
        }:
            return cls.DB_ENCRYPTION_PROVIDER_SQLITE_DEFAULT
        if normalized in {
            cls.DB_ENCRYPTION_PROVIDER_SQLCIPHER_COMPAT,
            "sqlcipher",
            "sqlcipher3",
            "pysqlcipher3",
        }:
            return cls.DB_ENCRYPTION_PROVIDER_SQLCIPHER_COMPAT
        return cls.DB_ENCRYPTION_PROVIDER_AUTO

    @staticmethod
    def _derive_db_key_id(raw_key: str) -> str:
        return hashlib.sha256(str(raw_key or "").encode("utf-8")).hexdigest()[:16]

    def _provider_matches_runtime(self, runtime_provider: str) -> bool:
        requested_provider = self._requested_db_encryption_provider
        if requested_provider == self.DB_ENCRYPTION_PROVIDER_AUTO:
            return True
        return requested_provider == runtime_provider

    def _ensure_requested_db_provider_matches(self, runtime_provider: str, *, requires_sqlcipher: bool) -> None:
        if self._provider_matches_runtime(runtime_provider):
            return
        requested_provider = self._requested_db_encryption_provider
        if requires_sqlcipher or requested_provider == self.DB_ENCRYPTION_PROVIDER_SQLCIPHER_COMPAT:
            raise RuntimeError(
                f"Configured DB encryption provider '{requested_provider}' is unavailable; "
                f"current runtime provider is '{runtime_provider}'"
            )

    def _iter_dbapi_module_candidates(self, *, requires_sqlcipher: bool) -> list[tuple[str, str]]:
        requested_provider = self._requested_db_encryption_provider
        if requested_provider == self.DB_ENCRYPTION_PROVIDER_SQLITE_DEFAULT:
            return [(self.DB_ENCRYPTION_PROVIDER_SQLITE_DEFAULT, self.DB_ENCRYPTION_PROVIDER_SQLITE_MODULE)]
        if requested_provider == self.DB_ENCRYPTION_PROVIDER_SQLCIPHER_COMPAT:
            return [
                (self.DB_ENCRYPTION_PROVIDER_SQLCIPHER_COMPAT, module_name)
                for module_name in self.DB_ENCRYPTION_PROVIDER_SQLCIPHER_MODULES
            ]
        if requires_sqlcipher:
            return [
                *[
                    (self.DB_ENCRYPTION_PROVIDER_SQLCIPHER_COMPAT, module_name)
                    for module_name in self.DB_ENCRYPTION_PROVIDER_SQLCIPHER_MODULES
                ],
                (self.DB_ENCRYPTION_PROVIDER_SQLITE_DEFAULT, self.DB_ENCRYPTION_PROVIDER_SQLITE_MODULE),
            ]
        return [(self.DB_ENCRYPTION_PROVIDER_SQLITE_DEFAULT, self.DB_ENCRYPTION_PROVIDER_SQLITE_MODULE)]

    def _resolve_dbapi_module(self, *, requires_sqlcipher: bool) -> tuple[Any, str]:
        for runtime_provider, module_name in self._iter_dbapi_module_candidates(requires_sqlcipher=requires_sqlcipher):
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue
            return module, module_name
        import sqlite3
        return sqlite3, self.DB_ENCRYPTION_PROVIDER_SQLITE_MODULE

    def _build_db_driver_install_hint(
        self,
        *,
        runtime_provider: str,
        provider_match: bool,
        driver_available: bool,
    ) -> str:
        if self._requested_db_encryption_mode != self.DB_ENCRYPTION_MODE_SQLCIPHER:
            return ""
        if provider_match and driver_available:
            return ""
        requested_provider = self._requested_db_encryption_provider
        if requested_provider == self.DB_ENCRYPTION_PROVIDER_SQLITE_DEFAULT:
            return (
                "Configure ASSISTIM_DB_ENCRYPTION_PROVIDER=sqlcipher-compatible and install one SQLCipher "
                f"DB-API module: {', '.join(self.DB_ENCRYPTION_PROVIDER_SQLCIPHER_MODULES)}"
            )
        if requested_provider == self.DB_ENCRYPTION_PROVIDER_SQLCIPHER_COMPAT:
            return (
                "Install one SQLCipher-compatible DB-API module and ensure it is importable in the current "
                f"environment: {', '.join(self.DB_ENCRYPTION_PROVIDER_SQLCIPHER_MODULES)}"
            )
        return (
            "Install one SQLCipher-compatible DB-API module or keep auto provider selection enabled. "
            f"Recognized modules: {', '.join(self.DB_ENCRYPTION_PROVIDER_SQLCIPHER_MODULES)}"
        )

    def _load_db_crypto_metadata(self) -> dict[str, Any]:
        path = Path(self._db_crypto_metadata_path)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_db_crypto_metadata(self, payload: dict[str, Any]) -> None:
        path = Path(self._db_crypto_metadata_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")

    async def _ensure_db_encryption_state(self) -> None:
        """Persist one stable DB encryption status snapshot and optional SQLCipher key material."""
        metadata = self._load_db_crypto_metadata()
        app_state_mode_raw = str(await self.get_app_state(self.APP_STATE_DB_ENCRYPTION_MODE) or "").strip()
        stored_mode_raw = str(metadata.get("db_encryption_mode") or app_state_mode_raw or "").strip()
        stored_mode = self._normalize_db_encryption_mode(stored_mode_raw)
        legacy_key_cipher = str(await self.get_app_state(self.APP_STATE_DB_ENCRYPTION_KEY) or "").strip()
        legacy_key_id = str(await self.get_app_state(self.APP_STATE_DB_ENCRYPTION_KEY_ID) or "").strip()
        stored_key_cipher = str(metadata.get("db_encryption_key") or legacy_key_cipher or "").strip()
        stored_key_id = str(metadata.get("db_encryption_key_id") or legacy_key_id or "").strip()
        driver_available, driver_version, runtime_provider = await self._detect_sqlcipher_runtime()
        provider_match = self._provider_matches_runtime(runtime_provider)
        runtime_module = str(self._active_dbapi_module_name or self.DB_ENCRYPTION_PROVIDER_SQLITE_MODULE)

        requested_mode = self._requested_db_encryption_mode
        effective_mode = self.DB_ENCRYPTION_MODE_PLAIN
        key_cipher = stored_key_cipher
        key_id = stored_key_id
        metadata_dirty = False

        if (legacy_key_cipher or legacy_key_id) and (
            metadata.get("db_encryption_key") != legacy_key_cipher
            or metadata.get("db_encryption_key_id") != legacy_key_id
        ):
            metadata["db_encryption_key"] = legacy_key_cipher
            metadata["db_encryption_key_id"] = legacy_key_id
            metadata_dirty = True

        if requested_mode == self.DB_ENCRYPTION_MODE_SQLCIPHER:
            self._ensure_requested_db_provider_matches(runtime_provider, requires_sqlcipher=False)
            if not key_cipher:
                raw_key = base64.b64encode(os.urandom(32)).decode("ascii")
                key_cipher = SecureStorage.encrypt_text(raw_key)
                metadata["db_encryption_key"] = key_cipher
                metadata_dirty = True
            if not key_id:
                raw_key = SecureStorage.decrypt_text(key_cipher)
                key_id = self._derive_db_key_id(raw_key)
                metadata["db_encryption_key_id"] = key_id
                metadata_dirty = True
            if stored_mode == self.DB_ENCRYPTION_MODE_SQLCIPHER:
                effective_mode = self.DB_ENCRYPTION_MODE_SQLCIPHER
            else:
                effective_mode = self.DB_ENCRYPTION_MODE_SQLCIPHER_PENDING
            if self._normalize_db_encryption_mode(app_state_mode_raw) != effective_mode or app_state_mode_raw != effective_mode:
                await self.set_app_state(self.APP_STATE_DB_ENCRYPTION_MODE, effective_mode)
        else:
            if self._normalize_db_encryption_mode(app_state_mode_raw) != self.DB_ENCRYPTION_MODE_PLAIN or not app_state_mode_raw:
                await self.set_app_state(self.APP_STATE_DB_ENCRYPTION_MODE, self.DB_ENCRYPTION_MODE_PLAIN)

        if metadata.get("db_encryption_mode") != effective_mode and (key_cipher or metadata):
            metadata["db_encryption_mode"] = effective_mode
            metadata_dirty = True
        if metadata_dirty and (key_cipher or metadata):
            self._save_db_crypto_metadata(metadata)

        if legacy_key_cipher:
            await self.delete_app_state(self.APP_STATE_DB_ENCRYPTION_KEY)
        if legacy_key_id:
            await self.delete_app_state(self.APP_STATE_DB_ENCRYPTION_KEY_ID)

        self._db_encryption_status = {
            "requested_mode": requested_mode,
            "requested_provider": self._requested_db_encryption_provider,
            "effective_mode": effective_mode,
            "runtime_provider": runtime_provider,
            "runtime_module": runtime_module,
            "provider_match": provider_match,
            "driver_available": driver_available,
            "driver_version": driver_version,
            "has_key_material": bool(key_cipher),
            "key_id": key_id,
            "ready_for_sqlcipher": effective_mode == self.DB_ENCRYPTION_MODE_SQLCIPHER_PENDING and bool(key_cipher),
            "migration_required": requested_mode == self.DB_ENCRYPTION_MODE_SQLCIPHER and effective_mode != self.DB_ENCRYPTION_MODE_SQLCIPHER,
            "fts_available": bool(self._search_fts_tokenizer),
            "fts_tokenizer": str(self._search_fts_tokenizer or ""),
            "supported_sqlcipher_modules": list(self.DB_ENCRYPTION_PROVIDER_SQLCIPHER_MODULES),
            "install_hint": self._build_db_driver_install_hint(
                runtime_provider=runtime_provider,
                provider_match=provider_match,
                driver_available=driver_available,
            ),
        }

    def get_db_encryption_status(self) -> dict[str, Any]:
        """Return the current local database encryption status snapshot."""
        return dict(self._db_encryption_status)

    def get_db_encryption_self_check(self) -> dict[str, Any]:
        """Return one stable, user-facing self-check summary for local DB encryption."""
        status = self.get_db_encryption_status()
        requested_mode = str(status.get("requested_mode") or self.DB_ENCRYPTION_MODE_PLAIN)
        effective_mode = str(status.get("effective_mode") or self.DB_ENCRYPTION_MODE_PLAIN)
        provider_match = bool(status.get("provider_match"))
        driver_available = bool(status.get("driver_available"))
        runtime_provider = str(status.get("runtime_provider") or self.DB_ENCRYPTION_PROVIDER_SQLITE_DEFAULT)
        install_hint = str(status.get("install_hint") or "").strip()
        fts_available = bool(status.get("fts_available"))
        fts_tokenizer = str(status.get("fts_tokenizer") or "").strip()
        search_mode = "like_fallback"
        search_message = "Local message search is using LIKE fallback queries"
        if fts_available:
            normalized_tokenizer = fts_tokenizer or "fts5"
            search_mode = f"fts5_{normalized_tokenizer}"
            search_message = f"Local message search is using FTS5 ({normalized_tokenizer})"

        result = dict(status)
        if requested_mode == self.DB_ENCRYPTION_MODE_PLAIN:
            result.update(
                {
                    "state": "plain",
                    "severity": "info",
                    "can_start": True,
                    "action_required": False,
                    "message": "Local database encryption is disabled",
                    "search_mode": search_mode,
                    "search_message": search_message,
                }
            )
            return result

        if not provider_match:
            result.update(
                {
                    "state": "provider_mismatch",
                    "severity": "error",
                    "can_start": False,
                    "action_required": True,
                    "message": (
                        "Configured DB encryption provider does not match the current runtime "
                        f"provider ({runtime_provider})"
                    ),
                    "search_mode": search_mode,
                    "search_message": search_message,
                }
            )
            if install_hint:
                result["recommended_action"] = install_hint
            return result

        if effective_mode == self.DB_ENCRYPTION_MODE_SQLCIPHER:
            result.update(
                {
                    "state": "sqlcipher_active",
                    "severity": "ok",
                    "can_start": True,
                    "action_required": False,
                    "message": "SQLCipher is active for the local database",
                    "search_mode": search_mode,
                    "search_message": search_message,
                }
            )
            return result

        if driver_available:
            result.update(
                {
                    "state": "migration_pending",
                    "severity": "warning",
                    "can_start": True,
                    "action_required": True,
                    "message": "SQLCipher runtime is available, but the local database still needs migration",
                    "search_mode": search_mode,
                    "search_message": search_message,
                }
            )
            if install_hint:
                result["recommended_action"] = install_hint
            return result

        result.update(
            {
                "state": "runtime_missing",
                "severity": "warning",
                "can_start": True,
                "action_required": True,
                "message": "SQLCipher key material is ready, but the current runtime does not provide SQLCipher support",
                "search_mode": search_mode,
                "search_message": search_message,
            }
        )
        if install_hint:
            result["recommended_action"] = install_hint
        return result

    async def _auto_migrate_sqlcipher_if_needed(self) -> bool:
        """Automatically migrate into SQLCipher when the runtime and config are ready."""
        status = self.get_db_encryption_status()
        if not (
            status.get("requested_mode") == self.DB_ENCRYPTION_MODE_SQLCIPHER
            and status.get("driver_available")
            and status.get("migration_required")
        ):
            return False
        await self._migrate_current_connection_to_sqlcipher()
        return True

    async def migrate_to_sqlcipher(self) -> dict[str, Any]:
        """Export the current plain SQLite database into one SQLCipher-protected file in place."""
        if self._db is None:
            raise RuntimeError("database must be connected before migration")

        status = self.get_db_encryption_status()
        if status.get("requested_mode") != self.DB_ENCRYPTION_MODE_SQLCIPHER:
            raise RuntimeError("SQLCipher mode is not requested")
        if not status.get("driver_available"):
            raise RuntimeError("SQLCipher runtime is unavailable")
        if not status.get("has_key_material"):
            raise RuntimeError("SQLCipher database key material is unavailable")
        if status.get("effective_mode") == self.DB_ENCRYPTION_MODE_SQLCIPHER:
            return {
                "migrated": False,
                "effective_mode": self.DB_ENCRYPTION_MODE_SQLCIPHER,
                "reason": "already_sqlcipher",
            }

        await self._migrate_current_connection_to_sqlcipher()
        await self._ensure_db_encryption_state()
        return {
            "migrated": True,
            "effective_mode": self.DB_ENCRYPTION_MODE_SQLCIPHER,
            "backup_path": str(Path(f"{self._db_path}.pre-sqlcipher.bak")),
        }

    async def _migrate_current_connection_to_sqlcipher(self) -> None:
        """Run one in-place SQLCipher export for the currently open plain SQLite connection."""
        if self._db is None:
            raise RuntimeError("database must be connected before migration")

        metadata = self._load_db_crypto_metadata()
        key_cipher = str(metadata.get("db_encryption_key") or "").strip()
        if not key_cipher:
            raise RuntimeError("SQLCipher database key material is unavailable")
        raw_key = SecureStorage.decrypt_text(key_cipher)

        temp_path = str(Path(f"{self._db_path}.sqlcipher.tmp"))
        backup_path = str(Path(f"{self._db_path}.pre-sqlcipher.bak"))
        temp_file = Path(temp_path)
        backup_file = Path(backup_path)
        if temp_file.exists():
            temp_file.unlink()
        if backup_file.exists():
            backup_file.unlink()

        try:
            await self._db.execute(
                f"ATTACH DATABASE {self._sql_literal(temp_path)} AS encrypted KEY {self._sql_literal(raw_key)}"
            )
            await self._db.execute("SELECT sqlcipher_export('encrypted')")
            await self._db.execute("DETACH DATABASE encrypted")
            await self._db.commit()

            await self.close()
            os.replace(self._db_path, backup_path)
            os.replace(temp_path, self._db_path)

            metadata["db_encryption_mode"] = self.DB_ENCRYPTION_MODE_SQLCIPHER
            self._save_db_crypto_metadata(metadata)
            self._db = await self._open_connection()
        except Exception:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)
            raise

    async def _detect_sqlcipher_runtime_on_connection(
        self, connection: aiosqlite.Connection
    ) -> tuple[bool, str, str]:
        """Return whether one sqlite connection exposes SQLCipher support."""
        runtime_provider = self.DB_ENCRYPTION_PROVIDER_SQLITE_DEFAULT
        try:
            cursor = await connection.execute("PRAGMA cipher_version")
            row = await cursor.fetchone()
        except Exception:
            return False, "", runtime_provider
        if row is None:
            return False, "", runtime_provider
        try:
            version = str(row[0] or "").strip()
        except Exception:
            version = ""
        if version:
            runtime_provider = self.DB_ENCRYPTION_PROVIDER_SQLCIPHER_COMPAT
        return bool(version), version, runtime_provider

    async def _detect_sqlcipher_runtime(self) -> tuple[bool, str, str]:
        """Return whether the current sqlite runtime exposes SQLCipher support."""
        return await self._detect_sqlcipher_runtime_on_connection(self._db)

    async def _ensure_search_fts_schema(self) -> None:
        """Create and backfill SQLite FTS5 search indexes when available."""
        detected_tokenizer = await self._detect_search_fts_tokenizer()
        if detected_tokenizer:
            self._search_fts_tokenizer = detected_tokenizer
            self._db_encryption_status["fts_available"] = True
            self._db_encryption_status["fts_tokenizer"] = "trigram" if "trigram" in detected_tokenizer else "unicode61"
            await self._create_search_fts_schema(detected_tokenizer)
            await self._rebuild_search_fts_if_needed()
            return

        for tokenizer in ("trigram", "unicode61 remove_diacritics 2"):
            try:
                await self._create_search_fts_schema(tokenizer)
            except Exception as exc:
                logger.debug("Search FTS tokenizer unavailable (%s): %s", tokenizer, exc)
                await self._drop_search_fts_schema()
                continue
            self._search_fts_tokenizer = "trigram" if tokenizer == "trigram" else "unicode61"
            self._db_encryption_status["fts_available"] = True
            self._db_encryption_status["fts_tokenizer"] = self._search_fts_tokenizer
            await self._rebuild_search_fts_if_needed(force=True)
            logger.info("Enabled local search FTS with tokenizer: %s", self._search_fts_tokenizer)
            return

        self._search_fts_tokenizer = None
        self._db_encryption_status["fts_available"] = False
        self._db_encryption_status["fts_tokenizer"] = ""
        logger.info("SQLite FTS5 search unavailable; falling back to LIKE queries")

    async def _detect_search_fts_tokenizer(self) -> Optional[str]:
        """Return the tokenizer used by the existing search FTS tables, if any."""
        cursor = await self._db.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'message_search_fts'
            """
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        sql = str(row["sql"] or "").lower()
        if "trigram" in sql:
            return "trigram"
        if "unicode61" in sql:
            return "unicode61 remove_diacritics 2"
        return None

    async def _create_search_fts_schema(self, tokenizer: str) -> None:
        """Create search FTS tables and sync triggers for one tokenizer."""
        token_clause = str(tokenizer or "").strip()
        if not token_clause:
            raise ValueError("FTS tokenizer is required")

        await self._db.executescript(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS message_search_fts USING fts5(
                content,
                content='messages',
                content_rowid='rowid',
                tokenize='{token_clause}'
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS contact_search_fts USING fts5(
                display_name,
                nickname,
                remark,
                assistim_id,
                region,
                content='contacts_cache',
                content_rowid='rowid',
                tokenize='{token_clause}'
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS group_search_fts USING fts5(
                name,
                member_search_text,
                content='groups_cache',
                content_rowid='rowid',
                tokenize='{token_clause}'
            );

            CREATE TRIGGER IF NOT EXISTS messages_search_ai AFTER INSERT ON messages BEGIN
                INSERT INTO message_search_fts(rowid, content)
                VALUES (
                    new.rowid,
                    CASE
                        WHEN COALESCE(new.is_encrypted, 0) = 1 THEN ''
                        ELSE new.content
                    END
                );
            END;

            CREATE TRIGGER IF NOT EXISTS messages_search_ad AFTER DELETE ON messages BEGIN
                INSERT INTO message_search_fts(message_search_fts, rowid, content)
                VALUES (
                    'delete',
                    old.rowid,
                    CASE
                        WHEN COALESCE(old.is_encrypted, 0) = 1 THEN ''
                        ELSE old.content
                    END
                );
            END;

            CREATE TRIGGER IF NOT EXISTS messages_search_au AFTER UPDATE ON messages BEGIN
                INSERT INTO message_search_fts(message_search_fts, rowid, content)
                VALUES (
                    'delete',
                    old.rowid,
                    CASE
                        WHEN COALESCE(old.is_encrypted, 0) = 1 THEN ''
                        ELSE old.content
                    END
                );
                INSERT INTO message_search_fts(rowid, content)
                VALUES (
                    new.rowid,
                    CASE
                        WHEN COALESCE(new.is_encrypted, 0) = 1 THEN ''
                        ELSE new.content
                    END
                );
            END;

            CREATE TRIGGER IF NOT EXISTS contacts_search_ai AFTER INSERT ON contacts_cache BEGIN
                INSERT INTO contact_search_fts(rowid, display_name, nickname, remark, assistim_id, region)
                VALUES (new.rowid, new.display_name, new.nickname, new.remark, new.assistim_id, new.region);
            END;

            CREATE TRIGGER IF NOT EXISTS contacts_search_ad AFTER DELETE ON contacts_cache BEGIN
                INSERT INTO contact_search_fts(contact_search_fts, rowid, display_name, nickname, remark, assistim_id, region)
                VALUES ('delete', old.rowid, old.display_name, old.nickname, old.remark, old.assistim_id, old.region);
            END;

            CREATE TRIGGER IF NOT EXISTS contacts_search_au AFTER UPDATE ON contacts_cache BEGIN
                INSERT INTO contact_search_fts(contact_search_fts, rowid, display_name, nickname, remark, assistim_id, region)
                VALUES ('delete', old.rowid, old.display_name, old.nickname, old.remark, old.assistim_id, old.region);
                INSERT INTO contact_search_fts(rowid, display_name, nickname, remark, assistim_id, region)
                VALUES (new.rowid, new.display_name, new.nickname, new.remark, new.assistim_id, new.region);
            END;

            CREATE TRIGGER IF NOT EXISTS groups_search_ai AFTER INSERT ON groups_cache BEGIN
                INSERT INTO group_search_fts(rowid, name, member_search_text)
                VALUES (new.rowid, new.name, new.member_search_text);
            END;

            CREATE TRIGGER IF NOT EXISTS groups_search_ad AFTER DELETE ON groups_cache BEGIN
                INSERT INTO group_search_fts(group_search_fts, rowid, name, member_search_text)
                VALUES ('delete', old.rowid, old.name, old.member_search_text);
            END;

            CREATE TRIGGER IF NOT EXISTS groups_search_au AFTER UPDATE ON groups_cache BEGIN
                INSERT INTO group_search_fts(group_search_fts, rowid, name, member_search_text)
                VALUES ('delete', old.rowid, old.name, old.member_search_text);
                INSERT INTO group_search_fts(rowid, name, member_search_text)
                VALUES (new.rowid, new.name, new.member_search_text);
            END;
            """
        )
        await self._db.commit()

    async def _drop_search_fts_schema(self) -> None:
        """Drop partially created search FTS tables after one failed attempt."""
        await self._db.executescript(
            """
            DROP TRIGGER IF EXISTS messages_search_ai;
            DROP TRIGGER IF EXISTS messages_search_ad;
            DROP TRIGGER IF EXISTS messages_search_au;
            DROP TRIGGER IF EXISTS contacts_search_ai;
            DROP TRIGGER IF EXISTS contacts_search_ad;
            DROP TRIGGER IF EXISTS contacts_search_au;
            DROP TRIGGER IF EXISTS groups_search_ai;
            DROP TRIGGER IF EXISTS groups_search_ad;
            DROP TRIGGER IF EXISTS groups_search_au;
            DROP TABLE IF EXISTS message_search_fts;
            DROP TABLE IF EXISTS contact_search_fts;
            DROP TABLE IF EXISTS group_search_fts;
            """
        )
        await self._db.commit()

    async def _rebuild_search_fts_if_needed(self, *, force: bool = False) -> None:
        """Backfill FTS tables from current cache contents when needed."""
        if not self._search_fts_tokenizer and not force:
            return

        rebuild_specs = (
            ("messages", "message_search_fts"),
            ("contacts_cache", "contact_search_fts"),
            ("groups_cache", "group_search_fts"),
        )
        rebuilt = False

        for base_table, fts_table in rebuild_specs:
            if force or await self._fts_table_requires_rebuild(base_table, fts_table):
                await self._db.execute(
                    f"INSERT INTO {fts_table}({fts_table}) VALUES ('rebuild')"
                )
                rebuilt = True
        if rebuilt:
            await self._db.commit()

    async def _table_row_count(self, table_name: str) -> int:
        """Return the current row count for one SQLite table."""
        cursor = await self._db.execute(f"SELECT COUNT(*) AS count FROM {table_name}")
        row = await cursor.fetchone()
        return int((row["count"] if row is not None else 0) or 0)

    async def _fts_table_requires_rebuild(self, base_table: str, fts_table: str) -> bool:
        """Return whether one FTS index drifted from its source table."""
        base_count = await self._table_row_count(base_table)
        fts_count = await self._table_row_count(fts_table)
        if base_count != fts_count:
            return True
        try:
            await self._db.execute(
                f"INSERT INTO {fts_table}({fts_table}) VALUES ('integrity-check')"
            )
        except Exception as exc:
            logger.debug("FTS integrity check failed for %s: %s", fts_table, exc)
            return True
        return False

    async def _normalize_cached_session_types(self) -> None:
        """Upgrade legacy cached one-to-one sessions to the canonical direct type."""
        cursor = await self._db.execute(
            "UPDATE sessions SET session_type = 'direct' WHERE session_type = 'private'"
        )
        await self._db.commit()
        if int(getattr(cursor, "rowcount", 0) or 0) > 0:
            logger.info("Normalized %s cached sessions from private to direct", cursor.rowcount)
    
    # ============== Session Operations ==============
    
    async def save_session(self, session: Session) -> None:
        """
        Save or update a session.
        
        Args:
            session: Session to save
        """
        await self._db.execute(
            """
            INSERT OR REPLACE INTO sessions 
            (session_id, name, session_type, participant_ids, last_message, 
             last_message_time, unread_count, avatar, is_ai_session, extra,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                session.name,
                session.session_type,
                json.dumps(session.participant_ids),
                session.last_message,
                session.last_message_time.timestamp() if session.last_message_time else None,
                session.unread_count,
                session.avatar,
                1 if session.is_ai_session else 0,
                json.dumps(session.extra),
                session.created_at.timestamp() if session.created_at else None,
                session.updated_at.timestamp() if session.updated_at else None,
            ),
        )
        await self._db.commit()
        logger.debug(f"Session saved: {session.session_id}")

    async def save_sessions_batch(self, sessions: list[Session]) -> None:
        """
        Save multiple sessions in a single transaction.

        Args:
            sessions: Sessions to save
        """
        if not sessions:
            return

        for session in sessions:
            await self._db.execute(
                """
                INSERT OR REPLACE INTO sessions
                (session_id, name, session_type, participant_ids, last_message,
                 last_message_time, unread_count, avatar, is_ai_session, extra,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.name,
                    session.session_type,
                    json.dumps(session.participant_ids),
                    session.last_message,
                    session.last_message_time.timestamp() if session.last_message_time else None,
                    session.unread_count,
                    session.avatar,
                    1 if session.is_ai_session else 0,
                    json.dumps(session.extra),
                    session.created_at.timestamp() if session.created_at else None,
                    session.updated_at.timestamp() if session.updated_at else None,
                ),
            )

        await self._db.commit()
        logger.debug(f"Batch saved {len(sessions)} sessions")

    async def replace_sessions(self, sessions: list[Session]) -> None:
        """Replace the cached session list and prune state for sessions outside the snapshot."""
        snapshot_ids = [str(session.session_id or "").strip() for session in sessions if str(session.session_id or "").strip()]
        try:
            await self._db.execute("BEGIN")
            if snapshot_ids:
                placeholders = ", ".join("?" for _ in snapshot_ids)
                await self._db.execute(
                    f"DELETE FROM messages WHERE session_id NOT IN ({placeholders})",
                    snapshot_ids,
                )
                await self._db.execute(
                    f"DELETE FROM session_read_cursors WHERE session_id NOT IN ({placeholders})",
                    snapshot_ids,
                )
            else:
                await self._db.execute("DELETE FROM messages")
                await self._db.execute("DELETE FROM session_read_cursors")

            await self._db.execute("DELETE FROM sessions")
            for session in sessions:
                await self._db.execute(
                    """
                    INSERT OR REPLACE INTO sessions (
                        session_id, name, session_type, participant_ids,
                        last_message, last_message_time, unread_count,
                        avatar, is_ai_session, extra, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.session_id,
                        session.name,
                        session.session_type,
                        json.dumps(session.participant_ids),
                        session.last_message,
                        session.last_message_time.timestamp() if session.last_message_time else None,
                        session.unread_count,
                        session.avatar,
                        1 if session.is_ai_session else 0,
                        json.dumps(session.extra),
                        session.created_at.timestamp() if session.created_at else None,
                        session.updated_at.timestamp() if session.updated_at else None,
                    ),
                )
            await self._db.commit()
        except Exception:
            await self._db.execute("ROLLBACK")
            raise
        logger.debug(f"Replaced session cache with {len(sessions)} sessions")
    async def get_session(self, session_id: str) -> Optional[Session]:
        """
        Get a session by ID.
        
        Args:
            session_id: Session ID
        
        Returns:
            Session or None if not found
        """
        cursor = await self._db.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        
        if row is None:
            return None
        
        return self._row_to_session(row)

    async def get_session_search_metadata(self, session_ids: list[str]) -> dict[str, dict[str, str]]:
        """Return lightweight session metadata for one batch of search hits."""
        normalized_ids = [str(session_id or "").strip() for session_id in session_ids if str(session_id or "").strip()]
        if not normalized_ids:
            return {}

        placeholders = ", ".join("?" for _ in normalized_ids)
        cursor = await self._db.execute(
            f"""
            SELECT session_id, name, avatar, session_type, extra
            FROM sessions
            WHERE session_id IN ({placeholders})
            """,
            tuple(normalized_ids),
        )
        rows = await cursor.fetchall()
        metadata: dict[str, dict[str, str]] = {}
        for row in rows:
            extra = json.loads(row["extra"] or "{}")
            if not isinstance(extra, dict):
                extra = {}
            session_type = str(row["session_type"] or "")
            session_avatar = str(row["avatar"] or "")
            if session_type == "direct":
                session_avatar = str(extra.get("counterpart_avatar") or session_avatar or "")
            metadata[str(row["session_id"])] = {
                "session_name": str(row["name"] or ""),
                "session_avatar": session_avatar,
                "session_type": session_type,
            }
        return metadata
    
    async def get_all_sessions(self) -> list[Session]:
        """
        Get all sessions ordered by last update.
        
        Returns:
            List of sessions
        """
        cursor = await self._db.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
        return [self._row_to_session(row) for row in rows]
    
    async def delete_session(self, session_id: str) -> None:
        """
        Delete a session and its messages.
        
        Args:
            session_id: Session ID
        """
        await self._db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await self._db.execute("DELETE FROM session_read_cursors WHERE session_id = ?", (session_id,))
        await self._db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        await self._db.commit()
        logger.debug(f"Session deleted: {session_id}")

    async def list_session_message_ids(self, session_id: str) -> list[str]:
        """Return all persisted message ids for one session."""
        cursor = await self._db.execute(
            "SELECT message_id FROM messages WHERE session_id = ?",
            (session_id,),
        )
        rows = await cursor.fetchall()
        return [str(row["message_id"] or "") for row in rows if str(row["message_id"] or "")]

    async def list_session_local_attachment_paths(self, session_id: str) -> list[str]:
        """Return all cached local attachment paths referenced by one session."""
        cursor = await self._db.execute(
            "SELECT extra FROM messages WHERE session_id = ?",
            (session_id,),
        )
        rows = await cursor.fetchall()
        local_paths: list[str] = []
        for row in rows:
            try:
                extra = json.loads(str(row["extra"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                extra = {}
            local_path = str(dict(extra or {}).get("local_path") or "").strip()
            if local_path:
                local_paths.append(local_path)
        return local_paths
    
    async def update_session_unread(self, session_id: str, count: int) -> None:
        """
        Update session unread count.
        
        Args:
            session_id: Session ID
            count: New unread count
        """
        await self._db.execute(
            "UPDATE sessions SET unread_count = ?, updated_at = ? WHERE session_id = ?",
            (count, __import__("time").time(), session_id),
        )
        await self._db.commit()
    
    def _row_to_session(self, row: aiosqlite.Row) -> Session:
        """Convert database row to Session."""
        import datetime
        
        created_at = row["created_at"]
        if created_at:
            created_at = datetime.datetime.fromtimestamp(created_at)
        
        updated_at = row["updated_at"]
        if updated_at:
            updated_at = datetime.datetime.fromtimestamp(updated_at)
        
        last_message_time = row["last_message_time"]
        if last_message_time:
            last_message_time = datetime.datetime.fromtimestamp(last_message_time)
        
        return Session(
            session_id=row["session_id"],
            name=row["name"],
            session_type=row["session_type"],
            participant_ids=json.loads(row["participant_ids"]),
            last_message=row["last_message"],
            last_message_time=last_message_time,
            unread_count=row["unread_count"],
            avatar=row["avatar"],
            is_ai_session=bool(row["is_ai_session"]),
            extra=json.loads(row["extra"]),
            created_at=created_at,
            updated_at=updated_at,
        )
    
    # ============== Message Operations ==============
    
    async def save_message(self, message: ChatMessage) -> None:
        """
        Save or update a message.
        
        Args:
            message: Message to save
        """
        is_encrypted, encryption_scheme = self._message_crypto_storage_fields(message)
        await self._db.execute(
            """
            INSERT OR REPLACE INTO messages
            (message_id, session_id, sender_id, content, message_type,
             status, timestamp, updated_at, is_self, is_ai, is_encrypted, encryption_scheme, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.message_id,
                message.session_id,
                message.sender_id,
                self._content_for_storage(message),
                message.message_type.value,
                message.status.value,
                message.timestamp.timestamp() if message.timestamp else None,
                message.updated_at.timestamp() if message.updated_at else None,
                1 if message.is_self else 0,
                1 if message.is_ai else 0,
                is_encrypted,
                encryption_scheme,
                json.dumps(message.extra),
            ),
        )
        await self._db.commit()
        logger.debug(f"Message saved: {message.message_id}")
    
    async def get_message(self, message_id: str) -> Optional[ChatMessage]:
        """
        Get a message by ID.
        
        Args:
            message_id: Message ID
        
        Returns:
            Message or None if not found
        """
        cursor = await self._db.execute(
            "SELECT * FROM messages WHERE message_id = ?",
            (message_id,),
        )
        row = await cursor.fetchone()
        
        if row is None:
            return None

        message = self._row_to_message(row)
        read_cursors = await self._load_session_read_cursors(message.session_id)
        return self._overlay_read_cursors_on_message(message, read_cursors)

    async def get_existing_message_ids(self, message_ids: list[str]) -> set[str]:
        """
        Return the subset of provided message ids that already exist.

        Args:
            message_ids: Candidate ids

        Returns:
            Existing ids
        """
        ids = [message_id for message_id in message_ids if message_id]
        if not ids:
            return set()

        placeholders = ", ".join("?" for _ in ids)
        cursor = await self._db.execute(
            f"SELECT message_id FROM messages WHERE message_id IN ({placeholders})",
            ids,
        )
        rows = await cursor.fetchall()
        return {row["message_id"] for row in rows}

    async def get_messages_by_ids(self, message_ids: list[str]) -> dict[str, ChatMessage]:
        """Return cached messages keyed by id for one batch of candidate ids."""
        ids = list(dict.fromkeys(message_id for message_id in message_ids if message_id))
        if not ids:
            return {}

        placeholders = ", ".join("?" for _ in ids)
        cursor = await self._db.execute(
            f"SELECT * FROM messages WHERE message_id IN ({placeholders})",
            ids,
        )
        rows = await cursor.fetchall()
        messages = [self._row_to_message(row) for row in rows]
        read_cursors_by_session = {
            session_id: await self._load_session_read_cursors(session_id)
            for session_id in {message.session_id for message in messages}
        }
        return {
            message.message_id: self._overlay_read_cursors_on_message(
                message,
                read_cursors_by_session.get(message.session_id, {}),
            )
            for message in messages
        }
    
    async def get_messages(
        self,
        session_id: str,
        limit: int = 50,
        before_timestamp: Optional[float] = None,
    ) -> list[ChatMessage]:
        """
        Get messages for a session.
        
        Args:
            session_id: Session ID
            limit: Maximum number of messages
            before_timestamp: Load messages before this timestamp
        
        Returns:
            List of messages (newest first)
        """
        if before_timestamp:
            cursor = await self._db.execute(
                """
                SELECT * FROM messages 
                WHERE session_id = ? AND timestamp < ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (session_id, before_timestamp, limit),
            )
        else:
            cursor = await self._db.execute(
                """
                SELECT * FROM messages 
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (session_id, limit),
            )
        
        rows = await cursor.fetchall()
        read_cursors = await self._load_session_read_cursors(session_id)
        messages = [self._overlay_read_cursors_on_message(self._row_to_message(row), read_cursors) for row in rows]
        messages.reverse()
        return messages

    @staticmethod
    def _escape_like_pattern(keyword: str) -> str:
        """Escape one keyword for literal SQLite LIKE matching."""
        escaped = str(keyword or "")
        escaped = escaped.replace("\\", "\\\\")
        escaped = escaped.replace("%", "\\%")
        escaped = escaped.replace("_", "\\_")
        return f"%{escaped}%"

    def _should_use_search_fts(self, keyword: str) -> bool:
        """Return whether the current keyword should use the local FTS path."""
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword or not self._search_fts_tokenizer:
            return False
        if self._search_fts_tokenizer == "trigram":
            return len(normalized_keyword) >= 3
        return len(normalized_keyword) >= 2

    @staticmethod
    def _build_fts_match_query(keyword: str) -> str:
        """Quote one literal keyword for SQLite FTS MATCH."""
        normalized_keyword = str(keyword or "").strip().replace('"', '""')
        return f'"{normalized_keyword}"'

    async def search_messages(
        self,
        keyword: str,
        session_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[ChatMessage]:
        """Search cached messages by one literal keyword."""
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return []

        normalized_limit = max(1, int(limit or 0))
        if self._should_use_search_fts(normalized_keyword):
            try:
                return await self._search_messages_fts(normalized_keyword, session_id=session_id, limit=normalized_limit)
            except Exception as exc:
                logger.debug("Message FTS search failed, falling back to LIKE: %s", exc)
        like_pattern = self._escape_like_pattern(normalized_keyword)

        if session_id:
            cursor = await self._db.execute(
                """
                SELECT * FROM messages
                WHERE session_id = ?
                  AND COALESCE(is_encrypted, 0) != 1
                  AND content LIKE ? ESCAPE '\\'
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (session_id, like_pattern, normalized_limit),
            )
        else:
            cursor = await self._db.execute(
                """
                SELECT * FROM messages
                WHERE COALESCE(is_encrypted, 0) != 1
                  AND content LIKE ? ESCAPE '\\'
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (like_pattern, normalized_limit),
            )

        rows = await cursor.fetchall()
        return [self._row_to_message(row) for row in rows]

    async def count_search_message_sessions(
        self,
        keyword: str,
        session_id: Optional[str] = None,
    ) -> int:
        """Count unique sessions matching one message-search keyword."""
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return 0

        if self._should_use_search_fts(normalized_keyword):
            try:
                return await self._count_search_message_sessions_fts(normalized_keyword, session_id=session_id)
            except Exception as exc:
                logger.debug("Message FTS count failed, falling back to LIKE: %s", exc)

        like_pattern = self._escape_like_pattern(normalized_keyword)
        if session_id:
            cursor = await self._db.execute(
                """
                SELECT COUNT(DISTINCT session_id) AS count
                FROM messages
                WHERE session_id = ?
                  AND COALESCE(is_encrypted, 0) != 1
                  AND content LIKE ? ESCAPE '\\'
                """,
                (session_id, like_pattern),
            )
        else:
            cursor = await self._db.execute(
                """
                SELECT COUNT(DISTINCT session_id) AS count
                FROM messages
                WHERE COALESCE(is_encrypted, 0) != 1
                  AND content LIKE ? ESCAPE '\\'
                """,
                (like_pattern,),
            )
        row = await cursor.fetchone()
        return int((row["count"] if row is not None else 0) or 0)

    async def _search_messages_fts(
        self,
        keyword: str,
        *,
        session_id: Optional[str],
        limit: int,
    ) -> list[ChatMessage]:
        """Search cached messages through the FTS5 index."""
        match_query = self._build_fts_match_query(keyword)
        if session_id:
            cursor = await self._db.execute(
                """
                SELECT m.*
                FROM message_search_fts f
                JOIN messages m ON m.rowid = f.rowid
                WHERE message_search_fts MATCH ?
                  AND m.session_id = ?
                  AND COALESCE(m.is_encrypted, 0) != 1
                ORDER BY bm25(message_search_fts), m.timestamp DESC
                LIMIT ?
                """,
                (match_query, session_id, limit),
            )
        else:
            cursor = await self._db.execute(
                """
                SELECT m.*
                FROM message_search_fts f
                JOIN messages m ON m.rowid = f.rowid
                WHERE message_search_fts MATCH ?
                  AND COALESCE(m.is_encrypted, 0) != 1
                ORDER BY bm25(message_search_fts), m.timestamp DESC
                LIMIT ?
                """,
                (match_query, limit),
            )
        rows = await cursor.fetchall()
        return [self._row_to_message(row) for row in rows]

    async def _count_search_message_sessions_fts(
        self,
        keyword: str,
        *,
        session_id: Optional[str],
    ) -> int:
        """Count distinct message sessions through the FTS5 index."""
        match_query = self._build_fts_match_query(keyword)
        if session_id:
            cursor = await self._db.execute(
                """
                SELECT COUNT(DISTINCT m.session_id) AS count
                FROM message_search_fts f
                JOIN messages m ON m.rowid = f.rowid
                WHERE message_search_fts MATCH ?
                  AND m.session_id = ?
                  AND COALESCE(m.is_encrypted, 0) != 1
                """,
                (match_query, session_id),
            )
        else:
            cursor = await self._db.execute(
                """
                SELECT COUNT(DISTINCT m.session_id) AS count
                FROM message_search_fts f
                JOIN messages m ON m.rowid = f.rowid
                WHERE message_search_fts MATCH ?
                  AND COALESCE(m.is_encrypted, 0) != 1
                """,
                (match_query,),
            )
        row = await cursor.fetchone()
        return int((row["count"] if row is not None else 0) or 0)

    async def _resolve_directory_cache_owner_user_id(self, owner_user_id: str | None = None) -> str:
        """Return the authoritative owner for one directory-cache read or write."""
        normalized_owner = str(owner_user_id or "").strip()
        if normalized_owner:
            return normalized_owner
        return str(await self.get_app_state(self.AUTH_USER_ID_STATE_KEY) or "").strip()

    async def replace_contacts_cache(
        self,
        contacts: list[dict[str, Any]],
        *,
        owner_user_id: str | None = None,
    ) -> None:
        """Replace the cached contact directory snapshot."""
        normalized_owner = await self._resolve_directory_cache_owner_user_id(owner_user_id)
        if not normalized_owner:
            logger.debug("Skip replacing contacts cache without one active owner scope")
            return

        updated_at = int(time.time())
        try:
            await self._db.execute("BEGIN")
            await self._db.execute(
                "DELETE FROM contacts_cache WHERE owner_user_id = ?",
                (normalized_owner,),
            )

            for contact in contacts:
                extra = dict(contact.get("extra") or {})
                await self._db.execute(
                    """
                    INSERT OR REPLACE INTO contacts_cache
                    (owner_user_id, contact_id, display_name, username, nickname, remark,
                     assistim_id, region, avatar, signature, category, status, extra, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_owner,
                        str(contact.get("id", "") or ""),
                        str(contact.get("display_name") or contact.get("name") or ""),
                        str(contact.get("username", "") or ""),
                        str(contact.get("nickname", "") or ""),
                        str(contact.get("remark", "") or ""),
                        str(contact.get("assistim_id", "") or ""),
                        str(contact.get("region", "") or ""),
                        str(contact.get("avatar", "") or ""),
                        str(contact.get("signature", "") or ""),
                        str(contact.get("category", "friend") or "friend"),
                        str(contact.get("status", "") or ""),
                        json.dumps(extra),
                        updated_at,
                    ),
                )

            await self._db.commit()
        except Exception:
            await self._db.execute("ROLLBACK")
            raise
        logger.debug(f"Replaced contact cache with {len(contacts)} contacts for owner {normalized_owner}")

    async def replace_groups_cache(
        self,
        groups: list[dict[str, Any]],
        *,
        owner_user_id: str | None = None,
    ) -> None:
        """Replace the cached group directory snapshot."""
        normalized_owner = await self._resolve_directory_cache_owner_user_id(owner_user_id)
        if not normalized_owner:
            logger.debug("Skip replacing groups cache without one active owner scope")
            return

        updated_at = int(time.time())
        try:
            await self._db.execute("BEGIN")
            await self._db.execute(
                "DELETE FROM groups_cache WHERE owner_user_id = ?",
                (normalized_owner,),
            )

            for group in groups:
                extra = dict(group.get("extra") or {})
                member_search_text = str(group.get("member_search_text", "") or "")
                await self._db.execute(
                    """
                    INSERT OR REPLACE INTO groups_cache
                    (owner_user_id, group_id, name, avatar, owner_id, session_id, member_count, member_search_text, extra, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_owner,
                        str(group.get("id", "") or ""),
                        str(group.get("name", "") or ""),
                        str(group.get("avatar", "") or ""),
                        str(group.get("owner_id", "") or ""),
                        str(group.get("session_id", "") or ""),
                        max(0, int(group.get("member_count", 0) or 0)),
                        member_search_text,
                        json.dumps(extra),
                        updated_at,
                    ),
                )

            await self._db.commit()
        except Exception:
            await self._db.execute("ROLLBACK")
            raise
        logger.debug(f"Replaced group cache with {len(groups)} groups for owner {normalized_owner}")

    async def list_contacts_cache_by_ids(
        self,
        contact_ids: list[str],
        *,
        owner_user_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Return one contact lookup map for the given ids."""
        normalized_ids = [
            value
            for value in dict.fromkeys(str(contact_id or "").strip() for contact_id in (contact_ids or []))
            if value
        ]
        if not normalized_ids:
            return {}
        normalized_owner = await self._resolve_directory_cache_owner_user_id(owner_user_id)
        if not normalized_owner:
            return {}

        placeholders = ",".join("?" for _ in normalized_ids)
        cursor = await self._db.execute(
            f"SELECT * FROM contacts_cache WHERE owner_user_id = ? AND contact_id IN ({placeholders})",
            (normalized_owner, *normalized_ids),
        )
        rows = await cursor.fetchall()
        return {
            payload["id"]: payload
            for payload in (self._row_to_contact_cache(row) for row in rows)
            if str(payload.get("id", "") or "").strip()
        }

    async def search_contacts(
        self,
        keyword: str,
        limit: int = 50,
        *,
        owner_user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search cached contacts by one literal keyword."""
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return []
        normalized_owner = await self._resolve_directory_cache_owner_user_id(owner_user_id)
        if not normalized_owner:
            return []

        normalized_limit = max(1, int(limit or 0))
        if self._should_use_search_fts(normalized_keyword):
            try:
                return await self._search_contacts_fts(
                    normalized_keyword,
                    owner_user_id=normalized_owner,
                    limit=normalized_limit,
                )
            except Exception as exc:
                logger.debug("Contact FTS search failed, falling back to LIKE: %s", exc)
        like_pattern = self._escape_like_pattern(normalized_keyword)
        cursor = await self._db.execute(
            """
            SELECT * FROM contacts_cache
            WHERE owner_user_id = ?
              AND (
                   display_name LIKE ? ESCAPE '\\'
               OR nickname LIKE ? ESCAPE '\\'
               OR remark LIKE ? ESCAPE '\\'
               OR assistim_id LIKE ? ESCAPE '\\'
               OR region LIKE ? ESCAPE '\\'
              )
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (
                normalized_owner,
                like_pattern,
                like_pattern,
                like_pattern,
                like_pattern,
                like_pattern,
                normalized_limit,
            ),
        )
        rows = await cursor.fetchall()
        return [self._row_to_contact_cache(row) for row in rows]

    async def count_search_contacts(self, keyword: str, *, owner_user_id: str | None = None) -> int:
        """Count contact search hits for one keyword."""
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return 0
        normalized_owner = await self._resolve_directory_cache_owner_user_id(owner_user_id)
        if not normalized_owner:
            return 0

        if self._should_use_search_fts(normalized_keyword):
            try:
                cursor = await self._db.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM contact_search_fts f
                    JOIN contacts_cache c ON c.rowid = f.rowid
                    WHERE contact_search_fts MATCH ?
                      AND c.owner_user_id = ?
                    """,
                    (self._build_fts_match_query(normalized_keyword), normalized_owner),
                )
                row = await cursor.fetchone()
                return int((row["count"] if row is not None else 0) or 0)
            except Exception as exc:
                logger.debug("Contact FTS count failed, falling back to LIKE: %s", exc)

        like_pattern = self._escape_like_pattern(normalized_keyword)
        cursor = await self._db.execute(
            """
            SELECT COUNT(*) AS count
            FROM contacts_cache
            WHERE owner_user_id = ?
              AND (
                   display_name LIKE ? ESCAPE '\\'
               OR nickname LIKE ? ESCAPE '\\'
               OR remark LIKE ? ESCAPE '\\'
               OR assistim_id LIKE ? ESCAPE '\\'
               OR region LIKE ? ESCAPE '\\'
              )
            """,
            (
                normalized_owner,
                like_pattern,
                like_pattern,
                like_pattern,
                like_pattern,
                like_pattern,
            ),
        )
        row = await cursor.fetchone()
        return int((row["count"] if row is not None else 0) or 0)

    async def _search_contacts_fts(
        self,
        keyword: str,
        *,
        owner_user_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Search cached contacts through the FTS5 index."""
        cursor = await self._db.execute(
            """
            SELECT c.*
            FROM contact_search_fts f
            JOIN contacts_cache c ON c.rowid = f.rowid
            WHERE contact_search_fts MATCH ?
              AND c.owner_user_id = ?
            ORDER BY bm25(contact_search_fts), c.updated_at DESC
            LIMIT ?
            """,
            (self._build_fts_match_query(keyword), owner_user_id, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_contact_cache(row) for row in rows]

    async def search_groups(
        self,
        keyword: str,
        limit: int = 50,
        *,
        owner_user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search cached groups by one literal keyword."""
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return []
        normalized_owner = await self._resolve_directory_cache_owner_user_id(owner_user_id)
        if not normalized_owner:
            return []

        normalized_limit = max(1, int(limit or 0))
        if self._should_use_search_fts(normalized_keyword):
            try:
                return await self._search_groups_fts(
                    normalized_keyword,
                    owner_user_id=normalized_owner,
                    limit=normalized_limit,
                )
            except Exception as exc:
                logger.debug("Group FTS search failed, falling back to LIKE: %s", exc)
        like_pattern = self._escape_like_pattern(normalized_keyword)
        cursor = await self._db.execute(
            """
            SELECT * FROM groups_cache
            WHERE owner_user_id = ?
              AND (
                   name LIKE ? ESCAPE '\\'
               OR member_search_text LIKE ? ESCAPE '\\'
              )
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (
                normalized_owner,
                like_pattern,
                like_pattern,
                normalized_limit,
            ),
        )
        rows = await cursor.fetchall()
        return [self._row_to_group_cache(row) for row in rows]

    async def count_search_groups(self, keyword: str, *, owner_user_id: str | None = None) -> int:
        """Count group search hits for one keyword."""
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return 0
        normalized_owner = await self._resolve_directory_cache_owner_user_id(owner_user_id)
        if not normalized_owner:
            return 0

        if self._should_use_search_fts(normalized_keyword):
            try:
                cursor = await self._db.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM group_search_fts f
                    JOIN groups_cache g ON g.rowid = f.rowid
                    WHERE group_search_fts MATCH ?
                      AND g.owner_user_id = ?
                    """,
                    (self._build_fts_match_query(normalized_keyword), normalized_owner),
                )
                row = await cursor.fetchone()
                return int((row["count"] if row is not None else 0) or 0)
            except Exception as exc:
                logger.debug("Group FTS count failed, falling back to LIKE: %s", exc)

        like_pattern = self._escape_like_pattern(normalized_keyword)
        cursor = await self._db.execute(
            """
            SELECT COUNT(*) AS count
            FROM groups_cache
            WHERE owner_user_id = ?
              AND (
                   name LIKE ? ESCAPE '\\'
               OR member_search_text LIKE ? ESCAPE '\\'
              )
            """,
            (normalized_owner, like_pattern, like_pattern),
        )
        row = await cursor.fetchone()
        return int((row["count"] if row is not None else 0) or 0)

    async def _search_groups_fts(
        self,
        keyword: str,
        *,
        owner_user_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Search cached groups through the FTS5 index."""
        cursor = await self._db.execute(
            """
            SELECT g.*
            FROM group_search_fts f
            JOIN groups_cache g ON g.rowid = f.rowid
            WHERE group_search_fts MATCH ?
              AND g.owner_user_id = ?
            ORDER BY bm25(group_search_fts), g.updated_at DESC
            LIMIT ?
            """,
            (self._build_fts_match_query(keyword), owner_user_id, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_group_cache(row) for row in rows]

    def _row_to_contact_cache(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert one cached contact row into a normalized payload."""
        return {
            "id": row["contact_id"],
            "name": row["display_name"],
            "display_name": row["display_name"],
            "username": row["username"],
            "nickname": row["nickname"],
            "remark": row["remark"],
            "assistim_id": row["assistim_id"],
            "region": row["region"],
            "avatar": row["avatar"],
            "signature": row["signature"],
            "category": row["category"],
            "status": row["status"],
            "extra": json.loads(row["extra"]),
        }

    def _row_to_group_cache(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert one cached group row into a normalized payload."""
        return {
            "id": row["group_id"],
            "name": row["name"],
            "avatar": row["avatar"],
            "owner_id": row["owner_id"],
            "session_id": row["session_id"],
            "member_count": row["member_count"],
            "member_search_text": row["member_search_text"],
            "extra": json.loads(row["extra"]),
        }
    
    async def delete_message(self, message_id: str) -> None:
        """
        Delete a message.

        Args:
            message_id: Message ID
        """
        await self._db.execute(
            "DELETE FROM messages WHERE message_id = ?",
            (message_id,),
        )
        await self._db.commit()
        logger.debug(f"Message deleted: {message_id}")

    async def update_message_status(self, message_id: str, status) -> None:
        """
        Update message status.

        Args:
            message_id: Message ID
            status: New message status
        """
        from client.models.message import MessageStatus

        status_value = status.value if isinstance(status, MessageStatus) else status

        await self._db.execute(
            "UPDATE messages SET status = ? WHERE message_id = ?",
            (status_value, message_id),
        )
        await self._db.commit()
        logger.debug(f"Message status updated: {message_id} -> {status_value}")

    async def apply_read_receipt(
        self,
        session_id: str,
        reader_id: str,
        message_id: str,
        last_read_seq: int,
    ) -> list[str]:
        """Persist one cumulative read cursor without rewriting every cached message row."""
        if not session_id or not reader_id or last_read_seq <= 0:
            return []

        cursor = await self._db.execute(
            """
            SELECT COALESCE(last_read_seq, 0) AS last_read_seq
            FROM session_read_cursors
            WHERE session_id = ? AND reader_id = ?
            """,
            (session_id, reader_id),
        )
        row = await cursor.fetchone()
        current_seq = max(0, int((row["last_read_seq"] if row is not None else 0) or 0))
        if current_seq >= last_read_seq:
            return []

        await self._db.execute(
            """
            INSERT INTO session_read_cursors (session_id, reader_id, last_read_seq, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id, reader_id) DO UPDATE SET
                last_read_seq = CASE
                    WHEN excluded.last_read_seq > session_read_cursors.last_read_seq THEN excluded.last_read_seq
                    ELSE session_read_cursors.last_read_seq
                END,
                updated_at = CASE
                    WHEN excluded.last_read_seq > session_read_cursors.last_read_seq THEN excluded.updated_at
                    ELSE session_read_cursors.updated_at
                END
            """,
            (session_id, reader_id, last_read_seq, time.time()),
        )
        await self._db.commit()

        logger.debug(
            f"Applied read receipt cursor: session={session_id}, reader={reader_id}, message={message_id}, seq={last_read_seq}"
        )
        return []


    async def _load_session_read_cursors(self, session_id: str) -> dict[str, int]:
        """Return the latest per-reader read cursor for one session."""
        if not session_id:
            return {}

        cursor = await self._db.execute(
            """
            SELECT reader_id, last_read_seq
            FROM session_read_cursors
            WHERE session_id = ?
            """,
            (session_id,),
        )
        rows = await cursor.fetchall()
        read_cursors: dict[str, int] = {}
        for row in rows:
            reader_id = str(row["reader_id"] or "").strip()
            if not reader_id:
                continue
            try:
                read_cursors[reader_id] = max(0, int(row["last_read_seq"] or 0))
            except (TypeError, ValueError):
                continue
        return read_cursors

    @staticmethod
    def _normalized_reader_ids(raw_reader_ids: list[Any]) -> list[str]:
        normalized_reader_ids: list[str] = []
        for existing_reader_id in raw_reader_ids or []:
            normalized_reader = str(existing_reader_id or "").strip()
            if normalized_reader and normalized_reader not in normalized_reader_ids:
                normalized_reader_ids.append(normalized_reader)
        normalized_reader_ids.sort()
        return normalized_reader_ids

    @staticmethod
    def _message_session_seq(message: ChatMessage) -> int:
        try:
            return max(0, int((message.extra or {}).get("session_seq", 0) or 0))
        except (TypeError, ValueError):
            return 0

    def _overlay_read_cursors_on_message(
        self,
        message: ChatMessage,
        read_cursors: dict[str, int],
    ) -> ChatMessage:
        """Project per-session read cursors onto one cached self message."""
        if not message.is_self or not read_cursors:
            return message

        from client.models.message import MessageStatus

        message_seq = self._message_session_seq(message)
        if message_seq <= 0:
            return message

        read_by_user_ids = self._normalized_reader_ids(list((message.extra or {}).get("read_by_user_ids") or []))
        changed = False
        for reader_id, reader_seq in read_cursors.items():
            if reader_seq < message_seq or reader_id == message.sender_id:
                continue
            if reader_id not in read_by_user_ids:
                read_by_user_ids.append(reader_id)
                changed = True

        if not changed and read_by_user_ids == list((message.extra or {}).get("read_by_user_ids") or []):
            return message

        read_by_user_ids = self._normalized_reader_ids(read_by_user_ids)
        read_target_count = max(0, int((message.extra or {}).get("read_target_count", 0) or 0))
        message.extra["read_by_user_ids"] = read_by_user_ids
        message.extra["read_count"] = len(read_by_user_ids)
        message.extra["read_target_count"] = read_target_count

        if read_by_user_ids and read_target_count <= 1 and message.status not in {MessageStatus.FAILED, MessageStatus.RECALLED}:
            message.status = MessageStatus.READ
        elif read_by_user_ids and message.status in {MessageStatus.SENT, MessageStatus.DELIVERED, MessageStatus.READ}:
            message.status = MessageStatus.DELIVERED

        return message

    async def update_message_content(self, message_id: str, content: str) -> None:
        """
        Update message content.

        Args:
            message_id: Message ID
            content: New message content
        """
        await self._db.execute(
            "UPDATE messages SET content = ? WHERE message_id = ?",
            (content, message_id),
        )
        await self._db.commit()
        logger.debug(f"Message content updated: {message_id}")

    async def delete_session_messages(self, session_id: str) -> None:
        """
        Delete all messages in a session.
        
        Args:
            session_id: Session ID
        """
        await self._db.execute(
            "DELETE FROM messages WHERE session_id = ?",
            (session_id,),
        )
        await self._db.execute(
            "DELETE FROM session_read_cursors WHERE session_id = ?",
            (session_id,),
        )
        await self._db.commit()
        logger.debug(f"Messages deleted for session: {session_id}")

    async def clear_chat_state(self) -> None:
        """Remove all locally cached sessions, messages, search caches, and sync markers."""
        await self._db.execute("DELETE FROM messages")
        await self._db.execute("DELETE FROM session_read_cursors")
        await self._db.execute("DELETE FROM sessions")
        await self._db.execute("DELETE FROM contacts_cache")
        await self._db.execute("DELETE FROM groups_cache")
        await self._db.execute(
            "DELETE FROM app_state WHERE key IN (?, ?, ?, ?)",
            ("last_sync_session_cursors", "last_sync_event_cursors", "last_sync_timestamp", "chat.hidden_sessions"),
        )
        await self._db.commit()
        logger.info("Local chat state cleared")
    
    async def get_last_message(self, session_id: str) -> Optional[ChatMessage]:
        """
        Get the last message in a session.
        
        Args:
            session_id: Session ID
        
        Returns:
            Last message or None
        """
        cursor = await self._db.execute(
            """
            SELECT * FROM messages 
            WHERE session_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (session_id,),
        )
        row = await cursor.fetchone()
        
        if row is None:
            return None

        message = self._row_to_message(row)
        read_cursors = await self._load_session_read_cursors(session_id)
        return self._overlay_read_cursors_on_message(message, read_cursors)

    async def get_message_count(self, session_id: str) -> int:
        """
        Get total message count for a session.
        
        Args:
            session_id: Session ID
        
        Returns:
            Number of messages
        """
        cursor = await self._db.execute(
            "SELECT COUNT(*) as count FROM messages WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        return row["count"] if row else 0

    async def get_session_last_timestamp(self, session_id: str) -> Optional[float]:
        """
        Get the latest message timestamp for a session.
        
        Args:
            session_id: Session ID
        
        Returns:
            Timestamp of latest message, or None
        """
        cursor = await self._db.execute(
            """
            SELECT MAX(timestamp) as last_timestamp 
            FROM messages 
            WHERE session_id = ?
            """,
            (session_id,),
        )
        row = await cursor.fetchone()
        return row["last_timestamp"] if row and row["last_timestamp"] else None

    async def get_latest_message_timestamp(self) -> Optional[float]:
        """
        Get the latest message timestamp across all sessions.

        Returns:
            Timestamp of latest message, or None
        """
        cursor = await self._db.execute(
            """
            SELECT MAX(timestamp) as last_timestamp
            FROM messages
            """
        )
        row = await cursor.fetchone()
        return row["last_timestamp"] if row and row["last_timestamp"] else None

    async def get_session_sync_cursors(self) -> dict[str, int]:
        """Return the highest cached session_seq per session for reconnect sync."""
        cursor = await self._db.execute(
            "SELECT session_id, extra FROM messages"
        )
        rows = await cursor.fetchall()

        session_cursors: dict[str, int] = {}
        for row in rows:
            session_id = str(row["session_id"] or "").strip()
            if not session_id:
                continue

            try:
                extra = json.loads(row["extra"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                extra = {}

            try:
                session_seq = max(0, int((extra or {}).get("session_seq", 0) or 0))
            except (TypeError, ValueError):
                session_seq = 0

            if session_seq <= 0:
                continue

            current_seq = session_cursors.get(session_id, 0)
            if session_seq > current_seq:
                session_cursors[session_id] = session_seq

        return session_cursors

    async def save_messages_batch(self, messages: list[ChatMessage]) -> None:
        """
        Save multiple messages in batch.
        
        Args:
            messages: List of messages to save
        """
        if not messages:
            return
        
        for message in messages:
            is_encrypted, encryption_scheme = self._message_crypto_storage_fields(message)
            await self._db.execute(
                """
                INSERT OR REPLACE INTO messages
                (message_id, session_id, sender_id, content, message_type,
                 status, timestamp, updated_at, is_self, is_ai, is_encrypted, encryption_scheme, extra)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.message_id,
                    message.session_id,
                    message.sender_id,
                    self._content_for_storage(message),
                    message.message_type.value,
                    message.status.value,
                    message.timestamp.timestamp() if message.timestamp else None,
                    message.updated_at.timestamp() if message.updated_at else None,
                    1 if message.is_self else 0,
                    1 if message.is_ai else 0,
                    is_encrypted,
                    encryption_scheme,
                    json.dumps(message.extra),
                ),
            )
        
        await self._db.commit()
        logger.debug(f"Batch saved {len(messages)} messages")

    async def apply_sender_profile_update(
        self,
        session_id: str,
        user_id: str,
        sender_profile: dict[str, Any],
    ) -> list[str]:
        """Apply one sender-profile update to cached messages for the affected session."""
        normalized_session_id = str(session_id or "").strip()
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return []

        if normalized_session_id:
            cursor = await self._db.execute(
                "SELECT message_id, extra FROM messages WHERE session_id = ? AND sender_id = ?",
                (normalized_session_id, normalized_user_id),
            )
        else:
            cursor = await self._db.execute(
                "SELECT message_id, extra FROM messages WHERE sender_id = ?",
                (normalized_user_id,),
            )
        rows = await cursor.fetchall()

        changed_message_ids: list[str] = []
        for row in rows:
            try:
                extra = json.loads(row["extra"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                extra = {}
            if not isinstance(extra, dict):
                extra = {}

            merged_extra = merge_sender_profile_extra(extra, sender_profile)
            if merged_extra == extra:
                continue

            await self._db.execute(
                "UPDATE messages SET extra = ? WHERE message_id = ?",
                (json.dumps(merged_extra), row["message_id"]),
            )
            changed_message_ids.append(str(row["message_id"] or ""))

        if changed_message_ids:
            await self._db.commit()
        return changed_message_ids
    
    def _row_to_message(self, row: aiosqlite.Row) -> ChatMessage:
        """Convert database row to ChatMessage."""
        import datetime
        from client.models.message import MessageStatus, MessageType
        
        timestamp = row["timestamp"]
        if timestamp:
            timestamp = datetime.datetime.fromtimestamp(timestamp)
        
        updated_at = row["updated_at"]
        if updated_at:
            updated_at = datetime.datetime.fromtimestamp(updated_at)

        try:
            extra = json.loads(row["extra"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            extra = {}
        if not isinstance(extra, dict):
            extra = {}

        return ChatMessage(
            message_id=row["message_id"],
            session_id=row["session_id"],
            sender_id=row["sender_id"],
            content=self._content_for_display(str(row["content"] or ""), extra),
            message_type=MessageType(row["message_type"]),
            status=MessageStatus(row["status"]),
            timestamp=timestamp,
            updated_at=updated_at,
            is_self=bool(row["is_self"]),
            is_ai=bool(row["is_ai"]),
            extra=extra,
        )

    @staticmethod
    def _content_for_storage(message: ChatMessage) -> str:
        encryption = dict((message.extra or {}).get("encryption") or {})
        if encryption.get("enabled"):
            ciphertext = str(encryption.get("content_ciphertext") or "").strip()
            if ciphertext:
                return ciphertext
        return str(message.content or "")

    @staticmethod
    def _message_crypto_storage_fields(message: ChatMessage) -> tuple[int, str]:
        encryption = dict((message.extra or {}).get("encryption") or {})
        attachment_encryption = dict((message.extra or {}).get("attachment_encryption") or {})
        if encryption.get("enabled"):
            return 1, str(encryption.get("scheme") or "").strip()
        if attachment_encryption.get("enabled"):
            return 1, str(attachment_encryption.get("scheme") or "").strip()
        return 0, ""

    @staticmethod
    def _content_for_display(content: str, extra: dict[str, Any]) -> str:
        encryption = dict((extra or {}).get("encryption") or {})
        if not encryption.get("enabled"):
            return content

        protected_plaintext = str(encryption.get("local_plaintext") or "").strip()
        if protected_plaintext:
            try:
                return SecureStorage.decrypt_text(protected_plaintext)
            except Exception as exc:
                logger.warning("Failed to decrypt locally protected message content: %s", exc)
        return ENCRYPTED_MESSAGE_PLACEHOLDER
    
    # ============== Utility ==============

    async def get_app_state(self, key: str) -> Optional[str]:
        """
        Get app state value.

        Args:
            key: State key

        Returns:
            State value or None
        """
        cursor = await self._db.execute(
            "SELECT value FROM app_state WHERE key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        return row["value"] if row else None

    async def replace_app_state(self, values: dict[str, str] | None = None, *, delete_keys: Iterable[str] = ()) -> None:
        """Atomically apply app-state key updates and deletions."""
        normalized_values = {str(key): value for key, value in dict(values or {}).items() if str(key)}
        normalized_delete_keys = [str(key) for key in delete_keys if str(key)]
        if not normalized_values and not normalized_delete_keys:
            return

        try:
            await self._db.execute("BEGIN")
            if normalized_delete_keys:
                placeholders = ", ".join("?" for _ in normalized_delete_keys)
                await self._db.execute(
                    f"DELETE FROM app_state WHERE key IN ({placeholders})",
                    normalized_delete_keys,
                )
            for key, value in normalized_values.items():
                await self._db.execute(
                    "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
                    (key, value),
                )
            await self._db.commit()
        except Exception:
            await self._db.execute("ROLLBACK")
            raise

    async def set_app_state(self, key: str, value: str) -> None:
        """
        Set app state value.

        Args:
            key: State key
            value: State value
        """
        await self.replace_app_state({key: value})

    async def set_app_states(self, values: dict[str, str]) -> None:
        """Set multiple app-state values in one transaction."""
        await self.replace_app_state(values)

    async def delete_app_state(self, key: str) -> None:
        """
        Delete app state value.

        Args:
            key: State key
        """
        await self.replace_app_state(delete_keys=[key])

    async def delete_app_states(self, keys: Iterable[str]) -> None:
        """Delete multiple app-state values in one transaction."""
        await self.replace_app_state(delete_keys=keys)

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("Database closed")
    
    async def vacuum(self) -> None:
        """Optimize database."""
        await self._db.execute("VACUUM")
        await self._db.commit()
        logger.info("Database vacuumed")


_database: Optional[Database] = None


def peek_database() -> Optional[Database]:
    """Return the existing database singleton if it was created."""
    return _database


def get_database() -> Database:
    """Get the global database instance."""
    global _database
    if _database is None:
        _database = Database()
    return _database


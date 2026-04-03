"""
Database Module

SQLite database using aiosqlite for async operations.
"""
import aiosqlite
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from client.core import logging
from client.core.config_backend import get_config
from client.core.logging import setup_logging
from client.models.message import ChatMessage, Session, merge_sender_profile_extra


setup_logging()
logger = logging.get_logger(__name__)

class Database:
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
        
        self._db_path = str(Path(db_path).expanduser().resolve())
        self._db: Optional[aiosqlite.Connection] = None
        self._search_fts_tokenizer: Optional[str] = None
    
    @property
    def is_connected(self) -> bool:
        """Check if database is connected."""
        return self._db is not None
    
    async def connect(self) -> None:
        """Connect to database and create tables."""
        if self._db is not None:
            return
        
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        
        await self._create_tables()
        await self._ensure_local_search_cache_schema()
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
                contact_id TEXT PRIMARY KEY,
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
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS groups_cache (
                group_id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                avatar TEXT NOT NULL DEFAULT '',
                owner_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                member_count INTEGER NOT NULL DEFAULT 0,
                member_search_text TEXT NOT NULL DEFAULT '',
                extra TEXT NOT NULL DEFAULT '{}',
                updated_at INTEGER NOT NULL
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

    async def _ensure_local_search_cache_schema(self) -> None:
        """Add newly introduced cache columns to existing local databases."""
        await self._ensure_table_columns(
            "contacts_cache",
            {
                "region": "TEXT NOT NULL DEFAULT ''",
            },
        )
        await self._ensure_table_columns(
            "groups_cache",
            {
                "member_search_text": "TEXT NOT NULL DEFAULT ''",
            },
        )

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

    async def _ensure_search_fts_schema(self) -> None:
        """Create and backfill SQLite FTS5 search indexes when available."""
        detected_tokenizer = await self._detect_search_fts_tokenizer()
        if detected_tokenizer:
            self._search_fts_tokenizer = detected_tokenizer
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
            await self._rebuild_search_fts_if_needed(force=True)
            logger.info("Enabled local search FTS with tokenizer: %s", self._search_fts_tokenizer)
            return

        self._search_fts_tokenizer = None
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
                VALUES (new.rowid, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS messages_search_ad AFTER DELETE ON messages BEGIN
                INSERT INTO message_search_fts(message_search_fts, rowid, content)
                VALUES ('delete', old.rowid, old.content);
            END;

            CREATE TRIGGER IF NOT EXISTS messages_search_au AFTER UPDATE ON messages BEGIN
                INSERT INTO message_search_fts(message_search_fts, rowid, content)
                VALUES ('delete', old.rowid, old.content);
                INSERT INTO message_search_fts(rowid, content)
                VALUES (new.rowid, new.content);
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
            base_count = await self._table_row_count(base_table)
            fts_count = await self._table_row_count(fts_table)
            if force or base_count != fts_count:
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
        """Replace the cached session list with the provided snapshot."""
        await self._db.execute("DELETE FROM sessions")
        await self._db.commit()
        if sessions:
            await self.save_sessions_batch(sessions)
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
        await self._db.execute(
            """
            INSERT OR REPLACE INTO messages
            (message_id, session_id, sender_id, content, message_type,
             status, timestamp, updated_at, is_self, is_ai, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.message_id,
                message.session_id,
                message.sender_id,
                message.content,
                message.message_type.value,
                message.status.value,
                message.timestamp.timestamp() if message.timestamp else None,
                message.updated_at.timestamp() if message.updated_at else None,
                1 if message.is_self else 0,
                1 if message.is_ai else 0,
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
                WHERE session_id = ? AND content LIKE ? ESCAPE '\\'
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (session_id, like_pattern, normalized_limit),
            )
        else:
            cursor = await self._db.execute(
                """
                SELECT * FROM messages
                WHERE content LIKE ? ESCAPE '\\'
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
                WHERE session_id = ? AND content LIKE ? ESCAPE '\\'
                """,
                (session_id, like_pattern),
            )
        else:
            cursor = await self._db.execute(
                """
                SELECT COUNT(DISTINCT session_id) AS count
                FROM messages
                WHERE content LIKE ? ESCAPE '\\'
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
                """,
                (match_query,),
            )
        row = await cursor.fetchone()
        return int((row["count"] if row is not None else 0) or 0)

    async def replace_contacts_cache(self, contacts: list[dict[str, Any]]) -> None:
        """Replace the cached contact directory snapshot."""
        await self._db.execute("DELETE FROM contacts_cache")
        updated_at = int(time.time())

        for contact in contacts:
            extra = dict(contact.get("extra") or {})
            await self._db.execute(
                """
                INSERT OR REPLACE INTO contacts_cache
                (contact_id, display_name, username, nickname, remark,
                 assistim_id, region, avatar, signature, category, status, extra, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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
        logger.debug(f"Replaced contact cache with {len(contacts)} contacts")

    async def replace_groups_cache(self, groups: list[dict[str, Any]]) -> None:
        """Replace the cached group directory snapshot."""
        await self._db.execute("DELETE FROM groups_cache")
        updated_at = int(time.time())

        for group in groups:
            extra = dict(group.get("extra") or {})
            member_search_text = str(group.get("member_search_text", "") or "")
            await self._db.execute(
                """
                INSERT OR REPLACE INTO groups_cache
                (group_id, name, avatar, owner_id, session_id, member_count, member_search_text, extra, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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
        logger.debug(f"Replaced group cache with {len(groups)} groups")

    async def list_contacts_cache_by_ids(self, contact_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Return one contact lookup map for the given ids."""
        normalized_ids = [
            value
            for value in dict.fromkeys(str(contact_id or "").strip() for contact_id in (contact_ids or []))
            if value
        ]
        if not normalized_ids:
            return {}

        placeholders = ",".join("?" for _ in normalized_ids)
        cursor = await self._db.execute(
            f"SELECT * FROM contacts_cache WHERE contact_id IN ({placeholders})",
            tuple(normalized_ids),
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
    ) -> list[dict[str, Any]]:
        """Search cached contacts by one literal keyword."""
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return []

        normalized_limit = max(1, int(limit or 0))
        if self._should_use_search_fts(normalized_keyword):
            try:
                return await self._search_contacts_fts(normalized_keyword, limit=normalized_limit)
            except Exception as exc:
                logger.debug("Contact FTS search failed, falling back to LIKE: %s", exc)
        like_pattern = self._escape_like_pattern(normalized_keyword)
        cursor = await self._db.execute(
            """
            SELECT * FROM contacts_cache
            WHERE nickname LIKE ? ESCAPE '\\'
               OR remark LIKE ? ESCAPE '\\'
               OR assistim_id LIKE ? ESCAPE '\\'
               OR region LIKE ? ESCAPE '\\'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (
                like_pattern,
                like_pattern,
                like_pattern,
                like_pattern,
                normalized_limit,
            ),
        )
        rows = await cursor.fetchall()
        return [self._row_to_contact_cache(row) for row in rows]

    async def count_search_contacts(self, keyword: str) -> int:
        """Count contact search hits for one keyword."""
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return 0

        if self._should_use_search_fts(normalized_keyword):
            try:
                cursor = await self._db.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM contact_search_fts
                    WHERE contact_search_fts MATCH ?
                    """,
                    (self._build_fts_match_query(normalized_keyword),),
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
            WHERE nickname LIKE ? ESCAPE '\\'
               OR remark LIKE ? ESCAPE '\\'
               OR assistim_id LIKE ? ESCAPE '\\'
               OR region LIKE ? ESCAPE '\\'
            """,
            (like_pattern, like_pattern, like_pattern, like_pattern),
        )
        row = await cursor.fetchone()
        return int((row["count"] if row is not None else 0) or 0)

    async def _search_contacts_fts(
        self,
        keyword: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Search cached contacts through the FTS5 index."""
        cursor = await self._db.execute(
            """
            SELECT c.*
            FROM contact_search_fts f
            JOIN contacts_cache c ON c.rowid = f.rowid
            WHERE contact_search_fts MATCH ?
            ORDER BY bm25(contact_search_fts), c.updated_at DESC
            LIMIT ?
            """,
            (self._build_fts_match_query(keyword), limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_contact_cache(row) for row in rows]

    async def search_groups(
        self,
        keyword: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search cached groups by one literal keyword."""
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return []

        normalized_limit = max(1, int(limit or 0))
        if self._should_use_search_fts(normalized_keyword):
            try:
                return await self._search_groups_fts(normalized_keyword, limit=normalized_limit)
            except Exception as exc:
                logger.debug("Group FTS search failed, falling back to LIKE: %s", exc)
        like_pattern = self._escape_like_pattern(normalized_keyword)
        cursor = await self._db.execute(
            """
            SELECT * FROM groups_cache
            WHERE name LIKE ? ESCAPE '\\'
               OR member_search_text LIKE ? ESCAPE '\\'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (
                like_pattern,
                like_pattern,
                normalized_limit,
            ),
        )
        rows = await cursor.fetchall()
        return [self._row_to_group_cache(row) for row in rows]

    async def count_search_groups(self, keyword: str) -> int:
        """Count group search hits for one keyword."""
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return 0

        if self._should_use_search_fts(normalized_keyword):
            try:
                cursor = await self._db.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM group_search_fts
                    WHERE group_search_fts MATCH ?
                    """,
                    (self._build_fts_match_query(normalized_keyword),),
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
            WHERE name LIKE ? ESCAPE '\\'
               OR member_search_text LIKE ? ESCAPE '\\'
            """,
            (like_pattern, like_pattern),
        )
        row = await cursor.fetchone()
        return int((row["count"] if row is not None else 0) or 0)

    async def _search_groups_fts(
        self,
        keyword: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Search cached groups through the FTS5 index."""
        cursor = await self._db.execute(
            """
            SELECT g.*
            FROM group_search_fts f
            JOIN groups_cache g ON g.rowid = f.rowid
            WHERE group_search_fts MATCH ?
            ORDER BY bm25(group_search_fts), g.updated_at DESC
            LIMIT ?
            """,
            (self._build_fts_match_query(keyword), limit),
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
            await self._db.execute(
                """
                INSERT OR REPLACE INTO messages
                (message_id, session_id, sender_id, content, message_type,
                 status, timestamp, updated_at, is_self, is_ai, extra)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.message_id,
                    message.session_id,
                    message.sender_id,
                    message.content,
                    message.message_type.value,
                    message.status.value,
                    message.timestamp.timestamp() if message.timestamp else None,
                    message.updated_at.timestamp() if message.updated_at else None,
                    1 if message.is_self else 0,
                    1 if message.is_ai else 0,
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
        
        return ChatMessage(
            message_id=row["message_id"],
            session_id=row["session_id"],
            sender_id=row["sender_id"],
            content=row["content"],
            message_type=MessageType(row["message_type"]),
            status=MessageStatus(row["status"]),
            timestamp=timestamp,
            updated_at=updated_at,
            is_self=bool(row["is_self"]),
            is_ai=bool(row["is_ai"]),
            extra=json.loads(row["extra"]),
        )
    
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

    async def set_app_state(self, key: str, value: str) -> None:
        """
        Set app state value.

        Args:
            key: State key
            value: State value
        """
        await self._db.execute(
            "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
            (key, value),
        )
        await self._db.commit()

    async def delete_app_state(self, key: str) -> None:
        """
        Delete app state value.

        Args:
            key: State key
        """
        await self._db.execute(
            "DELETE FROM app_state WHERE key = ?",
            (key,),
        )
        await self._db.commit()

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








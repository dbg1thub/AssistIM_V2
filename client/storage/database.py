"""
Database Module

SQLite database using aiosqlite for async operations.
"""
import aiosqlite
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from client.core.config import get_config
from client.models.message import ChatMessage, Session


logger = logging.getLogger(__name__)


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
            
            CREATE INDEX IF NOT EXISTS idx_messages_session 
                ON messages(session_id, timestamp DESC);
            
            CREATE INDEX IF NOT EXISTS idx_sessions_updated 
                ON sessions(updated_at DESC);
        """)
        await self._db.commit()
    
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
        
        return self._row_to_message(row)
    
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
        messages = [self._row_to_message(row) for row in rows]
        messages.reverse()
        return messages
    
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
        await self._db.commit()
        logger.debug(f"Messages deleted for session: {session_id}")
    
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
        
        return self._row_to_message(row)
    
    def _row_to_message(self, row: aiosqlite.Row) -> ChatMessage:
        """Convert database row to ChatMessage."""
        import datetime
        from models.message import MessageStatus, MessageType
        
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


def get_database() -> Database:
    """Get the global database instance."""
    global _database
    if _database is None:
        _database = Database()
    return _database

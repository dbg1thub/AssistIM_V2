"""Read-only development dashboard aggregation service."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import RUNTIME_SCHEMA_REQUIRED_TABLES
from app.core.rate_limit import rate_limiter
from app.core.runtime_diagnostics import runtime_diagnostics_snapshot
from app.models.device import UserDevice, UserPreKey, UserSignedPreKey
from app.models.admin import AdminAuditLog
from app.models.file import StoredFile
from app.models.group import Group, GroupMember
from app.models.message import Message, MessageRead
from app.models.moment import Moment, MomentComment, MomentLike
from app.models.session import ChatSession, SessionEvent
from app.models.user import FriendRequest, Friendship, User
from app.realtime.call_registry import get_call_registry
from app.websocket.manager import connection_manager


class AdminDashboardService:
    """Build one backend-only development diagnostics snapshot."""

    def __init__(self, db: Session, settings: Settings, *, started_at: float | None = None) -> None:
        self.db = db
        self.settings = settings
        self.started_at = float(started_at or time.time())

    def build(self) -> dict[str, Any]:
        diagnostics = runtime_diagnostics_snapshot()
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "system": self._system_snapshot(),
            "database": self._database_snapshot(),
            "users": self._user_snapshot(),
            "admin": self._admin_snapshot(),
            "contacts": self._contact_snapshot(),
            "chat": self._chat_snapshot(),
            "groups": self._group_snapshot(),
            "moments": self._moment_snapshot(),
            "files": self._file_snapshot(),
            "realtime": connection_manager.snapshot(),
            "calls": self._call_snapshot(),
            "e2ee": self._e2ee_snapshot(),
            "http": diagnostics["http"],
            "logs": diagnostics["logs"],
        }

    def _system_snapshot(self) -> dict[str, Any]:
        return {
            "app_name": self.settings.app_name,
            "app_version": self.settings.app_version,
            "debug": bool(self.settings.debug),
            "api_v1_prefix": self.settings.api_v1_prefix,
            "media_storage_backend": self.settings.media_storage_backend,
            "rate_limit_store_backend": self.settings.rate_limit_store_backend,
            "rate_limit_store": type(rate_limiter.store).__name__,
            "uptime_seconds": max(0, round(time.time() - self.started_at, 2)),
        }

    def _database_snapshot(self) -> dict[str, Any]:
        try:
            bind = self.db.get_bind()
            inspector = inspect(bind)
            table_names = set(inspector.get_table_names())
            required_tables = {
                table_name: table_name in table_names
                for table_name in sorted(RUNTIME_SCHEMA_REQUIRED_TABLES)
            }
            return {
                "status": "ok",
                "dialect": bind.dialect.name,
                "table_count": len(table_names),
                "required_tables": required_tables,
            }
        except SQLAlchemyError as exc:
            return {
                "status": "error",
                "error": type(exc).__name__,
                "required_tables": {
                    table_name: False
                    for table_name in sorted(RUNTIME_SCHEMA_REQUIRED_TABLES)
                },
            }

    def _user_snapshot(self) -> dict[str, Any]:
        realtime = connection_manager.snapshot()
        return {
            "total": self._count(User),
            "online": int(realtime.get("online_users", 0) or 0),
            "devices": {
                "total": self._count(UserDevice),
                "active": self._count(UserDevice, UserDevice.is_active.is_(True)),
            },
        }

    def _contact_snapshot(self) -> dict[str, int]:
        return {
            "friendships": self._count(Friendship),
            "pending_friend_requests": self._count(FriendRequest, FriendRequest.status == "pending"),
        }

    def _admin_snapshot(self) -> dict[str, int]:
        return {
            "admin_users": self._count(User, User.role == "admin"),
            "audit_logs": self._count(AdminAuditLog),
        }

    def _chat_snapshot(self) -> dict[str, Any]:
        return {
            "sessions": {
                "total": self._count(ChatSession),
                "private": self._count(
                    ChatSession,
                    ChatSession.type == "private",
                    ChatSession.is_ai_session.is_(False),
                ),
                "group": self._count(ChatSession, ChatSession.type == "group"),
                "ai": self._count(ChatSession, ChatSession.is_ai_session.is_(True)),
            },
            "messages": {
                "total": self._count(Message),
                "by_type": self._count_by(Message.type, Message),
            },
            "events": self._count(SessionEvent),
            "read_records": self._count(MessageRead),
        }

    def _group_snapshot(self) -> dict[str, int]:
        return {
            "total": self._count(Group),
            "members": self._count(GroupMember),
            "with_announcements": self._count(Group, Group.announcement != ""),
        }

    def _moment_snapshot(self) -> dict[str, int]:
        return {
            "total": self._count(Moment),
            "likes": self._count(MomentLike),
            "comments": self._count(MomentComment),
        }

    def _file_snapshot(self) -> dict[str, Any]:
        total_size = self.db.execute(select(func.coalesce(func.sum(StoredFile.size_bytes), 0))).scalar_one()
        return {
            "total": self._count(StoredFile),
            "total_size_bytes": int(total_size or 0),
            "by_type": self._count_by(StoredFile.file_type, StoredFile),
            "upload_dir": self._upload_dir_snapshot(),
        }

    def _call_snapshot(self) -> dict[str, Any]:
        snapshot = get_call_registry().snapshot()
        ice_sources = (
            self.settings.webrtc_ice_server_urls
            or self.settings.webrtc_stun_urls
            or self.settings.webrtc_turn_urls
        )
        turn_urls = tuple(self.settings.webrtc_turn_urls or ())
        snapshot["ice_servers_configured"] = bool(ice_sources)
        snapshot["turn_configured"] = bool(
            turn_urls
            and (
                self.settings.webrtc_turn_shared_secret
                or (self.settings.webrtc_turn_username and self.settings.webrtc_turn_credential)
            )
        )
        return snapshot

    def _e2ee_snapshot(self) -> dict[str, Any]:
        return {
            "encrypted_sessions": self._count(ChatSession, ChatSession.encryption_mode != "plain"),
            "private_sessions": self._count(ChatSession, ChatSession.encryption_mode == "e2ee_private"),
            "group_sessions": self._count(ChatSession, ChatSession.encryption_mode == "e2ee_group"),
            "devices": {
                "total": self._count(UserDevice),
                "active": self._count(UserDevice, UserDevice.is_active.is_(True)),
            },
            "one_time_prekeys": {
                "total": self._count(UserPreKey),
                "available": self._count(UserPreKey, UserPreKey.is_consumed.is_(False)),
                "consumed": self._count(UserPreKey, UserPreKey.is_consumed.is_(True)),
            },
            "signed_prekeys": {
                "total": self._count(UserSignedPreKey),
                "active": self._count(UserSignedPreKey, UserSignedPreKey.is_active.is_(True)),
            },
        }

    def _upload_dir_snapshot(self) -> dict[str, Any]:
        raw_path = Path(self.settings.upload_dir)
        path = raw_path.expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        exists = resolved.exists()
        return {
            "path": str(resolved),
            "exists": exists,
            "is_dir": resolved.is_dir() if exists else False,
            "writable": bool(os.access(resolved, os.W_OK)) if exists else False,
        }

    def _count(self, model: Any, *criteria: Any) -> int:
        statement = select(func.count()).select_from(model)
        for condition in criteria:
            statement = statement.where(condition)
        return int(self.db.execute(statement).scalar_one() or 0)

    def _count_by(self, column: Any, model: Any) -> dict[str, int]:
        rows = self.db.execute(
            select(column, func.count()).select_from(model).group_by(column)
        ).all()
        result: dict[str, int] = {}
        for raw_key, raw_count in rows:
            key = str(raw_key or "unknown").strip() or "unknown"
            result[key] = int(raw_count or 0)
        return dict(sorted(result.items()))

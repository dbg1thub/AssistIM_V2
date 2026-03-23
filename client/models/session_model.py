"""
Session Model Module

QAbstractListModel for chat session list.
"""

import time
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QAbstractListModel, Qt, QModelIndex

from client.models.message import Session


class SessionModel(QAbstractListModel):
    """
    Session list model using QAbstractListModel.

    Sorting rules:
        1. Pinned sessions first (is_pinned)
        2. Latest message time (last_message_time)

    Qt Roles:
        Qt.ItemDataRole.DisplayRole: Session name
        Qt.ItemDataRole.UserRole: Session object
        SessionModel.SessionRole: Full session data dict
        SessionModel.LastMessageRole: Last message preview
        SessionModel.UnreadCountRole: Unread count
        SessionModel.TimestampRole: Last message timestamp
        SessionModel.IsPinnedRole: Whether session is pinned
    """

    SessionRole = Qt.ItemDataRole.UserRole + 1
    LastMessageRole = Qt.ItemDataRole.UserRole + 2
    UnreadCountRole = Qt.ItemDataRole.UserRole + 3
    TimestampRole = Qt.ItemDataRole.UserRole + 4
    IsPinnedRole = Qt.ItemDataRole.UserRole + 5
    AvatarRole = Qt.ItemDataRole.UserRole + 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sessions: list[Session] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        """Return number of sessions."""
        return len(self._sessions)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        """Return data for given index and role."""
        if not index.isValid():
            return None

        row = index.row()
        if row < 0 or row >= len(self._sessions):
            return None

        session = self._sessions[row]

        if role == Qt.ItemDataRole.DisplayRole:
            return session.name
        if role == Qt.ItemDataRole.UserRole:
            return session
        if role == self.SessionRole:
            return session.to_dict()
        if role == self.LastMessageRole:
            return session.last_message
        if role == self.UnreadCountRole:
            return session.unread_count
        if role == self.TimestampRole:
            return session.last_message_time
        if role == self.IsPinnedRole:
            return getattr(session, 'is_pinned', False)
        if role == self.AvatarRole:
            return session.avatar
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        return None

    def add_session(self, session: Session) -> None:
        """Add a session to the list."""
        insert_at = self._find_insert_index(session)
        self.beginInsertRows(QModelIndex(), insert_at, insert_at)
        self._sessions.insert(insert_at, session)
        self.endInsertRows()

    def set_sessions(self, sessions: list[Session]) -> None:
        """Replace all sessions, using insert/remove when transitioning from or to empty."""
        sorted_sessions = sorted(sessions, key=self._session_sort_key, reverse=True)

        if not self._sessions and not sorted_sessions:
            return
        if not self._sessions:
            self.beginInsertRows(QModelIndex(), 0, len(sorted_sessions) - 1)
            self._sessions = sorted_sessions
            self.endInsertRows()
            return
        if not sorted_sessions:
            self.beginRemoveRows(QModelIndex(), 0, len(self._sessions) - 1)
            self._sessions = []
            self.endRemoveRows()
            return

        self.beginResetModel()
        self._sessions = sorted_sessions
        self.endResetModel()

    def insert_session(self, index: int, session: Session) -> None:
        """Insert a session at specific index, then move it to the sorted position."""
        target_index = max(0, min(index, len(self._sessions)))
        self.beginInsertRows(QModelIndex(), target_index, target_index)
        self._sessions.insert(target_index, session)
        self.endInsertRows()
        self._move_session_if_needed(target_index, self._session_roles())

    def remove_session(self, session_id: str) -> None:
        """Remove a session by ID."""
        for i, session in enumerate(self._sessions):
            if session.session_id == session_id:
                self.beginRemoveRows(QModelIndex(), i, i)
                self._sessions.pop(i)
                self.endRemoveRows()
                break

    def update_session(self, session_id: str, **kwargs) -> None:
        """Update one session and move it if the sort key changed."""
        for i, session in enumerate(self._sessions):
            if session.session_id != session_id:
                continue

            for key, value in kwargs.items():
                if hasattr(session, key):
                    setattr(session, key, value)

            self._move_session_if_needed(i, self._roles_for_update(kwargs))
            break

    def get_session(self, index: int) -> Optional[Session]:
        """Get session at index."""
        if 0 <= index < len(self._sessions):
            return self._sessions[index]
        return None

    def get_session_by_id(self, session_id: str) -> Optional[Session]:
        """Get session by ID."""
        for session in self._sessions:
            if session.session_id == session_id:
                return session
        return None

    def get_sessions(self) -> list[Session]:
        """Get all sessions."""
        return self._sessions

    def clear(self) -> None:
        """Clear all sessions."""
        if not self._sessions:
            return
        self.beginRemoveRows(QModelIndex(), 0, len(self._sessions) - 1)
        self._sessions.clear()
        self.endRemoveRows()

    def sort_sessions(self) -> None:
        """Sort sessions by pinned first, then by latest message time."""
        if len(self._sessions) < 2:
            return
        self.layoutAboutToBeChanged.emit()
        self._sessions.sort(key=self._session_sort_key, reverse=True)
        self.layoutChanged.emit()

    def _session_sort_key(self, session: Session) -> tuple:
        """Sort key for session: pinned first, newest pin first, then latest message time."""
        is_pinned = getattr(session, 'is_pinned', False)
        try:
            pinned_at = float(session.extra.get("pinned_at") or 0.0) if hasattr(session, "extra") else 0.0
        except (TypeError, ValueError):
            pinned_at = 0.0
        last_time = session.last_message_time or session.created_at or datetime.min
        return (is_pinned, pinned_at, last_time)

    def _find_insert_index(self, session: Session) -> int:
        """Return the descending sort position for a new session."""
        new_key = self._session_sort_key(session)
        for i, existing in enumerate(self._sessions):
            if new_key > self._session_sort_key(existing):
                return i
        return len(self._sessions)

    def _target_index_for_row(self, row: int) -> int:
        """Return the sorted index of one session after temporarily removing it."""
        session = self._sessions[row]
        remaining = self._sessions[:row] + self._sessions[row + 1 :]
        new_key = self._session_sort_key(session)
        for i, existing in enumerate(remaining):
            if new_key > self._session_sort_key(existing):
                return i
        return len(remaining)

    def _move_session_if_needed(self, row: int, roles: list[int]) -> None:
        """Move one session to its sorted position, otherwise emit dataChanged in place."""
        if row < 0 or row >= len(self._sessions):
            return

        target_row = self._target_index_for_row(row)
        if target_row == row:
            index = self.index(row)
            self.dataChanged.emit(index, index, roles)
            return

        destination_child = target_row if target_row < row else target_row + 1
        self.beginMoveRows(QModelIndex(), row, row, QModelIndex(), destination_child)
        session = self._sessions.pop(row)
        self._sessions.insert(target_row, session)
        self.endMoveRows()

        index = self.index(target_row)
        self.dataChanged.emit(index, index, roles)

    def _session_roles(self) -> list[int]:
        """Return the complete role list for one session row update."""
        return [
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.UserRole,
            self.SessionRole,
            self.LastMessageRole,
            self.UnreadCountRole,
            self.TimestampRole,
            self.IsPinnedRole,
            self.AvatarRole,
        ]

    def _roles_for_update(self, kwargs: dict) -> list[int]:
        """Return the minimal role list affected by one update payload."""
        roles = {Qt.ItemDataRole.UserRole, self.SessionRole}
        for key in kwargs:
            if key == 'name':
                roles.add(Qt.ItemDataRole.DisplayRole)
            elif key == 'last_message':
                roles.add(self.LastMessageRole)
            elif key == 'unread_count':
                roles.add(self.UnreadCountRole)
            elif key == 'last_message_time':
                roles.add(self.TimestampRole)
            elif key == 'avatar':
                roles.add(self.AvatarRole)
            elif key in {'is_pinned', 'extra'}:
                roles.add(self.IsPinnedRole)
                roles.add(Qt.ItemDataRole.DisplayRole)
            else:
                return self._session_roles()
        return list(roles) if roles else self._session_roles()

    def set_pinned(self, session_id: str, pinned: bool, *, pinned_at: float | None = None) -> None:
        """Set session pinned status without forcing a full layout refresh."""
        for i, session in enumerate(self._sessions):
            if session.session_id != session_id:
                continue

            target_state = pinned
            desired_pinned_at = pinned_at if (target_state and pinned_at is not None) else (time.time() if target_state else None)
            current_pinned_at = session.extra.get("pinned_at") if hasattr(session, "extra") else None
            if getattr(session, "is_pinned", False) == target_state and current_pinned_at == desired_pinned_at:
                return

            if hasattr(session, "is_pinned"):
                session.is_pinned = target_state
            if hasattr(session, "extra"):
                session.extra["is_pinned"] = target_state
                session.extra["pinned_at"] = desired_pinned_at

            self._move_session_if_needed(i, [Qt.ItemDataRole.UserRole, self.SessionRole, self.IsPinnedRole])
            return

    def move_to_top(self, session_id: str) -> None:
        """Move session to top (temporary pin)."""
        self.set_pinned(session_id, True)
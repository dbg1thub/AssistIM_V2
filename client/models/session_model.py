"""
Session Model Module

QAbstractListModel for chat session list.
"""

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

    # Custom Qt roles
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
        elif role == Qt.ItemDataRole.UserRole:
            return session
        elif role == self.SessionRole:
            return session.to_dict()
        elif role == self.LastMessageRole:
            return session.last_message
        elif role == self.UnreadCountRole:
            return session.unread_count
        elif role == self.TimestampRole:
            return session.last_message_time
        elif role == self.IsPinnedRole:
            return getattr(session, 'is_pinned', False)
        elif role == self.AvatarRole:
            return session.avatar
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        return None

    def add_session(self, session: Session) -> None:
        """Add a session to the list."""
        insert_at = self._find_insert_index(session)
        self.beginInsertRows(QModelIndex(), insert_at, insert_at)
        self._sessions.insert(insert_at, session)
        self.endInsertRows()

    def set_sessions(self, sessions: list[Session]) -> None:
        """Replace all sessions in one model reset."""
        self.beginResetModel()
        self._sessions = sorted(sessions, key=self._session_sort_key, reverse=True)
        self.endResetModel()

    def insert_session(self, index: int, session: Session) -> None:
        """Insert a session at specific index."""
        self.beginInsertRows(QModelIndex(), index, index)
        self._sessions.insert(index, session)
        self.endInsertRows()
        self.sort_sessions()

    def remove_session(self, session_id: str) -> None:
        """Remove a session by ID."""
        for i, session in enumerate(self._sessions):
            if session.session_id == session_id:
                self.beginRemoveRows(QModelIndex(), i, i)
                self._sessions.pop(i)
                self.endRemoveRows()
                break

    def update_session(self, session_id: str, **kwargs) -> None:
        """Update session fields."""
        for i, session in enumerate(self._sessions):
            if session.session_id == session_id:
                old_sort_key = self._session_sort_key(session)
                for key, value in kwargs.items():
                    if hasattr(session, key):
                        setattr(session, key, value)

                index = self.index(i)
                self.dataChanged.emit(index, index)
                if self._session_sort_key(session) != old_sort_key:
                    self.sort_sessions()
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
        self.beginResetModel()
        self._sessions.clear()
        self.endResetModel()

    def sort_sessions(self) -> None:
        """Sort sessions by pinned first, then by latest message time."""
        self.layoutAboutToBeChanged.emit()

        self._sessions.sort(key=self._session_sort_key, reverse=True)

        self.layoutChanged.emit()

    def _session_sort_key(self, session: Session) -> tuple:
        """Sort key for session: (is_pinned, last_message_time)"""
        is_pinned = getattr(session, 'is_pinned', False)
        last_time = session.last_message_time or session.created_at or datetime.min
        return (is_pinned, last_time)

    def _find_insert_index(self, session: Session) -> int:
        """Return the descending sort position for a new session."""
        new_key = self._session_sort_key(session)
        for i, existing in enumerate(self._sessions):
            if new_key > self._session_sort_key(existing):
                return i
        return len(self._sessions)

    def set_pinned(self, session_id: str, pinned: bool) -> None:
        """Set session pinned status."""
        for i, session in enumerate(self._sessions):
            if session.session_id == session_id:
                if hasattr(session, 'is_pinned'):
                    session.is_pinned = pinned
                    index = self.index(i)
                    self.dataChanged.emit(index, index, [self.IsPinnedRole])
                    self.sort_sessions()
                break

    def move_to_top(self, session_id: str) -> None:
        """Move session to top (temporary pin)."""
        self.set_pinned(session_id, True)

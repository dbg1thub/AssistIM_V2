"""Qt list model for local AI assistant messages."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from client.models.ai_assistant import AIMessage


class AIAssistantMessageModel(QAbstractListModel):
    """Expose AI assistant messages to a ``QListView``."""

    MessageRole = Qt.ItemDataRole.UserRole + 1
    RoleRole = Qt.ItemDataRole.UserRole + 2
    StatusRole = Qt.ItemDataRole.UserRole + 3
    ThreadIdRole = Qt.ItemDataRole.UserRole + 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages: list[AIMessage] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._messages)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._messages):
            return None
        message = self._messages[row]
        if role == Qt.ItemDataRole.DisplayRole:
            return message.content
        if role in {Qt.ItemDataRole.UserRole, self.MessageRole}:
            return message
        if role == self.RoleRole:
            return message.role
        if role == self.StatusRole:
            return message.status
        if role == self.ThreadIdRole:
            return message.thread_id
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignRight if self._is_user_message(message) else Qt.AlignmentFlag.AlignLeft
        return None

    def set_messages(self, messages: list[AIMessage]) -> None:
        next_messages = list(messages or [])
        if not self._messages and not next_messages:
            return
        self.beginResetModel()
        self._messages = next_messages
        self.endResetModel()

    def add_message(self, message: AIMessage) -> None:
        row = len(self._messages)
        self.beginInsertRows(QModelIndex(), row, row)
        self._messages.append(message)
        self.endInsertRows()

    def update_message(self, message: AIMessage) -> bool:
        row = self._find_row(message.message_id)
        if row < 0:
            return False
        self._messages[row] = message
        index = self.index(row, 0)
        self.dataChanged.emit(
            index,
            index,
            [
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.UserRole,
                self.MessageRole,
                self.RoleRole,
                self.StatusRole,
            ],
        )
        return True

    def clear(self) -> None:
        if not self._messages:
            return
        self.beginRemoveRows(QModelIndex(), 0, len(self._messages) - 1)
        self._messages.clear()
        self.endRemoveRows()

    def get_messages(self) -> list[AIMessage]:
        return list(self._messages)

    def get_message_by_id(self, message_id: str) -> AIMessage | None:
        row = self._find_row(message_id)
        if row < 0:
            return None
        return self._messages[row]

    def _find_row(self, message_id: str) -> int:
        normalized = str(message_id or "").strip()
        if not normalized:
            return -1
        for index, message in enumerate(self._messages):
            if message.message_id == normalized:
                return index
        return -1

    @staticmethod
    def _is_user_message(message: AIMessage) -> bool:
        return str(getattr(message.role, "value", message.role) or "") == "user"

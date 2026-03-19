"""
Message Model Module

QAbstractListModel for chat message list.
"""

from PySide6.QtCore import QAbstractListModel, Qt, QModelIndex
from PySide6.QtGui import QColor

from client.models.message import ChatMessage


class MessageModel(QAbstractListModel):
    """
    Message list model using QAbstractListModel.

    Qt Roles:
        Qt.ItemDataRole.DisplayRole: Message content
        Qt.ItemDataRole.UserRole: ChatMessage object
        MessageModel.MessageRole: Full message data dict
        MessageModel.IsSelfRole: Whether message is from current user
        MessageModel.MessageTypeRole: Message type
        MessageModel.StatusRole: Message status
    """

    # Custom Qt roles
    MessageRole = Qt.ItemDataRole.UserRole + 1
    IsSelfRole = Qt.ItemDataRole.UserRole + 2
    MessageTypeRole = Qt.ItemDataRole.UserRole + 3
    StatusRole = Qt.ItemDataRole.UserRole + 4
    TimestampRole = Qt.ItemDataRole.UserRole + 5
    SenderIdRole = Qt.ItemDataRole.UserRole + 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages: list[ChatMessage] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        """Return number of messages."""
        return len(self._messages)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        """Return data for given index and role."""
        if not index.isValid():
            return None

        row = index.row()
        if row < 0 or row >= len(self._messages):
            return None

        message = self._messages[row]

        if role == Qt.ItemDataRole.DisplayRole:
            return message.content
        elif role == Qt.ItemDataRole.UserRole:
            return message
        elif role == self.MessageRole:
            return message.to_dict()
        elif role == self.IsSelfRole:
            return message.is_self
        elif role == self.MessageTypeRole:
            return message.message_type
        elif role == self.StatusRole:
            return message.status
        elif role == self.TimestampRole:
            return message.timestamp
        elif role == self.SenderIdRole:
            return message.sender_id
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if message.is_self:
                return Qt.AlignmentFlag.AlignRight
            return Qt.AlignmentFlag.AlignLeft

        return None

    def add_message(self, message: ChatMessage) -> None:
        """Add a message to the list."""
        self.beginInsertRows(QModelIndex(), len(self._messages), len(self._messages))
        self._messages.append(message)
        self.endInsertRows()

    def add_messages(self, messages: list[ChatMessage]) -> None:
        """Append multiple messages in one insert operation."""
        if not messages:
            return

        start = len(self._messages)
        end = start + len(messages) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self._messages.extend(messages)
        self.endInsertRows()

    def prepend_messages(self, messages: list[ChatMessage]) -> None:
        """Insert multiple older messages at the beginning of the model."""
        if not messages:
            return

        end = len(messages) - 1
        self.beginInsertRows(QModelIndex(), 0, end)
        self._messages = list(messages) + self._messages
        self.endInsertRows()

    def refresh_message(self, message_id: str) -> None:
        """Emit a full data refresh for an existing message row."""
        for i, msg in enumerate(self._messages):
            if msg.message_id == message_id:
                index = self.index(i)
                self.dataChanged.emit(index, index)
                break

    def insert_message(self, index: int, message: ChatMessage) -> None:
        """Insert a message at specific index."""
        self.beginInsertRows(QModelIndex(), index, index)
        self._messages.insert(index, message)
        self.endInsertRows()

    def get_message(self, index: int) -> ChatMessage:
        """Get message at index."""
        if 0 <= index < len(self._messages):
            return self._messages[index]
        return None

    def get_message_by_id(self, message_id: str) -> ChatMessage:
        """Get message by ID."""
        for message in self._messages:
            if message.message_id == message_id:
                return message
        return None

    def contains_message(self, message_id: str) -> bool:
        """Check whether a message already exists in the model."""
        return self.get_message_by_id(message_id) is not None

    def get_messages(self) -> list[ChatMessage]:
        """Get all messages."""
        return self._messages

    def clear(self) -> None:
        """Clear all messages."""
        self.beginResetModel()
        self._messages.clear()
        self.endResetModel()

    def set_messages(self, messages: list[ChatMessage]) -> None:
        """Replace all messages in one model reset."""
        self.beginResetModel()
        self._messages = list(messages)
        self.endResetModel()

    def update_message_status(self, message_id: str, status) -> None:
        """Update message status."""
        for i, msg in enumerate(self._messages):
            if msg.message_id == message_id:
                msg.status = status
                index = self.index(i)
                self.dataChanged.emit(index, index, [self.StatusRole])
                break

    def update_message_content(self, message_id: str, content: str) -> None:
        """Update message content."""
        for i, msg in enumerate(self._messages):
            if msg.message_id == message_id:
                msg.content = content
                index = self.index(i)
                self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, self.MessageRole])
                break

    def remove_message(self, message_id: str) -> None:
        """Remove a message by ID."""
        for i, msg in enumerate(self._messages):
            if msg.message_id == message_id:
                self.beginRemoveRows(QModelIndex(), i, i)
                self._messages.pop(i)
                self.endRemoveRows()
                break

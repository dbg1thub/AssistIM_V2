"""
Message Model Module

QAbstractListModel for chat message list.
"""

from datetime import datetime

from PySide6.QtCore import QAbstractListModel, Qt, QModelIndex

from client.models.message import ChatMessage, MessageStatus, MessageType


class MessageModel(QAbstractListModel):
    """
    Message list model using QAbstractListModel.

    The model keeps two layers:
        - ``_messages``: real persisted messages
        - ``_display_items``: visible rows, including synthetic time/recall rows
    """

    MessageRole = Qt.ItemDataRole.UserRole + 1
    IsSelfRole = Qt.ItemDataRole.UserRole + 2
    MessageTypeRole = Qt.ItemDataRole.UserRole + 3
    StatusRole = Qt.ItemDataRole.UserRole + 4
    TimestampRole = Qt.ItemDataRole.UserRole + 5
    SenderIdRole = Qt.ItemDataRole.UserRole + 6
    ShowTimeAfterRole = Qt.ItemDataRole.UserRole + 7
    DisplayKindRole = Qt.ItemDataRole.UserRole + 8
    SourceMessageIdRole = Qt.ItemDataRole.UserRole + 9

    DISPLAY_MESSAGE = "message"
    DISPLAY_TIME_SEPARATOR = "time_separator"
    DISPLAY_RECALL_NOTICE = "recall_notice"

    DISPLAY_KIND_KEY = "_display_item_kind"
    SOURCE_MESSAGE_ID_KEY = "_source_message_id"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages: list[ChatMessage] = []
        self._display_items: list[ChatMessage] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        """Return number of visible rows."""
        return len(self._display_items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        """Return data for given index and role."""
        if not index.isValid():
            return None

        row = index.row()
        if row < 0 or row >= len(self._display_items):
            return None

        item = self._display_items[row]
        display_kind = self._display_kind(item)

        if role == Qt.ItemDataRole.DisplayRole:
            return item.content
        if role == Qt.ItemDataRole.UserRole:
            return item
        if role == self.MessageRole:
            return item.to_dict()
        if role == self.IsSelfRole:
            return item.is_self
        if role == self.MessageTypeRole:
            return item.message_type
        if role == self.StatusRole:
            return item.status
        if role == self.TimestampRole:
            return item.timestamp
        if role == self.SenderIdRole:
            return item.sender_id
        if role == self.ShowTimeAfterRole:
            return False
        if role == self.DisplayKindRole:
            return display_kind
        if role == self.SourceMessageIdRole:
            return self._source_message_id(item)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if display_kind != self.DISPLAY_MESSAGE:
                return Qt.AlignmentFlag.AlignCenter
            if item.is_self:
                return Qt.AlignmentFlag.AlignRight
            return Qt.AlignmentFlag.AlignLeft

        return None

    def add_message(self, message: ChatMessage) -> None:
        """Add a message to the list."""
        self._messages.append(message)
        self._reset_with_rebuilt_display_items()

    def add_messages(self, messages: list[ChatMessage]) -> None:
        """Append multiple messages."""
        if not messages:
            return
        self._messages.extend(messages)
        self._reset_with_rebuilt_display_items()

    def prepend_messages(self, messages: list[ChatMessage]) -> None:
        """Insert multiple older messages at the beginning of the model."""
        if not messages:
            return
        self._messages = list(messages) + self._messages
        self._reset_with_rebuilt_display_items()

    def refresh_message(self, message_id: str) -> None:
        """Emit a full refresh for a changed message."""
        self._reset_with_rebuilt_display_items()

    def insert_message(self, index: int, message: ChatMessage) -> None:
        """Insert a message at specific index."""
        self._messages.insert(index, message)
        self._reset_with_rebuilt_display_items()

    def get_message(self, index: int) -> ChatMessage | None:
        """Get the real message at an actual-message index."""
        if 0 <= index < len(self._messages):
            return self._messages[index]
        return None

    def get_message_by_id(self, message_id: str) -> ChatMessage | None:
        """Get a real message by ID."""
        for message in self._messages:
            if message.message_id == message_id:
                return message
        return None

    def contains_message(self, message_id: str) -> bool:
        """Check whether a message already exists in the real message list."""
        return self.get_message_by_id(message_id) is not None

    def get_messages(self) -> list[ChatMessage]:
        """Return real messages only."""
        return self._messages

    def clear(self) -> None:
        """Clear all messages."""
        self.beginResetModel()
        self._messages.clear()
        self._display_items.clear()
        self.endResetModel()

    def set_messages(self, messages: list[ChatMessage]) -> None:
        """Replace all messages in one model reset."""
        self.beginResetModel()
        self._messages = list(messages)
        self._rebuild_display_items()
        self.endResetModel()

    def update_message_status(self, message_id: str, status) -> None:
        """Update one message status and refresh the corresponding display row(s)."""
        message = self.get_message_by_id(message_id)
        if message is None:
            return

        previous_status = message.status
        message.status = status

        if previous_status == MessageStatus.RECALLED or status == MessageStatus.RECALLED:
            self._reset_with_rebuilt_display_items()
            return

        self._emit_display_row_changed(
            message_id,
            [
                self.StatusRole,
                Qt.ItemDataRole.UserRole,
                Qt.ItemDataRole.SizeHintRole,
                Qt.ItemDataRole.DisplayRole,
                self.MessageRole,
            ],
        )

    def mark_read_through(self, session_id: str, message_id: str, status) -> None:
        """Mark all self messages up to the target message as read within a session."""
        target_timestamp = None
        for message in self._messages:
            if message.session_id == session_id and message.message_id == message_id:
                target_timestamp = message.timestamp
                break

        if target_timestamp is None:
            return

        changed_ids: list[str] = []
        for message in self._messages:
            if message.session_id != session_id or not message.is_self or message.timestamp is None:
                continue
            if message.timestamp <= target_timestamp and message.status != status:
                message.status = status
                changed_ids.append(message.message_id)

        for changed_id in changed_ids:
            self._emit_display_row_changed(changed_id, [self.StatusRole, Qt.ItemDataRole.UserRole])

    def update_message_content(self, message_id: str, content: str) -> None:
        """Update message content and refresh the corresponding display row."""
        message = self.get_message_by_id(message_id)
        if message is None:
            return

        message.content = content
        self._emit_display_row_changed(
            message_id,
            [
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.UserRole,
                Qt.ItemDataRole.SizeHintRole,
                self.MessageRole,
            ],
        )

    def remove_message(self, message_id: str) -> None:
        """Remove a real message by ID."""
        for i, message in enumerate(self._messages):
            if message.message_id == message_id:
                self._messages.pop(i)
                self._reset_with_rebuilt_display_items()
                break

    def _reset_with_rebuilt_display_items(self) -> None:
        """Rebuild visible rows in one safe model reset."""
        self.beginResetModel()
        self._rebuild_display_items()
        self.endResetModel()

    def _rebuild_display_items(self) -> None:
        """Recompute visible rows from the real message list."""
        display_items: list[ChatMessage] = []
        message_count = len(self._messages)

        for index, message in enumerate(self._messages):
            if message.status == MessageStatus.RECALLED:
                display_items.append(self._build_recall_notice_item(message))
            else:
                display_items.append(message)

            if index >= message_count - 1:
                continue

            next_message = self._messages[index + 1]
            if self._is_time_break(message, next_message):
                display_items.append(self._build_time_separator_item(message))

        self._display_items = display_items

    def _emit_display_row_changed(self, message_id: str, roles: list[int]) -> None:
        """Emit dataChanged for the display row representing one real message."""
        row = self._find_display_row_for_message(message_id)
        if row < 0:
            self._reset_with_rebuilt_display_items()
            return

        index = self.index(row, 0)
        self.dataChanged.emit(index, index, roles)

    def _find_display_row_for_message(self, message_id: str) -> int:
        """Return the display row for the message body/notice, skipping time rows."""
        for row, item in enumerate(self._display_items):
            if self._display_kind(item) == self.DISPLAY_TIME_SEPARATOR:
                continue
            if self._source_message_id(item) == message_id:
                return row
        return -1

    def _build_time_separator_item(self, message: ChatMessage) -> ChatMessage:
        """Build a synthetic standalone time-separator row."""
        return ChatMessage(
            message_id=f"__time__::{message.message_id}",
            session_id=message.session_id,
            sender_id=message.sender_id,
            content="",
            message_type=MessageType.SYSTEM,
            status=message.status,
            timestamp=message.timestamp,
            updated_at=message.updated_at,
            is_self=False,
            is_ai=message.is_ai,
            extra={
                self.DISPLAY_KIND_KEY: self.DISPLAY_TIME_SEPARATOR,
                self.SOURCE_MESSAGE_ID_KEY: message.message_id,
            },
        )

    def _build_recall_notice_item(self, message: ChatMessage) -> ChatMessage:
        """Build a synthetic standalone recall-notice row."""
        return ChatMessage(
            message_id=f"__recall__::{message.message_id}",
            session_id=message.session_id,
            sender_id=message.sender_id,
            content=message.content,
            message_type=MessageType.SYSTEM,
            status=MessageStatus.RECALLED,
            timestamp=message.timestamp,
            updated_at=message.updated_at,
            is_self=message.is_self,
            is_ai=message.is_ai,
            extra={
                self.DISPLAY_KIND_KEY: self.DISPLAY_RECALL_NOTICE,
                self.SOURCE_MESSAGE_ID_KEY: message.message_id,
            },
        )

    def _display_kind(self, item: ChatMessage) -> str:
        """Return the display kind for a visible row."""
        return str((item.extra or {}).get(self.DISPLAY_KIND_KEY, self.DISPLAY_MESSAGE))

    def _source_message_id(self, item: ChatMessage) -> str:
        """Return the real message id represented by a visible row."""
        return str((item.extra or {}).get(self.SOURCE_MESSAGE_ID_KEY, item.message_id))

    @staticmethod
    def _normalize_timestamp(value):
        """Normalize timestamps for time-break comparisons."""
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    def _is_time_break(self, current: ChatMessage, next_message: ChatMessage) -> bool:
        """Return whether adjacent messages belong to different visible time groups."""
        current_time = self._normalize_timestamp(current.timestamp)
        next_time = self._normalize_timestamp(next_message.timestamp)
        if current_time is None or next_time is None:
            return False
        if current_time.date() != next_time.date():
            return True
        return abs((next_time - current_time).total_seconds()) >= 5 * 60

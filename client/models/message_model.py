"""
Message Model Module

QAbstractListModel for chat message list.
"""

from datetime import datetime

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from client.core.datetime_utils import coerce_local_datetime
from client.models.message import ChatMessage, MessageStatus, MessageType, resolve_recall_notice


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
    TimeExpandedRole = Qt.ItemDataRole.UserRole + 10

    DISPLAY_MESSAGE = "message"
    DISPLAY_TIME_SEPARATOR = "time_separator"
    DISPLAY_RECALL_NOTICE = "recall_notice"

    DISPLAY_KIND_KEY = "_display_item_kind"
    SOURCE_MESSAGE_ID_KEY = "_source_message_id"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages: list[ChatMessage] = []
        self._display_items: list[ChatMessage] = []
        self._expanded_time_separator_ids: set[str] = set()

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
        if role == self.TimeExpandedRole:
            return display_kind == self.DISPLAY_TIME_SEPARATOR and self.is_time_separator_expanded(self._source_message_id(item))
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if display_kind != self.DISPLAY_MESSAGE:
                return Qt.AlignmentFlag.AlignCenter
            if item.is_self:
                return Qt.AlignmentFlag.AlignRight
            return Qt.AlignmentFlag.AlignLeft

        return None

    def add_message(self, message: ChatMessage) -> None:
        """Add a message to the list."""
        if self._can_incrementally_append([message]):
            self._messages.append(message)
            self._append_display_items([message])
            return

        self._messages.append(message)
        self._sort_messages()
        self._apply_display_rebuild(changed_message_ids=[message.message_id])

    def add_messages(self, messages: list[ChatMessage]) -> None:
        """Append multiple messages."""
        if not messages:
            return

        if self._can_incrementally_append(messages):
            self._messages.extend(messages)
            self._append_display_items(messages)
            return

        self._messages.extend(messages)
        self._sort_messages()
        self._apply_display_rebuild(changed_message_ids=[message.message_id for message in messages])

    def prepend_messages(self, messages: list[ChatMessage]) -> None:
        """Insert multiple older messages at the beginning of the model."""
        if not messages:
            return

        self._messages = list(messages) + self._messages
        self._sort_messages()
        self._apply_display_rebuild(changed_message_ids=[message.message_id for message in messages])

    def refresh_message(self, message_id: str, *, allow_reorder: bool = False) -> None:
        """Refresh one changed message without resetting the whole model when possible."""
        message = self.get_message_by_id(message_id)
        if message is None:
            return

        if allow_reorder and self._should_reorder_message(message_id):
            self._sort_messages()
            self._apply_display_rebuild(changed_message_ids=[message_id])
            return

        row = self._find_display_row_for_message(message_id)
        if row < 0:
            self._apply_display_rebuild(changed_message_ids=[message_id])
            return

        desired_kind = self.DISPLAY_RECALL_NOTICE if message.status == MessageStatus.RECALLED else self.DISPLAY_MESSAGE
        current_item = self._display_items[row]
        current_kind = self._display_kind(current_item)

        if current_kind == desired_kind:
            if desired_kind == self.DISPLAY_RECALL_NOTICE:
                self._display_items[row] = self._build_recall_notice_item(message)
            self._emit_display_row_changed(message_id, self._display_roles())
            return

        self._apply_display_rebuild(changed_message_ids=[message_id])

    def insert_message(self, index: int, message: ChatMessage) -> None:
        """Insert a message at specific index."""
        self._messages.insert(index, message)
        self._apply_display_rebuild()

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
        self._expanded_time_separator_ids.clear()
        if not self._display_items:
            self._messages.clear()
            return

        self.beginRemoveRows(QModelIndex(), 0, len(self._display_items) - 1)
        self._messages.clear()
        self._display_items.clear()
        self.endRemoveRows()

    def set_messages(self, messages: list[ChatMessage]) -> None:
        """Replace all messages, using incremental updates for empty/non-empty edges."""
        new_messages = list(messages)
        new_messages.sort(key=self._message_sort_key)
        self._prune_expanded_time_separator_ids(new_messages)
        new_display_items = self._build_display_items(new_messages)

        if not self._display_items and not new_display_items:
            self._messages = new_messages
            return

        if not self._display_items:
            self._messages = new_messages
            self.beginInsertRows(QModelIndex(), 0, len(new_display_items) - 1)
            self._display_items = new_display_items
            self.endInsertRows()
            return

        if not new_display_items:
            self.beginRemoveRows(QModelIndex(), 0, len(self._display_items) - 1)
            self._messages = new_messages
            self._display_items = []
            self.endRemoveRows()
            return

        self.beginResetModel()
        self._messages = new_messages
        self._display_items = new_display_items
        self.endResetModel()

    def update_message_status(self, message_id: str, status) -> None:
        """Update one message status and refresh the corresponding display row(s)."""
        message = self.get_message_by_id(message_id)
        if message is None:
            return

        previous_status = message.status
        message.status = status

        if previous_status == MessageStatus.RECALLED or status == MessageStatus.RECALLED:
            self.refresh_message(message_id)
            return

        self._emit_display_row_changed(message_id, self._display_roles())

    def apply_read_receipt(self, session_id: str, reader_id: str, last_read_seq: int) -> None:
        """Apply one cumulative read receipt to visible self messages in a session."""
        if not session_id or not reader_id or last_read_seq <= 0:
            return

        changed_ids: list[str] = []
        for message in self._messages:
            if message.session_id != session_id or not message.is_self:
                continue

            message_seq = self._coerce_extra_int(message, "session_seq")
            if message_seq <= 0 or message_seq > last_read_seq:
                continue

            read_by_user_ids = self._normalized_reader_ids(message)
            if reader_id in read_by_user_ids:
                continue

            read_by_user_ids.append(reader_id)
            read_by_user_ids.sort()

            read_target_count = self._coerce_extra_int(message, "read_target_count")
            message.extra["read_by_user_ids"] = read_by_user_ids
            message.extra["read_count"] = len(read_by_user_ids)
            message.extra["read_target_count"] = read_target_count

            if read_target_count <= 1 and message.status not in {MessageStatus.FAILED, MessageStatus.RECALLED}:
                message.status = MessageStatus.READ
            elif message.status in {MessageStatus.SENT, MessageStatus.DELIVERED, MessageStatus.READ}:
                message.status = MessageStatus.DELIVERED

            message.updated_at = datetime.now()
            changed_ids.append(message.message_id)

        for changed_id in changed_ids:
            self._emit_display_row_changed(changed_id, self._display_roles())

    def update_message_content(self, message_id: str, content: str) -> None:
        """Update message content and refresh the corresponding display row."""
        message = self.get_message_by_id(message_id)
        if message is None:
            return

        message.content = content
        self._emit_display_row_changed(message_id, self._display_roles())

    def replace_message(self, message: ChatMessage, *, allow_reorder: bool = False) -> None:
        """Replace one authoritative message snapshot in-place and refresh its display rows."""
        for index, existing in enumerate(self._messages):
            if existing.message_id != message.message_id:
                continue
            self._messages[index] = message
            self.refresh_message(message.message_id, allow_reorder=allow_reorder)
            return

    def remove_message(self, message_id: str) -> None:
        """Remove a real message by ID."""
        for i, message in enumerate(self._messages):
            if message.message_id == message_id:
                self._messages.pop(i)
                self._apply_display_rebuild()
                break

    def _append_display_items(self, messages: list[ChatMessage]) -> None:
        """Append one contiguous display fragment for newly appended real messages."""
        if not messages:
            return

        previous_message = None
        existing_message_count = len(self._messages) - len(messages)
        if existing_message_count > 0:
            previous_message = self._messages[existing_message_count - 1]

        fragment = self._build_append_fragment(previous_message, messages)
        if not fragment:
            return

        insert_at = len(self._display_items)
        self.beginInsertRows(QModelIndex(), insert_at, insert_at + len(fragment) - 1)
        self._display_items.extend(fragment)
        self.endInsertRows()

    def _prepend_display_items(self, messages: list[ChatMessage]) -> None:
        """Prepend one contiguous display fragment for older history messages."""
        if not messages:
            return

        next_message = self._messages[len(messages)] if len(self._messages) > len(messages) else None
        fragment = self._build_prepend_fragment(messages, next_message)
        if not fragment:
            return

        self.beginInsertRows(QModelIndex(), 0, len(fragment) - 1)
        self._display_items = fragment + self._display_items
        self.endInsertRows()

    def _apply_display_rebuild(self, *, changed_message_ids: list[str] | None = None) -> None:
        """Recompute visible rows and apply the smallest safe model change."""
        self._prune_expanded_time_separator_ids(self._messages)
        self._apply_display_items(self._build_display_items(), changed_message_ids=changed_message_ids)

    def _apply_display_items(self, new_items: list[ChatMessage], *, changed_message_ids: list[str] | None = None) -> None:
        """Apply one rebuilt display snapshot with insert/remove/update instead of reset when possible."""
        old_items = list(self._display_items)

        if not old_items and not new_items:
            return
        if not old_items:
            self.beginInsertRows(QModelIndex(), 0, len(new_items) - 1)
            self._display_items = list(new_items)
            self.endInsertRows()
            return
        if not new_items:
            self.beginRemoveRows(QModelIndex(), 0, len(old_items) - 1)
            self._display_items = []
            self.endRemoveRows()
            return

        prefix = 0
        max_prefix = min(len(old_items), len(new_items))
        while prefix < max_prefix and self._display_signature(old_items[prefix]) == self._display_signature(new_items[prefix]):
            prefix += 1

        suffix = 0
        max_suffix = min(len(old_items), len(new_items)) - prefix
        while suffix < max_suffix and self._display_signature(old_items[-1 - suffix]) == self._display_signature(new_items[-1 - suffix]):
            suffix += 1

        old_mid_count = len(old_items) - prefix - suffix
        new_mid_count = len(new_items) - prefix - suffix

        if old_mid_count == 0 and new_mid_count == 0:
            self._display_items = list(new_items)
            self._emit_rows_for_message_ids(changed_message_ids)
            return

        if old_mid_count == new_mid_count:
            self._display_items = list(new_items)
            if new_mid_count > 0:
                top = self.index(prefix, 0)
                bottom = self.index(prefix + new_mid_count - 1, 0)
                self.dataChanged.emit(top, bottom, self._display_roles())
            else:
                self._emit_rows_for_message_ids(changed_message_ids)
            return

        if old_mid_count > 0:
            remove_start = prefix
            remove_end = prefix + old_mid_count - 1
            self.beginRemoveRows(QModelIndex(), remove_start, remove_end)
            self._display_items = old_items[:prefix] + old_items[len(old_items) - suffix :]
            self.endRemoveRows()

        if new_mid_count > 0:
            insert_start = prefix
            insert_end = prefix + new_mid_count - 1
            current_items = list(self._display_items)
            self.beginInsertRows(QModelIndex(), insert_start, insert_end)
            self._display_items = current_items[:insert_start] + new_items[prefix : prefix + new_mid_count] + current_items[insert_start:]
            self.endInsertRows()

        self._display_items = list(new_items)

    def _build_display_items(self, messages: list[ChatMessage] | None = None) -> list[ChatMessage]:
        """Recompute visible rows from the real message list."""
        items = self._messages if messages is None else messages
        display_items: list[ChatMessage] = []

        for index, message in enumerate(items):
            previous_message = items[index - 1] if index > 0 else None
            if previous_message is None or self._is_time_break(previous_message, message):
                display_items.append(self._build_time_separator_item(message))
            display_items.append(self._build_display_message_item(message))

        return display_items

    def _build_append_fragment(self, previous_message: ChatMessage | None, messages: list[ChatMessage]) -> list[ChatMessage]:
        """Build the display fragment for messages appended to the tail."""
        fragment: list[ChatMessage] = []

        for index, message in enumerate(messages):
            candidate_previous = previous_message if index == 0 else messages[index - 1]
            if candidate_previous is None or self._is_time_break(candidate_previous, message):
                fragment.append(self._build_time_separator_item(message))
            fragment.append(self._build_display_message_item(message))

        return fragment

    def _build_prepend_fragment(self, messages: list[ChatMessage], next_message: ChatMessage | None) -> list[ChatMessage]:
        """Build the display fragment for older history inserted at the head."""
        fragment: list[ChatMessage] = []

        for index, message in enumerate(messages):
            candidate_previous = messages[index - 1] if index > 0 else None
            if candidate_previous is None or self._is_time_break(candidate_previous, message):
                fragment.append(self._build_time_separator_item(message))
            fragment.append(self._build_display_message_item(message))

        if messages and next_message is not None and self._is_time_break(messages[-1], next_message):
            fragment.append(self._build_time_separator_item(next_message))

        return fragment

    def _emit_rows_for_message_ids(self, message_ids: list[str] | None) -> None:
        """Emit dataChanged for a set of real messages when structure is unchanged."""
        if not message_ids:
            return
        seen: set[str] = set()
        for message_id in message_ids:
            if message_id in seen:
                continue
            seen.add(message_id)
            self._emit_display_row_changed(message_id, self._display_roles())

    def _emit_display_row_changed(self, message_id: str, roles: list[int]) -> None:
        """Emit dataChanged for the display row representing one real message."""
        row = self._find_display_row_for_message(message_id)
        if row < 0:
            self._apply_display_rebuild(changed_message_ids=[message_id])
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

    def _find_display_row_for_time_separator(self, source_message_id: str) -> int:
        """Return the display row for one standalone time separator."""
        for row, item in enumerate(self._display_items):
            if self._display_kind(item) != self.DISPLAY_TIME_SEPARATOR:
                continue
            if self._source_message_id(item) == source_message_id:
                return row
        return -1

    def is_time_separator_expanded(self, source_message_id: str) -> bool:
        """Return whether one time separator currently uses the expanded format."""
        return bool(source_message_id) and source_message_id in self._expanded_time_separator_ids

    def toggle_time_separator_expanded(self, source_message_id: str) -> bool:
        """Toggle the display format for one time separator row."""
        row = self._find_display_row_for_time_separator(source_message_id)
        if row < 0:
            return False

        if source_message_id in self._expanded_time_separator_ids:
            self._expanded_time_separator_ids.remove(source_message_id)
        else:
            self._expanded_time_separator_ids.add(source_message_id)

        index = self.index(row, 0)
        self.dataChanged.emit(index, index, self._display_roles())
        return True

    def _build_display_message_item(self, message: ChatMessage) -> ChatMessage:
        """Return the visible row item for one real message."""
        if message.status == MessageStatus.RECALLED:
            return self._build_recall_notice_item(message)
        return message

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
        extra = dict(message.extra or {})
        extra.update(
            {
                self.DISPLAY_KIND_KEY: self.DISPLAY_RECALL_NOTICE,
                self.SOURCE_MESSAGE_ID_KEY: message.message_id,
            }
        )
        return ChatMessage(
            message_id=f"__recall__::{message.message_id}",
            session_id=message.session_id,
            sender_id=message.sender_id,
            content=resolve_recall_notice(message),
            message_type=MessageType.SYSTEM,
            status=MessageStatus.RECALLED,
            timestamp=message.timestamp,
            updated_at=message.updated_at,
            is_self=message.is_self,
            is_ai=message.is_ai,
            extra=extra,
        )

    def _display_kind(self, item: ChatMessage) -> str:
        """Return the display kind for a visible row."""
        return str((item.extra or {}).get(self.DISPLAY_KIND_KEY, self.DISPLAY_MESSAGE))

    def _source_message_id(self, item: ChatMessage) -> str:
        """Return the real message id represented by a visible row."""
        return str((item.extra or {}).get(self.SOURCE_MESSAGE_ID_KEY, item.message_id))

    def _display_signature(self, item: ChatMessage) -> tuple[str, str]:
        """Return a stable signature for one visible row."""
        return (self._display_kind(item), self._source_message_id(item))

    def _display_roles(self) -> list[int]:
        """Return the Qt roles affected by visible-row updates."""
        return [
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.UserRole,
            Qt.ItemDataRole.SizeHintRole,
            self.MessageRole,
            self.IsSelfRole,
            self.MessageTypeRole,
            self.StatusRole,
            self.TimestampRole,
            self.SenderIdRole,
            self.DisplayKindRole,
            self.SourceMessageIdRole,
            self.TimeExpandedRole,
        ]

    def _message_sort_key(self, message: ChatMessage) -> tuple[float, str]:
        """Return a stable ordering key for real chat messages."""
        normalized = self._normalize_timestamp(message.timestamp)
        epoch_seconds = normalized.timestamp() if normalized is not None else 0.0
        return (epoch_seconds, message.message_id)

    def _sort_messages(self) -> None:
        """Keep the real message list sorted by message timestamp."""
        self._messages.sort(key=self._message_sort_key)

    def _prune_expanded_time_separator_ids(self, messages: list[ChatMessage]) -> None:
        """Drop expanded-state entries for messages that are no longer loaded."""
        loaded_ids = {message.message_id for message in messages}
        self._expanded_time_separator_ids.intersection_update(loaded_ids)

    def _are_messages_non_decreasing(self, messages: list[ChatMessage]) -> bool:
        """Return whether a message batch is already ordered by timestamp."""
        return all(self._message_sort_key(messages[index - 1]) <= self._message_sort_key(messages[index]) for index in range(1, len(messages)))

    def _can_incrementally_append(self, messages: list[ChatMessage]) -> bool:
        """Return whether a batch can be appended without rebuilding the full list."""
        if not messages:
            return False
        if not self._are_messages_non_decreasing(messages):
            return False
        if not self._messages:
            return True
        return self._message_sort_key(self._messages[-1]) <= self._message_sort_key(messages[0])

    def _can_incrementally_prepend(self, messages: list[ChatMessage]) -> bool:
        """Return whether a batch can be prepended without rebuilding the full list."""
        if not messages:
            return False
        if not self._are_messages_non_decreasing(messages):
            return False
        if not self._messages:
            return True
        return self._message_sort_key(messages[-1]) <= self._message_sort_key(self._messages[0])

    def _should_reorder_message(self, message_id: str) -> bool:
        """Return whether one updated message now falls outside its neighbor ordering."""
        for index, message in enumerate(self._messages):
            if message.message_id != message_id:
                continue
            current_key = self._message_sort_key(message)
            if index > 0 and current_key < self._message_sort_key(self._messages[index - 1]):
                return True
            if index < len(self._messages) - 1 and current_key > self._message_sort_key(self._messages[index + 1]):
                return True
            return False
        return False

    @staticmethod
    def _normalize_timestamp(value):
        """Normalize timestamps for time-break comparisons."""
        return coerce_local_datetime(value)

    @staticmethod
    def _coerce_extra_int(message: ChatMessage, key: str) -> int:
        """Read one integer from message extra metadata safely."""
        try:
            return max(0, int((message.extra or {}).get(key, 0) or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _normalized_reader_ids(message: ChatMessage) -> list[str]:
        """Return a stable unique reader-id list from message extra metadata."""
        normalized: list[str] = []
        for reader_id in (message.extra or {}).get("read_by_user_ids", []) or []:
            value = str(reader_id or "").strip()
            if value and value not in normalized:
                normalized.append(value)
        return normalized

    def _is_time_break(self, current: ChatMessage, next_message: ChatMessage) -> bool:
        """Return whether adjacent messages belong to different visible time groups."""
        current_time = self._normalize_timestamp(current.timestamp)
        next_time = self._normalize_timestamp(next_message.timestamp)
        if current_time is None or next_time is None:
            return False
        if current_time.date() != next_time.date():
            return True
        return abs((next_time - current_time).total_seconds()) >= 5 * 60

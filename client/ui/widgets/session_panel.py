"""Left-side session list panel with migrated prototype styling."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import QEvent, QItemSelectionModel, QSortFilterProxyModel, Qt, QTimer, Signal
from PySide6.QtWidgets import QAbstractItemView, QFrame, QHBoxLayout, QListView, QVBoxLayout, QWidget

from qfluentwidgets import FluentIcon, ScrollBarHandleDisplayMode, SearchLineEdit, ToolButton
from qfluentwidgets.components.widgets.scroll_bar import SmoothScrollDelegate

from client.delegates.session_delegate import SessionDelegate
from client.events.event_bus import get_event_bus
from client.managers.session_manager import SessionEvent, get_session_manager
from client.models.message import Session
from client.models.session_model import SessionModel
from client.ui.styles import StyleSheet


class SessionFilterProxyModel(QSortFilterProxyModel):
    """Proxy model used for search filtering."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_text = ""

    def set_filter_text(self, text: str) -> None:
        """Update current filter text."""
        self._filter_text = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        """Filter sessions by name or latest message preview."""
        if not self._filter_text:
            return True

        index = self.sourceModel().index(source_row, 0, source_parent)
        session = index.data(Qt.ItemDataRole.UserRole)
        if not session:
            return False

        name = (session.name or "").lower()
        preview = (session.last_message or "").lower()
        return self._filter_text in name or self._filter_text in preview


class SessionPanel(QWidget):
    """Session list panel with search and event-driven updates."""

    session_selected = Signal(str)
    add_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("SessionPanel")

        self._session_model: Optional[SessionModel] = None
        self._proxy_model: Optional[SessionFilterProxyModel] = None
        self._session_delegate: Optional[SessionDelegate] = None
        self._scroll_delegate: Optional[SmoothScrollDelegate] = None
        self._session_manager = get_session_manager()
        self._event_bus = get_event_bus()
        self._sessions_snapshot: tuple | None = None

        self._setup_ui()
        self._subscribe_to_events()

    def _setup_ui(self) -> None:
        """Create search box and list view."""
        self.setMinimumWidth(220)
        self.setMaximumWidth(520)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.search_bar = QWidget(self)
        self.search_bar.setObjectName("sessionSearchBar")
        self.search_bar_layout = QHBoxLayout(self.search_bar)
        self.search_bar_layout.setContentsMargins(12, 12, 12, 12)
        self.search_bar_layout.setSpacing(12)

        self.search_box = SearchLineEdit(self.search_bar)
        self.search_box.setPlaceholderText("搜索")
        self.search_box.setFixedHeight(36)
        self.search_box.textChanged.connect(self._on_search_text_changed)

        self.add_button = ToolButton(FluentIcon.ADD, self.search_bar)
        self.add_button.setObjectName("sessionAddButton")
        self.add_button.setToolTip("新建会话")
        self.add_button.setFixedSize(36, 36)
        self.add_button.clicked.connect(self.add_requested.emit)

        self.search_bar_layout.addWidget(self.search_box, 1, Qt.AlignmentFlag.AlignVCenter)
        self.search_bar_layout.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.session_list = QListView(self)
        self.session_list.setObjectName("sessionListView")
        self.session_list.setFrameShape(QFrame.Shape.NoFrame)
        self.session_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.session_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.session_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.session_list.setLayoutMode(QListView.LayoutMode.Batched)
        self.session_list.setBatchSize(24)
        self.session_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.session_list.setContentsMargins(0, 0, 0, 0)
        self.session_list.setSpacing(0)
        self.session_list.setMouseTracking(True)

        self._setup_session_model()
        self.session_list.clicked.connect(self._on_session_clicked)

        self.main_layout.addWidget(self.search_bar)
        self.main_layout.addWidget(self.session_list, 1)
        StyleSheet.SESSION_PANEL.apply(self)

    def _setup_session_model(self) -> None:
        """Initialize session model, proxy, and delegate."""
        self._session_model = SessionModel(self)
        self._proxy_model = SessionFilterProxyModel(self)
        self._proxy_model.setSourceModel(self._session_model)
        self._session_delegate = SessionDelegate(self)
        self._scroll_delegate = SmoothScrollDelegate(self.session_list)
        self._scroll_delegate.vScrollBar.setHandleDisplayMode(ScrollBarHandleDisplayMode.ALWAYS)
        self._scroll_delegate.hScrollBar.setForceHidden(True)
        self._scroll_delegate.vScrollBar.setForceHidden(True)

        self.session_list.setModel(self._proxy_model)
        self.session_list.setItemDelegate(self._session_delegate)
        self.session_list.installEventFilter(self)
        self.session_list.viewport().installEventFilter(self)
        self._scroll_delegate.vScrollBar.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        """Show overlay scrollbar on list hover without changing viewport width."""
        if self._scroll_delegate and watched in {
            self.session_list,
            self.session_list.viewport(),
            self._scroll_delegate.vScrollBar,
        }:
            if event.type() == QEvent.Type.Enter:
                self._scroll_delegate.vScrollBar.setForceHidden(False)
            elif event.type() == QEvent.Type.Leave:
                QTimer.singleShot(0, self._sync_scrollbar_visibility)

        return super().eventFilter(watched, event)

    def _sync_scrollbar_visibility(self) -> None:
        if not self._scroll_delegate:
            return
        hovered = (
            self.session_list.underMouse()
            or self.session_list.viewport().underMouse()
            or self._scroll_delegate.vScrollBar.underMouse()
        )
        self._scroll_delegate.vScrollBar.setForceHidden(not hovered)

    def load_sessions_from_manager(self) -> None:
        """Load sessions from SessionManager into the model."""
        sessions = self._session_manager.sessions
        snapshot = self._session_snapshot(sessions)
        if snapshot == self._sessions_snapshot:
            return
        self._sessions_snapshot = snapshot
        self._session_model.set_sessions(sessions)

    def _subscribe_to_events(self) -> None:
        """Subscribe to session events."""
        self._event_bus.subscribe_sync(SessionEvent.CREATED, self._on_session_created)
        self._event_bus.subscribe_sync(SessionEvent.UPDATED, self._on_session_updated)
        self._event_bus.subscribe_sync(SessionEvent.DELETED, self._on_session_deleted)
        self._event_bus.subscribe_sync(SessionEvent.MESSAGE_ADDED, self._on_message_added)
        self._event_bus.subscribe_sync(SessionEvent.UNREAD_CHANGED, self._on_unread_changed)

    def _on_session_created(self, data: dict) -> None:
        """Handle newly created sessions."""
        session = data.get("session")
        if session:
            self._add_session_safe(session)

    def _on_session_updated(self, data: dict) -> None:
        """Handle session updates or full reloads."""
        session = data.get("session")
        if session:
            self._update_session_safe(session)
            return

        sessions = data.get("sessions")
        if sessions:
            self._load_all_sessions_safe(sessions)

    def _on_session_deleted(self, data: dict) -> None:
        """Handle deleted sessions."""
        session_id = data.get("session_id")
        if session_id:
            self._remove_session_safe(session_id)

    def _on_message_added(self, data: dict) -> None:
        """Update preview text when a message arrives."""
        session_id = data.get("session_id")
        message = data.get("message")
        if session_id and message:
            self._session_model.update_session(
                session_id,
                last_message=getattr(message, "content", ""),
                last_message_time=getattr(message, "timestamp", None),
            )

    def _on_unread_changed(self, data: dict) -> None:
        """Update unread badge count."""
        session_id = data.get("session_id")
        unread_count = data.get("unread_count", 0)
        if session_id:
            self._session_model.update_session(session_id, unread_count=unread_count)

    def _add_session_safe(self, session: Session) -> None:
        """Insert session into the list model."""
        self._sessions_snapshot = None
        self._session_model.add_session(session)

    def _update_session_safe(self, session: Session) -> None:
        """Update a session in the list model."""
        self._sessions_snapshot = None
        self._session_model.update_session(
            session.session_id,
            name=session.name,
            avatar=session.avatar,
            last_message=session.last_message,
            last_message_time=session.last_message_time,
            unread_count=session.unread_count,
        )

    def _remove_session_safe(self, session_id: str) -> None:
        """Remove a session from the list model."""
        self._sessions_snapshot = None
        self._session_model.remove_session(session_id)

    def _load_all_sessions_safe(self, sessions: list[Session]) -> None:
        """Reset the list model with a fresh session array."""
        snapshot = self._session_snapshot(sessions)
        if snapshot == self._sessions_snapshot:
            return
        self._sessions_snapshot = snapshot
        self._session_model.set_sessions(sessions)

    def _on_search_text_changed(self, text: str) -> None:
        """Apply search filter."""
        if self._proxy_model:
            self._proxy_model.set_filter_text(text)

    def _on_session_clicked(self, index) -> None:
        """Emit selected session ID."""
        if not index.isValid():
            return

        session = index.data(Qt.ItemDataRole.UserRole)
        if session:
            self.session_selected.emit(session.session_id)

    def get_search_box(self) -> SearchLineEdit:
        """Return search box widget."""
        return self.search_box

    def get_add_button(self) -> ToolButton:
        """Return add button widget."""
        return self.add_button

    def get_session_list(self) -> QListView:
        """Return the list view widget."""
        return self.session_list

    def get_session_model(self) -> SessionModel:
        """Return the source session model."""
        return self._session_model

    def get_proxy_model(self) -> SessionFilterProxyModel:
        """Return the search proxy model."""
        return self._proxy_model

    @staticmethod
    def _session_snapshot(sessions: list[Session]) -> tuple:
        """Build a lightweight immutable signature for full-list reload skipping."""
        def normalize_timestamp(value) -> float | None:
            if value is None:
                return None
            if isinstance(value, datetime):
                return value.timestamp()
            if hasattr(value, "timestamp"):
                try:
                    return float(value.timestamp())
                except (TypeError, ValueError):
                    return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        return tuple(
            (
                session.session_id,
                session.name,
                session.last_message,
                normalize_timestamp(session.last_message_time),
                session.unread_count,
                getattr(session, "is_pinned", False),
            )
            for session in sessions
        )

    def select_session(self, session_id: str, emit_signal: bool = True) -> bool:
        """Programmatically select a session in the list."""
        if not self._session_model or not self._proxy_model:
            return False

        for row, session in enumerate(self._session_model.get_sessions()):
            if session.session_id != session_id:
                continue

            source_index = self._session_model.index(row, 0)
            proxy_index = self._proxy_model.mapFromSource(source_index)
            if not proxy_index.isValid():
                return False

            self.session_list.selectionModel().setCurrentIndex(
                proxy_index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Current,
            )
            self.session_list.scrollTo(proxy_index, QAbstractItemView.ScrollHint.PositionAtCenter)
            if emit_signal:
                self.session_selected.emit(session_id)
            return True

        return False

    def add_session(self, session: Session) -> None:
        """Public helper to add a session to the model."""
        self._session_model.add_session(session)

    def remove_session(self, session_id: str) -> None:
        """Public helper to remove a session."""
        self._session_model.remove_session(session_id)

    def update_session(self, session_id: str, **kwargs) -> None:
        """Public helper to update a session."""
        self._session_model.update_session(session_id, **kwargs)

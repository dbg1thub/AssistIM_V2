"""Left-side session list panel with migrated prototype styling."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QItemSelectionModel, QSortFilterProxyModel, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QFrame, QListView, QVBoxLayout, QWidget

from qfluentwidgets import SearchLineEdit

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

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("SessionPanel")

        self._session_model: Optional[SessionModel] = None
        self._proxy_model: Optional[SessionFilterProxyModel] = None
        self._session_delegate: Optional[SessionDelegate] = None
        self._session_manager = get_session_manager()
        self._event_bus = get_event_bus()

        self._setup_ui()
        self._subscribe_to_events()

    def _setup_ui(self) -> None:
        """Create search box and list view."""
        self.setMinimumWidth(220)
        self.setMaximumWidth(520)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(12)

        self.search_box = SearchLineEdit(self)
        self.search_box.setPlaceholderText("搜索")
        self.search_box.setMinimumHeight(38)
        self.search_box.textChanged.connect(self._on_search_text_changed)

        self.session_list = QListView(self)
        self.session_list.setObjectName("sessionListView")
        self.session_list.setFrameShape(QFrame.Shape.NoFrame)
        self.session_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.session_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.session_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.session_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.session_list.setSpacing(2)
        self.session_list.setMouseTracking(True)

        self._setup_session_model()
        self.session_list.clicked.connect(self._on_session_clicked)

        self.main_layout.addWidget(self.search_box)
        self.main_layout.addWidget(self.session_list, 1)
        StyleSheet.SESSION_PANEL.apply(self)

    def _setup_session_model(self) -> None:
        """Initialize session model, proxy, and delegate."""
        self._session_model = SessionModel(self)
        self._proxy_model = SessionFilterProxyModel(self)
        self._proxy_model.setSourceModel(self._session_model)
        self._session_delegate = SessionDelegate(self)

        self.session_list.setModel(self._proxy_model)
        self.session_list.setItemDelegate(self._session_delegate)

    def load_sessions_from_manager(self) -> None:
        """Load sessions from SessionManager into the model."""
        sessions = self._session_manager.sessions
        self._session_model.clear()
        for session in sessions:
            self._session_model.add_session(session)

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
        self._session_model.add_session(session)

    def _update_session_safe(self, session: Session) -> None:
        """Update a session in the list model."""
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
        self._session_model.remove_session(session_id)

    def _load_all_sessions_safe(self, sessions: list[Session]) -> None:
        """Reset the list model with a fresh session array."""
        self._session_model.clear()
        for session in sessions:
            self._session_model.add_session(session)

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

    def get_session_list(self) -> QListView:
        """Return the list view widget."""
        return self.session_list

    def get_session_model(self) -> SessionModel:
        """Return the source session model."""
        return self._session_model

    def get_proxy_model(self) -> SessionFilterProxyModel:
        """Return the search proxy model."""
        return self._proxy_model

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

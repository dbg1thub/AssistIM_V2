"""Left-side session list panel with migrated prototype styling."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QEvent, QItemSelectionModel, QSortFilterProxyModel, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QDialog, QFrame, QHBoxLayout, QListView, QSizePolicy, QVBoxLayout, QWidget

from qfluentwidgets import Action, BodyLabel, InfoBar, MessageBoxBase, RoundMenu, ScrollBarHandleDisplayMode, SearchLineEdit, SubtitleLabel, ToolButton
from qfluentwidgets.components.widgets.scroll_bar import SmoothScrollDelegate

from client.core.app_icons import AppIcon
from client.core.i18n import tr
from client.delegates.session_delegate import SessionDelegate
from client.events.event_bus import get_event_bus
from client.managers.search_manager import search_all
from client.managers.session_manager import SessionEvent
from client.models.message import Session, format_message_preview
from client.models.session_model import SessionModel
from client.ui.controllers.session_controller import get_session_controller
from client.ui.styles import StyleSheet
from client.ui.widgets.global_search_panel import GlobalSearchPopupOverlay


logger = logging.getLogger(__name__)


class DeleteSessionConfirmDialog(MessageBoxBase):
    """Ask for confirmation before removing one conversation locally."""

    def __init__(self, session_name: str, parent=None):
        super().__init__(parent=parent)
        display_name = (session_name or "").strip() or tr("session.unnamed", "Unnamed Session")
        title = SubtitleLabel(tr("session.delete.confirm_title", "Delete Conversation"), self.widget)
        content = BodyLabel(
            tr(
                "session.delete.confirm_content",
                "Remove {name} from this device and clear its local chat history?",
                name=display_name,
            ),
            self.widget,
        )
        content.setWordWrap(True)
        self.viewLayout.addWidget(title)
        self.viewLayout.addWidget(content)
        self.viewLayout.addStretch(1)
        self.yesButton.setText(tr("session.delete.confirm_action", "Delete"))
        self.cancelButton.setText(tr("common.cancel", "Cancel"))
        self.widget.setMinimumWidth(380)


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

        name = (session.display_name() or "").lower()
        preview = (session.last_message or "").lower()
        draft_preview = (getattr(session, "draft_preview", "") or "").lower()
        return self._filter_text in name or self._filter_text in preview or self._filter_text in draft_preview


class SessionPanel(QWidget):
    """Session list panel with search and event-driven updates."""

    session_selected = Signal(str)
    add_requested = Signal()
    search_result_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("SessionPanel")

        self._session_model: Optional[SessionModel] = None
        self._proxy_model: Optional[SessionFilterProxyModel] = None
        self._session_delegate: Optional[SessionDelegate] = None
        self._scroll_delegate: Optional[SmoothScrollDelegate] = None
        self._session_controller = get_session_controller()
        self._event_bus = get_event_bus()
        self._sessions_snapshot: tuple | None = None
        self._event_subscriptions: list[tuple[str, object]] = []
        self._ui_tasks: set[asyncio.Task] = set()
        self._teardown_started = False
        self._search_task: asyncio.Task | None = None
        self._search_flyout = None
        self._search_flyout_view: Optional[GlobalSearchPopupOverlay] = None
        self._pending_search_keyword = ''
        self._search_generation = 0
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._trigger_global_search)

        self._setup_ui()
        self._subscribe_to_events()
        self.destroyed.connect(self._on_destroyed)

    def _setup_ui(self) -> None:
        """Create search box and list view."""
        self.setMinimumWidth(0)
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
        self.search_box.setPlaceholderText(tr("session.search.placeholder", "搜索"))
        self.search_box.setFixedHeight(36)
        self.search_box.setMinimumWidth(0)
        self.search_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.search_box.textChanged.connect(self._on_search_text_changed)

        self.add_button = ToolButton(AppIcon.ADD, self.search_bar)
        self.add_button.setObjectName("sessionAddButton")
        self.add_button.setToolTip(tr("session.add.tooltip", "New Conversation"))
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
        self.session_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.session_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.session_list.setContentsMargins(0, 0, 0, 0)
        self.session_list.setSpacing(0)
        self.session_list.setMouseTracking(True)
        self.session_list.setMinimumWidth(0)

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
            elif event.type() == QEvent.Type.Resize:
                QTimer.singleShot(0, self._relayout_session_list)
            elif watched is self.session_list.viewport() and event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.RightButton:
                    self._show_session_context_menu(event.pos())
                    return True

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

    def _relayout_session_list(self) -> None:
        """Force item geometry to follow the latest viewport width during splitter drags."""
        self.session_list.doItemsLayout()
        self.session_list.updateGeometries()
        self.session_list.viewport().update()

    def load_sessions(self, sessions: Optional[list[Session]] = None) -> None:
        """Load sessions into the model, defaulting to the current controller cache."""
        sessions = list(sessions) if sessions is not None else self._session_controller.get_sessions()
        snapshot = self._session_snapshot(sessions)
        if snapshot == self._sessions_snapshot:
            return
        self._sessions_snapshot = snapshot
        self._session_model.set_sessions(sessions)

    def _subscribe_to_events(self) -> None:
        """Subscribe to session events."""
        self._subscribe_sync(SessionEvent.ADDED, self._on_session_added)
        self._subscribe_sync(SessionEvent.UPDATED, self._on_session_updated)
        self._subscribe_sync(SessionEvent.DELETED, self._on_session_deleted)
        self._subscribe_sync(SessionEvent.MESSAGE_ADDED, self._on_message_added)
        self._subscribe_sync(SessionEvent.UNREAD_CHANGED, self._on_unread_changed)

    def _subscribe_sync(self, event_type: str, handler) -> None:
        """Subscribe and retain the handler for explicit unsubscribe on teardown."""
        self._event_subscriptions.append((event_type, handler))
        self._event_bus.subscribe_sync(event_type, handler)

    def _unsubscribe_from_events(self) -> None:
        """Remove all event-bus subscriptions owned by this panel."""
        while self._event_subscriptions:
            event_type, handler = self._event_subscriptions.pop()
            self._event_bus.unsubscribe_sync(event_type, handler)

    def _on_destroyed(self, *_args) -> None:
        """Detach event listeners and cancel outstanding async actions."""
        self.quiesce()

    def quiesce(self) -> None:
        """Stop sidebar async work before logout clears runtime state."""
        if self._teardown_started:
            return
        self._teardown_started = True
        self._unsubscribe_from_events()
        self._search_timer.stop()
        self._cancel_pending_task(self._search_task)
        self._search_task = None
        self._dismiss_search_flyout(clear_results=False)
        self._cancel_all_ui_tasks()

    def _cancel_all_ui_tasks(self) -> None:
        """Cancel all background actions launched from this panel."""
        for task in list(self._ui_tasks):
            if not task.done():
                task.cancel()

    def _on_session_added(self, data: dict) -> None:
        """Handle newly cached visible sessions."""
        session = data.get("session")
        if session:
            self._add_session_safe(session)

    def _on_session_updated(self, data: dict) -> None:
        """Handle session updates or full reloads."""
        session = data.get("session")
        if session:
            self._update_session_safe(session)
            if self.search_box.text().strip():
                self._trigger_global_search()
            return

        sessions = data.get("sessions")
        if isinstance(sessions, list):
            self._load_all_sessions_safe(sessions)
            if self.search_box.text().strip():
                self._trigger_global_search()

    def _on_session_deleted(self, data: dict) -> None:
        """Handle deleted sessions."""
        session_id = data.get("session_id")
        if session_id:
            self._remove_session_safe(session_id)
            if self.search_box.text().strip():
                self._trigger_global_search()

    def _on_message_added(self, data: dict) -> None:
        """Update preview text when a message arrives."""
        session_id = data.get("session_id")
        message = data.get("message")
        if session_id and message:
            session = self._session_controller.get_session(session_id)
            if session is not None:
                self._update_session_safe(session)
                return
            self._session_model.update_session(
                session_id,
                last_message=format_message_preview(
                    getattr(message, "content", ""),
                    getattr(message, "message_type", None),
                ),
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
            extra=session.extra,
            draft_preview=getattr(session, "draft_preview", None),
            is_pinned=getattr(session, "is_pinned", session.extra.get("is_pinned", False)),
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
        """Open or update the anchored search flyout for the current keyword."""
        keyword = str(text or "").strip()
        self._pending_search_keyword = keyword
        if self._proxy_model:
            self._proxy_model.set_filter_text("")

        if not keyword:
            self._search_timer.stop()
            self._cancel_pending_task(self._search_task)
            self._search_task = None
            self._dismiss_search_flyout(clear_results=True)
            return

        self._search_timer.start()

    def _trigger_global_search(self) -> None:
        """Run the latest pending local-search request."""
        keyword = self._pending_search_keyword
        if not keyword:
            return
        self._search_generation += 1
        generation = self._search_generation
        flyout_view = self._show_search_flyout()
        if flyout_view is not None:
            flyout_view.set_loading(keyword)
        self._set_search_task(self._run_global_search(keyword, generation))

    async def _run_global_search(self, keyword: str, generation: int) -> None:
        """Populate grouped search results for the current keyword."""
        results = await search_all(keyword, message_limit=30, contact_limit=30, group_limit=30)
        if self.search_box.text().strip() != keyword or generation != self._search_generation:
            return
        flyout_view = self._show_search_flyout()
        if flyout_view is not None:
            flyout_view.set_results(keyword, results)

    def _clear_search_results_view(self) -> None:
        """Clear search results without tearing down the anchored flyout."""
        if self._search_flyout_view is not None:
            self._search_flyout_view.clear_results()

    def _on_search_result_activated(self, payload: object) -> None:
        """Forward one activated grouped-search result to the host chat window."""
        self.clear_search()
        self.search_result_requested.emit(payload)

    def _show_search_flyout(self) -> Optional[GlobalSearchPopupOverlay]:
        """Create or reuse the anchored search overlay below the search box."""
        if self._search_flyout_view is not None and self._search_flyout is not None:
            self._search_flyout_view.set_content_width(self.search_box.width() + 72)
            self._search_flyout_view.show_for(self.search_box)
            return self._search_flyout_view

        host = self.window() or self
        view = GlobalSearchPopupOverlay(host)
        view.set_content_width(self.search_box.width() + 72)
        view.resultActivated.connect(self._on_search_result_activated)
        view.closed.connect(self._on_search_flyout_closed)
        view.show_for(self.search_box)
        self._search_flyout = view
        self._search_flyout_view = view
        return view

    def _dismiss_search_flyout(self, *, clear_results: bool) -> None:
        """Close the anchored search overlay when the search is cleared or completed."""
        if self._search_flyout_view is not None and clear_results:
            self._search_flyout_view.clear_results()
        if self._search_flyout is not None:
            self._search_flyout.close_overlay()
        else:
            self._clear_search_flyout()

    def _clear_search_flyout(self) -> None:
        """Drop stale search-overlay references after the popup closes."""
        self._search_flyout = None
        self._search_flyout_view = None

    def _on_search_flyout_closed(self) -> None:
        """Reset search state when the overlay closes outside normal clear flow."""
        self._clear_search_flyout()

    def _on_session_clicked(self, index) -> None:
        """Emit selected session ID."""
        if not index.isValid():
            return

        session = index.data(Qt.ItemDataRole.UserRole)
        if session:
            self.session_selected.emit(session.session_id)

    def _show_session_context_menu(self, position) -> None:
        """Show a session-level context menu without changing selection."""
        index = self.session_list.indexAt(position)
        if not index.isValid():
            return

        session = index.data(Qt.ItemDataRole.UserRole)
        if not session:
            return

        pinned = bool(getattr(session, "is_pinned", False) or session.extra.get("is_pinned"))
        muted = bool(session.extra.get("is_muted", False))
        menu = RoundMenu(parent=self)
        menu.setMinimumWidth(148)
        pin_action = Action(
            tr("session.context.unpin", "Unpin") if pinned else tr("session.context.pin", "Pin"),
            self,
        )
        unread_action = Action(
            tr("session.context.mark_read", "Mark as Read")
            if session.unread_count > 0
            else tr("session.context.mark_unread", "Mark as Unread"),
            self,
        )
        mute_action = Action(
            tr("session.context.unmute", "Turn Off Mute") if muted else tr("session.context.mute", "Mute Notifications"),
            self,
        )
        delete_action = Action(tr("common.delete", "Delete"), self)

        menu.addAction(pin_action)
        menu.addAction(unread_action)
        menu.addAction(mute_action)
        menu.addSeparator()
        menu.addAction(delete_action)

        delete_item = delete_action.property("item")
        if delete_item is not None:
            delete_item.setForeground(QColor("#d13438"))

        pin_action.triggered.connect(
            lambda _checked=False, sid=session.session_id, target=not pinned: self._toggle_session_pin_local(
                sid,
                target,
            )
        )
        unread_action.triggered.connect(
            lambda _checked=False, sid=session.session_id, unread=(session.unread_count == 0): self._schedule_ui_task(
                self._session_controller.mark_session_unread(sid, unread),
                f"toggle unread {sid}",
            )
        )
        mute_action.triggered.connect(
            lambda _checked=False, sid=session.session_id, target=not muted: self._toggle_session_mute_local(
                sid,
                target,
            )
        )
        delete_action.triggered.connect(
            lambda _checked=False, sid=session.session_id: self._trigger_session_delete(sid)
        )

        menu.exec(self.session_list.viewport().mapToGlobal(position))

    def _trigger_session_delete(self, session_id: str) -> None:
        """Request session removal and wait for manager-driven deletion updates."""
        session = self._session_model.get_session_by_id(session_id) if self._session_model else None
        session_name = session.display_name() if session else ""
        dialog = DeleteSessionConfirmDialog(session_name, self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._schedule_ui_task(self._session_controller.remove_session(session_id), f"delete session {session_id}")

    def _toggle_session_pin_local(self, session_id: str, pinned: bool) -> None:
        """Delegate pin state changes to the controller/manager chain only."""
        self._schedule_ui_task(self._session_controller.set_pinned(session_id, pinned), f"toggle pin {session_id}")

    def _toggle_session_mute_local(self, session_id: str, muted: bool) -> None:
        """Delegate mute state changes to the controller/manager chain only."""
        self._schedule_ui_task(self._session_controller.set_muted(session_id, muted), f"toggle mute {session_id}")

    def _current_selected_session_id(self) -> str | None:
        """Return the session id currently selected in the list, if any."""
        current_index = self.session_list.currentIndex()
        if not current_index.isValid():
            return None
        session = current_index.data(Qt.ItemDataRole.UserRole)
        return getattr(session, "session_id", None) if session else None

    def _cancel_pending_task(self, task: asyncio.Task | None) -> None:
        """Cancel one tracked task if it is still running."""
        if task is not None and not task.done():
            task.cancel()

    def _set_search_task(self, coro) -> None:
        """Keep only the latest grouped-search task alive."""
        self._cancel_pending_task(self._search_task)
        task = asyncio.create_task(coro)
        self._search_task = task
        self._ui_tasks.add(task)
        task.add_done_callback(lambda finished: self._finalize_search_task(finished, "search sidebar"))

    def _finalize_search_task(self, task: asyncio.Task, context: str) -> None:
        """Drop the tracked grouped-search task and report failures."""
        if self._search_task is task:
            self._search_task = None
        self._finalize_ui_task(task, context)

    def _schedule_ui_task(self, coro, context: str) -> None:
        """Schedule a session-menu coroutine and log failures."""
        task = asyncio.create_task(coro)
        self._ui_tasks.add(task)
        task.add_done_callback(lambda finished, name=context: self._finalize_ui_task(finished, name))

    def _finalize_ui_task(self, task: asyncio.Task, context: str) -> None:
        """Drop completed tasks from tracking and report failures."""
        self._ui_tasks.discard(task)
        self._log_ui_task_result(task, context)

    def _log_ui_task_result(self, task: asyncio.Task, context: str) -> None:
        """Log background task failures from session-menu actions and surface one visible error."""
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Session menu task failed: %s", context)
            InfoBar.error(
                tr("session.action.failed.title", "Session Action Failed"),
                tr("session.action.failed.content", "Unable to complete the latest session action."),
                parent=self.window(),
                duration=2200,
            )

    def clear_search(self) -> None:
        """Reset the shared sidebar search state."""
        self.search_box.clear()
        self._dismiss_search_flyout(clear_results=True)

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
                session.display_name(),
                session.last_message,
                normalize_timestamp(session.last_message_time),
                session.unread_count,
                getattr(session, "is_pinned", False),
                session.extra.get("pinned_at"),
                bool(session.extra.get("last_message_mentions_current_user", False)),
                bool(session.extra.get("is_muted", False)),
                getattr(session, "draft_preview", None),
                session.display_avatar(),
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











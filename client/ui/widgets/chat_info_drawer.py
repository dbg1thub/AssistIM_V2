"""Right-side floating chat info drawer with an acrylic surface."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from qfluentwidgets import (
    AvatarWidget,
    BodyLabel,
    CaptionLabel,
    HyperlinkButton,
    IconWidget,
    IndicatorPosition,
    SingleDirectionScrollArea,
    SwitchButton,
    isDarkTheme,
)
from qfluentwidgets.components.widgets.acrylic_label import AcrylicBrush

from client.core.app_icons import AppIcon, CollectionIcon
from client.core.avatar_rendering import apply_avatar_widget_image
from client.core.avatar_utils import profile_avatar_seed
from client.core.i18n import tr
from client.models.message import Session
from client.ui.widgets.fluent_divider import FluentDivider


class ChatInfoTileCard(QWidget):
    """Rounded tile surface for avatar and add-entry cards."""

    def __init__(self, *, dashed: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._dashed = dashed
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:
        rect = self.rect().adjusted(1, 1, -1, -1)
        fill = QColor(255, 255, 255, 108) if not isDarkTheme() else QColor(255, 255, 255, 18)
        border = QColor(0, 0, 0, 26) if not isDarkTheme() else QColor(255, 255, 255, 22)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(fill)
        pen = QPen(border, 1)
        if self._dashed:
            pen.setDashPattern([6, 5])
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 12, 12)
        super().paintEvent(event)


class ChatInfoParticipantTile(QWidget):
    """One compact participant tile shown at the top of the drawer."""

    clicked = Signal()

    def __init__(self, *, is_add_tile: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._is_add_tile = is_add_tile
        self.setObjectName("chatInfoAddTile" if is_add_tile else "chatInfoParticipantTile")
        self.setCursor(Qt.PointingHandCursor if is_add_tile else Qt.ArrowCursor)
        self.setFixedWidth(76)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self.card = ChatInfoTileCard(dashed=is_add_tile, parent=self)
        self.card.setObjectName("chatInfoAddGlyph" if is_add_tile else "chatInfoParticipantCard")
        self.card.setFixedSize(56, 56)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if is_add_tile:
            self.avatar = None
            self.add_icon = IconWidget(AppIcon.ADD, self.card)
            self.add_icon.setFixedSize(22, 22)
            card_layout.addWidget(self.add_icon, 0, Qt.AlignmentFlag.AlignCenter)
        else:
            self.avatar = AvatarWidget(self.card)
            self.avatar.setRadius(28)
            card_layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignCenter)
            self.add_icon = None

        self.name_label = CaptionLabel(self)
        self.name_label.setObjectName("chatInfoAddName" if is_add_tile else "chatInfoParticipantName")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setFixedWidth(76)

        layout.addWidget(self.card, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.name_label, 0, Qt.AlignmentFlag.AlignCenter)

        if is_add_tile:
            self.name_label.setText(tr("chat.info.add", "Add"))

    def set_participant(self, *, title: str, avatar: object = "", user_id: str = "", username: str = "", gender: str = "") -> None:
        """Update one participant tile with avatar and display name."""
        if self._is_add_tile or self.avatar is None:
            return

        display_name = (title or "").strip() or tr("session.unnamed", "Untitled Session")
        self.name_label.setText(display_name)
        apply_avatar_widget_image(
            self.avatar,
            avatar,
            gender=gender,
            seed=profile_avatar_seed(user_id=user_id, username=username, display_name=display_name),
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._is_add_tile and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ChatInfoActionRow(QWidget):
    """Flat drawer row with chevron/switch trailing content."""

    activated = Signal()
    toggled = Signal(bool)

    def __init__(self, title: str, *, switch: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(12)

        self.title_label = BodyLabel(title, self)
        self.title_label.setObjectName("chatInfoActionTitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.title_label, 1)

        self.switch_button: SwitchButton | None = None
        self.chevron_icon: IconWidget | None = None

        if switch:
            self.switch_button = SwitchButton(self, indicatorPos=IndicatorPosition.RIGHT)
            self.switch_button.setText("")
            self.switch_button.label.hide()
            self.switch_button.setFixedWidth(46)
            self.switch_button.checkedChanged.connect(self.toggled.emit)
            layout.addWidget(self.switch_button, 0, Qt.AlignmentFlag.AlignRight)
        else:
            self.chevron_icon = IconWidget(CollectionIcon("chevron_right"), self)
            self.chevron_icon.setFixedSize(16, 16)
            layout.addWidget(self.chevron_icon, 0, Qt.AlignmentFlag.AlignRight)

    def set_checked(self, checked: bool) -> None:
        """Update switch state without emitting external change handlers."""
        if self.switch_button is None:
            return
        blocker = QSignalBlocker(self.switch_button)
        try:
            self.switch_button.setChecked(bool(checked))
        finally:
            del blocker

    def is_checked(self) -> bool:
        return bool(self.switch_button and self.switch_button.isChecked())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self.rect().contains(event.position().toPoint()):
            return super().mouseReleaseEvent(event)

        if self.switch_button is not None:
            if not self.switch_button.geometry().contains(event.position().toPoint()):
                self.switch_button.toggleChecked()
            event.accept()
            return

        self.activated.emit()
        event.accept()


class StaticHyperlinkButton(HyperlinkButton):
    """Hyperlink-style button that keeps a static visual state on hover."""

    def enterEvent(self, event) -> None:
        self.isHover = False
        self.update()
        event.accept()

    def leaveEvent(self, event) -> None:
        self.isHover = False
        self.update()
        event.accept()


class ChatInfoPrivateContent(QWidget):
    """Private-chat content shown inside the info drawer."""

    searchRequested = Signal()
    addRequested = Signal()
    clearRequested = Signal()
    muteToggled = Signal(bool)
    pinToggled = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session: Optional[Session] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 18)
        layout.setSpacing(14)

        members_layout = QHBoxLayout()
        members_layout.setContentsMargins(0, 0, 0, 0)
        members_layout.setSpacing(7)
        self.counterpart_tile = ChatInfoParticipantTile(parent=self)
        self.add_tile = ChatInfoParticipantTile(is_add_tile=True, parent=self)
        members_layout.addWidget(self.counterpart_tile, 0, Qt.AlignmentFlag.AlignLeft)
        members_layout.addWidget(self.add_tile, 0, Qt.AlignmentFlag.AlignLeft)
        members_layout.addStretch(1)

        self.search_row = ChatInfoActionRow(tr("chat.info.search", "Find Chat Content"), parent=self)
        self.mute_row = ChatInfoActionRow(tr("chat.info.mute", "Mute Notifications"), switch=True, parent=self)
        self.pin_row = ChatInfoActionRow(tr("chat.info.pin", "Pin Chat"), switch=True, parent=self)
        self.clear_button = StaticHyperlinkButton(parent=self)
        self.clear_button.setObjectName("chatInfoClearLink")
        self.clear_button.setText(tr("chat.info.clear", "Clear Chat History"))

        layout.addLayout(members_layout)
        layout.addWidget(FluentDivider(self, variant=FluentDivider.INSET, inset=12))
        layout.addWidget(self.search_row)
        layout.addWidget(FluentDivider(self, variant=FluentDivider.INSET, inset=12))
        layout.addWidget(self.mute_row)
        layout.addWidget(self.pin_row)
        layout.addWidget(FluentDivider(self, variant=FluentDivider.INSET, inset=12))
        layout.addSpacing(8)
        layout.addWidget(self.clear_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

        self.search_row.activated.connect(self.searchRequested.emit)
        self.add_tile.clicked.connect(self.addRequested.emit)
        self.mute_row.toggled.connect(self.muteToggled.emit)
        self.pin_row.toggled.connect(self.pinToggled.emit)
        self.clear_button.clicked.connect(self.clearRequested.emit)

    def set_session(self, session: Session | None) -> None:
        self._session = session
        if session is None:
            self.counterpart_tile.set_participant(title=tr("session.unnamed", "Untitled Session"))
            self.mute_row.set_checked(False)
            self.pin_row.set_checked(False)
            self.setEnabled(False)
            return

        self.setEnabled(True)
        extra = dict(session.extra or {})
        display_name = str(session.name or "").strip() or tr("session.unnamed", "Untitled Session")
        self.counterpart_tile.set_participant(
            title=display_name,
            avatar=session.avatar or "",
            user_id=str(extra.get("counterpart_id", "") or session.session_id),
            username=str(extra.get("counterpart_username", "") or ""),
            gender=str(extra.get("gender", "") or ""),
        )
        self.mute_row.set_checked(bool(extra.get("is_muted", False)))
        self.pin_row.set_checked(bool(getattr(session, "is_pinned", False) or extra.get("is_pinned", False)))


class ChatInfoPlaceholderContent(QWidget):
    """Simple placeholder shown for unsupported drawer content variants."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.title_label = BodyLabel(self)
        self.title_label.setObjectName("chatInfoPlaceholderTitle")
        self.content_label = CaptionLabel(self)
        self.content_label.setObjectName("chatInfoPlaceholderContent")
        self.content_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.content_label)
        layout.addStretch(1)

    def set_text(self, title: str, content: str) -> None:
        self.title_label.setText(title)
        self.content_label.setText(content)


class ChatInfoDrawerContent(QWidget):
    """Scrollable drawer content that switches between private and placeholder panels."""

    searchRequested = Signal()
    addRequested = Signal()
    clearRequested = Signal()
    muteToggled = Signal(bool)
    pinToggled = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session: Optional[Session] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget(self)
        self.private_content = ChatInfoPrivateContent(self)
        self.placeholder_content = ChatInfoPlaceholderContent(self)
        self.stack.addWidget(self.private_content)
        self.stack.addWidget(self.placeholder_content)
        layout.addWidget(self.stack)

        self.private_content.searchRequested.connect(self.searchRequested.emit)
        self.private_content.addRequested.connect(self.addRequested.emit)
        self.private_content.clearRequested.connect(self.clearRequested.emit)
        self.private_content.muteToggled.connect(self.muteToggled.emit)
        self.private_content.pinToggled.connect(self.pinToggled.emit)

    def set_session(self, session: Session | None) -> None:
        """Refresh content for the current session type."""
        self._session = session
        if session is None:
            self.placeholder_content.set_text(
                tr("chat.info.empty.title", "No Conversation Selected"),
                tr("chat.info.empty.content", "Select a conversation first to view chat details."),
            )
            self.stack.setCurrentWidget(self.placeholder_content)
            return

        if session.session_type == "direct" and not session.is_ai_session:
            self.private_content.set_session(session)
            self.stack.setCurrentWidget(self.private_content)
            return

        if session.session_type == "group":
            self.placeholder_content.set_text(
                tr("chat.info.group.title", "Group Chat Info"),
                tr("chat.info.group.content", "The group chat info panel will be implemented next."),
            )
        else:
            self.placeholder_content.set_text(
                tr("chat.info.ai.title", "AI Session Info"),
                tr("chat.info.ai.content", "The AI session info panel will be implemented later."),
            )
        self.stack.setCurrentWidget(self.placeholder_content)


class AcrylicDrawerSurface(QWidget):
    """One acrylic-painted surface used by the floating chat info drawer."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("chatInfoDrawer")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._acrylic_brush = AcrylicBrush(self, 30)

    def _update_acrylic_color(self) -> None:
        if isDarkTheme():
            self._acrylic_brush.tintColor = QColor(32, 32, 32, 204)
            self._acrylic_brush.luminosityColor = QColor(0, 0, 0, 0)
        else:
            self._acrylic_brush.tintColor = QColor(255, 255, 255, 188)
            self._acrylic_brush.luminosityColor = QColor(255, 255, 255, 0)

    def capture_backdrop(self, global_rect: QRect | None = None) -> None:
        """Grab one acrylic backdrop snapshot, mirroring NavigationPanel behavior."""
        if global_rect is None:
            if self.width() <= 0 or self.height() <= 0:
                return
            global_rect = QRect(self.mapToGlobal(QPoint(0, 0)), self.size())

        if global_rect.width() <= 0 or global_rect.height() <= 0:
            return
        if not self._acrylic_brush.isAvailable():
            self.update()
            return
        self._acrylic_brush.grabImage(global_rect)
        self.update()

    def paintEvent(self, event) -> None:
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        path.addRoundedRect(0, 1, self.width() - 1, self.height() - 1, 7, 7)
        path.addRect(self.width() - 8, 1, 8, self.height() - 1)
        shape_path = path.simplified()

        if self._acrylic_brush.isAvailable():
            self._acrylic_brush.setClipPath(shape_path)
            self._update_acrylic_color()
            self._acrylic_brush.paint()
        else:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(36, 36, 36, 232) if isDarkTheme() else QColor(255, 255, 255, 236))
            painter.drawPath(shape_path)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if isDarkTheme():
            pen = QPen(QColor(57, 57, 57), 1)
        else:
            pen = QPen(QColor(218, 218, 218), 1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(shape_path)


class ChatInfoDrawerOverlay(QWidget):
    """Full-content overlay that hosts a floating acrylic drawer."""

    searchRequested = Signal()
    addRequested = Signal()
    clearRequested = Signal()
    muteToggled = Signal(bool)
    pinToggled = Signal(bool)
    visibilityChanged = Signal(bool)

    DRAWER_WIDTH = 322

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session: Optional[Session] = None
        self._open = False
        self.setObjectName("chatInfoOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setEnabled(False)
        self.hide()

        self.drawer = AcrylicDrawerSurface(self)
        self.drawer.setObjectName("chatInfoDrawer")

        drawer_layout = QVBoxLayout(self.drawer)
        drawer_layout.setContentsMargins(0, 0, 0, 0)
        drawer_layout.setSpacing(0)

        self.scroll_area = SingleDirectionScrollArea(self.drawer, orient=Qt.Orientation.Vertical)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("QScrollArea{border: none; background: transparent}")
        self.scroll_area.viewport().setStyleSheet("background: transparent")

        self.content_widget = ChatInfoDrawerContent(self)
        self.content_widget.setObjectName("chatInfoDrawerContent")
        self.scroll_area.setWidget(self.content_widget)
        drawer_layout.addWidget(self.scroll_area)

        self._animation = QPropertyAnimation(self.drawer, b"geometry", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._animation.finished.connect(self._on_animation_finished)

        self.content_widget.searchRequested.connect(self.searchRequested.emit)
        self.content_widget.addRequested.connect(self.addRequested.emit)
        self.content_widget.clearRequested.connect(self.clearRequested.emit)
        self.content_widget.muteToggled.connect(self.muteToggled.emit)
        self.content_widget.pinToggled.connect(self.pinToggled.emit)

    def set_session(self, session: Session | None) -> None:
        self._session = session
        self.content_widget.set_session(session)
        if session is None and self.isVisible():
            self.close_drawer()

    def set_content_geometry(self, rect: QRect) -> None:
        self.setGeometry(rect)
        self._sync_drawer_geometry(immediate=True)

    def is_open(self) -> bool:
        return self._open and self.isVisible()

    def toggle(self) -> None:
        if self.is_open():
            self.close_drawer()
        else:
            self.open_drawer()

    def open_drawer(self) -> None:
        if self._session is None:
            return

        self._open = True
        self.setEnabled(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.show()
        self.raise_()
        self.visibilityChanged.emit(True)
        self._animation.stop()

        start_rect = self._closed_rect()
        end_rect = self._open_rect()
        if self.drawer._acrylic_brush.isAvailable():
            self.drawer.capture_backdrop(QRect(self.mapToGlobal(end_rect.topLeft()), end_rect.size()))
        self.drawer.setGeometry(start_rect)
        self.drawer.show()
        self._animation.setStartValue(start_rect)
        self._animation.setEndValue(end_rect)
        self._animation.start()

    def close_drawer(self, *, immediate: bool = False) -> None:
        if not self.isVisible():
            self._open = False
            self.setEnabled(False)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            return

        self._open = False
        self.visibilityChanged.emit(False)
        self._animation.stop()
        if immediate:
            self.drawer.setGeometry(self._closed_rect())
            self.setEnabled(False)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.hide()
            return
        self._animation.setStartValue(self.drawer.geometry())
        self._animation.setEndValue(self._closed_rect())
        self._animation.start()

    def _on_animation_finished(self) -> None:
        if not self._open:
            self.setEnabled(False)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.hide()

    def _drawer_width(self) -> int:
        available = max(0, self.width())
        if available <= 0:
            return 0
        return min(available, self.DRAWER_WIDTH)

    def _open_rect(self) -> QRect:
        width = self._drawer_width()
        return QRect(max(0, self.width() - width), 0, width, self.height())

    def _closed_rect(self) -> QRect:
        width = self._drawer_width()
        return QRect(self.width(), 0, width, self.height())

    def _sync_drawer_geometry(self, *, immediate: bool) -> None:
        target_rect = self._open_rect() if self._open and self.isVisible() else self._closed_rect()
        if immediate or self._animation.state() != QPropertyAnimation.State.Running:
            self.drawer.setGeometry(target_rect)
        if self.isVisible() and self._open:
            self.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_drawer_geometry(immediate=True)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.is_open() and not self.drawer.geometry().contains(event.position().toPoint()):
            self.close_drawer()
            event.accept()
            return
        super().mousePressEvent(event)

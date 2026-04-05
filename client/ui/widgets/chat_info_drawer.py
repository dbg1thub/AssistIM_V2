"""Right-side floating chat info drawer with an acrylic surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, QRectF, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    HyperlinkButton,
    IconWidget,
    IndicatorPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SingleDirectionScrollArea,
    SwitchButton,
    TextEdit,
    isDarkTheme,
)
from qfluentwidgets.components.widgets.acrylic_label import AcrylicBrush

from client.core.app_icons import AppIcon, CollectionIcon
from client.core.avatar_rendering import get_avatar_image_store
from client.core.avatar_utils import profile_avatar_seed
from client.core.i18n import tr
from client.models.message import Session
from client.ui.widgets.contact_shared import apply_themed_dialog_surface
from client.ui.widgets.fluent_divider import FluentDivider


@dataclass(frozen=True)
class GroupProfileUpdateRequest:
    """Typed shared group-profile mutation emitted by the drawer."""

    session_id: str
    group_id: str
    name: str | None = None
    announcement: str | None = None


@dataclass(frozen=True)
class GroupSelfProfileUpdateRequest:
    """Typed self-scoped group-profile mutation emitted by the drawer."""

    session_id: str
    group_id: str
    note: str | None = None
    my_group_nickname: str | None = None


@dataclass(frozen=True)
class GroupMemberManagementRequest:
    """Typed group-member management request emitted by the drawer."""

    session_id: str
    group_id: str
    mode: str = "browse"


class ChatInfoTileCard(QFrame):
    """Tile surface used by participant and action entries."""

    def __init__(self, *, dashed: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._dashed = dashed
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._dashed:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        border = QColor(255, 255, 255, 42) if isDarkTheme() else QColor(0, 0, 0, 52)
        pen = QPen(border, 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 12, 12)
        painter.end()


class ChatInfoAvatarWidget(QWidget):
    """Rounded-rect avatar used by the chat info drawer."""

    def __init__(
        self,
        avatar: str = "",
        *,
        gender: str = "",
        seed: str = "",
        size: int = 52,
        radius: int = 10,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._source = str(avatar or "")
        self._gender = str(gender or "")
        self._seed = str(seed or "")
        self._radius = max(0, int(radius))
        self._store = get_avatar_image_store()
        self._store.avatar_ready.connect(self._handle_avatar_ready)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedSize(size, size)

    def set_avatar(self, avatar: str, *, gender: str = "", seed: str = "") -> None:
        self._source = str(avatar or "")
        self._gender = str(gender or "")
        self._seed = str(seed or "")
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(path)

        _source, display_path = self._store.resolve_display_path(self._source, gender=self._gender, seed=self._seed)
        pixmap = QPixmap(display_path) if display_path else QPixmap()
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(self.rect(), scaled)
        else:
            painter.fillPath(path, QColor("#626B76") if isDarkTheme() else QColor("#D7DEE8"))

        painter.setClipping(False)
        if pixmap.isNull():
            initial = (self._seed or "?")[:1].upper()
            font = QFont()
            font.setPixelSize(16)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, initial)
        painter.end()

    def _handle_avatar_ready(self, source: str) -> None:
        if str(source or "") == self._source:
            self.update()


class ChatInfoAnnouncementDialog(QDialog):
    """Modal editor used for group announcements."""

    def __init__(self, initial_text: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("chat.info.group.announcement", "Announcement"))
        self.setModal(True)
        self.resize(360, 260)
        apply_themed_dialog_surface(self, "ChatInfoAnnouncementDialog")
        self._value = str(initial_text or "").strip()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.editor = TextEdit(self)
        self.editor.setPlaceholderText(tr("chat.info.group.announcement.empty", "No group announcement yet"))
        self.editor.setPlainText(self._value)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = PushButton(tr("common.cancel", "Cancel"), self)
        self.save_button = PrimaryPushButton(tr("common.save", "Save"), self)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.save_button)

        layout.addWidget(self.editor, 1)
        layout.addLayout(button_row)

        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._submit)

    def _submit(self) -> None:
        self._value = self.editor.toPlainText().strip()
        self.accept()

    def value(self) -> str:
        """Return the last confirmed announcement value."""
        return self._value


class ChatInfoAnnouncementPreview(CaptionLabel):
    """Single-line announcement preview that elides overflowing text."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._raw_text = ""
        self.setObjectName("chatInfoDetailFieldValue")
        self.setWordWrap(False)
        self.setToolTip("")

    def set_preview_text(self, value: str) -> None:
        self._raw_text = str(value or "").strip()
        self.setToolTip(self._raw_text)
        self._refresh_text()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_text()

    def _refresh_text(self) -> None:
        fm = self.fontMetrics()
        self.setText(fm.elidedText(self._raw_text, Qt.TextElideMode.ElideRight, max(0, self.width())))


class ChatInfoAnnouncementField(QWidget):
    """Compact group-announcement field aligned with other detail blocks."""

    activated = Signal()

    def __init__(self, title: str, *, parent=None) -> None:
        super().__init__(parent)
        self._editable = True
        self._value = ""
        self.setObjectName("chatInfoDetailField")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 3, 12, 3)
        layout.setSpacing(3)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        self.title_label = BodyLabel(title, self)
        self.title_label.setObjectName("chatInfoActionTitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.chevron_icon = IconWidget(CollectionIcon("chevron_right"), self)
        self.chevron_icon.setFixedSize(16, 16)

        header_layout.addWidget(self.title_label, 1)
        header_layout.addWidget(self.chevron_icon, 0, Qt.AlignmentFlag.AlignRight)

        self.preview_label = ChatInfoAnnouncementPreview(self)
        self.preview_label.setIndent(0)
        self.preview_label.hide()

        layout.addLayout(header_layout)
        layout.addWidget(self.preview_label)

    def set_preview_text(self, value: str) -> None:
        self._value = str(value or "").strip()
        self.setToolTip(self._value)
        self.preview_label.set_preview_text(self._value)
        self.preview_label.setVisible(bool(self._value))

    def current_value(self) -> str:
        """Return the raw announcement preview value currently bound into the field."""
        return self._value

    def is_editable(self) -> bool:
        """Return whether the field should respond to activation gestures."""
        return self._editable

    def set_editable(self, editable: bool) -> None:
        """Toggle whether the field can open the shared announcement editor."""
        self._editable = bool(editable)
        self.setEnabled(True)
        cursor = Qt.CursorShape.PointingHandCursor if self._editable else Qt.CursorShape.ArrowCursor
        self.setCursor(cursor)
        self.title_label.setCursor(cursor)
        self.chevron_icon.setCursor(cursor)
        self.chevron_icon.setVisible(self._editable)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._editable and event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ChatInfoParticipantTile(QWidget):
    """One compact participant tile shown at the top of the drawer."""

    clicked = Signal()

    def __init__(
        self,
        *,
        is_add_tile: bool = False,
        action_icon: AppIcon | CollectionIcon | None = None,
        action_label: str | None = None,
        dashed: bool | None = None,
        clickable: bool | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._is_add_tile = is_add_tile
        self._action_clickable = bool(is_add_tile if clickable is None else clickable)
        self.setObjectName("chatInfoAddTile" if is_add_tile else "chatInfoParticipantTile")
        self.setCursor(Qt.PointingHandCursor if self._action_clickable else Qt.ArrowCursor)
        self.setFixedWidth(60)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self.card = ChatInfoTileCard(dashed=bool(is_add_tile if dashed is None else dashed), parent=self)
        self.card.setObjectName("chatInfoAddGlyph" if is_add_tile else "chatInfoParticipantCard")
        self.card.setFixedSize(44, 44)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if is_add_tile:
            self.avatar = None
            self.add_icon = IconWidget(action_icon or AppIcon.ADD, self.card)
            self.add_icon.setFixedSize(16, 16)
            card_layout.addWidget(self.add_icon, 0, Qt.AlignmentFlag.AlignCenter)
        else:
            self.avatar = ChatInfoAvatarWidget(parent=self.card, size=44, radius=8)
            card_layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignCenter)
            self.add_icon = None

        self.name_label = CaptionLabel(self)
        self.name_label.setObjectName("chatInfoAddName" if is_add_tile else "chatInfoParticipantName")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setFixedWidth(60)

        layout.addWidget(self.card, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.name_label, 0, Qt.AlignmentFlag.AlignCenter)

        if is_add_tile:
            self.name_label.setText(str(action_label or tr("chat.info.add", "Add")))

    def set_participant(self, *, title: str, avatar: object = "", user_id: str = "", username: str = "", gender: str = "") -> None:
        """Update one participant tile with avatar and display name."""
        if self._is_add_tile or self.avatar is None:
            return

        display_name = (title or "").strip() or tr("session.unnamed", "Untitled Session")
        self.name_label.setText(display_name)
        self.avatar.set_avatar(
            str(avatar or ""),
            gender=gender,
            seed=profile_avatar_seed(user_id=user_id, username=username, display_name=display_name),
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            self._is_add_tile
            and self._action_clickable
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
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
        self.setFixedHeight(40)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(12)

        self.title_label = BodyLabel(title, self)
        self.title_label.setObjectName("chatInfoActionTitle")
        self.title_label.setCursor(Qt.PointingHandCursor)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.title_label, 1)

        self.switch_button: SwitchButton | None = None
        self.chevron_icon: IconWidget | None = None

        if switch:
            self.switch_button = SwitchButton(self, indicatorPos=IndicatorPosition.RIGHT)
            self.switch_button.setText("")
            self.switch_button.label.hide()
            self.switch_button.setFixedWidth(46)
            self.switch_button.setCursor(Qt.PointingHandCursor)
            self.switch_button.checkedChanged.connect(self.toggled.emit)
            layout.addWidget(self.switch_button, 0, Qt.AlignmentFlag.AlignRight)
        else:
            self.chevron_icon = IconWidget(CollectionIcon("chevron_right"), self)
            self.chevron_icon.setFixedSize(16, 16)
            self.chevron_icon.setCursor(Qt.PointingHandCursor)
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
        if (
            not self.isEnabled()
            or event.button() != Qt.MouseButton.LeftButton
            or not self.rect().contains(event.position().toPoint())
        ):
            return super().mouseReleaseEvent(event)

        point = event.position().toPoint()
        if self.switch_button is not None:
            if not self.switch_button.geometry().contains(point):
                self.switch_button.toggleChecked()
            event.accept()
            return

        if self.chevron_icon is not None:
            self.activated.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


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
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

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
        display_name = str(session.chat_title() or session.display_name() or "").strip() or tr("session.unnamed", "Untitled Session")
        self.counterpart_tile.set_participant(
            title=display_name,
            avatar=session.display_avatar() or "",
            user_id=str(extra.get("counterpart_id", "") or session.session_id),
            username=str(extra.get("counterpart_username", "") or ""),
            gender=session.display_gender(),
        )
        self.mute_row.set_checked(bool(extra.get("is_muted", False)))
        self.pin_row.set_checked(bool(getattr(session, "is_pinned", False) or extra.get("is_pinned", False)))


class ChatInfoDetailField(QWidget):
    """Editable label/value pair used by group-chat metadata blocks."""

    valueCommitted = Signal(str)

    def __init__(self, title: str, *, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("chatInfoDetailField")
        self._editable = True
        self._editing = False
        self._value = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 3, 12, 3)
        layout.setSpacing(3)

        self.title_label = BodyLabel(title, self)
        self.title_label.setObjectName("chatInfoDetailFieldTitle")
        self.value_label = CaptionLabel(self)
        self.value_label.setObjectName("chatInfoDetailFieldValue")
        self.value_label.setWordWrap(True)
        self.value_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.editor = LineEdit(self)
        self.editor.setObjectName("chatInfoDetailFieldEditor")
        self.editor.hide()
        self.editor.editingFinished.connect(self._commit_edit)
        self.editor.installEventFilter(self)
        self.value_label.installEventFilter(self)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.editor)

    def set_value(self, value: str) -> None:
        normalized = str(value or "").strip()
        self._value = normalized
        self.value_label.setText(normalized)
        self.editor.setText(normalized)

    def set_editable(self, editable: bool) -> None:
        """Toggle whether the value label can enter inline edit mode."""
        self._editable = bool(editable)
        self.value_label.setCursor(
            Qt.CursorShape.PointingHandCursor if self._editable else Qt.CursorShape.ArrowCursor
        )
        if not self._editable and self._editing:
            self._cancel_edit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        super().mouseReleaseEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if (
            watched is self.value_label
            and self._editable
            and event.type() == QEvent.Type.MouseButtonRelease
            and not self._editing
        ):
            self._begin_edit()
            event.accept()
            return True
        if watched is self.editor and event.type() == QEvent.Type.FocusOut:
            QTimer.singleShot(0, self._commit_edit)
        return super().eventFilter(watched, event)

    def _begin_edit(self) -> None:
        if self._editing or not self._editable:
            return
        self._editing = True
        self.value_label.hide()
        self.editor.show()
        self.editor.setFocus()
        self.editor.selectAll()

    def _cancel_edit(self) -> None:
        self._editing = False
        self.editor.setText(self._value)
        self.editor.hide()
        self.value_label.show()

    def _commit_edit(self) -> None:
        if not self._editing:
            return
        value = str(self.editor.text() or "").strip()
        self._editing = False
        previous_value = self._value
        self._value = value
        self.value_label.setText(value)
        self.editor.hide()
        self.value_label.show()
        if value != previous_value:
            self.valueCommitted.emit(value)


class ChatInfoGroupMemberRow(QWidget):
    """One compact row shown when filtering group members from the search box."""

    def __init__(self, member: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("chatInfoGroupMemberRow")
        self.setFixedHeight(58)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(10)

        self.avatar = ChatInfoAvatarWidget(parent=self, size=44, radius=9)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        self.name_label = BodyLabel(self)
        self.name_label.setObjectName("chatInfoGroupMemberName")
        self.meta_label = CaptionLabel(self)
        self.meta_label.setObjectName("chatInfoGroupMemberMeta")
        self.meta_label.setWordWrap(False)

        text_layout.addWidget(self.name_label)
        text_layout.addWidget(self.meta_label)
        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(text_layout, 1)

        self.set_member(member)

    def set_member(self, member: dict[str, Any]) -> None:
        display_name = ChatInfoGroupContent.member_display_name(member)
        self.name_label.setText(display_name)
        username = str(member.get("username", "") or "").strip()
        assistim_id = str(member.get("assistim_id", "") or "").strip()
        meta = username or assistim_id or str(member.get("id", "") or "").strip()
        self.meta_label.setText(meta)
        self.meta_label.setVisible(bool(meta))
        self.avatar.set_avatar(
            str(member.get("avatar", "") or ""),
            gender=str(member.get("gender", "") or ""),
            seed=profile_avatar_seed(
                user_id=str(member.get("id", "") or ""),
                username=username,
                display_name=display_name,
            ),
        )


class ChatInfoGroupContent(QWidget):
    """Group-chat content shown inside the info drawer."""

    MAX_VISIBLE_TILES = 12
    MAX_VISIBLE_MEMBER_TILES = 10
    SEARCH_RESULT_LIMIT = 60

    searchRequested = Signal()
    clearRequested = Signal()
    leaveRequested = Signal()
    muteToggled = Signal(bool)
    pinToggled = Signal(bool)
    showNicknameToggled = Signal(bool)
    memberManagementRequested = Signal(object)
    groupProfileUpdateRequested = Signal(object)
    groupSelfProfileUpdateRequested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session: Optional[Session] = None
        self._members: list[dict[str, Any]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.member_search_box = SearchLineEdit(self)
        self.member_search_box.setObjectName("chatInfoMemberSearchBox")
        self.member_search_box.setPlaceholderText(tr("chat.info.group.member_search.placeholder", "Search Group Members"))
        self.member_search_box.setFixedHeight(36)

        self.members_grid_widget = QWidget(self)
        self.members_grid_widget.setObjectName("chatInfoMembersGrid")
        self.members_grid_layout = QGridLayout(self.members_grid_widget)
        self.members_grid_layout.setContentsMargins(0, 0, 0, 0)
        self.members_grid_layout.setHorizontalSpacing(7)
        self.members_grid_layout.setVerticalSpacing(10)

        self.search_results_widget = QWidget(self)
        self.search_results_widget.setObjectName("chatInfoMemberSearchResults")
        self.search_results_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.search_results_layout = QVBoxLayout(self.search_results_widget)
        self.search_results_layout.setContentsMargins(0, 0, 0, 0)
        self.search_results_layout.setSpacing(0)
        self.search_results_widget.setVisible(False)

        self.search_empty_label = CaptionLabel(tr("chat.info.group.member_search.empty", "No matching group members"), self)
        self.search_empty_label.setObjectName("chatInfoMemberSearchEmpty")
        self.search_empty_label.setVisible(False)

        self.group_name_field = ChatInfoDetailField(tr("chat.info.group.name", "Group Name"), parent=self)
        self.announcement_field = ChatInfoAnnouncementField(tr("chat.info.group.announcement", "Announcement"), parent=self)
        self.note_field = ChatInfoDetailField(tr("chat.info.group.note", "Note"), parent=self)
        self.nickname_field = ChatInfoDetailField(tr("chat.info.group.my_nickname", "My Group Nickname"), parent=self)

        self.search_row = ChatInfoActionRow(tr("chat.info.search", "Find Chat Content"), parent=self)
        self.mute_row = ChatInfoActionRow(tr("chat.info.mute", "Mute Notifications"), switch=True, parent=self)
        self.pin_row = ChatInfoActionRow(tr("chat.info.pin", "Pin Chat"), switch=True, parent=self)
        self.show_nickname_row = ChatInfoActionRow(
            tr("chat.info.group.show_member_nickname", "Show Group Member Nicknames"),
            switch=True,
            parent=self,
        )
        self.view_more_button = StaticHyperlinkButton(parent=self)
        self.view_more_button.setObjectName("chatInfoSecondaryLink")
        self.view_more_button.setText(tr("chat.info.group.view_more", "View More Members"))
        self.view_more_button.setVisible(False)
        self.clear_button = StaticHyperlinkButton(parent=self)
        self.clear_button.setObjectName("chatInfoClearLink")
        self.clear_button.setText(tr("chat.info.clear", "Clear Chat History"))
        self.leave_button = StaticHyperlinkButton(parent=self)
        self.leave_button.setObjectName("chatInfoDangerLink")
        self.leave_button.setText(tr("chat.info.group.leave", "Leave Group Chat"))

        self.content_stack = QStackedWidget(self)
        self.default_page = QWidget(self)
        self.default_page.setObjectName("chatInfoDefaultPage")
        self.search_page = QWidget(self)
        self.search_page.setObjectName("chatInfoSearchPage")

        default_layout = QVBoxLayout(self.default_page)
        default_layout.setContentsMargins(0, 6, 0, 0)
        default_layout.setSpacing(10)
        self.members_divider = FluentDivider(self.default_page, variant=FluentDivider.INSET, inset=12)
        self.search_divider = FluentDivider(self.default_page, variant=FluentDivider.INSET, inset=12)
        self.settings_divider = FluentDivider(self.default_page, variant=FluentDivider.INSET, inset=12)
        self.leave_divider = FluentDivider(self.default_page, variant=FluentDivider.INSET, inset=12)
        default_layout.addWidget(self.members_grid_widget)
        default_layout.addWidget(self.view_more_button, 0, Qt.AlignmentFlag.AlignLeft)
        default_layout.addWidget(self.members_divider)
        default_layout.addWidget(self.group_name_field)
        default_layout.addWidget(self.announcement_field)
        default_layout.addWidget(self.note_field)
        default_layout.addWidget(self.nickname_field)
        default_layout.addWidget(self.search_divider)
        default_layout.addWidget(self.search_row)
        default_layout.addWidget(self.settings_divider)
        default_layout.addWidget(self.mute_row)
        default_layout.addWidget(self.pin_row)
        default_layout.addWidget(self.show_nickname_row)
        default_layout.addWidget(self.leave_divider)
        default_layout.addSpacing(6)
        default_layout.addWidget(self.clear_button, 0, Qt.AlignmentFlag.AlignHCenter)
        default_layout.addWidget(FluentDivider(self.default_page, variant=FluentDivider.INSET, inset=12))
        default_layout.addWidget(self.leave_button, 0, Qt.AlignmentFlag.AlignHCenter)
        default_layout.addStretch(1)

        search_layout = QVBoxLayout(self.search_page)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(0)
        search_layout.addWidget(self.search_results_widget, 1)
        search_layout.addWidget(self.search_empty_label, 0, Qt.AlignmentFlag.AlignTop)
        search_layout.addStretch(1)

        self.content_stack.addWidget(self.default_page)
        self.content_stack.addWidget(self.search_page)
        self.content_stack.setCurrentWidget(self.default_page)

        layout.addWidget(self.member_search_box)
        layout.addWidget(self.content_stack, 1)

        self.member_search_box.textChanged.connect(self._on_member_search_text_changed)
        self.search_row.activated.connect(self.searchRequested.emit)
        self.mute_row.toggled.connect(self.muteToggled.emit)
        self.pin_row.toggled.connect(self.pinToggled.emit)
        self.show_nickname_row.toggled.connect(self.showNicknameToggled.emit)
        self.announcement_field.activated.connect(self._open_announcement_editor)
        self.view_more_button.clicked.connect(lambda: self._emit_member_management_request("browse"))
        self.clear_button.clicked.connect(self.clearRequested.emit)
        self.leave_button.clicked.connect(self.leaveRequested.emit)
        self.group_name_field.valueCommitted.connect(self._emit_group_name_update)
        self.note_field.valueCommitted.connect(self._emit_note_update)
        self.nickname_field.valueCommitted.connect(self._emit_nickname_update)

    @staticmethod
    def member_display_name(member: dict[str, Any]) -> str:
        return (
            str(member.get("remark", "") or "").strip()
            or str(member.get("group_nickname", "") or "").strip()
            or str(member.get("nickname", "") or "").strip()
            or str(member.get("display_name", "") or "").strip()
            or str(member.get("username", "") or "").strip()
            or str(member.get("id", "") or "").strip()
            or tr("session.unnamed", "Untitled Session")
        )

    @staticmethod
    def _normalize_member_payload(member: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(member or {})
        normalized.setdefault("id", str(normalized.get("user_id", "") or ""))
        normalized["id"] = str(normalized.get("id", "") or "")
        normalized["username"] = str(normalized.get("username", "") or "")
        normalized["nickname"] = str(normalized.get("nickname", "") or "")
        normalized["group_nickname"] = str(normalized.get("group_nickname", "") or "")
        normalized["remark"] = str(normalized.get("remark", "") or "")
        normalized["display_name"] = ChatInfoGroupContent.member_display_name(normalized)
        normalized["avatar"] = str(normalized.get("avatar", "") or "")
        normalized["gender"] = str(normalized.get("gender", "") or "")
        return normalized

    def _current_group_id(self) -> str:
        if self._session is None:
            return ""
        return self._session.authoritative_group_id()

    def _build_group_profile_request(self, **changes: str | None) -> GroupProfileUpdateRequest | None:
        if self._session is None:
            return None
        return GroupProfileUpdateRequest(
            session_id=self._session.session_id,
            group_id=self._current_group_id(),
            name=changes.get("name"),
            announcement=changes.get("announcement"),
        )

    def _build_group_self_profile_request(self, **changes: str | None) -> GroupSelfProfileUpdateRequest | None:
        if self._session is None:
            return None
        return GroupSelfProfileUpdateRequest(
            session_id=self._session.session_id,
            group_id=self._current_group_id(),
            note=changes.get("note"),
            my_group_nickname=changes.get("my_group_nickname"),
        )

    def _emit_member_management_request(self, mode: str) -> None:
        if self._session is None:
            return
        self.memberManagementRequested.emit(
            GroupMemberManagementRequest(
                session_id=self._session.session_id,
                group_id=self._current_group_id(),
                mode=str(mode or "browse").strip().lower() or "browse",
            )
        )

    def _emit_group_name_update(self, value: str) -> None:
        request = self._build_group_profile_request(name=value)
        if request is not None:
            self.groupProfileUpdateRequested.emit(request)

    def _emit_note_update(self, value: str) -> None:
        request = self._build_group_self_profile_request(note=value)
        if request is not None:
            self.groupSelfProfileUpdateRequested.emit(request)

    def _emit_nickname_update(self, value: str) -> None:
        request = self._build_group_self_profile_request(my_group_nickname=value)
        if request is not None:
            self.groupSelfProfileUpdateRequested.emit(request)

    def _current_member_role(self) -> str:
        current_user_id = ""
        if self._session is not None:
            current_user_id = str(getattr(self._session, "extra", {}).get("current_user_id", "") or "").strip()
        if not current_user_id:
            return ""
        for member in self._members:
            if str(member.get("id", "") or "").strip() == current_user_id:
                return str(member.get("role", "") or "").strip().lower()
        return ""

    def _set_group_profile_editability(self, editable: bool) -> None:
        self.group_name_field.set_editable(editable)
        self.announcement_field.set_editable(editable)

    def _clear_layout(self, layout: QVBoxLayout | QGridLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_member_grid(self) -> None:
        self._clear_layout(self.members_grid_layout)
        members = list(self._members)
        show_view_more = len(members) > self.MAX_VISIBLE_MEMBER_TILES
        visible_member_limit = self.MAX_VISIBLE_MEMBER_TILES - 1 if show_view_more else self.MAX_VISIBLE_MEMBER_TILES
        visible_members = members[: max(0, visible_member_limit)]
        current_role = self._current_member_role()
        can_manage_members = current_role == "owner"

        tiles: list[ChatInfoParticipantTile] = []
        for member in visible_members:
            tile = ChatInfoParticipantTile(parent=self)
            tile.set_participant(
                title=self.member_display_name(member),
                avatar=str(member.get("avatar", "") or ""),
                user_id=str(member.get("id", "") or ""),
                username=str(member.get("username", "") or ""),
                gender=str(member.get("gender", "") or ""),
            )
            tiles.append(tile)

        if can_manage_members:
            add_tile = ChatInfoParticipantTile(
                is_add_tile=True,
                action_icon=AppIcon.ADD,
                action_label=tr("chat.info.add", "Add"),
                dashed=True,
                clickable=True,
                parent=self,
            )
            add_tile.clicked.connect(lambda: self._emit_member_management_request("add"))
            tiles.append(add_tile)

            remove_tile = ChatInfoParticipantTile(
                is_add_tile=True,
                action_icon=AppIcon.CLOSE,
                action_label=tr("chat.info.group.remove", "Remove"),
                dashed=True,
                clickable=True,
                parent=self,
            )
            remove_tile.clicked.connect(lambda: self._emit_member_management_request("remove"))
            tiles.append(remove_tile)

        if show_view_more:
            view_more_tile = ChatInfoParticipantTile(
                is_add_tile=True,
                action_icon=CollectionIcon("chevron_right"),
                action_label=tr("chat.info.group.view_more_short", "More"),
                dashed=False,
                clickable=True,
                parent=self,
            )
            view_more_tile.clicked.connect(lambda: self._emit_member_management_request("browse"))
            tiles.append(view_more_tile)

        tiles = tiles[: self.MAX_VISIBLE_TILES]
        for index, tile in enumerate(tiles):
            row = index // 4
            column = index % 4
            self.members_grid_layout.addWidget(tile, row, column, Qt.AlignmentFlag.AlignTop)
        self.view_more_button.setVisible(show_view_more)

    def _render_search_results(self, keyword: str) -> None:
        self._clear_layout(self.search_results_layout)
        normalized_keyword = str(keyword or "").strip().lower()
        if not normalized_keyword:
            self.content_stack.setCurrentWidget(self.default_page)
            self.search_results_widget.setVisible(False)
            self.search_empty_label.setVisible(False)
            self.view_more_button.setVisible(len(self._members) > self.MAX_VISIBLE_MEMBER_TILES)
            return

        self.content_stack.setCurrentWidget(self.search_page)
        matches: list[dict[str, Any]] = []
        for member in self._members:
            tokens = [
                str(member.get("display_name", "") or "").lower(),
                str(member.get("username", "") or "").lower(),
                str(member.get("remark", "") or "").lower(),
                str(member.get("group_nickname", "") or "").lower(),
                str(member.get("nickname", "") or "").lower(),
                str(member.get("id", "") or "").lower(),
            ]
            if any(normalized_keyword in token for token in tokens if token):
                matches.append(member)
            if len(matches) >= self.SEARCH_RESULT_LIMIT:
                break

        if not matches:
            self.search_results_widget.setVisible(False)
            self.search_empty_label.setVisible(True)
            return

        for member in matches:
            row = ChatInfoGroupMemberRow(member, self.search_results_widget)
            self.search_results_layout.addWidget(row)
        self.search_results_layout.addStretch(1)
        self.search_empty_label.setVisible(False)
        self.search_results_widget.setVisible(True)

    def _resolve_my_group_nickname(self, session: Session, members: list[dict[str, Any]]) -> str:
        extra = dict(session.extra or {})
        explicit = (
            str(extra.get("my_group_nickname", "") or "").strip()
            or str(extra.get("self_nickname", "") or "").strip()
            or str(extra.get("group_nickname", "") or "").strip()
        )
        if explicit:
            return explicit

        current_user_id = str(extra.get("current_user_id", "") or "").strip()
        if not current_user_id:
            return tr("chat.info.group.my_nickname.empty", "Not Set")
        for member in members:
            if str(member.get("id", "") or "").strip() != current_user_id:
                continue
            value = str(member.get("group_nickname", "") or "").strip()
            if value:
                return value
        return tr("chat.info.group.my_nickname.empty", "Not Set")

    def _on_member_search_text_changed(self, text: str) -> None:
        self._render_search_results(str(text or ""))

    def _open_announcement_editor(self) -> None:
        if self._session is None or not self.announcement_field.is_editable():
            return
        extra = dict(self._session.extra or {})
        announcement = str(extra.get("group_announcement", "") or extra.get("announcement", "") or "").strip()
        dialog = ChatInfoAnnouncementDialog(announcement, self.window())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._apply_announcement_value(dialog.value())

    def _apply_announcement_value(self, value: str) -> None:
        normalized_value = str(value or "").strip()
        if normalized_value == self.announcement_field.current_value():
            return
        self.announcement_field.title_label.setText(tr("chat.info.group.announcement", "Announcement"))
        self.announcement_field.set_preview_text(normalized_value)
        request = self._build_group_profile_request(announcement=normalized_value)
        if request is not None:
            self.groupProfileUpdateRequested.emit(request)

    def set_session(self, session: Session | None) -> None:
        self._session = session
        blocker = QSignalBlocker(self.member_search_box)
        try:
            self.member_search_box.clear()
        finally:
            del blocker
        if session is None:
            self.setEnabled(False)
            self._members = []
            self._render_member_grid()
            self._render_search_results("")
            self._set_group_profile_editability(False)
            self.group_name_field.set_value("")
            self.announcement_field.title_label.setText(tr("chat.info.group.announcement", "Announcement"))
            self.announcement_field.set_preview_text("")
            self.note_field.set_value(tr("chat.info.group.note.empty", "群聊的备注仅自己可见"))
            self.nickname_field.set_value(tr("chat.info.group.my_nickname.empty", "Not Set"))
            self.mute_row.set_checked(False)
            self.pin_row.set_checked(False)
            self.show_nickname_row.set_checked(True)
            self.view_more_button.setVisible(False)
            self.leave_button.setEnabled(False)
            self.leave_button.setToolTip("")
            return

        self.setEnabled(True)
        extra = dict(session.extra or {})
        self._members = [
            self._normalize_member_payload(item)
            for item in list(extra.get("members") or [])
            if isinstance(item, dict)
        ]
        current_role = self._current_member_role()
        can_edit_shared = current_role in {"owner", "admin"}
        is_owner = current_role == "owner"
        self._set_group_profile_editability(can_edit_shared)
        self.group_name_field.setToolTip(
            "" if can_edit_shared else tr("chat.info.group.profile.read_only", "Only the owner or admin can edit group info.")
        )
        self.announcement_field.setToolTip(
            "" if can_edit_shared else tr("chat.info.group.profile.read_only", "Only the owner or admin can edit group info.")
        )

        self.group_name_field.set_value(session.authoritative_group_name())
        announcement_text = str(extra.get("group_announcement", "") or extra.get("announcement", "") or "").strip()
        self.announcement_field.title_label.setText(tr("chat.info.group.announcement", "Announcement"))
        self.announcement_field.set_preview_text(announcement_text)
        self.note_field.set_value(
            str(extra.get("group_note", "") or extra.get("note", "") or tr("chat.info.group.note.empty", "群聊的备注仅自己可见"))
        )
        self.nickname_field.set_value(self._resolve_my_group_nickname(session, self._members))

        self.mute_row.set_checked(bool(extra.get("is_muted", False)))
        self.pin_row.set_checked(bool(getattr(session, "is_pinned", False) or extra.get("is_pinned", False)))
        self.show_nickname_row.set_checked(bool(extra.get("show_member_nickname", True)))
        self.leave_button.setEnabled(not is_owner)
        self.leave_button.setToolTip(
            "" if not is_owner else tr("chat.info.group.leave.owner_blocked", "Transfer ownership before leaving this group.")
        )

        self._render_member_grid()
        self._render_search_results("")


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
    leaveRequested = Signal()
    muteToggled = Signal(bool)
    pinToggled = Signal(bool)
    showNicknameToggled = Signal(bool)
    memberManagementRequested = Signal(object)
    groupProfileUpdateRequested = Signal(object)
    groupSelfProfileUpdateRequested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session: Optional[Session] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget(self)
        self.private_content = ChatInfoPrivateContent(self)
        self.group_content = ChatInfoGroupContent(self)
        self.placeholder_content = ChatInfoPlaceholderContent(self)
        self.stack.addWidget(self.private_content)
        self.stack.addWidget(self.group_content)
        self.stack.addWidget(self.placeholder_content)
        layout.addWidget(self.stack)

        self.private_content.searchRequested.connect(self.searchRequested.emit)
        self.private_content.addRequested.connect(self.addRequested.emit)
        self.private_content.clearRequested.connect(self.clearRequested.emit)
        self.private_content.muteToggled.connect(self.muteToggled.emit)
        self.private_content.pinToggled.connect(self.pinToggled.emit)
        self.group_content.searchRequested.connect(self.searchRequested.emit)
        self.group_content.clearRequested.connect(self.clearRequested.emit)
        self.group_content.leaveRequested.connect(self.leaveRequested.emit)
        self.group_content.muteToggled.connect(self.muteToggled.emit)
        self.group_content.pinToggled.connect(self.pinToggled.emit)
        self.group_content.showNicknameToggled.connect(self.showNicknameToggled.emit)
        self.group_content.memberManagementRequested.connect(self.memberManagementRequested.emit)
        self.group_content.groupProfileUpdateRequested.connect(self.groupProfileUpdateRequested.emit)
        self.group_content.groupSelfProfileUpdateRequested.connect(self.groupSelfProfileUpdateRequested.emit)

    def set_session(self, session: Session | None) -> None:
        """Refresh content for the current session type."""
        self._session = session
        if session is None:
            self.private_content.set_session(None)
            self.group_content.set_session(None)
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
            self.group_content.set_session(session)
            self.stack.setCurrentWidget(self.group_content)
            return

        self.placeholder_content.set_text(
            tr("chat.info.ai.title", "AI Session Info"),
            tr("chat.info.ai.content", "The AI session info panel will be implemented later."),
        )
        self.stack.setCurrentWidget(self.placeholder_content)


class AcrylicDrawerSurface(QFrame):
    """Reusable Fluent-style acrylic surface for drawer and popup panels."""

    def __init__(self, parent=None, *, extend_right_edge: bool = False, radius: int = 7) -> None:
        super().__init__(parent)
        self.setObjectName("chatInfoDrawer")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._extend_right_edge = bool(extend_right_edge)
        self._radius = max(0, int(radius))
        self._acrylic_brush = AcrylicBrush(self, 30)
        self._border_frame = QFrame(self)
        self._border_frame.setObjectName("chatInfoDrawerBorder")
        self._border_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._border_frame.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._border_frame.show()
        self._last_border_style = ""
        self._update_border_style()

    def set_border_object_name(self, object_name: str) -> None:
        """Update the overlay frame used for the crisp Fluent border."""
        self._border_frame.setObjectName(str(object_name or ""))
        self._update_border_style(force=True)

    def _update_border_style(self, *, force: bool = False) -> None:
        border_rgb = "57, 57, 57" if isDarkTheme() else "229, 229, 229"
        if self._extend_right_edge:
            style = (
                "QFrame {"
                " background: transparent;"
                f" border-top: 1px solid rgb({border_rgb});"
                f" border-left: 1px solid rgb({border_rgb});"
                f" border-bottom: 1px solid rgb({border_rgb});"
                " border-right: none;"
                f" border-top-left-radius: {self._radius}px;"
                f" border-bottom-left-radius: {self._radius}px;"
                " border-top-right-radius: 0px;"
                " border-bottom-right-radius: 0px;"
                "}"
            )
        else:
            style = (
                "QFrame {"
                " background: transparent;"
                f" border: 1px solid rgb({border_rgb});"
                f" border-radius: {self._radius}px;"
                "}"
            )

        if force or style != self._last_border_style:
            self._border_frame.setStyleSheet(style)
            self._last_border_style = style

    def _update_acrylic_color(self) -> None:
        if isDarkTheme():
            self._acrylic_brush.tintColor = QColor(32, 32, 32, 200)
            self._acrylic_brush.luminosityColor = QColor(0, 0, 0, 0)
        else:
            self._acrylic_brush.tintColor = QColor(255, 255, 255, 180)
            self._acrylic_brush.luminosityColor = QColor(255, 255, 255, 0)

    def _fallback_fill_color(self) -> QColor:
        return QColor(40, 40, 40, 232) if isDarkTheme() else QColor(248, 248, 248, 236)

    def _shape_path(self) -> QPainterPath:
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        path.addRoundedRect(rect, self._radius, self._radius)
        if self._extend_right_edge:
            extension = max(8.0, float(self._radius) + 1.0)
            path.addRect(QRectF(rect.right() - extension + 1.0, rect.top(), extension, rect.height()))
        return path.simplified()

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
        shape_path = self._shape_path()
        self._update_border_style()

        if self._acrylic_brush.isAvailable():
            self._acrylic_brush.setClipPath(shape_path)
            self._update_acrylic_color()
            self._acrylic_brush.paint()
        else:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._fallback_fill_color())
            painter.drawPath(shape_path)

        super().paintEvent(event)
        self._border_frame.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._border_frame.setGeometry(self.rect())
        self._border_frame.raise_()


class ChatInfoDrawerOverlay(QWidget):
    """Full-content overlay that hosts a floating acrylic drawer."""

    searchRequested = Signal()
    addRequested = Signal()
    clearRequested = Signal()
    leaveRequested = Signal()
    muteToggled = Signal(bool)
    pinToggled = Signal(bool)
    showNicknameToggled = Signal(bool)
    memberManagementRequested = Signal(object)
    groupProfileUpdateRequested = Signal(object)
    groupSelfProfileUpdateRequested = Signal(object)
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

        self.drawer = AcrylicDrawerSurface(self, extend_right_edge=True)
        self.drawer.setObjectName("chatInfoDrawer")

        drawer_layout = QVBoxLayout(self.drawer)
        drawer_layout.setContentsMargins(0, 0, 0, 0)
        drawer_layout.setSpacing(0)

        self.scroll_area = SingleDirectionScrollArea(self.drawer, orient=Qt.Orientation.Vertical)
        self.scroll_area.setObjectName("chatInfoDrawerScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setViewportMargins(0, 0, 0, 0)
        self.scroll_area.viewport().setObjectName("chatInfoDrawerScrollViewport")
        self.scroll_area.verticalScrollBar().hide()
        self.drawer.installEventFilter(self)
        self.scroll_area.viewport().installEventFilter(self)
        self.scroll_area.verticalScrollBar().installEventFilter(self)

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
        self.content_widget.leaveRequested.connect(self.leaveRequested.emit)
        self.content_widget.muteToggled.connect(self.muteToggled.emit)
        self.content_widget.pinToggled.connect(self.pinToggled.emit)
        self.content_widget.showNicknameToggled.connect(self.showNicknameToggled.emit)
        self.content_widget.memberManagementRequested.connect(self.memberManagementRequested.emit)
        self.content_widget.groupProfileUpdateRequested.connect(self.groupProfileUpdateRequested.emit)
        self.content_widget.groupSelfProfileUpdateRequested.connect(self.groupSelfProfileUpdateRequested.emit)

    def eventFilter(self, watched, event) -> bool:
        if watched in {self.drawer, self.scroll_area.viewport(), self.scroll_area.verticalScrollBar()}:
            if event.type() in {QEvent.Type.Enter, QEvent.Type.MouseMove}:
                self._set_scrollbar_visible(True)
            elif event.type() == QEvent.Type.Leave:
                QTimer.singleShot(0, self._sync_scrollbar_hover_state)
        return super().eventFilter(watched, event)

    def _set_scrollbar_visible(self, visible: bool) -> None:
        scrollbar = self.scroll_area.verticalScrollBar()
        if visible and scrollbar.maximum() > 0:
            self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scrollbar.show()
            return
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scrollbar.hide()

    def _sync_scrollbar_hover_state(self) -> None:
        if not self.isVisible() or not self.drawer.isVisible():
            self._set_scrollbar_visible(False)
            return
        cursor_pos = QCursor.pos()
        drawer_rect = QRect(self.drawer.mapToGlobal(QPoint(0, 0)), self.drawer.size())
        self._set_scrollbar_visible(drawer_rect.contains(cursor_pos))

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
        self._set_scrollbar_visible(False)

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
            self._set_scrollbar_visible(False)
            self.hide()
            return
        self._animation.setStartValue(self.drawer.geometry())
        self._animation.setEndValue(self._closed_rect())
        self._animation.start()

    def _on_animation_finished(self) -> None:
        if not self._open:
            self._set_scrollbar_visible(False)
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


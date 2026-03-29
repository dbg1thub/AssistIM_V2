"""Shared contact UI primitives used by contact and group-creation views."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget, ScrollArea, SingleDirectionScrollArea, ToolButton, isDarkTheme

from client.core.app_icons import AppIcon
from client.core.avatar_rendering import get_avatar_image_store
from client.core.i18n import tr
from client.core.avatar_utils import avatar_seed, profile_avatar_seed
from client.ui.widgets.fluent_divider import FluentDivider

if TYPE_CHECKING:
    from client.ui.controllers.contact_controller import ContactRecord

CONTACT_SIDEBAR_AVATAR_SIZE = 44
CONTACT_SIDEBAR_ITEM_HEIGHT = 80
CONTACT_SIDEBAR_ITEM_PADDING = 12
CONTACT_SIDEBAR_CONTENT_GAP = 12
CONTACT_SIDEBAR_TEXT_TOP_OFFSET = 2
CONTACT_SIDEBAR_TEXT_SPACING = 4
CONTACT_SIDEBAR_TITLE_FONT_SIZE = 16
CONTACT_SECTION_INSET = 32
CONTACT_SECTION_LABEL_GAP = 8


def apply_themed_dialog_surface(dialog: QDialog, object_name: str, *, radius: int = 14) -> None:
    """Apply one stable theme-aware palette to a plain dialog surface."""
    del radius
    dialog.setObjectName(object_name)
    dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    dialog.setAutoFillBackground(True)
    background = QColor(39, 43, 48) if isDarkTheme() else QColor(255, 255, 255)
    palette = dialog.palette()
    palette.setColor(QPalette.ColorRole.Window, background)
    palette.setColor(QPalette.ColorRole.Base, background)
    dialog.setPalette(palette)


def prepare_transparent_scroll_area(area: ScrollArea | SingleDirectionScrollArea) -> None:
    """Keep qfluent scroll areas transparent so parent surfaces show through."""
    area.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    area.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    area.setAutoFillBackground(False)
    area.setStyleSheet("QAbstractScrollArea{background: transparent; border: none;} QScrollArea{background: transparent; border: none;}")
    viewport = area.viewport()
    if viewport is not None:
        viewport.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        viewport.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        viewport.setAutoFillBackground(False)
        viewport.setStyleSheet("background: transparent; border: none;")
    if hasattr(area, "enableTransparentBackground"):
        area.enableTransparentBackground()


class ContactAvatar(QWidget):
    def __init__(self, size: int = 48, parent=None):
        super().__init__(parent)
        self._size = size
        self._radius = max(8, size // 6)
        self._pixmap: QPixmap | None = None
        self._fallback = "?"
        self._avatar_source = ""
        self._avatar_gender = ""
        self._avatar_seed = ""
        self._avatar_store = get_avatar_image_store()
        self._avatar_store.avatar_ready.connect(self._on_avatar_ready)
        self.setFixedSize(size, size)

    def set_avatar(self, avatar_path: str = "", fallback: str = "?", *, gender: str = "", seed: str = "") -> None:
        self._fallback = (fallback or "?").strip()[:2].upper() or "?"
        self._avatar_gender = str(gender or "")
        self._avatar_seed = str(seed or avatar_seed(fallback, avatar_path, gender))
        self._avatar_source, resolved = self._avatar_store.resolve_display_path(
            avatar_path,
            gender=self._avatar_gender,
            seed=self._avatar_seed,
        )
        self._apply_avatar_path(resolved)

    def _apply_avatar_path(self, avatar_path: str) -> None:
        self._pixmap = None
        if avatar_path:
            pixmap = QPixmap(avatar_path)
            if not pixmap.isNull():
                self._pixmap = pixmap
        self.update()

    def _on_avatar_ready(self, source: str) -> None:
        if source != self._avatar_source:
            return
        resolved = self._avatar_store.display_path_for_source(
            source,
            gender=self._avatar_gender,
            seed=self._avatar_seed,
        )
        self._apply_avatar_path(resolved)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        clip = QPainterPath()
        clip.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(clip)

        if self._pixmap is not None:
            scaled = self._pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(rect, scaled)
            return

        painter.fillPath(clip, QColor("#626B76") if isDarkTheme() else QColor("#D7DEE8"))
        painter.setClipping(False)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(12, self._size // 3))
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF") if isDarkTheme() else QColor("#27486B"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._fallback)


class ElidedBodyLabel(QLabel):
    """Body label that elides long text to the available width."""

    def __init__(self, text: str = "", parent=None):
        super().__init__("", parent)
        self._full_text = ""
        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        font = QFont(self.font())
        font.setPixelSize(15)
        self.setFont(font)
        self.setObjectName("elidedBodyLabel")
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full_text = text or ""
        self._refresh_text()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_text()

    def _refresh_text(self) -> None:
        available = max(0, self.contentsRect().width())
        display = self._full_text
        if available > 0:
            display = self.fontMetrics().elidedText(display, Qt.TextElideMode.ElideRight, available)
        super().setText(display)
        self.setToolTip(self._full_text if display != self._full_text else "")


class ElidedCaptionLabel(QLabel):
    """Caption label that elides long text to the available width."""

    def __init__(self, text: str = "", parent=None):
        super().__init__("", parent)
        self._full_text = ""
        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        font = QFont(self.font())
        font.setPixelSize(12)
        self.setFont(font)
        self.setObjectName("elidedCaptionLabel")
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full_text = text or ""
        self._refresh_text()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_text()

    def _refresh_text(self) -> None:
        available = max(0, self.contentsRect().width())
        display = self._full_text
        if available > 0:
            display = self.fontMetrics().elidedText(display, Qt.TextElideMode.ElideRight, available)
        super().setText(display)
        self.setToolTip(self._full_text if display != self._full_text else "")


class ContactSectionHeader(QWidget):
    """WeChat-like alphabetical divider shown inside contact selection lists."""

    def __init__(self, letter: str, parent=None):
        super().__init__(parent)
        self.letter = (letter or "#").upper()
        self.setObjectName("contactSectionHeader")
        self.setFixedHeight(40)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setSpacing(CONTACT_SECTION_LABEL_GAP)

        self.label = CaptionLabel(self.letter, self)
        self.label.setObjectName("contactSectionIndexLabel")
        self.label.setTextColor(QColor(122, 122, 122), QColor(196, 196, 196))

        label_row = QHBoxLayout()
        label_row.setContentsMargins(CONTACT_SECTION_INSET, 0, 0, 0)
        label_row.setSpacing(0)
        label_row.addWidget(self.label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label_row.addStretch(1)

        divider = FluentDivider(
            self,
            variant=FluentDivider.FULL,
            left_inset=CONTACT_SECTION_INSET,
            right_inset=0,
        )

        layout.addLayout(label_row)
        layout.addWidget(divider, 0, Qt.AlignmentFlag.AlignVCenter)


class GroupMemberItem(CardWidget):
    toggled = Signal(str, bool)

    def __init__(self, contact: ContactRecord, parent=None):
        super().__init__(parent)
        self.setObjectName("GroupMemberItem")
        self.contact = contact
        self._selected = False
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        self.avatar = ContactAvatar(42, self)
        self.avatar.set_avatar(
            contact.avatar,
            contact.display_name,
            gender=contact.gender,
            seed=profile_avatar_seed(user_id=contact.id, username=contact.username, display_name=contact.display_name),
        )

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        text_layout.addWidget(BodyLabel(contact.display_name, self))

        subtitle = CaptionLabel(contact.signature or contact.username or "-", self)
        subtitle.setWordWrap(True)
        text_layout.addWidget(subtitle)

        self.state_label = CaptionLabel(tr("contact.group_member.unselected", "Not Selected"), self)

        layout.addWidget(self.avatar, 0)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.state_label, 0)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.state_label.setText(
            tr("contact.group_member.selected", "Selected") if selected else tr("contact.group_member.unselected", "Not Selected")
        )
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.set_selected(not self._selected)
            self.toggled.emit(self.contact.id, self._selected)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._selected and not self._hovered:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        painter.fillPath(path, QColor(94, 146, 255, 22 if self._selected else 10))


class ContactSelectionIndicator(QWidget):
    """Draw one circular WeChat-like multi-select indicator."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._checked = False
        self._locked = False
        self.setFixedSize(20, 20)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_state(self, checked: bool, *, locked: bool = False) -> None:
        self._checked = bool(checked)
        self._locked = bool(locked)
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)

        if self._checked:
            fill = QColor("#07C160")
            if self._locked:
                fill = QColor(fill)
                fill.setAlpha(200)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawEllipse(rect)

            pen = painter.pen()
            pen.setColor(QColor("#FFFFFF"))
            pen.setWidth(2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(6, 10, 9, 13)
            painter.drawLine(9, 13, 14, 7)
            return

        border = QColor(0, 0, 0, 56) if not isDarkTheme() else QColor(255, 255, 255, 86)
        painter.setPen(border)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect)


class SelectableContactListItem(QWidget):
    """Friend-list row with one leading multi-select indicator."""

    toggled = Signal(str, bool)

    def __init__(self, contact: ContactRecord, *, locked: bool = False, parent=None):
        super().__init__(parent)
        self.contact = contact
        self._locked = bool(locked)
        self._selected = bool(locked)
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor if not locked else Qt.CursorShape.ArrowCursor)
        self.setFixedHeight(CONTACT_SIDEBAR_ITEM_HEIGHT)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            CONTACT_SIDEBAR_ITEM_PADDING,
            CONTACT_SIDEBAR_ITEM_PADDING,
            CONTACT_SIDEBAR_ITEM_PADDING,
            CONTACT_SIDEBAR_ITEM_PADDING,
        )
        layout.setSpacing(CONTACT_SIDEBAR_CONTENT_GAP)

        self.indicator = ContactSelectionIndicator(self)
        self.indicator.set_state(self._selected, locked=self._locked)

        self.avatar = ContactAvatar(CONTACT_SIDEBAR_AVATAR_SIZE, self)
        self.avatar.set_avatar(
            contact.avatar,
            contact.display_name,
            gender=contact.gender,
            seed=profile_avatar_seed(
                user_id=contact.id,
                username=contact.username,
                display_name=contact.display_name,
            ),
        )

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, CONTACT_SIDEBAR_TEXT_TOP_OFFSET, 0, 0)
        text_layout.setSpacing(CONTACT_SIDEBAR_TEXT_SPACING)

        self.title_label = ElidedBodyLabel(contact.display_name, self)
        title_font = QFont(self.title_label.font())
        title_font.setPixelSize(CONTACT_SIDEBAR_TITLE_FONT_SIZE)
        title_font.setBold(False)
        self.title_label.setFont(title_font)

        self.subtitle_label = ElidedCaptionLabel(
            contact.assistim_id or contact.username or contact.signature,
            self,
        )
        self.subtitle_label.setVisible(bool(self.subtitle_label.text()))

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)

        layout.addWidget(self.indicator, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(text_layout, 1)

    @property
    def is_locked(self) -> bool:
        return self._locked

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected or self._locked)
        self.indicator.set_state(self._selected, locked=self._locked)
        self.update()

    def enterEvent(self, event) -> None:
        if not self._locked:
            self._hovered = True
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._locked:
            self.set_selected(not self._selected)
            self.toggled.emit(self.contact.id, self._selected)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        dark = isDarkTheme()
        if self._hovered:
            painter.fillRect(self.rect(), QColor(255, 255, 255, 24) if dark else QColor(0, 0, 0, 10))
        super().paintEvent(event)


class SelectedContactSummaryItem(QWidget):
    """Compact row shown in the group-picker side panel for selected contacts."""

    remove_requested = Signal(str)

    def __init__(self, contact: ContactRecord, *, removable: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.contact = contact
        self._removable = bool(removable)
        self.setObjectName("startGroupChatSelectedItem")
        self.setFixedHeight(64)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(12)

        self.avatar = ContactAvatar(38, self)
        self.avatar.set_avatar(
            contact.avatar,
            contact.display_name,
            gender=contact.gender,
            seed=profile_avatar_seed(
                user_id=contact.id,
                username=contact.username,
                display_name=contact.display_name,
            ),
        )

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        self.title_label = ElidedBodyLabel(contact.display_name, self)
        title_font = QFont(self.title_label.font())
        title_font.setPixelSize(14)
        title_font.setBold(False)
        self.title_label.setFont(title_font)

        self.subtitle_label = ElidedCaptionLabel(contact.assistim_id or contact.username or "-", self)
        self.subtitle_label.setVisible(bool(self.subtitle_label.text()))

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)

        self.remove_button = ToolButton(AppIcon.CLOSE, self)
        self.remove_button.setObjectName("startGroupChatSelectedRemoveButton")
        self.remove_button.setFixedSize(28, 28)
        self.remove_button.setVisible(self._removable)
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self.contact.id))

        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.remove_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

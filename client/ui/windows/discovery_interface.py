"""Moments/discovery interface with animated comment expansion."""

from __future__ import annotations

import asyncio
import html
import mimetypes
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPalette, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    IconWidget,
    InfoBar,
    isDarkTheme,
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SubtitleLabel,
    TextEdit,
    TitleLabel,
    TransparentToolButton,
)

from client.core.app_icons import AppIcon
from client.core import logging
from client.core.avatar_rendering import get_avatar_image_store
from client.core.avatar_utils import avatar_seed, profile_avatar_seed
from client.core.config_backend import get_config
from client.core.exceptions import APIError, NetworkError
from client.core.i18n import format_relative_time, tr
from client.core.logging import setup_logging
from client.events.event_bus import get_event_bus
from client.events.moment_events import MomentEvent
from client.services.file_service import get_file_service
from client.ui.controllers.discovery_controller import (
    MomentCommentRecord,
    MomentMediaRecord,
    MomentPrivacySettings,
    MomentRecord,
    get_discovery_controller,
)
from client.ui.controllers.contact_controller import ContactRecord, get_contact_controller
from client.ui.styles import StyleSheet
from client.ui.widgets.image_viewer import ImageViewer


setup_logging()
logger = logging.get_logger(__name__)


def _apply_safe_button_font(*buttons: TransparentToolButton) -> None:
    """Ensure tooltip rendering gets a valid point-size font."""
    font = QFont()
    if font.pointSize() <= 0:
        if font.pixelSize() > 0:
            font.setPointSize(max(9, round(font.pixelSize() * 0.75)))
        else:
            font.setPointSize(10)

    for button in buttons:
        button.setFont(font)


def _prepare_transparent_scroll_area(area: ScrollArea) -> None:
    """Keep discovery scroll containers transparent in both themes."""
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


def _apply_themed_dialog_surface(dialog: QDialog, object_name: str, *, radius: int = 14) -> None:
    """Apply one stable theme-aware palette to plain discovery dialogs."""
    dialog.setObjectName(object_name)
    dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    dialog.setAutoFillBackground(True)
    background = QColor(39, 43, 48) if isDarkTheme() else QColor(255, 255, 255)
    palette = dialog.palette()
    palette.setColor(QPalette.ColorRole.Window, background)
    palette.setColor(QPalette.ColorRole.Base, background)
    dialog.setPalette(palette)


class DeleteMomentConfirmDialog(MessageBoxBase):
    """Ask before deleting one moment."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        title = SubtitleLabel(tr("discovery.delete_moment.title", "Delete Moment"), self.widget)
        content = BodyLabel(
            tr(
                "discovery.delete_moment.confirm",
                "Delete this moment? Comments and likes on it will also be removed.",
            ),
            self.widget,
        )
        content.setWordWrap(True)
        self.viewLayout.addWidget(title)
        self.viewLayout.addWidget(content)
        self.viewLayout.addStretch(1)
        self.yesButton.setText(tr("common.delete", "Delete"))
        self.cancelButton.setText(tr("common.cancel", "Cancel"))
        self.widget.setMinimumWidth(380)


class DeleteCommentConfirmDialog(MessageBoxBase):
    """Ask before deleting one moment comment."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        title = SubtitleLabel(tr("discovery.delete_comment.title", "Delete Comment"), self.widget)
        content = BodyLabel(
            tr("discovery.delete_comment.confirm", "Delete this comment?"),
            self.widget,
        )
        content.setWordWrap(True)
        self.viewLayout.addWidget(title)
        self.viewLayout.addWidget(content)
        self.viewLayout.addStretch(1)
        self.yesButton.setText(tr("common.delete", "Delete"))
        self.cancelButton.setText(tr("common.cancel", "Cancel"))
        self.widget.setMinimumWidth(360)


def _clear_layout(layout: QVBoxLayout | QHBoxLayout | QGridLayout) -> None:
    """Delete all child widgets from a layout."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)


def _build_local_media_record(file_path: str, *, media_type: str | None = None) -> MomentMediaRecord:
    """Build one preview-only media record from a local file path."""
    normalized_path = str(file_path or "").strip()
    guessed_mime, _ = mimetypes.guess_type(normalized_path)
    inferred_type = str(media_type or "").strip().lower()
    if inferred_type not in {"image", "video"}:
        inferred_type = "video" if str(guessed_mime or "").lower().startswith("video/") else "image"
    return MomentMediaRecord(
        media_type=inferred_type,
        url=normalized_path,
        original_name=Path(normalized_path).name,
        mime_type=str(guessed_mime or ""),
        size_bytes=0,
        local_path=normalized_path,
    )


class DiscoveryAvatar(QWidget):
    """Circular avatar used by the discovery feed."""

    def __init__(self, size: int = 48, parent=None):
        super().__init__(parent)
        self._size = size
        self._pixmap: Optional[QPixmap] = None
        self._fallback = "?"
        self._avatar_source = ""
        self._avatar_gender = ""
        self._avatar_seed = ""
        self._avatar_store = get_avatar_image_store()
        self._avatar_store.avatar_ready.connect(self._on_avatar_ready)
        self.setFixedSize(size, size)

    def set_avatar(self, avatar_path: str = "", fallback: str = "?", *, gender: str = "", seed: str = "") -> None:
        """Update avatar image or fallback initials."""
        self._fallback = (fallback or "?").strip()[:2].upper() or "?"
        self._avatar_gender = str(gender or "")
        self._avatar_seed = str(seed or avatar_seed(fallback))
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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        clip = QPainterPath()
        clip.addEllipse(rect)
        painter.setClipPath(clip)

        if self._pixmap:
            scaled = self._pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(rect, scaled)
            return

        if isDarkTheme():
            painter.fillPath(clip, QColor(98, 107, 118))
            text_color = QColor("#F8FAFC")
        else:
            painter.fillPath(clip, QColor("#D8E8F8"))
            text_color = QColor("#27486B")
        painter.setClipping(False)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(12, self._size // 3))
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._fallback)


class ClickableMediaLabel(QLabel):
    """Simple clickable moment media tile."""

    clicked = Signal(object)

    def __init__(self, media: MomentMediaRecord, parent=None):
        super().__init__(parent)
        self.media = media
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.media)
        super().mousePressEvent(event)


class MomentMediaGrid(QWidget):
    """Responsive grid for moment image and video attachments."""

    image_requested = Signal(str)
    video_requested = Signal(str)

    def __init__(self, media: list[MomentMediaRecord], parent=None, *, compact: bool = False):
        super().__init__(parent)
        self._compact = compact
        self._media: list[MomentMediaRecord] = []
        self._network_manager = QNetworkAccessManager(self)
        self._network_manager.finished.connect(self._on_image_loaded)
        self._pending_replies: dict[QNetworkReply, QLabel] = {}
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(8)
        self._layout.setVerticalSpacing(8)
        self.set_media(media)

    def set_media(self, media: list[MomentMediaRecord]) -> None:
        """Replace the preview media set and rebuild the grid."""
        for reply in list(self._pending_replies):
            try:
                reply.abort()
            except RuntimeError:
                pass
            reply.deleteLater()
        self._pending_replies.clear()
        _clear_layout(self._layout)
        self._media = list(media[:9])
        self._build()

    def _build(self) -> None:
        if not self._media:
            self.hide()
            return

        count = len(self._media)
        if count == 1:
            sizes = [(0, 0, 1, 1, 200, 140) if self._compact else (0, 0, 1, 1, 360, 220)]
        elif count in (2, 4):
            if self._compact:
                sizes = [(index // 2, index % 2, 1, 1, 112, 84) for index in range(count)]
            else:
                sizes = [(index // 2, index % 2, 1, 1, 172, 132) for index in range(count)]
        else:
            if self._compact:
                sizes = [(index // 3, index % 3, 1, 1, 84, 84) for index in range(count)]
            else:
                sizes = [(index // 3, index % 3, 1, 1, 112, 112) for index in range(count)]

        for index, media in enumerate(self._media):
            row, col, row_span, col_span, width, height = sizes[index]
            label = ClickableMediaLabel(media, self)
            label.setObjectName("momentMediaTile")
            label.setFixedSize(width, height)
            self._load_media(label, media, width, height)
            label.clicked.connect(self._emit_media_request)
            self._layout.addWidget(label, row, col, row_span, col_span)

    def _load_media(self, label: QLabel, media: MomentMediaRecord, width: int, height: int) -> None:
        if media.is_video:
            label.setText(tr("discovery.video.placeholder", "Video"))
            label.setProperty("momentMediaKind", "video")
            return

        source = self._resolve_media_source(media)
        if not source:
            label.setText(tr("discovery.image.placeholder", "Image"))
            return

        pixmap = QPixmap(source)
        if not pixmap.isNull():
            self._apply_scaled_pixmap(label, pixmap, width, height)
            return

        if source.startswith(("http://", "https://")):
            reply = self._network_manager.get(QNetworkRequest(QUrl(source)))
            self._pending_replies[reply] = label
            label.setText(tr("discovery.image.loading", "Loading..."))
            return

        label.setText(tr("discovery.image.placeholder", "Image"))

    def _on_image_loaded(self, reply: QNetworkReply) -> None:
        label = self._pending_replies.pop(reply, None)
        try:
            if label is None:
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                label.setText(tr("discovery.image.placeholder", "Image"))
                return
            pixmap = QPixmap()
            if not pixmap.loadFromData(bytes(reply.readAll())):
                label.setText(tr("discovery.image.placeholder", "Image"))
                return
            self._apply_scaled_pixmap(label, pixmap, label.width(), label.height())
        finally:
            reply.deleteLater()

    @staticmethod
    def _apply_scaled_pixmap(label: QLabel, pixmap: QPixmap, width: int, height: int) -> None:
        scaled = pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(scaled)
        label.setText("")

    def _emit_media_request(self, media: object) -> None:
        if not isinstance(media, MomentMediaRecord):
            return
        source = self._resolve_media_source(media)
        if media.is_video:
            self.video_requested.emit(source)
        else:
            self.image_requested.emit(source)

    @staticmethod
    def _resolve_media_source(media: MomentMediaRecord) -> str:
        for value in (media.local_path, media.url):
            source = str(value or "").strip()
            if not source:
                continue
            if Path(source).exists():
                return source
            if source.startswith(("http://", "https://")):
                return source
            if source.startswith("/"):
                origin_base = get_config().server.origin_url.rstrip("/")
                return f"{origin_base}{source}"
            return source
        return ""


class MomentCommentItem(QWidget):
    """A single comment row."""

    delete_requested = Signal(str)

    def __init__(self, comment: MomentCommentRecord, parent=None):
        super().__init__(parent)
        self.comment = comment
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.text_label = QLabel(self)
        self.text_label.setWordWrap(True)
        self.text_label.setTextFormat(Qt.TextFormat.RichText)
        self._apply_comment_text()

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        self.delete_button = PushButton(tr("common.delete", "Delete"), self)
        self.delete_button.setObjectName("momentCommentDeleteButton")
        self.delete_button.setFixedHeight(24)
        self.delete_button.setVisible(comment.can_delete)
        self.delete_button.clicked.connect(self._request_delete)

        time_label = CaptionLabel(format_relative_time(comment.created_at), self)
        time_label.setObjectName("momentCommentTimeLabel")

        header_row.addWidget(self.text_label, 1)
        header_row.addWidget(self.delete_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header_row)
        if comment.image is not None:
            self.image_grid = MomentMediaGrid([comment.image], self)
            self.image_grid.image_requested.connect(self._open_image)
            layout.addWidget(self.image_grid)
        layout.addWidget(time_label)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.StyleChange,
        }:
            self._apply_comment_text()

    def _apply_comment_text(self) -> None:
        """Refresh the rich text colors to match the current theme."""
        if isDarkTheme():
            author_color = "#E2E8F0"
            body_color = "#CBD5E1"
        else:
            author_color = "#24425E"
            body_color = "#4A5565"

        self.text_label.setText(
            f"<span style='color:{author_color};font-weight:600'>{html.escape(self.comment.display_name)}</span>"
            f"<span style='color:{body_color}'>：{html.escape(self.comment.content)}</span>"
        )

    def _open_image(self, image_path: str) -> None:
        viewer = ImageViewer(image_path, self.window())
        viewer.show()
        viewer.raise_()
        viewer.activateWindow()

    def _request_delete(self) -> None:
        self.delete_requested.emit(self.comment.id)


class AnimatedCommentSection(QWidget):
    """Comment block with ExpandSettingCard-like expansion animation."""

    comment_submitted = Signal(str, object)
    detail_requested = Signal(str)
    comment_delete_requested = Signal(str, str)

    COLLAPSED_COUNT = 2

    def __init__(
        self,
        comments: list[MomentCommentRecord],
        parent=None,
        *,
        moment_id: str = "",
        comments_truncated: bool = False,
    ):
        super().__init__(parent)
        self._moment_id = moment_id
        self._comments = list(comments)
        self._comments_truncated = comments_truncated
        self._expanded = False
        self._editor_visible = False
        self._selected_image_path = ""
        self._animation: Optional[QParallelAnimationGroup] = None

        self._setup_ui()
        self.set_comments(self._comments)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.surface = QFrame(self)
        self.surface.setObjectName("MomentCommentSurface")

        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(14, 12, 14, 12)
        surface_layout.setSpacing(10)

        self.preview_widget = QWidget(self.surface)
        self.preview_layout = QVBoxLayout(self.preview_widget)
        self.preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_layout.setSpacing(10)

        self.extra_widget = QWidget(self.surface)
        self.extra_layout = QVBoxLayout(self.extra_widget)
        self.extra_layout.setContentsMargins(0, 0, 0, 0)
        self.extra_layout.setSpacing(10)
        self.extra_widget.setMaximumHeight(0)

        self.extra_opacity = QGraphicsOpacityEffect(self.extra_widget)
        self.extra_opacity.setOpacity(0.0)
        self.extra_widget.setGraphicsEffect(self.extra_opacity)

        self.toggle_button = PushButton(tr("discovery.comments.more", "View more comments"), self.surface)
        self.toggle_button.setFixedHeight(30)
        self.toggle_button.clicked.connect(self._toggle_expanded)

        self.editor_widget = QWidget(self.surface)
        self.editor_widget.setVisible(False)
        editor_layout = QHBoxLayout(self.editor_widget)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(8)

        self.comment_edit = LineEdit(self.editor_widget)
        self.comment_edit.setPlaceholderText(tr("discovery.comments.placeholder", "Write a comment"))
        self.image_button = PushButton(tr("discovery.comments.add_image", "Image"), self.editor_widget)
        self.image_button.setFixedWidth(72)
        self.send_button = PrimaryPushButton(tr("common.send", "Send"), self.editor_widget)
        self.send_button.setFixedWidth(70)

        editor_layout.addWidget(self.comment_edit, 1)
        editor_layout.addWidget(self.image_button, 0)
        editor_layout.addWidget(self.send_button, 0)

        self.image_hint = CaptionLabel("", self.surface)
        self.image_hint.setObjectName("momentCommentImageHint")

        self.image_button.clicked.connect(self._select_comment_image)
        self.send_button.clicked.connect(self._submit_comment)
        self.comment_edit.returnPressed.connect(self._submit_comment)

        surface_layout.addWidget(self.preview_widget)
        surface_layout.addWidget(self.extra_widget)
        surface_layout.addWidget(self.toggle_button, 0, Qt.AlignmentFlag.AlignLeft)
        surface_layout.addWidget(self.editor_widget)
        surface_layout.addWidget(self.image_hint)
        self.image_preview = MomentMediaGrid([], self.surface, compact=True)
        self.image_preview.setVisible(False)
        surface_layout.addWidget(self.image_preview)
        layout.addWidget(self.surface)

        self.setObjectName("MomentCommentSection")

    def set_comments(
        self,
        comments: list[MomentCommentRecord],
        *,
        moment_id: str | None = None,
        comments_truncated: bool | None = None,
    ) -> None:
        """Replace the comment list and rebuild the section."""
        if moment_id is not None:
            self._moment_id = moment_id
        if comments_truncated is not None:
            self._comments_truncated = comments_truncated
        self._comments = list(comments)
        self._rebuild()

    def append_comment(self, comment: MomentCommentRecord) -> None:
        """Append a new comment and keep the current expansion state."""
        self._comments.append(comment)
        self._rebuild()

    def remove_comment(self, comment_id: str) -> None:
        """Remove one comment and keep the current expansion state."""
        normalized_id = str(comment_id or "").strip()
        if not normalized_id:
            return
        self._comments = [comment for comment in self._comments if comment.id != normalized_id]
        self._rebuild()

    def open_editor(self) -> None:
        """Reveal the inline editor and focus it."""
        self._editor_visible = True
        self.editor_widget.setVisible(True)
        self._sync_visibility()
        self.comment_edit.setFocus()

    def _rebuild(self) -> None:
        _clear_layout(self.preview_layout)
        _clear_layout(self.extra_layout)

        preview = self._comments[: self.COLLAPSED_COUNT]
        extra = self._comments[self.COLLAPSED_COUNT :]

        for comment in preview:
            self.preview_layout.addWidget(self._create_comment_item(comment, self.preview_widget))

        for comment in extra:
            self.extra_layout.addWidget(self._create_comment_item(comment, self.extra_widget))

        self.toggle_button.setVisible(bool(extra) or self._comments_truncated)
        self._update_toggle_text()

        target_height = self._expanded_height() if self._expanded and extra else 0
        self.extra_widget.setMaximumHeight(target_height)
        self.extra_opacity.setOpacity(1.0 if self._expanded and extra else 0.0)
        self._sync_visibility()

    def _create_comment_item(self, comment: MomentCommentRecord, parent: QWidget) -> MomentCommentItem:
        item = MomentCommentItem(comment, parent)
        item.delete_requested.connect(lambda comment_id, moment_id=self._moment_id: self.comment_delete_requested.emit(moment_id, comment_id))
        return item

    def _expanded_height(self) -> int:
        """Measure the fully expanded comment height."""
        hint = self.extra_layout.sizeHint().height()
        return max(0, hint)

    def _toggle_expanded(self) -> None:
        if self._comments_truncated and not self._expanded:
            self.detail_requested.emit(self._moment_id)
            return
        self._set_expanded(not self._expanded)

    def _set_expanded(self, expanded: bool) -> None:
        if not self.toggle_button.isVisible():
            return

        self._expanded = expanded
        self._update_toggle_text()

        start_height = self.extra_widget.maximumHeight()
        end_height = self._expanded_height() if expanded else 0
        start_opacity = self.extra_opacity.opacity()
        end_opacity = 1.0 if expanded else 0.0

        if self._animation is not None:
            self._animation.stop()

        height_animation = QPropertyAnimation(self.extra_widget, b"maximumHeight", self)
        height_animation.setDuration(220)
        height_animation.setStartValue(start_height)
        height_animation.setEndValue(end_height)
        height_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        opacity_animation = QPropertyAnimation(self.extra_opacity, b"opacity", self)
        opacity_animation.setDuration(220)
        opacity_animation.setStartValue(start_opacity)
        opacity_animation.setEndValue(end_opacity)
        opacity_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._animation = QParallelAnimationGroup(self)
        self._animation.addAnimation(height_animation)
        self._animation.addAnimation(opacity_animation)
        self._animation.start()

    def _update_toggle_text(self) -> None:
        hidden_count = max(0, len(self._comments) - self.COLLAPSED_COUNT)
        if self._comments_truncated:
            hidden_count = max(hidden_count, 1)
        if not hidden_count:
            self.toggle_button.setText("")
            return
        self.toggle_button.setText(
            tr("discovery.comments.collapse", "Collapse comments")
            if self._expanded
            else tr("discovery.comments.more_count", "View more comments ({count})", count=hidden_count)
        )

    def _sync_visibility(self) -> None:
        self.setVisible(bool(self._comments) or self._editor_visible)

    def _submit_comment(self) -> None:
        text = self.comment_edit.text().strip()
        if not text and not self._selected_image_path:
            return
        self.comment_submitted.emit(text, self._selected_image_path or None)
        self.comment_edit.clear()
        self._selected_image_path = ""
        self._sync_comment_image_preview()

    def _select_comment_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("discovery.comments.select_image", "Select comment image"),
            "",
            tr("discovery.dialog.image_filter", "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All Files (*.*)"),
        )
        if not file_path:
            return
        self._selected_image_path = file_path
        self._sync_comment_image_preview()

    def _sync_comment_image_preview(self) -> None:
        if not self._selected_image_path:
            self.image_hint.setText("")
            self.image_preview.set_media([])
            self.image_preview.hide()
            return
        self.image_hint.setText(Path(self._selected_image_path).name)
        self.image_preview.set_media([_build_local_media_record(self._selected_image_path, media_type="image")])
        self.image_preview.show()


def _contact_display_name(contact: ContactRecord | None) -> str:
    if contact is None:
        return ""
    return str(getattr(contact, "display_name", "") or getattr(contact, "username", "") or getattr(contact, "id", "") or "")


def _contact_id(contact: ContactRecord | None) -> str:
    if contact is None:
        return ""
    return str(getattr(contact, "id", "") or "").strip()


class MomentVisibilitySelectDialog(QDialog):
    """Dialog for selecting one post's visibility scope."""

    submitted = Signal(str, list)

    def __init__(
        self,
        contacts: list[ContactRecord],
        *,
        current_scope: str = "public",
        current_user_ids: list[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._contacts = [contact for contact in contacts if _contact_id(contact)]
        self._current_user_ids = set(str(item or "").strip() for item in (current_user_ids or []) if str(item or "").strip())
        self._target_checkboxes: dict[str, CheckBox] = {}
        self.setWindowTitle(tr("discovery.visibility.window_title", "Who can see this"))
        self.setModal(True)
        self.resize(480, 560)
        _apply_themed_dialog_surface(self, "MomentVisibilitySelectDialog")
        self._setup_ui(current_scope)

    def _setup_ui(self, current_scope: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        layout.addWidget(TitleLabel(tr("discovery.visibility.title", "Who can see this"), self))
        self.scope_combo = ComboBox(self)
        self.scope_combo.addItem(tr("discovery.visibility.public", "Public"), userData="public")
        self.scope_combo.addItem(tr("discovery.visibility.private", "Private"), userData="private")
        self.scope_combo.addItem(tr("discovery.visibility.include", "Selected friends"), userData="include")
        self.scope_combo.addItem(tr("discovery.visibility.exclude", "Do not show to selected friends"), userData="exclude")
        for index in range(self.scope_combo.count()):
            if self.scope_combo.itemData(index) == current_scope:
                self.scope_combo.setCurrentIndex(index)
                break
        self.scope_combo.currentIndexChanged.connect(self._sync_contacts_enabled)
        layout.addWidget(self.scope_combo)

        layout.addWidget(BodyLabel(tr("discovery.visibility.contacts_title", "Friends"), self))

        scroll_area = ScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        _prepare_transparent_scroll_area(scroll_area)
        contacts_widget = QWidget(scroll_area)
        contacts_layout = QVBoxLayout(contacts_widget)
        contacts_layout.setContentsMargins(0, 0, 0, 0)
        contacts_layout.setSpacing(8)
        for contact in self._contacts:
            user_id = _contact_id(contact)
            checkbox = CheckBox(_contact_display_name(contact), contacts_widget)
            checkbox.setChecked(user_id in self._current_user_ids)
            contacts_layout.addWidget(checkbox)
            self._target_checkboxes[user_id] = checkbox
        contacts_layout.addStretch(1)
        scroll_area.setWidget(contacts_widget)
        layout.addWidget(scroll_area, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel_button = PushButton(tr("common.cancel", "Cancel"), self)
        save_button = PrimaryPushButton(tr("common.confirm", "Confirm"), self)
        cancel_button.clicked.connect(self.reject)
        save_button.clicked.connect(self._submit)
        footer.addWidget(cancel_button)
        footer.addWidget(save_button)
        layout.addLayout(footer)
        self._sync_contacts_enabled()

    def _sync_contacts_enabled(self) -> None:
        enabled = self.selected_scope() in {"include", "exclude"}
        for checkbox in self._target_checkboxes.values():
            checkbox.setEnabled(enabled)

    def selected_scope(self) -> str:
        return str(self.scope_combo.currentData() or "public")

    def selected_user_ids(self) -> list[str]:
        if self.selected_scope() not in {"include", "exclude"}:
            return []
        return [user_id for user_id, checkbox in self._target_checkboxes.items() if checkbox.isChecked()]

    def _submit(self) -> None:
        scope = self.selected_scope()
        user_ids = self.selected_user_ids()
        if scope in {"include", "exclude"} and not user_ids:
            InfoBar.warning(
                tr("discovery.visibility.title", "Who can see this"),
                tr("discovery.visibility.empty_warning", "Select at least one friend."),
                parent=self,
                duration=1800,
            )
            return
        self.submitted.emit(scope, user_ids)
        self.accept()


class MomentPrivacySettingsDialog(QDialog):
    """Dialog for long-term moments privacy settings."""

    submitted = Signal(list, list, str)

    def __init__(
        self,
        contacts: list[ContactRecord],
        settings: MomentPrivacySettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._contacts = [contact for contact in contacts if _contact_id(contact)]
        self._settings = settings
        self._hide_my_checkboxes: dict[str, CheckBox] = {}
        self._hide_their_checkboxes: dict[str, CheckBox] = {}
        self.setWindowTitle(tr("discovery.privacy.window_title", "Moment Privacy"))
        self.setModal(True)
        self.resize(560, 640)
        _apply_themed_dialog_surface(self, "MomentPrivacySettingsDialog")
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        layout.addWidget(TitleLabel(tr("discovery.privacy.title", "Moment Privacy"), self))
        layout.addWidget(CaptionLabel(tr("discovery.privacy.visible_time_scope", "Allow friends to view moments from"), self))
        self.visible_time_combo = ComboBox(self)
        self.visible_time_combo.addItem(tr("discovery.privacy.time_all", "All time"), userData="all")
        self.visible_time_combo.addItem(tr("discovery.privacy.time_half_year", "Last half year"), userData="half_year")
        self.visible_time_combo.addItem(tr("discovery.privacy.time_month", "Last month"), userData="month")
        self.visible_time_combo.addItem(tr("discovery.privacy.time_three_days", "Last three days"), userData="three_days")
        for index in range(self.visible_time_combo.count()):
            if self.visible_time_combo.itemData(index) == self._settings.visible_time_scope:
                self.visible_time_combo.setCurrentIndex(index)
                break
        layout.addWidget(self.visible_time_combo)

        scroll_area = ScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        _prepare_transparent_scroll_area(scroll_area)
        content = QWidget(scroll_area)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)
        self._add_contact_section(
            content_layout,
            tr("discovery.privacy.hide_my_title", "Do not show my moments to"),
            set(self._settings.hide_my_moments_user_ids),
            self._hide_my_checkboxes,
        )
        self._add_contact_section(
            content_layout,
            tr("discovery.privacy.hide_their_title", "Do not view their moments"),
            set(self._settings.hide_their_moments_user_ids),
            self._hide_their_checkboxes,
        )
        content_layout.addStretch(1)
        scroll_area.setWidget(content)
        layout.addWidget(scroll_area, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel_button = PushButton(tr("common.cancel", "Cancel"), self)
        save_button = PrimaryPushButton(tr("common.save", "Save"), self)
        cancel_button.clicked.connect(self.reject)
        save_button.clicked.connect(self._submit)
        footer.addWidget(cancel_button)
        footer.addWidget(save_button)
        layout.addLayout(footer)

    def _add_contact_section(
        self,
        layout: QVBoxLayout,
        title: str,
        selected_ids: set[str],
        target: dict[str, CheckBox],
    ) -> None:
        layout.addWidget(BodyLabel(title, self))
        if not self._contacts:
            empty_label = CaptionLabel(tr("discovery.privacy.no_friends", "No friends available."), self)
            empty_label.setWordWrap(True)
            layout.addWidget(empty_label)
            return
        for contact in self._contacts:
            user_id = _contact_id(contact)
            checkbox = CheckBox(_contact_display_name(contact), self)
            checkbox.setChecked(user_id in selected_ids)
            layout.addWidget(checkbox)
            target[user_id] = checkbox

    def _checked_user_ids(self, checkboxes: dict[str, CheckBox]) -> list[str]:
        return [user_id for user_id, checkbox in checkboxes.items() if checkbox.isChecked()]

    def _submit(self) -> None:
        self.submitted.emit(
            self._checked_user_ids(self._hide_my_checkboxes),
            self._checked_user_ids(self._hide_their_checkboxes),
            str(self.visible_time_combo.currentData() or "all"),
        )
        self.accept()


class CreateMomentDialog(QDialog):
    """Dialog for publishing a moment with text, images, or video."""

    submitted = Signal(str, list, str, list)
    MAX_MEDIA_ITEMS = 9

    def __init__(self, parent=None, *, contacts: list[ContactRecord] | None = None):
        super().__init__(parent)
        self._media_paths: list[str] = []
        self._contacts = list(contacts or [])
        self._visibility_scope = "public"
        self._visibility_user_ids: list[str] = []
        self.setWindowTitle(tr("discovery.dialog.window_title", "Publish Moment"))
        self.setModal(True)
        self.resize(600, 460)
        _apply_themed_dialog_surface(self, "CreateMomentDialog")
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        layout.addWidget(TitleLabel(tr("discovery.dialog.title", "Post a moment"), self))
        hint = CaptionLabel(
            tr(
                "discovery.dialog.hint",
                "Share text, up to 9 images, or one video.",
            ),
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.editor = TextEdit(self)
        self.editor.setAcceptRichText(False)
        self.editor.setPlaceholderText(
            tr("discovery.dialog.placeholder", "Share what's new today, a thought, or a status")
        )
        self.editor.setMinimumHeight(200)
        layout.addWidget(self.editor, 1)

        media_row = QHBoxLayout()
        media_row.setContentsMargins(0, 0, 0, 0)
        media_row.setSpacing(8)
        self.add_images_button = PushButton(tr("discovery.dialog.add_images", "Add Images"), self)
        self.add_video_button = PushButton(tr("discovery.dialog.add_video", "Add Video"), self)
        self.clear_media_button = PushButton(tr("common.clear", "Clear"), self)
        self.add_images_button.clicked.connect(self._select_images)
        self.add_video_button.clicked.connect(self._select_video)
        self.clear_media_button.clicked.connect(self._clear_media)
        media_row.addWidget(self.add_images_button, 0)
        media_row.addWidget(self.add_video_button, 0)
        media_row.addWidget(self.clear_media_button, 0)
        media_row.addStretch(1)
        layout.addLayout(media_row)

        self.media_hint = CaptionLabel("", self)
        self.media_hint.setWordWrap(True)
        layout.addWidget(self.media_hint)
        self.media_preview = MomentMediaGrid([], self, compact=True)
        self.media_preview.setVisible(False)
        layout.addWidget(self.media_preview)
        self._sync_media_hint()
        self._sync_media_preview()

        visibility_row = QHBoxLayout()
        visibility_row.setContentsMargins(0, 0, 0, 0)
        visibility_row.setSpacing(10)
        self.visibility_button = PushButton(tr("discovery.dialog.visibility_title", "Who can see this"), self)
        self.visibility_value_label = CaptionLabel("", self)
        self.visibility_value_label.setWordWrap(True)
        self.visibility_button.clicked.connect(self._open_visibility_dialog)
        visibility_row.addWidget(self.visibility_button, 0)
        visibility_row.addWidget(self.visibility_value_label, 1)
        layout.addLayout(visibility_row)
        self._sync_visibility_summary()

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)
        footer.addStretch(1)

        cancel_button = PushButton(tr("common.cancel", "Cancel"), self)
        publish_button = PrimaryPushButton(tr("common.publish", "Publish"), self)
        cancel_button.clicked.connect(self.reject)
        publish_button.clicked.connect(self._submit)
        footer.addWidget(cancel_button)
        footer.addWidget(publish_button)
        layout.addLayout(footer)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.StyleChange,
        }:
            _apply_themed_dialog_surface(self, "CreateMomentDialog")

    def _submit(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text and not self._media_paths:
            InfoBar.warning(
                tr("discovery.publish.title", "Publish Moment"),
                tr("discovery.dialog.empty_warning", "Please enter something to post."),
                parent=self,
                duration=1800,
            )
            return
        self.submitted.emit(text, list(self._media_paths), self._visibility_scope, list(self._visibility_user_ids))
        self.accept()

    def _open_visibility_dialog(self) -> None:
        dialog = MomentVisibilitySelectDialog(
            self._contacts,
            current_scope=self._visibility_scope,
            current_user_ids=self._visibility_user_ids,
            parent=self,
        )
        dialog.submitted.connect(self._apply_visibility_selection)
        dialog.exec()

    def _apply_visibility_selection(self, visibility_scope: str, visibility_user_ids: list[str]) -> None:
        self._visibility_scope = visibility_scope
        self._visibility_user_ids = list(visibility_user_ids or [])
        self._sync_visibility_summary()

    def _sync_visibility_summary(self) -> None:
        labels = {
            "public": tr("discovery.visibility.public", "Public"),
            "private": tr("discovery.visibility.private", "Private"),
            "include": tr("discovery.visibility.include", "Selected friends"),
            "exclude": tr("discovery.visibility.exclude", "Do not show to selected friends"),
        }
        if self._visibility_scope in {"include", "exclude"} and self._visibility_user_ids:
            names = self._names_for_user_ids(self._visibility_user_ids)
            label = labels.get(self._visibility_scope, labels["public"])
            self.visibility_value_label.setText(f"{label}: {', '.join(names)}")
            return
        self.visibility_value_label.setText(labels.get(self._visibility_scope, labels["public"]))

    def _names_for_user_ids(self, user_ids: list[str]) -> list[str]:
        contacts_by_id = {_contact_id(contact): contact for contact in self._contacts}
        return [
            _contact_display_name(contacts_by_id.get(user_id)) or user_id
            for user_id in user_ids
        ]

    def _select_images(self) -> None:
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("discovery.dialog.select_images", "Select Images"),
            "",
            tr("discovery.dialog.image_filter", "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All Files (*.*)"),
        )
        if not file_paths:
            return
        if any(self._is_video_path(path) for path in self._media_paths):
            self._media_paths.clear()
        self._media_paths = (self._media_paths + list(file_paths))[: self.MAX_MEDIA_ITEMS]
        self._sync_media_hint()
        self._sync_media_preview()

    def _select_video(self) -> None:
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("discovery.dialog.select_video", "Select Video"),
            "",
            tr("discovery.dialog.video_filter", "Videos (*.mp4 *.mov *.m4v *.avi *.mkv *.webm);;All Files (*.*)"),
        )
        if not file_paths:
            return
        self._media_paths = [file_paths[0]]
        self._sync_media_hint()
        self._sync_media_preview()

    def _clear_media(self) -> None:
        self._media_paths.clear()
        self._sync_media_hint()
        self._sync_media_preview()

    def _sync_media_hint(self) -> None:
        if not self._media_paths:
            self.media_hint.setText(tr("discovery.dialog.media_empty", "No media selected."))
            return
        names = ", ".join(Path(path).name for path in self._media_paths[:3])
        remaining = max(0, len(self._media_paths) - 3)
        if remaining:
            names = f"{names} +{remaining}"
        self.media_hint.setText(
            tr(
                "discovery.dialog.media_selected",
                "{count} selected: {names}",
                count=len(self._media_paths),
                names=names,
            )
        )

    def _sync_media_preview(self) -> None:
        if not self._media_paths:
            self.media_preview.set_media([])
            self.media_preview.hide()
            return
        self.media_preview.set_media([_build_local_media_record(path) for path in self._media_paths])
        self.media_preview.show()

    @staticmethod
    def _is_video_path(path: str) -> bool:
        mime_type, _ = mimetypes.guess_type(path)
        if str(mime_type or "").lower().startswith("video/"):
            return True
        return str(path or "").lower().endswith((".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"))


class MomentCard(CardWidget):
    """Single moment card in the timeline."""

    like_requested = Signal(str, bool, int)
    comment_requested = Signal(str, str, object)
    detail_requested = Signal(str)
    delete_requested = Signal(str)
    comment_delete_requested = Signal(str, str)

    CONTENT_PREVIEW_LENGTH = 180

    def __init__(self, moment: MomentRecord, parent=None):
        super().__init__(parent)
        self.moment = moment
        self._content_expanded = False
        self._image_dialogs: set[QDialog] = set()
        self.setBorderRadius(8)
        self._setup_ui()
        self._apply_moment()

    def _setup_ui(self) -> None:
        self.setObjectName("MomentCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(16)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(14)

        self.avatar = DiscoveryAvatar(52, self)
        self.name_label = SubtitleLabel("", self)
        self.time_label = CaptionLabel("", self)
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)
        info_layout.addWidget(self.name_label)
        info_layout.addWidget(self.time_label)

        self.more_button = TransparentToolButton(AppIcon.CANCEL_MEDIUM, self)
        self.more_button.setToolTip(tr("discovery.card.delete_tooltip", "Delete moment"))
        self.more_button.clicked.connect(self._request_delete)
        _apply_safe_button_font(self.more_button)

        header_row.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)
        header_row.addLayout(info_layout, 1)
        header_row.addWidget(self.more_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header_row)

        self.content_label = BodyLabel("", self)
        self.content_label.setObjectName("momentContentLabel")
        self.content_label.setWordWrap(True)
        layout.addWidget(self.content_label)

        self.expand_button = PushButton(tr("discovery.card.expand", "Read More"), self)
        self.expand_button.setFixedHeight(30)
        self.expand_button.clicked.connect(self._toggle_content)
        layout.addWidget(self.expand_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.media_grid = MomentMediaGrid([], self)
        self.media_grid.image_requested.connect(self._open_image)
        self.media_grid.video_requested.connect(self._open_video)
        layout.addWidget(self.media_grid)

        self.stats_label = CaptionLabel("", self)
        self.stats_label.setObjectName("momentStatsLabel")
        layout.addWidget(self.stats_label)

        divider = QFrame(self)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setObjectName("MomentCardDivider")
        layout.addWidget(divider)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(10)

        self.like_button = PushButton("", self)
        self.comment_button = PushButton("", self)
        self.comment_button.clicked.connect(self._open_comment_editor)
        self.like_button.clicked.connect(self._toggle_like)

        action_row.addWidget(self.like_button, 0)
        action_row.addWidget(self.comment_button, 0)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.comment_section = AnimatedCommentSection([], self, moment_id=self.moment.id, comments_truncated=self.moment.comments_truncated)
        self.comment_section.comment_submitted.connect(self._submit_comment)
        self.comment_section.detail_requested.connect(self._request_detail)
        self.comment_section.comment_delete_requested.connect(self._request_comment_delete)
        layout.addWidget(self.comment_section)

    def _apply_moment(self) -> None:
        self.avatar.set_avatar(
            self.moment.avatar,
            self.moment.display_name,
            gender=self.moment.gender,
            seed=profile_avatar_seed(user_id=self.moment.user_id, username=self.moment.username, display_name=self.moment.display_name),
        )
        self.name_label.setText(self.moment.display_name)
        self.time_label.setText(format_relative_time(self.moment.created_at))
        self._refresh_content()
        self.layout().removeWidget(self.media_grid)
        self.media_grid.deleteLater()
        if self.moment.media:
            self.media_grid = MomentMediaGrid(self.moment.media, self)
            self.media_grid.image_requested.connect(self._open_image)
            self.media_grid.video_requested.connect(self._open_video)
            self.layout().insertWidget(3, self.media_grid)
        else:
            self.media_grid = MomentMediaGrid([], self)
            self.media_grid.hide()
            self.layout().insertWidget(3, self.media_grid)
        self.comment_section.set_comments(
            self.moment.comments,
            moment_id=self.moment.id,
            comments_truncated=self.moment.comments_truncated,
        )
        self._refresh_actions()

    def _refresh_content(self) -> None:
        text = self.moment.content.strip() or tr("discovery.card.no_content", "This moment has no body text yet.")
        is_long = len(text) > self.CONTENT_PREVIEW_LENGTH
        if is_long and not self._content_expanded:
            self.content_label.setText(text[: self.CONTENT_PREVIEW_LENGTH].rstrip() + "…")
        else:
            self.content_label.setText(text)
        self.expand_button.setVisible(is_long)
        self.expand_button.setText(
            tr("discovery.card.collapse", "Collapse")
            if self._content_expanded
            else tr("discovery.card.expand", "Read More")
        )

    def _refresh_actions(self) -> None:
        like_prefix = (
            tr("discovery.card.liked", "Liked")
            if self.moment.is_liked
            else tr("discovery.card.like", "Like")
        )
        self.like_button.setText(f"{like_prefix} {self.moment.like_count}" if self.moment.like_count else like_prefix)
        comment_prefix = tr("discovery.card.comment", "Comment")
        self.comment_button.setText(
            f"{comment_prefix} {self.moment.comment_count}" if self.moment.comment_count else comment_prefix
        )
        self.more_button.setVisible(self.moment.is_self)

        if self.moment.like_count or self.moment.comment_count:
            self.stats_label.setText(
                tr(
                    "discovery.card.stats_summary",
                    "{likes} likes · {comments} comments",
                    likes=self.moment.like_count,
                    comments=self.moment.comment_count,
                )
            )
        else:
            self.stats_label.setText(tr("discovery.card.stats_empty", "No interactions yet. Be the first."))

    def set_like_state(self, liked: bool, like_count: int) -> None:
        """Update like state from optimistic UI or rollback."""
        self.moment.is_liked = liked
        self.moment.like_count = max(0, like_count)
        self._refresh_actions()

    def append_comment(self, comment: MomentCommentRecord) -> None:
        """Append a new comment to the card."""
        self.moment.comments.append(comment)
        self.moment.comment_count = max(self.moment.comment_count + 1, len(self.moment.comments))
        self.comment_section.append_comment(comment)
        self._refresh_actions()

    def remove_comment(self, comment_id: str) -> None:
        """Remove one comment from the card."""
        normalized_id = str(comment_id or "").strip()
        if not normalized_id:
            return
        previous_count = len(self.moment.comments)
        self.moment.comments = [comment for comment in self.moment.comments if comment.id != normalized_id]
        if len(self.moment.comments) == previous_count:
            return
        self.moment.comment_count = max(0, self.moment.comment_count - 1, len(self.moment.comments))
        self.comment_section.remove_comment(normalized_id)
        self._refresh_actions()

    def apply_detail(self, moment: MomentRecord) -> None:
        """Refresh the card with one full moment detail payload."""
        self.moment.comments = list(moment.comments)
        self.moment.comment_count = max(moment.comment_count, len(moment.comments))
        self.moment.comments_truncated = moment.comments_truncated
        self.comment_section.set_comments(
            self.moment.comments,
            moment_id=self.moment.id,
            comments_truncated=self.moment.comments_truncated,
        )
        self.comment_section._set_expanded(True)
        self._refresh_actions()

    def _toggle_content(self) -> None:
        self._content_expanded = not self._content_expanded
        self._refresh_content()

    def _toggle_like(self) -> None:
        next_liked = not self.moment.is_liked
        next_count = self.moment.like_count + (1 if next_liked else -1)
        self.set_like_state(next_liked, next_count)
        self.like_requested.emit(self.moment.id, next_liked, self.moment.like_count)

    def _open_comment_editor(self) -> None:
        self.comment_section.open_editor()

    def _submit_comment(self, content: str, image_path: object = None) -> None:
        self.comment_requested.emit(self.moment.id, content, image_path)

    def _request_detail(self, moment_id: str) -> None:
        self.detail_requested.emit(moment_id)

    def _request_delete(self) -> None:
        self.delete_requested.emit(self.moment.id)

    def _request_comment_delete(self, moment_id: str, comment_id: str) -> None:
        self.comment_delete_requested.emit(moment_id, comment_id)

    def _open_image(self, image_path: str) -> None:
        viewer = ImageViewer(image_path, self.window())
        self._image_dialogs.add(viewer)
        viewer.finished.connect(lambda _result=0, dlg=viewer: self._image_dialogs.discard(dlg))
        viewer.show()
        viewer.raise_()
        viewer.activateWindow()

    def _open_video(self, video_source: str) -> None:
        if not video_source:
            return
        if Path(video_source).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(video_source))
            return
        QDesktopServices.openUrl(QUrl(video_source))


class DiscoveryInterface(QWidget):
    """Moments feed styled to match the current chat/contact Fluent UI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DiscoveryInterface")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self._controller = get_discovery_controller()
        self._contact_controller = get_contact_controller()
        self._event_bus = get_event_bus()
        self._moments: list[MomentRecord] = []
        self._cards: dict[str, MomentCard] = {}
        self._load_task: Optional[asyncio.Task] = None
        self._publish_task: Optional[asyncio.Task] = None
        self._keyed_ui_tasks: dict[tuple[str, str], asyncio.Task] = {}
        self._ui_tasks: set[asyncio.Task] = set()
        self._dialog_refs: set[QDialog] = set()
        self._image_dialogs: set[QDialog] = set()
        self._initial_load_done = False
        self._teardown_started = False

        self._setup_ui()
        self._connect_signals()
        self.destroyed.connect(self._on_destroyed)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.ensure_initial_load()

    def ensure_initial_load(self) -> None:
        """Kick off the first moments load once per runtime."""
        if self._initial_load_done:
            return
        self._initial_load_done = True
        QTimer.singleShot(0, self.reload_data)

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        _prepare_transparent_scroll_area(self.scroll_area)
        if self.scroll_area.viewport() is not None:
            self.scroll_area.viewport().setObjectName("discoveryViewport")

        self.scroll_widget = QWidget(self.scroll_area)
        self.scroll_widget.setObjectName("discoveryScrollWidget")
        self.scroll_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.scroll_widget.setAutoFillBackground(False)
        self.scroll_widget.setStyleSheet("background: transparent; border: none;")
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(24, 24, 24, 32)
        self.scroll_layout.setSpacing(18)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.column = QWidget(self.scroll_widget)
        self.column.setObjectName("discoveryColumn")
        self.column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.column.setAutoFillBackground(False)
        self.column.setMaximumWidth(880)
        self.column_layout = QVBoxLayout(self.column)
        self.column_layout.setContentsMargins(0, 0, 0, 0)
        self.column_layout.setSpacing(16)

        self.hero_card = CardWidget(self.column)
        self.hero_card.setObjectName("DiscoveryHeroCard")
        self.hero_card.setBorderRadius(8)
        hero_layout = QVBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(24, 24, 24, 24)
        hero_layout.setSpacing(18)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(6)
        title_stack.addWidget(TitleLabel(tr("discovery.feed.title", "Moments"), self.hero_card))
        title_stack.addWidget(
            CaptionLabel(
                tr(
                    "discovery.feed.subtitle",
                    "Share updates, browse what's new, and keep the conversation going in comments.",
                ),
                self.hero_card,
            )
        )

        self.refresh_button = TransparentToolButton(AppIcon.SYNC, self.hero_card)
        self.refresh_button.setToolTip(tr("discovery.feed.refresh_tooltip", "Refresh feed"))
        _apply_safe_button_font(self.refresh_button)
        self.privacy_button = PushButton(tr("discovery.feed.privacy_button", "Moment Privacy"), self.hero_card)
        self.publish_button = PrimaryPushButton(tr("discovery.feed.publish_button", "Publish Moment"), self.hero_card)

        top_row.addLayout(title_stack, 1)
        top_row.addWidget(self.refresh_button, 0)
        top_row.addWidget(self.privacy_button, 0)
        top_row.addWidget(self.publish_button, 0)

        self.summary_label = BodyLabel(tr("discovery.feed.loading", "Loading moments..."), self.hero_card)
        self.summary_label.setObjectName("discoverySummaryLabel")
        self.summary_label.setWordWrap(True)

        hero_layout.addLayout(top_row)
        hero_layout.addWidget(self.summary_label)

        self.feed_container = QWidget(self.column)
        self.feed_container.setObjectName("discoveryFeedContainer")
        self.feed_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.feed_container.setAutoFillBackground(False)
        self.feed_layout = QVBoxLayout(self.feed_container)
        self.feed_layout.setContentsMargins(0, 0, 0, 0)
        self.feed_layout.setSpacing(16)

        self.column_layout.addWidget(self.hero_card)
        self.column_layout.addWidget(self.feed_container)
        self.scroll_layout.addWidget(self.column, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.scroll_widget)
        main_layout.addWidget(self.scroll_area)

        StyleSheet.DISCOVERY_INTERFACE.apply(self)

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.reload_data)
        self.privacy_button.clicked.connect(self._open_privacy_settings_dialog)
        self.publish_button.clicked.connect(self._open_publish_dialog)
        self._event_bus.subscribe_sync(MomentEvent.SYNC_REQUIRED, self._on_moment_sync_required)

    def reload_data(self) -> None:
        """Refresh the feed from the backend."""
        if self._teardown_started:
            return
        self._set_load_task(self._reload_data_async())

    def _on_moment_sync_required(self, payload: object) -> None:
        """Refresh the visible feed after a realtime moment mutation hint."""
        if self._teardown_started or not self._initial_load_done or not self.isVisible():
            return
        event_payload = dict(payload or {}) if isinstance(payload, dict) else {}
        moment_payload = dict(event_payload.get("payload") or {}) if isinstance(event_payload.get("payload"), dict) else {}
        logger.info(
            "Discovery moment refresh requested action=%s moment_id=%s",
            moment_payload.get("action") or event_payload.get("reason"),
            moment_payload.get("moment_id"),
        )
        self.reload_data()

    async def _reload_data_async(self) -> None:
        self.refresh_button.setEnabled(False)
        self.summary_label.setText(tr("discovery.feed.syncing", "Syncing the moments feed..."))
        try:
            moments = await self._controller.load_moments()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.summary_label.setText(tr("discovery.feed.load_failed", "Failed to load moments."))
            raise
        finally:
            self.refresh_button.setEnabled(True)

        self._moments = moments
        self.summary_label.setText(
            tr(
                "discovery.feed.summary",
                "{count} moments total. Click comment to expand the inline editor.",
                count=len(self._moments),
            )
        )
        self._rebuild_feed()

    def _rebuild_feed(self) -> None:
        _clear_layout(self.feed_layout)
        self._cards.clear()

        if not self._moments:
            self.feed_layout.addWidget(self._create_empty_state())
            self.feed_layout.addStretch(1)
            return

        for moment in self._moments:
            card = MomentCard(moment, self.feed_container)
            card.like_requested.connect(self._request_like_toggle)
            card.comment_requested.connect(self._request_comment_create)
            card.detail_requested.connect(self._request_moment_detail)
            card.delete_requested.connect(self._request_moment_delete)
            card.comment_delete_requested.connect(self._request_comment_delete)
            self.feed_layout.addWidget(card)
            self._cards[moment.id] = card

        self.feed_layout.addStretch(1)

    def _create_empty_state(self) -> CardWidget:
        """Create an empty placeholder when the feed is blank."""
        card = CardWidget(self.feed_container)
        card.setBorderRadius(8)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(36, 36, 36, 36)
        layout.setSpacing(12)

        icon = IconWidget(AppIcon.GLOBE, card)
        icon.setFixedSize(48, 48)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignCenter)

        title = SubtitleLabel(tr("discovery.feed.empty_title", "No moments yet"), card)
        caption = CaptionLabel(
            tr(
                "discovery.feed.empty_caption",
                "Publish the first update, or refresh to check the latest moments.",
            ),
            card,
        )
        caption.setWordWrap(True)

        layout.addWidget(title, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(caption, 0, Qt.AlignmentFlag.AlignCenter)
        return card

    def _open_publish_dialog(self) -> None:
        self._create_ui_task(self._open_publish_dialog_async(), "open publish moment dialog")

    async def _open_publish_dialog_async(self) -> None:
        try:
            contacts = await self._contact_controller.load_contacts()
        except Exception:
            logger.exception("Failed to load contacts for moment visibility selector")
            contacts = []
        dialog = CreateMomentDialog(self.window(), contacts=contacts)
        dialog.submitted.connect(self._create_moment)
        self._dialog_refs.add(dialog)
        dialog.finished.connect(lambda _result=0, dlg=dialog: self._dialog_refs.discard(dlg))
        dialog.finished.connect(dialog.deleteLater)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _open_privacy_settings_dialog(self) -> None:
        self._create_ui_task(self._open_privacy_settings_dialog_async(), "open moment privacy settings dialog")

    async def _open_privacy_settings_dialog_async(self) -> None:
        contacts_result, settings = await asyncio.gather(
            self._contact_controller.load_contacts(),
            self._controller.load_moment_privacy_settings(),
            return_exceptions=True,
        )
        contacts = []
        if isinstance(contacts_result, Exception):
            logger.error(
                "Failed to load contacts for moment privacy settings",
                exc_info=(type(contacts_result), contacts_result, contacts_result.__traceback__),
            )
        else:
            contacts = list(contacts_result)
        if isinstance(settings, Exception):
            raise settings
        dialog = MomentPrivacySettingsDialog(contacts, settings, self.window())
        dialog.submitted.connect(self._save_moment_privacy_settings)
        self._dialog_refs.add(dialog)
        dialog.finished.connect(lambda _result=0, dlg=dialog: self._dialog_refs.discard(dlg))
        dialog.finished.connect(dialog.deleteLater)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _create_moment(self, content: str, media_paths: list | None = None, visibility_scope: str = "public", visibility_user_ids: list | None = None) -> None:
        if self._teardown_started:
            return
        if self._publish_task is not None and not self._publish_task.done():
            return
        self._set_publish_task(
            self._create_moment_async(
                content,
                media_paths or [],
                visibility_scope,
                visibility_user_ids or [],
            )
        )

    async def _create_moment_async(
        self,
        content: str,
        media_paths: list[str],
        visibility_scope: str = "public",
        visibility_user_ids: list[str] | None = None,
    ) -> None:
        self.publish_button.setEnabled(False)
        try:
            uploaded_media = await self.upload_moment_media(media_paths)
            moment = await self._controller.create_moment(
                content,
                media=[self._server_media_payload(item) for item in uploaded_media],
                visibility_scope=visibility_scope,
                visibility_user_ids=list(visibility_user_ids or []),
            )
            self._attach_local_media_previews(moment, uploaded_media)
        except Exception:
            InfoBar.error(
                tr("discovery.publish.title", "Publish Moment"),
                tr("discovery.publish.failed", "Publish failed. Please try again later."),
                parent=self.window(),
                duration=2200,
            )
            raise
        finally:
            self.publish_button.setEnabled(True)

        self._moments.insert(0, moment)
        self.summary_label.setText(
            tr(
                "discovery.feed.summary",
                "{count} moments total. Click comment to expand the inline editor.",
                count=len(self._moments),
            )
        )
        self._rebuild_feed()
        self.scroll_area.verticalScrollBar().setValue(0)
        InfoBar.success(
            tr("discovery.publish.title", "Publish Moment"),
            tr("discovery.publish.success", "Moment published."),
            parent=self.window(),
            duration=1800,
        )

    def _save_moment_privacy_settings(
        self,
        hide_my_moments_user_ids: list,
        hide_their_moments_user_ids: list,
        visible_time_scope: str,
    ) -> None:
        self._create_ui_task(
            self._save_moment_privacy_settings_async(
                [str(item) for item in hide_my_moments_user_ids],
                [str(item) for item in hide_their_moments_user_ids],
                visible_time_scope,
            ),
            "save moment privacy settings",
        )

    async def _save_moment_privacy_settings_async(
        self,
        hide_my_moments_user_ids: list[str],
        hide_their_moments_user_ids: list[str],
        visible_time_scope: str,
    ) -> None:
        await self._controller.update_moment_privacy_settings(
            hide_my_moments_user_ids=hide_my_moments_user_ids,
            hide_their_moments_user_ids=hide_their_moments_user_ids,
            visible_time_scope=visible_time_scope,
        )
        self.reload_data()
        InfoBar.success(
            tr("discovery.privacy.title", "Moment Privacy"),
            tr("discovery.privacy.saved", "Moment privacy settings saved."),
            parent=self.window(),
            duration=1800,
        )

    def _request_like_toggle(self, moment_id: str, liked: bool, like_count: int) -> None:
        self._schedule_keyed_ui_task(
            ("moment_like", moment_id),
            self._request_like_toggle_async(moment_id, liked, like_count),
            f"toggle moment like {moment_id}",
        )

    async def _request_like_toggle_async(self, moment_id: str, liked: bool, like_count: int) -> None:
        card = self._cards.get(moment_id)
        previous_liked = not liked
        previous_count = like_count - 1 if liked else like_count + 1
        try:
            await self._controller.set_liked(moment_id, liked, like_count)
        except asyncio.CancelledError:
            raise
        except Exception:
            if card is not None:
                card.set_like_state(previous_liked, previous_count)
            raise

        moment = next((item for item in self._moments if item.id == moment_id), None)
        if moment is not None:
            moment.is_liked = liked
            moment.like_count = like_count

    def _request_moment_detail(self, moment_id: str) -> None:
        self._schedule_keyed_ui_task(
            ("moment_detail", moment_id),
            self._request_moment_detail_async(moment_id),
            f"load moment detail {moment_id}",
        )

    async def _request_moment_detail_async(self, moment_id: str) -> None:
        moment = await self._controller.load_moment_detail(moment_id)
        existing_index = next((index for index, item in enumerate(self._moments) if item.id == moment_id), None)
        if existing_index is not None:
            self._moments[existing_index] = moment

        card = self._cards.get(moment_id)
        if card is not None:
            card.apply_detail(moment)

    def _request_comment_create(self, moment_id: str, content: str, image_path: object = None) -> None:
        self._schedule_keyed_ui_task(
            ("moment_comment", moment_id),
            self._request_comment_create_async(moment_id, content, image_path),
            f"create moment comment {moment_id}",
        )

    async def _request_comment_create_async(self, moment_id: str, content: str, image_path: object = None) -> None:
        image_payload = None
        if isinstance(image_path, str) and image_path:
            uploaded_image = await self.upload_comment_image(image_path)
            image_payload = self._server_media_payload(uploaded_image)
        comment = await self._controller.add_comment(moment_id, content, image=image_payload)
        if image_payload is not None and comment.image is not None and isinstance(image_path, str):
            comment.image.local_path = image_path

        card = self._cards.get(moment_id)
        if card is not None:
            card.append_comment(comment)
        self._apply_local_comment(moment_id, comment)

        InfoBar.success(
            tr("discovery.comment.title", "Post Comment"),
            tr("discovery.comment.success", "Comment sent."),
            parent=self.window(),
            duration=1400,
        )

    def _apply_local_comment(self, moment_id: str, comment) -> None:
        """Keep the backing moment record aligned with the visible card."""
        moment = next((item for item in self._moments if item.id == moment_id), None)
        if moment is None:
            return
        comment_id = str(getattr(comment, "id", "") or "")
        if any(
            existing is comment or (comment_id and getattr(existing, "id", "") == comment_id)
            for existing in moment.comments
        ):
            moment.comment_count = max(moment.comment_count, len(moment.comments))
            return
        moment.comments.append(comment)
        moment.comment_count = max(moment.comment_count + 1, len(moment.comments))

    def _request_moment_delete(self, moment_id: str) -> None:
        moment = next((item for item in self._moments if item.id == moment_id), None)
        if moment is None or not moment.is_self:
            return
        dialog = DeleteMomentConfirmDialog(self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._schedule_keyed_ui_task(
            ("moment_delete", moment_id),
            self._request_moment_delete_async(moment_id),
            f"delete moment {moment_id}",
        )

    async def _request_moment_delete_async(self, moment_id: str) -> None:
        try:
            await self._controller.delete_moment(moment_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            InfoBar.error(
                tr("discovery.delete_moment.title", "Delete Moment"),
                tr("discovery.delete_moment.failed", "Delete failed. Please try again later."),
                parent=self.window(),
                duration=2200,
            )
            raise
        self._apply_local_moment_delete(moment_id)
        InfoBar.success(
            tr("discovery.delete_moment.title", "Delete Moment"),
            tr("discovery.delete_moment.success", "Moment deleted."),
            parent=self.window(),
            duration=1600,
        )

    def _apply_local_moment_delete(self, moment_id: str) -> None:
        """Remove one deleted moment from the feed backing records."""
        normalized_id = str(moment_id or "").strip()
        self._moments = [moment for moment in self._moments if moment.id != normalized_id]
        self.summary_label.setText(
            tr(
                "discovery.feed.summary",
                "{count} moments total. Click comment to expand the inline editor.",
                count=len(self._moments),
            )
        )
        self._rebuild_feed()

    def _request_comment_delete(self, moment_id: str, comment_id: str) -> None:
        comment = self._find_comment(moment_id, comment_id)
        if comment is None or not comment.can_delete:
            return
        dialog = DeleteCommentConfirmDialog(self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._schedule_keyed_ui_task(
            ("moment_comment_delete", comment_id),
            self._request_comment_delete_async(moment_id, comment_id),
            f"delete moment comment {comment_id}",
        )

    async def _request_comment_delete_async(self, moment_id: str, comment_id: str) -> None:
        try:
            await self._controller.delete_comment(moment_id, comment_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            InfoBar.error(
                tr("discovery.delete_comment.title", "Delete Comment"),
                tr("discovery.delete_comment.failed", "Delete failed. Please try again later."),
                parent=self.window(),
                duration=2200,
            )
            raise
        self._apply_local_comment_delete(moment_id, comment_id)
        InfoBar.success(
            tr("discovery.delete_comment.title", "Delete Comment"),
            tr("discovery.delete_comment.success", "Comment deleted."),
            parent=self.window(),
            duration=1400,
        )

    def _apply_local_comment_delete(self, moment_id: str, comment_id: str) -> None:
        """Remove one deleted comment from the feed backing records."""
        card = self._cards.get(moment_id)
        if card is not None:
            card.remove_comment(comment_id)
            return
        moment = next((item for item in self._moments if item.id == moment_id), None)
        if moment is None:
            return
        previous_count = len(moment.comments)
        moment.comments = [comment for comment in moment.comments if comment.id != comment_id]
        if len(moment.comments) != previous_count:
            moment.comment_count = max(0, moment.comment_count - 1, len(moment.comments))

    def _find_comment(self, moment_id: str, comment_id: str) -> MomentCommentRecord | None:
        moment = next((item for item in self._moments if item.id == moment_id), None)
        if moment is None:
            return None
        return next((comment for comment in moment.comments if comment.id == comment_id), None)

    async def upload_moment_media(self, file_paths: list[str]) -> list[dict[str, object]]:
        """Upload selected moment media files and return normalized client-side payloads."""
        uploaded: list[dict[str, object]] = []
        for file_path in file_paths[: CreateMomentDialog.MAX_MEDIA_ITEMS]:
            media = await self._upload_media_file(file_path)
            uploaded.append(media)
        return uploaded

    async def upload_comment_image(self, file_path: str) -> dict[str, object]:
        """Upload one comment image using the shared file service."""
        media = await self._upload_media_file(file_path)
        media["type"] = "image"
        return media

    async def _upload_media_file(self, file_path: str) -> dict[str, object]:
        payload = await get_file_service().upload_file(file_path)
        media = dict(payload.get("media") or payload)
        url = str(media.get("url") or payload.get("url") or "").strip()
        mime_type = str(media.get("mime_type") or payload.get("mime_type") or "").strip()
        original_name = str(media.get("original_name") or payload.get("original_name") or Path(file_path).name).strip()
        try:
            size_bytes = max(0, int(media.get("size_bytes") or payload.get("size_bytes") or 0))
        except (TypeError, ValueError):
            size_bytes = 0
        return {
            "type": self._media_type_for_path(file_path, mime_type),
            "url": url,
            "original_name": original_name,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "local_path": file_path,
        }

    @staticmethod
    def _server_media_payload(media: dict[str, object]) -> dict[str, object]:
        return {
            "type": str(media.get("type") or "").strip(),
            "url": str(media.get("url") or "").strip(),
            "original_name": str(media.get("original_name") or "").strip(),
            "mime_type": str(media.get("mime_type") or "").strip(),
            "size_bytes": max(0, int(media.get("size_bytes") or 0)),
        }

    @staticmethod
    def _media_type_for_path(file_path: str, mime_type: str = "") -> str:
        lowered_mime = str(mime_type or "").strip().lower()
        if not lowered_mime:
            guessed, _ = mimetypes.guess_type(file_path)
            lowered_mime = str(guessed or "").lower()
        if lowered_mime.startswith("video/"):
            return "video"
        return "image"

    @staticmethod
    def _attach_local_media_previews(moment: MomentRecord, uploaded_media: list[dict[str, object]]) -> None:
        local_paths_by_url = {
            str(item.get("url") or "").strip(): str(item.get("local_path") or "").strip()
            for item in uploaded_media
            if item.get("url") and item.get("local_path")
        }
        for item in moment.media:
            if item.url in local_paths_by_url:
                item.local_path = local_paths_by_url[item.url]

    def _on_destroyed(self, *_args) -> None:
        """Cancel outstanding async work when the page is torn down."""
        self.quiesce()

    def quiesce(self) -> None:
        """Stop discovery tasks before logout tears down the runtime."""
        if self._teardown_started:
            return
        self._teardown_started = True
        self._event_bus.unsubscribe_sync(MomentEvent.SYNC_REQUIRED, self._on_moment_sync_required)
        self._cancel_pending_task(self._load_task)
        self._load_task = None
        self._cancel_pending_task(self._publish_task)
        self._publish_task = None
        for task in list(self._keyed_ui_tasks.values()):
            if not task.done():
                task.cancel()
        self._keyed_ui_tasks.clear()
        for dialog in list(self._dialog_refs):
            dialog.close()
        self._dialog_refs.clear()
        for dialog in list(getattr(self, "_image_dialogs", ())):
            dialog.close()
        self._image_dialogs.clear()
        self._cancel_all_ui_tasks()

    def _cancel_pending_task(self, task: Optional[asyncio.Task]) -> None:
        """Cancel one tracked task if it is still running."""
        if task is not None and not task.done():
            task.cancel()

    def _cancel_all_ui_tasks(self) -> None:
        """Cancel all background tasks launched from this page."""
        for task in list(self._ui_tasks):
            if not task.done():
                task.cancel()

    def _create_ui_task(self, coro, context: str, *, on_done=None) -> asyncio.Task:
        """Track page-owned coroutines for consistent cleanup."""
        task = asyncio.create_task(coro)
        self._ui_tasks.add(task)
        task.add_done_callback(lambda finished, name=context, callback=on_done: self._finalize_ui_task(finished, name, callback))
        return task

    def _finalize_ui_task(self, task: asyncio.Task, context: str, on_done=None) -> None:
        """Drop task bookkeeping and log failures."""
        self._ui_tasks.discard(task)
        if on_done is not None:
            on_done(task)

        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("DiscoveryInterface task failed: %s", context)

    def _set_load_task(self, coro) -> None:
        """Replace the active feed reload with the newest request."""
        self._cancel_pending_task(self._load_task)
        self._load_task = self._create_ui_task(coro, "reload moments", on_done=self._clear_load_task)

    def _clear_load_task(self, task: asyncio.Task) -> None:
        """Clear the tracked reload task when it finishes."""
        if self._load_task is task:
            self._load_task = None

    def _set_publish_task(self, coro) -> None:
        """Track the current publish request."""
        self._cancel_pending_task(self._publish_task)
        self._publish_task = self._create_ui_task(coro, "publish moment", on_done=self._clear_publish_task)

    def _clear_publish_task(self, task: asyncio.Task) -> None:
        """Clear the tracked publish task when it finishes."""
        if self._publish_task is task:
            self._publish_task = None

    def _schedule_keyed_ui_task(self, key: tuple[str, str], coro, context: str) -> None:
        """Prevent duplicate actions for the same moment while one is pending."""
        existing = self._keyed_ui_tasks.get(key)
        if existing is not None and not existing.done():
            return
        self._keyed_ui_tasks[key] = self._create_ui_task(
            coro,
            context,
            on_done=lambda task, task_key=key: self._clear_keyed_ui_task(task_key, task),
        )

    def _clear_keyed_ui_task(self, key: tuple[str, str], task: asyncio.Task) -> None:
        """Release a keyed action slot once its task finishes."""
        if self._keyed_ui_tasks.get(key) is task:
            self._keyed_ui_tasks.pop(key, None)


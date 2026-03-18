"""Moments/discovery interface with animated comment expansion."""

from __future__ import annotations

import asyncio
import html
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QDialog,
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
    ElevatedCardWidget,
    FluentIcon,
    IconWidget,
    InfoBar,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SubtitleLabel,
    TextEdit,
    TitleLabel,
    TransparentToolButton,
)

from client.core import logging
from client.core.exceptions import APIError, NetworkError
from client.core.logging import setup_logging
from client.ui.controllers.discovery_controller import (
    MomentCommentRecord,
    MomentRecord,
    get_discovery_controller,
)
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


def _parse_datetime(value: str) -> Optional[datetime]:
    """Parse common backend datetime formats."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def format_relative_time(value: str) -> str:
    """Format an ISO timestamp into a friendly Chinese label."""
    dt = _parse_datetime(value)
    if not dt:
        return value or "刚刚"

    now = datetime.now()
    delta = now - dt
    seconds = int(max(delta.total_seconds(), 0))
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    if seconds < 86400 * 7:
        return f"{seconds // 86400} 天前"
    return dt.strftime("%m-%d %H:%M")


class DiscoveryAvatar(QWidget):
    """Circular avatar used by the discovery feed."""

    def __init__(self, size: int = 48, parent=None):
        super().__init__(parent)
        self._size = size
        self._pixmap: Optional[QPixmap] = None
        self._fallback = "?"
        self.setFixedSize(size, size)

    def set_avatar(self, avatar_path: str = "", fallback: str = "?") -> None:
        """Update avatar image or fallback initials."""
        self._fallback = (fallback or "?").strip()[:2].upper() or "?"
        self._pixmap = None
        if avatar_path:
            pixmap = QPixmap(avatar_path)
            if not pixmap.isNull():
                self._pixmap = pixmap
        self.update()

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

        painter.fillPath(clip, QColor("#D8E8F8"))
        painter.setClipping(False)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(12, self._size // 3))
        painter.setFont(font)
        painter.setPen(QColor("#27486B"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._fallback)


class ClickableImageLabel(QLabel):
    """Simple clickable image tile."""

    clicked = Signal(str)

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.image_path)
        super().mousePressEvent(event)


class MomentMediaGrid(QWidget):
    """Responsive grid for moment images."""

    image_requested = Signal(str)

    def __init__(self, images: list[str], parent=None):
        super().__init__(parent)
        self._images = images[:9]
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(8)
        self._layout.setVerticalSpacing(8)
        self._build()

    def _build(self) -> None:
        if not self._images:
            self.hide()
            return

        count = len(self._images)
        if count == 1:
            sizes = [(0, 0, 1, 1, 360, 220)]
        elif count in (2, 4):
            sizes = [
                (index // 2, index % 2, 1, 1, 172, 132)
                for index in range(count)
            ]
        else:
            sizes = [
                (index // 3, index % 3, 1, 1, 112, 112)
                for index in range(count)
            ]

        for index, image_path in enumerate(self._images):
            row, col, row_span, col_span, width, height = sizes[index]
            label = ClickableImageLabel(image_path, self)
            label.setObjectName("momentMediaTile")
            label.setFixedSize(width, height)
            self._load_image(label, image_path, width, height)
            label.clicked.connect(self.image_requested.emit)
            self._layout.addWidget(label, row, col, row_span, col_span)

    def _load_image(self, label: QLabel, image_path: str, width: int, height: int) -> None:
        """Try to render a local image file, otherwise keep the placeholder."""
        path = Path(image_path)
        if not path.exists():
            label.setText("图片")
            return

        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            label.setText("图片")
            return

        scaled = pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(scaled)
        label.setText("")


class MomentCommentItem(QWidget):
    """A single comment row."""

    def __init__(self, comment: MomentCommentRecord, parent=None):
        super().__init__(parent)
        self.comment = comment
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        text_label = QLabel(self)
        text_label.setWordWrap(True)
        text_label.setTextFormat(Qt.TextFormat.RichText)
        text_label.setText(
            f"<span style='color:#24425E;font-weight:600'>{html.escape(comment.display_name)}</span>"
            f"<span style='color:#4A5565'>：{html.escape(comment.content)}</span>"
        )

        time_label = CaptionLabel(format_relative_time(comment.created_at), self)
        time_label.setObjectName("momentCommentTimeLabel")

        layout.addWidget(text_label)
        layout.addWidget(time_label)


class AnimatedCommentSection(QWidget):
    """Comment block with ExpandSettingCard-like expansion animation."""

    comment_submitted = Signal(str)

    COLLAPSED_COUNT = 2

    def __init__(self, comments: list[MomentCommentRecord], parent=None):
        super().__init__(parent)
        self._comments = list(comments)
        self._expanded = False
        self._editor_visible = False
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

        self.toggle_button = PushButton("查看更多评论", self.surface)
        self.toggle_button.setFixedHeight(30)
        self.toggle_button.clicked.connect(self._toggle_expanded)

        self.editor_widget = QWidget(self.surface)
        self.editor_widget.setVisible(False)
        editor_layout = QHBoxLayout(self.editor_widget)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(8)

        self.comment_edit = LineEdit(self.editor_widget)
        self.comment_edit.setPlaceholderText("写下你的评论")
        self.send_button = PrimaryPushButton("发送", self.editor_widget)
        self.send_button.setFixedWidth(70)

        editor_layout.addWidget(self.comment_edit, 1)
        editor_layout.addWidget(self.send_button, 0)

        self.send_button.clicked.connect(self._submit_comment)
        self.comment_edit.returnPressed.connect(self._submit_comment)

        surface_layout.addWidget(self.preview_widget)
        surface_layout.addWidget(self.extra_widget)
        surface_layout.addWidget(self.toggle_button, 0, Qt.AlignmentFlag.AlignLeft)
        surface_layout.addWidget(self.editor_widget)
        layout.addWidget(self.surface)

        self.setObjectName("MomentCommentSection")

    def set_comments(self, comments: list[MomentCommentRecord]) -> None:
        """Replace the comment list and rebuild the section."""
        self._comments = list(comments)
        self._rebuild()

    def append_comment(self, comment: MomentCommentRecord) -> None:
        """Append a new comment and keep the current expansion state."""
        self._comments.append(comment)
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
            self.preview_layout.addWidget(MomentCommentItem(comment, self.preview_widget))

        for comment in extra:
            self.extra_layout.addWidget(MomentCommentItem(comment, self.extra_widget))

        self.toggle_button.setVisible(bool(extra))
        self._update_toggle_text()

        target_height = self._expanded_height() if self._expanded and extra else 0
        self.extra_widget.setMaximumHeight(target_height)
        self.extra_opacity.setOpacity(1.0 if self._expanded and extra else 0.0)
        self._sync_visibility()

    def _expanded_height(self) -> int:
        """Measure the fully expanded comment height."""
        hint = self.extra_layout.sizeHint().height()
        return max(0, hint)

    def _toggle_expanded(self) -> None:
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
        if not hidden_count:
            self.toggle_button.setText("")
            return
        self.toggle_button.setText("收起评论" if self._expanded else f"查看更多评论 ({hidden_count})")

    def _sync_visibility(self) -> None:
        self.setVisible(bool(self._comments) or self._editor_visible)

    def _submit_comment(self) -> None:
        text = self.comment_edit.text().strip()
        if not text:
            return
        self.comment_submitted.emit(text)
        self.comment_edit.clear()


class CreateMomentDialog(QDialog):
    """Dialog for publishing a text moment."""

    submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("发布动态")
        self.setModal(True)
        self.resize(560, 360)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        layout.addWidget(TitleLabel("发布一条动态", self))
        hint = CaptionLabel("当前版本先支持文字动态，图片入口后续再接。", self)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.editor = TextEdit(self)
        self.editor.setAcceptRichText(False)
        self.editor.setPlaceholderText("分享今天的新鲜事、想法或状态")
        self.editor.setMinimumHeight(200)
        layout.addWidget(self.editor, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)
        footer.addStretch(1)

        cancel_button = PushButton("取消", self)
        publish_button = PrimaryPushButton("发布", self)
        cancel_button.clicked.connect(self.reject)
        publish_button.clicked.connect(self._submit)
        footer.addWidget(cancel_button)
        footer.addWidget(publish_button)
        layout.addLayout(footer)

    def _submit(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text:
            InfoBar.warning("发布动态", "请输入动态内容", parent=self, duration=1800)
            return
        self.submitted.emit(text)
        self.accept()


class MomentCard(ElevatedCardWidget):
    """Single moment card in the timeline."""

    like_requested = Signal(str, bool, int)
    comment_requested = Signal(str, str)

    CONTENT_PREVIEW_LENGTH = 180

    def __init__(self, moment: MomentRecord, parent=None):
        super().__init__(parent)
        self.moment = moment
        self._content_expanded = False
        self._image_dialogs: set[QDialog] = set()
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

        self.more_button = TransparentToolButton(FluentIcon.INFO, self)
        self.more_button.setToolTip("更多")
        self.more_button.clicked.connect(self._show_more_placeholder)
        _apply_safe_button_font(self.more_button)

        header_row.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)
        header_row.addLayout(info_layout, 1)
        header_row.addWidget(self.more_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header_row)

        self.content_label = BodyLabel("", self)
        self.content_label.setObjectName("momentContentLabel")
        self.content_label.setWordWrap(True)
        layout.addWidget(self.content_label)

        self.expand_button = PushButton("全文", self)
        self.expand_button.setFixedHeight(30)
        self.expand_button.clicked.connect(self._toggle_content)
        layout.addWidget(self.expand_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.media_grid = MomentMediaGrid([], self)
        self.media_grid.image_requested.connect(self._open_image)
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

        self.comment_section = AnimatedCommentSection([], self)
        self.comment_section.comment_submitted.connect(self._submit_comment)
        layout.addWidget(self.comment_section)

    def _apply_moment(self) -> None:
        self.avatar.set_avatar(self.moment.avatar, self.moment.display_name)
        self.name_label.setText(self.moment.display_name)
        self.time_label.setText(format_relative_time(self.moment.created_at))
        self._refresh_content()
        self.layout().removeWidget(self.media_grid)
        self.media_grid.deleteLater()
        if self.moment.images:
            self.media_grid = MomentMediaGrid(self.moment.images, self)
            self.media_grid.image_requested.connect(self._open_image)
            self.layout().insertWidget(3, self.media_grid)
        else:
            self.media_grid = MomentMediaGrid([], self)
            self.media_grid.hide()
            self.layout().insertWidget(3, self.media_grid)
        self.comment_section.set_comments(self.moment.comments)
        self._refresh_actions()

    def _refresh_content(self) -> None:
        text = self.moment.content.strip() or "这条动态还没有正文。"
        is_long = len(text) > self.CONTENT_PREVIEW_LENGTH
        if is_long and not self._content_expanded:
            self.content_label.setText(text[: self.CONTENT_PREVIEW_LENGTH].rstrip() + "…")
        else:
            self.content_label.setText(text)
        self.expand_button.setVisible(is_long)
        self.expand_button.setText("收起" if self._content_expanded else "全文")

    def _refresh_actions(self) -> None:
        like_prefix = "已赞" if self.moment.is_liked else "点赞"
        self.like_button.setText(f"{like_prefix} {self.moment.like_count}" if self.moment.like_count else like_prefix)
        comment_prefix = "评论"
        self.comment_button.setText(
            f"{comment_prefix} {self.moment.comment_count}" if self.moment.comment_count else comment_prefix
        )

        if self.moment.like_count or self.moment.comment_count:
            self.stats_label.setText(f"{self.moment.like_count} 次点赞 · {self.moment.comment_count} 条评论")
        else:
            self.stats_label.setText("还没有互动，抢个沙发吧。")

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

    def _submit_comment(self, content: str) -> None:
        self.comment_requested.emit(self.moment.id, content)

    def _show_more_placeholder(self) -> None:
        InfoBar.info("朋友圈", "更多操作入口先保留 UI，后续再补。", parent=self.window(), duration=1800)

    def _open_image(self, image_path: str) -> None:
        if image_path.startswith("http://") or image_path.startswith("https://"):
            InfoBar.info("图片预览", "远程图片预览稍后补上。", parent=self.window(), duration=1800)
            return

        path = Path(image_path)
        if not path.exists():
            InfoBar.warning("图片预览", "找不到图片文件。", parent=self.window(), duration=1800)
            return

        viewer = ImageViewer(str(path), self.window())
        self._image_dialogs.add(viewer)
        viewer.finished.connect(lambda _result=0, dlg=viewer: self._image_dialogs.discard(dlg))
        viewer.show()
        viewer.raise_()
        viewer.activateWindow()


class DiscoveryInterface(QWidget):
    """Moments feed styled to match the current chat/contact Fluent UI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DiscoveryInterface")
        self._controller = get_discovery_controller()
        self._moments: list[MomentRecord] = []
        self._cards: dict[str, MomentCard] = {}
        self._load_task: Optional[asyncio.Task] = None
        self._dialog_refs: set[QDialog] = set()

        self._setup_ui()
        self._connect_signals()
        QTimer.singleShot(0, self.reload_data)

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.scroll_widget = QWidget(self.scroll_area)
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(24, 24, 24, 32)
        self.scroll_layout.setSpacing(18)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.column = QWidget(self.scroll_widget)
        self.column.setMaximumWidth(880)
        self.column_layout = QVBoxLayout(self.column)
        self.column_layout.setContentsMargins(0, 0, 0, 0)
        self.column_layout.setSpacing(16)

        self.hero_card = CardWidget(self.column)
        self.hero_card.setObjectName("DiscoveryHeroCard")
        hero_layout = QVBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(24, 24, 24, 24)
        hero_layout.setSpacing(18)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(6)
        title_stack.addWidget(TitleLabel("朋友圈", self.hero_card))
        title_stack.addWidget(CaptionLabel("分享动态、浏览近况，并在评论里继续互动。", self.hero_card))

        self.refresh_button = TransparentToolButton(FluentIcon.SYNC, self.hero_card)
        self.refresh_button.setToolTip("刷新动态")
        _apply_safe_button_font(self.refresh_button)
        self.publish_button = PrimaryPushButton("发布动态", self.hero_card)

        top_row.addLayout(title_stack, 1)
        top_row.addWidget(self.refresh_button, 0)
        top_row.addWidget(self.publish_button, 0)

        self.summary_label = BodyLabel("正在加载动态…", self.hero_card)
        self.summary_label.setObjectName("discoverySummaryLabel")
        self.summary_label.setWordWrap(True)

        hero_layout.addLayout(top_row)
        hero_layout.addWidget(self.summary_label)

        self.feed_container = QWidget(self.column)
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
        self.publish_button.clicked.connect(self._open_publish_dialog)

    def reload_data(self) -> None:
        """Refresh the feed from the backend."""
        if self._load_task and not self._load_task.done():
            self._load_task.cancel()
        self._load_task = asyncio.create_task(self._reload_data_async())

    async def _reload_data_async(self) -> None:
        self.refresh_button.setEnabled(False)
        self.summary_label.setText("正在同步朋友圈动态…")
        try:
            moments = await self._controller.load_moments()
        except asyncio.CancelledError:
            raise
        except (APIError, NetworkError) as exc:
            self.summary_label.setText("动态加载失败")
            InfoBar.error("朋友圈", str(exc), parent=self.window(), duration=2400)
            return
        except Exception:
            logger.exception("Unexpected discovery load error")
            self.summary_label.setText("动态加载失败")
            InfoBar.error("朋友圈", "加载动态时发生未知错误", parent=self.window(), duration=2400)
            return
        finally:
            self.refresh_button.setEnabled(True)

        self._moments = moments
        self.summary_label.setText(f"共 {len(self._moments)} 条动态，点击评论可直接展开输入。")
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
            self.feed_layout.addWidget(card)
            self._cards[moment.id] = card

        self.feed_layout.addStretch(1)

    def _create_empty_state(self) -> CardWidget:
        """Create an empty placeholder when the feed is blank."""
        card = CardWidget(self.feed_container)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(36, 36, 36, 36)
        layout.setSpacing(12)

        icon = IconWidget(FluentIcon.GLOBE, card)
        icon.setFixedSize(48, 48)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignCenter)

        title = SubtitleLabel("还没有任何动态", card)
        caption = CaptionLabel("发布第一条内容，或者刷新后查看最新朋友圈。", card)
        caption.setWordWrap(True)

        layout.addWidget(title, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(caption, 0, Qt.AlignmentFlag.AlignCenter)
        return card

    def _open_publish_dialog(self) -> None:
        dialog = CreateMomentDialog(self.window())
        dialog.submitted.connect(self._create_moment)
        self._dialog_refs.add(dialog)
        dialog.finished.connect(lambda _result=0, dlg=dialog: self._dialog_refs.discard(dlg))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _create_moment(self, content: str) -> None:
        asyncio.create_task(self._create_moment_async(content))

    async def _create_moment_async(self, content: str) -> None:
        self.publish_button.setEnabled(False)
        try:
            moment = await self._controller.create_moment(content)
        except (APIError, NetworkError) as exc:
            InfoBar.error("发布动态", str(exc), parent=self.window(), duration=2400)
            return
        except Exception:
            logger.exception("Unexpected moment publish error")
            InfoBar.error("发布动态", "发布失败，请稍后重试", parent=self.window(), duration=2400)
            return
        finally:
            self.publish_button.setEnabled(True)

        self._moments.insert(0, moment)
        self.summary_label.setText(f"共 {len(self._moments)} 条动态，点击评论可直接展开输入。")
        self._rebuild_feed()
        self.scroll_area.verticalScrollBar().setValue(0)
        InfoBar.success("发布动态", "动态已发布", parent=self.window(), duration=1800)

    def _request_like_toggle(self, moment_id: str, liked: bool, like_count: int) -> None:
        asyncio.create_task(self._request_like_toggle_async(moment_id, liked, like_count))

    async def _request_like_toggle_async(self, moment_id: str, liked: bool, like_count: int) -> None:
        card = self._cards.get(moment_id)
        previous_liked = not liked
        previous_count = like_count - 1 if liked else like_count + 1
        try:
            await self._controller.set_liked(moment_id, liked, like_count)
        except Exception as exc:
            if card is not None:
                card.set_like_state(previous_liked, previous_count)
            InfoBar.error("朋友圈", str(exc), parent=self.window(), duration=2200)
            return

        moment = next((item for item in self._moments if item.id == moment_id), None)
        if moment is not None:
            moment.is_liked = liked
            moment.like_count = like_count

    def _request_comment_create(self, moment_id: str, content: str) -> None:
        asyncio.create_task(self._request_comment_create_async(moment_id, content))

    async def _request_comment_create_async(self, moment_id: str, content: str) -> None:
        try:
            comment = await self._controller.add_comment(moment_id, content)
        except Exception as exc:
            InfoBar.error("发表评论", str(exc), parent=self.window(), duration=2200)
            return

        card = self._cards.get(moment_id)
        if card is not None:
            card.append_comment(comment)

        InfoBar.success("发表评论", "评论已发送", parent=self.window(), duration=1400)

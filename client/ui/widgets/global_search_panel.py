"""Reusable grouped local-search content and anchored overlay panel."""

from __future__ import annotations

from html import escape
from typing import Any

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import AvatarWidget, BodyLabel, CaptionLabel, ScrollBarHandleDisplayMode, SingleDirectionScrollArea, isDarkTheme

from client.core.avatar_rendering import apply_avatar_widget_image
from client.core.avatar_utils import profile_avatar_seed
from client.core.i18n import tr
from client.managers.search_manager import ContactSearchResult, GroupSearchResult, SearchCatalogResults, SearchResult
from client.ui.widgets.chat_info_drawer import AcrylicDrawerSurface
from client.ui.widgets.fluent_divider import FluentDivider


def _highlight_html(text: object, keyword: str) -> str:
    raw_text = str(text or "")
    escaped_text = escape(raw_text)
    normalized_keyword = str(keyword or "").strip()
    if not normalized_keyword:
        return escaped_text

    source_lower = raw_text.lower()
    keyword_lower = normalized_keyword.lower()
    parts: list[str] = []
    cursor = 0
    while True:
        position = source_lower.find(keyword_lower, cursor)
        if position == -1:
            parts.append(escape(raw_text[cursor:]))
            break
        parts.append(escape(raw_text[cursor:position]))
        match_text = escape(raw_text[position:position + len(normalized_keyword)])
        parts.append(f'<span style="color:#19a15f; font-weight:600;">{match_text}</span>')
        cursor = position + len(normalized_keyword)
    return "".join(parts)


class SearchPopupSurface(AcrylicDrawerSurface):
    """Floating search popup surface that reuses the shared acrylic renderer."""

    def __init__(self, parent=None, *, radius: int = 10) -> None:
        super().__init__(parent, extend_right_edge=False, radius=radius)
        self.setObjectName("globalSearchAcrylicSurface")
        self.set_border_object_name("globalSearchAcrylicBorder")

    def _update_acrylic_color(self) -> None:
        """Match Fluent AcrylicFlyout tint values exactly."""
        if isDarkTheme():
            self._acrylic_brush.tintColor = QColor(32, 32, 32, 200)
            self._acrylic_brush.luminosityColor = QColor(0, 0, 0, 0)
        else:
            self._acrylic_brush.tintColor = QColor(255, 255, 255, 180)
            self._acrylic_brush.luminosityColor = QColor(255, 255, 255, 0)


class SearchResultCard(QWidget):
    """Compact clickable row used by the shared search overlay."""

    activated = Signal(object)

    def __init__(
        self,
        *,
        payload: dict[str, Any],
        title: str,
        subtitle: str = "",
        meta: str = "",
        keyword: str = "",
        avatar: str = "",
        seed: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._payload = dict(payload or {})
        self._hovered = False
        self.setObjectName("globalSearchResultCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedHeight(80)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        self.avatar = AvatarWidget(self)
        self.avatar.setRadius(22)
        self.avatar.setFixedSize(44, 44)
        apply_avatar_widget_image(self.avatar, avatar, seed=seed)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        self.title_label = BodyLabel(self)
        self.title_label.setObjectName("globalSearchResultTitle")
        self.title_label.setTextFormat(Qt.TextFormat.RichText)
        self.title_label.setText(_highlight_html(title, keyword))
        self.title_label.setWordWrap(False)

        self.subtitle_label = CaptionLabel(self)
        self.subtitle_label.setObjectName("globalSearchResultSubtitle")
        self.subtitle_label.setTextFormat(Qt.TextFormat.RichText)
        self.subtitle_label.setText(_highlight_html(subtitle, keyword))
        self.subtitle_label.setVisible(bool(subtitle))
        self.subtitle_label.setWordWrap(False)

        self.meta_label = CaptionLabel(meta, self)
        self.meta_label.setObjectName("globalSearchResultMeta")
        self.meta_label.setVisible(bool(meta))
        self.meta_label.setWordWrap(False)

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)
        text_layout.addWidget(self.meta_label)

        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text_layout, 1)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(dict(self._payload))
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        if self._hovered:
            rect = self.rect()
            fill = QColor(255, 255, 255, 24) if isDarkTheme() else QColor(0, 0, 0, 10)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setBrush(fill)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.fillRect(rect, fill)
        super().paintEvent(event)


class SearchSectionLinkRow(QWidget):
    """Full-width expand/collapse row that matches result-item hover."""

    activated = Signal()

    def __init__(self, *, text: str, parent=None) -> None:
        super().__init__(parent)
        self._hovered = False
        self.setObjectName("globalSearchSectionLinkRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(FluentDivider.DEFAULT_INSET, 0, FluentDivider.DEFAULT_INSET, 0)
        layout.setSpacing(0)

        self.label = BodyLabel(text, self)
        self.label.setObjectName("globalSearchSectionLinkLabel")
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)

    def set_text(self, text: str) -> None:
        self.label.setText(str(text or ""))

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        if self._hovered:
            fill = QColor(255, 255, 255, 24) if isDarkTheme() else QColor(0, 0, 0, 10)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.fillRect(self.rect(), fill)
        super().paintEvent(event)


class GlobalSearchResultsPanel(QWidget):
    """Grouped local-search content shared by chat and contact flyouts."""

    resultActivated = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("globalSearchPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._keyword = ""
        self._results = SearchCatalogResults(messages=[], contacts=[], groups=[])
        self._expanded_sections: set[str] = set()
        self._section_item_limit = 1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.state_label = CaptionLabel(tr("search.state.idle", "输入关键词搜索"), self)
        self.state_label.setObjectName("globalSearchStateLabel")
        self.state_label.setContentsMargins(FluentDivider.DEFAULT_INSET, 16, FluentDivider.DEFAULT_INSET, 16)
        self.state_label.setWordWrap(True)

        self.scroll_area = SingleDirectionScrollArea(self, orient=Qt.Orientation.Vertical)
        self.scroll_area.setObjectName("globalSearchScrollArea")
        self.scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.scroll_area.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.scroll_area.setStyleSheet("QScrollArea{background: transparent; border: none;} QAbstractScrollArea{background: transparent; border: none;}")
        self.scroll_area.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.scroll_area.viewport().setAutoFillBackground(False)
        self.scroll_area.viewport().setStyleSheet("background: transparent; border: none;")

        self.scroll_widget = QWidget(self.scroll_area)
        self.scroll_widget.setObjectName("globalSearchScrollWidget")
        self.scroll_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.scroll_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.scroll_widget.setAutoFillBackground(False)
        self.scroll_widget.setStyleSheet("background: transparent; border: none;")
        self.results_layout = QVBoxLayout(self.scroll_widget)
        self.results_layout.setContentsMargins(0, 8, 0, 12)
        self.results_layout.setSpacing(0)
        self.results_layout.addStretch(1)
        self.scroll_area.setWidget(self.scroll_widget)
        self.scroll_area.enableTransparentBackground()
        self.scroll_area.installEventFilter(self)
        self.scroll_area.viewport().installEventFilter(self)
        if hasattr(self.scroll_area, "vScrollBar"):
            self.scroll_area.vScrollBar.setHandleDisplayMode(ScrollBarHandleDisplayMode.ALWAYS)
            self.scroll_area.vScrollBar.setForceHidden(True)
            self.scroll_area.vScrollBar.installEventFilter(self)
        self.scroll_area.hide()

        layout.addWidget(self.state_label)
        layout.addWidget(self.scroll_area, 1)

    def set_loading(self, keyword: str) -> None:
        self._keyword = str(keyword or "").strip()
        self.state_label.setText(tr("search.state.loading", "搜索中..."))
        self.state_label.show()
        self.scroll_area.hide()

    def set_results(self, keyword: str, results: SearchCatalogResults) -> None:
        normalized_keyword = str(keyword or "").strip()
        if normalized_keyword != self._keyword:
            self._expanded_sections.clear()
        self._keyword = normalized_keyword
        self._results = results
        self._rebuild_sections()

    def clear_results(self) -> None:
        self._keyword = ""
        self._results = SearchCatalogResults(messages=[], contacts=[], groups=[])
        self._expanded_sections.clear()
        self.state_label.setText(tr("search.state.idle", "输入关键词搜索"))
        self.state_label.show()
        self.scroll_area.hide()
        self._clear_layout()

    def set_panel_height(self, height: int) -> None:
        """Keep the visible results viewport aligned with the popup height."""
        target_height = max(0, int(height or 0))
        self.setFixedHeight(target_height)
        self.updateGeometry()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in {
            self.scroll_area,
            self.scroll_area.viewport(),
            getattr(self.scroll_area, "vScrollBar", None),
        }:
            if event.type() == QEvent.Type.Enter:
                self._set_scrollbar_visible(True)
            elif event.type() == QEvent.Type.Leave:
                QTimer.singleShot(0, self._sync_scrollbar_visibility)
        return super().eventFilter(watched, event)

    def _rebuild_sections(self) -> None:
        self._clear_layout()
        total_count = len(self._results.contacts) + len(self._results.groups) + len(self._results.messages)
        if total_count <= 0:
            self.state_label.setText(tr("search.state.empty", "暂无搜索结果"))
            self.state_label.show()
            self.scroll_area.hide()
            return

        self.state_label.hide()
        self.scroll_area.show()
        self._add_contact_section()
        self._add_group_section()
        self._add_message_section()
        self.results_layout.addStretch(1)

    def _add_contact_section(self) -> None:
        if self._results.contacts:
            self._add_section(
                "contacts",
                tr("search.section.contacts", "联系人"),
                self._results.contacts,
                self._results.contact_total,
                self._build_contact_card,
            )

    def _add_group_section(self) -> None:
        if self._results.groups:
            self._add_section(
                "groups",
                tr("search.section.groups", "群聊"),
                self._results.groups,
                self._results.group_total,
                self._build_group_card,
            )

    def _add_message_section(self) -> None:
        if self._results.messages:
            self._add_section(
                "messages",
                tr("search.section.messages", "聊天记录"),
                self._results.messages,
                self._results.message_total,
                self._build_message_card,
            )

    def _add_section(self, section_key: str, title: str, items: list[Any], total_count: int, builder) -> None:
        header = QWidget(self.scroll_widget)
        header.setObjectName("globalSearchSectionHeader")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        header.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 8, 0, 4)
        header_layout.setSpacing(8)

        title_row = QWidget(header)
        title_row.setObjectName("globalSearchSectionTitleRow")
        title_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        title_row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        title_row_layout = QHBoxLayout(title_row)
        title_row_layout.setContentsMargins(FluentDivider.DEFAULT_INSET, 0, 0, 0)
        title_row_layout.setSpacing(0)

        title_label = CaptionLabel(title, title_row)
        title_label.setObjectName("globalSearchSectionTitle")
        title_row_layout.addWidget(title_label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        title_row_layout.addStretch(1)

        divider = FluentDivider(header)
        divider.setObjectName("globalSearchSectionDivider")

        header_layout.addWidget(title_row)
        header_layout.addWidget(divider)
        self.results_layout.addWidget(header)

        visible_items = items if section_key in self._expanded_sections else items[:self._section_item_limit]
        for item in visible_items:
            card = builder(item)
            card.activated.connect(self.resultActivated.emit)
            self.results_layout.addWidget(card)

        if total_count > self._section_item_limit:
            link_button = SearchSectionLinkRow(parent=self.scroll_widget, text="")
            if section_key in self._expanded_sections:
                link_button.set_text(tr("search.section.collapse", "收起"))
            else:
                link_button.set_text(tr("search.section.more", "查看更多({count})", count=total_count))
            link_button.activated.connect(lambda key=section_key: self._toggle_section(key))
            self.results_layout.addWidget(link_button)

    def _build_contact_card(self, result: ContactSearchResult) -> SearchResultCard:
        contact = dict(result.contact or {})
        title = str(contact.get("display_name") or contact.get("name") or contact.get("nickname") or "")
        subtitle = self._contact_subtitle(result)
        payload = {"type": "contact", "data": contact}
        return SearchResultCard(
            payload=payload,
            title=title,
            subtitle=subtitle,
            keyword=self._keyword,
            avatar=str(contact.get("avatar") or ""),
            seed=profile_avatar_seed(
                user_id=contact.get("id", ""),
                username=contact.get("username", ""),
                display_name=title,
            ),
            parent=self.scroll_widget,
        )

    def _build_group_card(self, result: GroupSearchResult) -> SearchResultCard:
        group = dict(result.group or {})
        member_count = int(group.get("member_count", 0) or 0)
        subtitle = (
            result.matched_text
            if result.matched_field in {"member", "name"}
            else tr("search.group.member_summary", "{count} 位成员", count=member_count)
        )
        payload = {"type": "group", "data": group}
        return SearchResultCard(
            payload=payload,
            title=str(group.get("name") or tr("session.unnamed", "Untitled Session")),
            subtitle=subtitle,
            keyword=self._keyword,
            avatar=str(group.get("avatar") or ""),
            seed=profile_avatar_seed(
                user_id=group.get("session_id") or group.get("id", ""),
                display_name=group.get("name", ""),
            ),
            parent=self.scroll_widget,
        )

    def _build_message_card(self, result: SearchResult) -> SearchResultCard:
        title = result.session_name or tr("session.unnamed", "Untitled Session")
        payload = {
            "type": "message",
            "data": {
                "session_id": result.message.session_id,
                "message_id": result.message.message_id,
                "session_name": result.session_name,
                "session_type": result.session_type,
            },
        }
        return SearchResultCard(
            payload=payload,
            title=title,
            subtitle=result.matched_text,
            meta=tr("search.message.total", "共 {count} 条相关记录", count=result.match_count),
            keyword=self._keyword,
            avatar=result.session_avatar,
            seed=profile_avatar_seed(
                user_id=result.message.session_id,
                display_name=title,
            ),
            parent=self.scroll_widget,
        )

    @staticmethod
    def _contact_subtitle(result: ContactSearchResult) -> str:
        contact = dict(result.contact or {})
        if result.matched_field == "assistim_id":
            return tr("search.contact.assistim_id", "AssistIM 号：{value}", value=result.matched_text)
        if result.matched_field == "region":
            return tr("search.contact.region", "地区：{value}", value=result.matched_text)
        if result.matched_field == "remark":
            return tr("search.contact.remark", "备注：{value}", value=result.matched_text)
        return result.matched_text or str(contact.get("assistim_id") or contact.get("region") or "")

    def _toggle_section(self, section_key: str) -> None:
        """Expand or collapse one grouped search section."""
        if section_key in self._expanded_sections:
            self._expanded_sections.discard(section_key)
        else:
            self._expanded_sections.add(section_key)
        self._rebuild_sections()

    def _set_scrollbar_visible(self, visible: bool) -> None:
        bar = getattr(self.scroll_area, "vScrollBar", None)
        if bar is None:
            return
        bar.setForceHidden(not visible)

    def _sync_scrollbar_visibility(self) -> None:
        bar = getattr(self.scroll_area, "vScrollBar", None)
        if bar is None:
            return
        hovered = (
            self.scroll_area.underMouse()
            or self.scroll_area.viewport().underMouse()
            or bar.underMouse()
        )
        bar.setForceHidden(not hovered)

    def _clear_layout(self) -> None:
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


class GlobalSearchPopupOverlay(QWidget):
    """Anchored overlay that reuses the chat-info acrylic surface."""

    resultActivated = Signal(object)
    closed = Signal()

    MIN_WIDTH = 360
    MAX_WIDTH = 520
    EDGE_MARGIN = 12
    ANCHOR_GAP = 8

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("globalSearchOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.hide()

        self._anchor: QWidget | None = None
        self._content_width = self.MIN_WIDTH
        self._last_surface_rect: QRect | None = None
        self._capture_timer = QTimer(self)
        self._capture_timer.setSingleShot(True)
        self._capture_timer.setInterval(120)
        self._capture_timer.timeout.connect(self._capture_current_backdrop)
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(120)
        self._geometry_timer.timeout.connect(self._refresh_after_geometry_change)

        self.surface = SearchPopupSurface(self, radius=10)
        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(0, 0, 0, 0)
        surface_layout.setSpacing(0)

        self.results_panel = GlobalSearchResultsPanel(self.surface)
        self.results_panel.resultActivated.connect(self.resultActivated.emit)
        surface_layout.addWidget(self.results_panel, 1)

        if parent is not None:
            parent.installEventFilter(self)

    def bind_anchor(self, anchor: QWidget) -> None:
        """Track the search box this overlay should stay attached to."""
        if self._anchor is anchor:
            return
        if self._anchor is not None:
            self._anchor.removeEventFilter(self)
        self._anchor = anchor
        if self._anchor is not None:
            self._anchor.installEventFilter(self)

    def set_loading(self, keyword: str) -> None:
        self.results_panel.set_loading(keyword)

    def set_results(self, keyword: str, results: SearchCatalogResults) -> None:
        self.results_panel.set_results(keyword, results)

    def clear_results(self) -> None:
        self.results_panel.clear_results()

    def set_content_width(self, width: int) -> None:
        normalized_width = max(self.MIN_WIDTH, min(self.MAX_WIDTH, int(width or 0)))
        if normalized_width == self._content_width:
            return
        self._content_width = normalized_width
        if self.isVisible():
            self._sync_geometry(force_capture=False)

    def show_for(self, anchor: QWidget) -> None:
        """Display the overlay and anchor it to the provided search widget."""
        self.bind_anchor(anchor)
        host = self.parentWidget()
        if host is None or self._anchor is None:
            return
        became_visible = not self.isVisible()
        self.setGeometry(host.rect())
        panel_rect = self._calculate_panel_rect(host)
        if panel_rect is None:
            return
        self._apply_panel_geometry(host, panel_rect, capture=became_visible)
        self.surface.show()
        self.show()
        self.raise_()

    def close_overlay(self) -> None:
        """Hide the overlay and notify listeners once it is fully closed."""
        if not self.isVisible():
            self._emit_closed()
            return
        self._capture_timer.stop()
        self._geometry_timer.stop()
        self.hide()
        self._last_surface_rect = None
        self._emit_closed()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[name-defined]
        parent = self.parentWidget()
        if watched is parent and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Move,
        }:
            if self.isVisible():
                self.close_overlay()
        elif watched is self._anchor and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Move,
        }:
            if self.isVisible():
                self._sync_geometry(force_capture=False)
        elif watched in {parent, self._anchor} and event.type() == QEvent.Type.Show:
            if self.isVisible():
                self.surface.show()
                self._sync_geometry(force_capture=True)
        elif watched in {parent, self._anchor} and event.type() == QEvent.Type.Hide:
            if self.isVisible():
                self.close_overlay()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.surface.geometry().contains(event.position().toPoint()):
            self.close_overlay()
            event.accept()
            return
        super().mousePressEvent(event)

    def _sync_geometry(self, *, force_capture: bool = False) -> None:
        host = self.parentWidget()
        if host is None or self._anchor is None:
            return

        self.setGeometry(host.rect())
        panel_rect = self._calculate_panel_rect(host)
        if panel_rect is None:
            return
        self._apply_panel_geometry(host, panel_rect, capture=force_capture or self._last_surface_rect != panel_rect)

    def _calculate_panel_rect(self, host: QWidget) -> QRect | None:
        if self._anchor is None:
            return None

        anchor_top_left = self._anchor.mapTo(host, QPoint(0, 0))
        anchor_rect = QRect(anchor_top_left, self._anchor.size())
        panel_width = self._content_width
        panel_y = max(self.EDGE_MARGIN, anchor_rect.bottom() + self.ANCHOR_GAP)
        available_below = max(140, host.height() - panel_y - self.EDGE_MARGIN)
        desired_height = max(220, host.height() - 56)
        panel_height = min(desired_height, available_below)
        max_x = max(self.EDGE_MARGIN, host.width() - panel_width - self.EDGE_MARGIN)
        panel_x = min(max(self.EDGE_MARGIN, anchor_rect.left()), max_x)
        return QRect(panel_x, panel_y, panel_width, panel_height)

    def _apply_panel_geometry(self, host: QWidget, panel_rect: QRect, *, capture: bool) -> None:
        self.surface.setGeometry(panel_rect)
        self.results_panel.setFixedWidth(panel_rect.width())
        self.results_panel.set_panel_height(panel_rect.height())
        layout = self.surface.layout()
        if layout is not None:
            layout.activate()
        if capture:
            self.surface.capture_backdrop(QRect(host.mapToGlobal(panel_rect.topLeft()), panel_rect.size()))
            self._last_surface_rect = QRect(panel_rect)

    def _schedule_backdrop_capture(self) -> None:
        if self.isVisible():
            self._capture_timer.start()

    def _refresh_after_geometry_change(self) -> None:
        if not self.isVisible():
            return
        self.surface.show()
        self.raise_()
        self._sync_geometry(force_capture=True)

    def _capture_current_backdrop(self) -> None:
        if not self.isVisible():
            return
        host = self.parentWidget()
        if host is None:
            return
        panel_rect = self.surface.geometry()
        if not panel_rect.isValid() or panel_rect.isEmpty():
            return
        self.surface.capture_backdrop(QRect(host.mapToGlobal(panel_rect.topLeft()), panel_rect.size()))
        self._last_surface_rect = QRect(panel_rect)

    def _emit_closed(self) -> None:
        self.closed.emit()

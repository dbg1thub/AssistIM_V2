import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from qfluentwidgets import Theme

from client.core.app_icons import CollectionIcon
from client.ui.styles import StyleSheet
from client.ui.widgets.toggle_badge import ToggleBadge


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _rgb_distance(left, right) -> int:
    return sum(abs(left[index] - right[index]) for index in range(3))


def _render_badge(*, show_border: bool = True):
    app = _ensure_app()
    root = QWidget()
    root.setStyleSheet(StyleSheet.DISCOVERY_INTERFACE.content(Theme.LIGHT))
    layout = QVBoxLayout(root)
    layout.setContentsMargins(20, 20, 20, 20)
    badge = ToggleBadge("赞", icon=CollectionIcon("thumb_like"), parent=root, show_border=show_border)
    layout.addWidget(badge)
    root.resize(120, 60)
    root.show()
    app.processEvents()
    return badge.grab().toImage()


def test_toggle_badge_border_is_visibly_painted_when_enabled() -> None:
    image = _render_badge(show_border=True)
    center_color = image.pixelColor(image.width() // 2, image.height() // 2).getRgb()
    edge_color = image.pixelColor(image.width() - 1, image.height() // 2).getRgb()

    assert _rgb_distance(center_color, edge_color) >= 60


def test_toggle_badge_border_can_be_hidden() -> None:
    image = _render_badge(show_border=False)
    center_color = image.pixelColor(image.width() // 2, image.height() // 2).getRgb()
    edge_color = image.pixelColor(image.width() - 1, image.height() // 2).getRgb()

    assert _rgb_distance(center_color, edge_color) < 60

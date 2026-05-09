import os


def test_scaled_avatar_pixmap_uses_physical_pixels_for_high_dpi() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QPixmap
    from PySide6.QtWidgets import QApplication

    from client.core.avatar_rendering import scaled_avatar_pixmap_for_device

    QApplication.instance() or QApplication([])
    source = QPixmap(120, 80)
    source.fill(QColor("#07c160"))

    scaled = scaled_avatar_pixmap_for_device(source, QSize(36, 36), 1.5)

    assert scaled.width() == 54
    assert scaled.height() == 54
    assert scaled.devicePixelRatioF() == 1.5
    assert scaled.deviceIndependentSize().toSize() == QSize(36, 36)


def test_scaled_avatar_pixmap_keeps_one_to_one_size_without_high_dpi() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QPixmap
    from PySide6.QtWidgets import QApplication

    from client.core.avatar_rendering import scaled_avatar_pixmap_for_device

    QApplication.instance() or QApplication([])
    source = QPixmap(120, 80)
    source.fill(QColor("#07c160"))

    scaled = scaled_avatar_pixmap_for_device(source, QSize(36, 36), 1.0)

    assert scaled.width() == 36
    assert scaled.height() == 36
    assert scaled.devicePixelRatioF() == 1.0

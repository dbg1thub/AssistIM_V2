"""Smoke tests for MessageDelegate font / theme caches.

These tests do not measure timing; they assert that the cache fields exist and
that hot-path callers reuse the same QFont / QFontMetrics instances. The
caches were introduced to keep per-row paint cheap — if a future change starts
constructing fonts inside paint or sizeHint again, these tests should fail.
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QApplication

from client.delegates.message_delegate import MessageDelegate


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_delegate_caches_text_font_and_metrics() -> None:
    _ensure_app()
    delegate = MessageDelegate()

    text_font = delegate._cached_text_font  # noqa: SLF001
    text_metrics = delegate._cached_text_metrics  # noqa: SLF001

    assert isinstance(text_font, QFont)
    assert isinstance(text_metrics, QFontMetrics)
    # Hot-path accessors must return the cached instance, not rebuild.
    assert delegate._time_block_font() is delegate._cached_time_block_font  # noqa: SLF001
    assert delegate._status_count_font() is delegate._cached_status_count_font  # noqa: SLF001
    assert delegate._group_sender_label_font() is delegate._cached_group_sender_label_font  # noqa: SLF001


def test_delegate_caches_secondary_paint_fonts() -> None:
    _ensure_app()
    delegate = MessageDelegate()

    # All secondary fonts must be present so paint() never rebuilds them.
    for attr in (
        "_cached_recall_notice_font",
        "_cached_recall_notice_action_font",
        "_cached_voice_duration_font",
        "_cached_video_duration_font",
        "_cached_media_state_font",
        "_cached_avatar_initial_font",
    ):
        assert isinstance(getattr(delegate, attr), QFont), attr


def test_delegate_caches_dark_theme_flag() -> None:
    _ensure_app()
    delegate = MessageDelegate()

    assert isinstance(delegate._is_dark, bool)  # noqa: SLF001

    # Manually flip the cache and trigger the theme handler — it should mirror
    # ``isDarkTheme()`` from qfluentwidgets.
    delegate._is_dark = not delegate._is_dark  # noqa: SLF001
    delegate._on_theme_changed()  # noqa: SLF001

    from qfluentwidgets import isDarkTheme

    assert delegate._is_dark == bool(isDarkTheme())  # noqa: SLF001


def test_delegate_metrics_match_font_pixel_sizes() -> None:
    _ensure_app()
    delegate = MessageDelegate()

    # Time separator font: 11px height should be reflected through the
    # cached QFontMetrics.
    assert delegate._cached_time_block_metrics.height() > 0  # noqa: SLF001
    # Group sender label uses the constant we expose on the class.
    expected_pixel_size = MessageDelegate.GROUP_SENDER_LABEL_FONT_PIXEL_SIZE
    assert delegate._cached_group_sender_label_font.pixelSize() == expected_pixel_size  # noqa: SLF001

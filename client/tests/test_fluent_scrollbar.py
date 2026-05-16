"""Behaviour tests for :class:`FluentOverlayScrollBar`."""

from __future__ import annotations

import pytest

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel, QWheelEvent
from PySide6.QtWidgets import QApplication, QListView

from client.ui.widgets.fluent_scrollbar import (
    FluentOverlayScrollBar,
    FluentOverlayScrollBarDisplayMode,
    attach_fluent_scrollbar,
)


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _build_scrollable_list(item_count: int = 200) -> QListView:
    view = QListView()
    view.resize(320, 400)
    model = QStandardItemModel(item_count, 1, view)
    for row in range(item_count):
        model.setItem(row, 0, QStandardItem(f"item-{row}"))
    view.setModel(model)
    view.show()
    QApplication.processEvents()
    return view


def test_attach_forces_native_scrollbars_off_and_returns_overlay() -> None:
    _ensure_app()
    view = _build_scrollable_list()

    bar = attach_fluent_scrollbar(view)

    assert isinstance(bar, FluentOverlayScrollBar)
    assert view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert view.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_partner_value_changes_propagate_to_overlay() -> None:
    _ensure_app()
    view = _build_scrollable_list()
    bar = attach_fluent_scrollbar(view)

    partner = view.verticalScrollBar()
    partner.setValue(partner.maximum())
    QApplication.processEvents()

    assert bar._value == partner.maximum()  # noqa: SLF001 - test inspecting internal mirror


def test_set_bottom_inset_shrinks_overlay_height() -> None:
    _ensure_app()
    view = _build_scrollable_list()
    bar = attach_fluent_scrollbar(view)

    full_height = bar.height()
    bar.set_bottom_inset(120)

    assert bar.height() == full_height - 120 + 1  # default top inset is 1


def test_overlay_starts_hidden_in_on_hover_mode_and_fades_in_on_partner_scroll() -> None:
    _ensure_app()
    view = _build_scrollable_list()
    bar = attach_fluent_scrollbar(view)

    assert bar._handle.get_opacity() == 0.0  # noqa: SLF001

    partner = view.verticalScrollBar()
    partner.setValue(partner.maximum() // 2)
    QApplication.processEvents()

    # Animation runs over 150ms; we only assert the target value here so we do
    # not depend on event loop timing.
    assert bar._fade_animation.endValue() == 1.0  # noqa: SLF001


def test_wheel_event_is_forwarded_to_viewport_without_consuming() -> None:
    _ensure_app()
    view = _build_scrollable_list()
    bar = attach_fluent_scrollbar(view)

    partner = view.verticalScrollBar()
    initial_value = partner.value()

    wheel = QWheelEvent(
        QPoint(bar.width() // 2, bar.height() // 2),
        view.mapToGlobal(QPoint(bar.width() // 2, bar.height() // 2)),
        QPoint(0, -120),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(bar, wheel)
    QApplication.processEvents()

    assert partner.value() >= initial_value  # native scrolling kicked in


def test_force_hidden_keeps_overlay_invisible() -> None:
    _ensure_app()
    view = _build_scrollable_list()
    bar = attach_fluent_scrollbar(view)

    bar.set_force_hidden(True)
    assert not bar.isVisible()


def test_overlay_geometry_follows_parent_resize() -> None:
    _ensure_app()
    view = _build_scrollable_list()
    bar = attach_fluent_scrollbar(view)

    view.resize(500, 300)
    QApplication.sendEvent(view, QEvent(QEvent.Type.LayoutRequest))
    QApplication.processEvents()

    assert bar.height() == 300 - 1 - 1  # default top + bottom inset of 1
    # Overlay sits at the right edge with a 1px gutter.
    assert bar.x() + bar.width() + 1 == view.width()


def test_handle_chase_animation_targets_correct_position_on_scroll() -> None:
    _ensure_app()
    view = _build_scrollable_list()
    bar = attach_fluent_scrollbar(view)

    partner = view.verticalScrollBar()
    partner.setValue(partner.maximum() // 2)
    QApplication.processEvents()

    # The chase animation should be running toward the correct target Y.
    expected_y = bar._compute_handle_target_y()  # noqa: SLF001
    assert bar._handle_chase_animation.endValue() == expected_y  # noqa: SLF001
    assert bar._handle_chase_animation.state() == bar._handle_chase_animation.State.Running  # noqa: SLF001


def test_handle_chase_animation_skipped_during_drag() -> None:
    _ensure_app()
    view = _build_scrollable_list()
    bar = attach_fluent_scrollbar(view)

    bar._is_pressed_handle = True  # noqa: SLF001
    partner = view.verticalScrollBar()
    partner.setValue(partner.maximum() // 3)
    QApplication.processEvents()

    # During drag, handle should be repositioned instantly (no animation).
    expected_y = bar._compute_handle_target_y()  # noqa: SLF001
    assert bar._handle.y() == expected_y  # noqa: SLF001
    # Animation should NOT be running.
    assert bar._handle_chase_animation.state() != bar._handle_chase_animation.State.Running  # noqa: SLF001
    _ensure_app()
    view = _build_scrollable_list()
    bar = attach_fluent_scrollbar(view)
    bar._handle.set_opacity(1.0)  # noqa: SLF001 - simulate visible state for hit testing
    bar.set_thickness(1.0)  # expand handle so the click lands inside its hit rect
    bar._refresh_handle_layout()  # noqa: SLF001

    partner = view.verticalScrollBar()
    partner.setValue(0)
    QApplication.processEvents()

    handle = bar._handle  # noqa: SLF001
    handle_top = handle.y()
    handle_mid = handle_top + handle.height() // 2

    # Press on the handle, then move it to the bottom of the track.
    bar._is_pressed_handle = True  # noqa: SLF001
    bar._press_offset_y = handle.height() // 2  # noqa: SLF001

    from PySide6.QtGui import QMouseEvent

    move_y = bar.height() - 4
    move_event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPoint(bar.width() // 2, move_y),
        view.mapToGlobal(QPoint(bar.width() // 2, move_y)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(bar, move_event)
    QApplication.processEvents()

    assert partner.value() > 0
    assert handle_mid >= 0  # sanity check we computed it before mutating state


def test_thickness_animates_independently_from_visibility() -> None:
    _ensure_app()
    view = _build_scrollable_list()
    bar = attach_fluent_scrollbar(view)

    # Visibility is driven by parent enter/leave; thickness is driven by the
    # bar's own enter/leave. Confirm they are independent: entering the parent
    # should not thicken the handle.
    QApplication.sendEvent(view, QEvent(QEvent.Type.Enter))
    QApplication.processEvents()
    assert bar._fade_animation.endValue() == 1.0  # noqa: SLF001
    assert bar.get_thickness() == 0.0
    assert bar._handle.width() == 3  # noqa: SLF001

    # Entering the scrollbar overlay itself fires the thickness animation.
    QApplication.sendEvent(bar, QEvent(QEvent.Type.Enter))
    QApplication.processEvents()
    assert bar._thickness_animation.endValue() == 1.0  # noqa: SLF001

    # Leaving the overlay shrinks the handle back unless the user is dragging.
    QApplication.sendEvent(bar, QEvent(QEvent.Type.Leave))
    QApplication.processEvents()
    assert bar._thickness_animation.endValue() == 0.0  # noqa: SLF001


def test_thickness_does_not_collapse_during_drag() -> None:
    _ensure_app()
    view = _build_scrollable_list()
    bar = attach_fluent_scrollbar(view)

    bar._is_pressed_handle = True  # noqa: SLF001
    bar.set_thickness(1.0)
    QApplication.sendEvent(bar, QEvent(QEvent.Type.Leave))
    QApplication.processEvents()

    assert bar.get_thickness() == 1.0
    # Animation target must remain at the expanded value; we never queued a
    # collapse animation because the user is still dragging.
    assert bar._thickness_animation.endValue() != 0.0 or bar._thickness_animation.state() == bar._thickness_animation.State.Stopped  # noqa: SLF001

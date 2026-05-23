"""Animated stacked widget helpers."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QParallelAnimationGroup, QPropertyAnimation
from PySide6.QtWidgets import QStackedWidget, QWidget


class AnimatedStackWidget(QStackedWidget):
    """QStackedWidget with a horizontal slide transition."""

    def __init__(self, parent=None, *, duration_ms: int = 280):
        super().__init__(parent)
        self._duration_ms = int(duration_ms)
        self._transition_group: QParallelAnimationGroup | None = None
        self._transition_active = False

    def slide_to_widget(self, target: QWidget, *, direction: str = "right") -> None:
        current = self.currentWidget()
        if current is target or target is None:
            return
        if self.indexOf(target) < 0:
            self.addWidget(target)

        stack_size = self.size()
        if current is None or stack_size.width() <= 0 or stack_size.height() <= 0:
            self.setCurrentWidget(target)
            return

        if self._transition_group is not None:
            self._transition_group.stop()
            self._transition_group.deleteLater()

        self._transition_active = True
        width = stack_size.width()
        target_start = QPoint(-width, 0) if direction == "right" else QPoint(width, 0)
        current_end = QPoint(width, 0) if direction == "right" else QPoint(-width, 0)

        current.setGeometry(0, 0, stack_size.width(), stack_size.height())
        target.setGeometry(0, 0, stack_size.width(), stack_size.height())
        target.move(target_start)
        target.show()
        target.raise_()

        current_animation = QPropertyAnimation(current, b"pos", self)
        current_animation.setDuration(self._duration_ms)
        current_animation.setStartValue(QPoint(0, 0))
        current_animation.setEndValue(current_end)
        current_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        target_animation = QPropertyAnimation(target, b"pos", self)
        target_animation.setDuration(self._duration_ms)
        target_animation.setStartValue(target_start)
        target_animation.setEndValue(QPoint(0, 0))
        target_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(current_animation)
        group.addAnimation(target_animation)

        def finish_transition() -> None:
            self.setCurrentWidget(target)
            current.move(0, 0)
            target.move(0, 0)
            self._transition_active = False
            if self._transition_group is group:
                self._transition_group = None
            group.deleteLater()

        group.finished.connect(finish_transition)
        self._transition_group = group
        group.start()

    def is_transition_active(self) -> bool:
        return self._transition_active

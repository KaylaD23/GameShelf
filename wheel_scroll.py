"""Predictable mouse-wheel motion for the library, sidebar and details area.

Standard mouse wheels get a short eased step. Precision touchpads retain their
native pixel movement, avoiding lag or fighting the device's own inertia.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QEvent, QPropertyAnimation, QEasingCurve, Qt

from scroll_math import DURATION_MS, wheel_delta, queued_scroll_target


class SmoothWheelFilter(QObject):
    """Single animation per scroll area; cancel/retarget during wheel bursts."""

    def __init__(self, area):
        super().__init__(area)
        self.area = area
        self.bar = area.verticalScrollBar()
        self.bar.setSingleStep(32)
        self.target = None
        self.remainder = 0.0
        self.animation = QPropertyAnimation(self.bar, b'value', self)
        self.animation.setDuration(DURATION_MS)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._finished)
        self.bar.rangeChanged.connect(self._range_changed)
        area.viewport().installEventFilter(self)

    def _finished(self):
        self.target = None

    def _range_changed(self, _minimum, _maximum):
        # A newly filtered game list or resized window must not inherit the
        # last wheel animation's target from the previous scroll range.
        self.cancel()

    def cancel(self):
        self.animation.stop()
        self.target = None
        self.remainder = 0.0

    def eventFilter(self, watched, event):
        if watched is not self.area.viewport() or event.type() != QEvent.Type.Wheel:
            return False
        # Don't hijack Ctrl+wheel conventions or horizontal gesture scrolling.
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return False
        pixels = event.pixelDelta().y()
        angles = event.angleDelta().y()
        if not pixels and not angles:
            return False
        if self.bar.maximum() <= self.bar.minimum():
            return False

        if pixels:
            # Native touchpads already issue smooth pixel deltas. In particular,
            # don't animate every touchpad tick and queue unwanted momentum.
            self.cancel()
            self.bar.setValue(self.bar.value() - pixels)
        else:
            self.remainder += wheel_delta(angles)
            step = int(self.remainder)
            self.remainder -= step
            if step:
                current = self.bar.value()
                goal = queued_scroll_target(current, self.target, -step,
                                            self.bar.maximum())
                if goal != current:
                    self.animation.stop()
                    self.target = goal
                    self.animation.setStartValue(current)
                    self.animation.setEndValue(goal)
                    self.animation.start()
        event.accept()
        return True


def enable_smooth_wheel(area):
    """Attach to QAbstractScrollArea/QListView without replacing keyboard input."""
    controller = getattr(area, '_gameshelf_wheel_filter', None)
    if controller is None:
        controller = SmoothWheelFilter(area)
        area._gameshelf_wheel_filter = controller
    return controller

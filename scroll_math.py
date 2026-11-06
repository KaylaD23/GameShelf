"""Pure calculations for GameShelf's mouse-wheel behaviour.

Kept free of GUI imports so the exact motion limits can be regression-tested.
"""

from __future__ import annotations

# A conventional wheel notch used to scroll much farther on Qt's default.
PIXELS_PER_NOTCH = 52
MAX_EVENT_DELTA = 120
MAX_AHEAD = 210
DURATION_MS = 155


def wheel_delta(angle_y: int | float, pixels_per_notch: int = PIXELS_PER_NOTCH) -> float:
    """Convert Qt angleDelta.y() into a bounded vertical pixel displacement.

    120 angle units normally equals one physical mouse-wheel notch. The sign
    is preserved so the receiving scrollbar can subtract it as usual.
    """
    if pixels_per_notch <= 0:
        raise ValueError('Wheel distance must be positive')
    amount = (float(angle_y) / 120.0) * pixels_per_notch
    return min(MAX_EVENT_DELTA, max(-MAX_EVENT_DELTA, amount))


def queued_scroll_target(current: int, previous_target: int | None, displacement: float,
                         maximum: int, max_ahead: int = MAX_AHEAD) -> int:
    """Accumulate wheel notches without letting rapid events skip many rows.

    displacement is in *scrollbar* coordinates; positive moves down. A queued
    target is not allowed more than max_ahead pixels ahead of the actual view.
    """
    if maximum < 0 or max_ahead < 0:
        raise ValueError('Scroll range/queue cap cannot be negative')
    current = max(0, min(int(current), maximum))
    base = current if previous_target is None else int(previous_target)
    requested = base + displacement
    bounded = max(current - max_ahead, min(current + max_ahead, requested))
    return int(round(max(0, min(maximum, bounded))))

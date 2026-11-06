"""v0.9.26 mouse-wheel regression tests (desktop and big picture)."""

from pathlib import Path

import pytest

from scroll_math import (DURATION_MS, PIXELS_PER_NOTCH, MAX_AHEAD,
                         queued_scroll_target, wheel_delta)

ROOT = Path(__file__).resolve().parents[1]


def test_one_notch_is_a_short_predictable_distance():
    assert wheel_delta(120) == 52
    assert wheel_delta(-120) == -52
    assert wheel_delta(60) == 26
    assert PIXELS_PER_NOTCH < 80
    assert 80 <= DURATION_MS <= 220


def test_unusually_large_hardware_wheel_delta_is_capped():
    assert wheel_delta(1200) == 120
    assert wheel_delta(-1200) == -120
    with pytest.raises(ValueError):
        wheel_delta(120, pixels_per_notch=0)


def test_rapid_events_cannot_queue_multiple_rows_ahead():
    current = 500
    target = None
    for _ in range(40):
        target = queued_scroll_target(current, target, 52, 3000)
    assert target == current + MAX_AHEAD
    for _ in range(40):
        target = queued_scroll_target(current, target, -52, 3000)
    assert current - MAX_AHEAD <= target <= current + MAX_AHEAD


def test_boundary_clamp_and_stale_target():
    assert queued_scroll_target(0, None, -52, 1500) == 0
    assert queued_scroll_target(1480, 1495, 60, 1500) == 1500
    assert queued_scroll_target(300, 3000, 52, 3000) == 510
    with pytest.raises(ValueError):
        queued_scroll_target(0, None, 50, -1)


def test_both_game_views_and_sidebar_details_install_wheel_controller():
    view = (ROOT / 'library_view.py').read_text(encoding='utf-8')
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    adapter = (ROOT / 'wheel_scroll.py').read_text(encoding='utf-8')
    assert 'enable_smooth_wheel(view)' in view
    assert 'self.scroller,self.desktop_model=make_game_view()' in main
    assert 'self.bigscroll,self.big_model=make_game_view(large=True)' in main
    assert 'enable_smooth_wheel(self.nav)' in main
    assert 'enable_smooth_wheel(self.details_scroller)' in main
    assert 'area.viewport().installEventFilter(self)' in adapter
    assert 'self.bar.setValue(self.bar.value() - pixels)' in adapter
    assert 'self.bar.rangeChanged.connect(self._range_changed)' in adapter


def test_wheel_handler_stops_animation_when_touchpad_moves():
    handler=(ROOT/'wheel_scroll.py').read_text(encoding='utf-8')
    assert 'if pixels:' in handler
    assert 'self.cancel()' in handler
    assert 'event.accept()' in handler


def test_installer_includes_all_new_scrolling_modules():
    update=(ROOT.parent/'update_existing_gameshelf.py').read_text(encoding='utf-8')
    for module in ('scroll_math.py','wheel_scroll.py','README_V0926.txt'):
        assert f'"{module}"' in update


def test_optional_real_qt_scroll_hook(monkeypatch):
    """Run a real QObject event test where a Qt GUI installation exists."""
    qtcore=pytest.importorskip('PySide6.QtCore')
    qtwidgets=pytest.importorskip('PySide6.QtWidgets')
    import os
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from wheel_scroll import enable_smooth_wheel
    app=qtwidgets.QApplication.instance() or qtwidgets.QApplication([])
    area=qtwidgets.QListWidget()
    try:
        for i in range(200):
            area.addItem(f'Entry {i}')
        area.resize(230,200)
        area.show()
        app.processEvents()
        bar=area.verticalScrollBar()
        assert bar.maximum()>0
        bar.setValue(bar.maximum()//2)
        filt=enable_smooth_wheel(area)
        assert filt is enable_smooth_wheel(area)
        assert filt.bar is bar
        filt.cancel()
    finally:
        area.close()

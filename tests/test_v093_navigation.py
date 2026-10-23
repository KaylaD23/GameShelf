"""Portable regression tests for Desktop-first startup and console filtering."""
from __future__ import annotations

import ast
import tempfile
from pathlib import Path

from core import Settings, PLATFORMS, CONSOLE_GROUPS
from title_lookup import TitleResolver, detect_id
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
MAIN=ast.parse((ROOT/'main.py').read_text(encoding='utf-8'))


def main_method(name):
    cls=next(n for n in MAIN.body if isinstance(n,ast.ClassDef) and n.name=='Main')
    return next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)


def test_first_launch_opens_desktop_and_persists_explicit_big_choice():
    with tempfile.TemporaryDirectory() as folder:
        cfg=Path(folder)/'settings.json'
        settings=Settings(cfg)
        assert settings.values['startup_mode']=='desktop'
        settings.values['startup_mode']='big'
        settings.save()
        assert Settings(cfg).values['startup_mode']=='big'
    launch=next(n for n in MAIN.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    body=ast.unparse(launch)
    assert "get('startup_mode', 'desktop')" in body
    assert 'w.enter_big()' in body
    assert 'w.open_desktop()' in body


def test_old_settings_without_startup_choice_default_to_desktop():
    with tempfile.TemporaryDirectory() as folder:
        cfg=Path(folder)/'settings.json'
        cfg.write_text('{"last_mode":"desktop","emulators":{}}',encoding='utf-8')
        assert Settings(cfg).values['startup_mode']=='desktop'


def test_sidebar_console_order_and_separation_preserved():
    assert CONSOLE_GROUPS[0][1][:5]==('ps1','ps2','ps3','ps4','ps5')
    assert CONSOLE_GROUPS[-1][1]==('xbox','xbox360')
    assert 'switch' in PLATFORMS
    for name in ('make_big','sync_filter_controls','on_big_system','big_filter','refresh_big'):
        assert main_method(name)
    source=ast.unparse(main_method('make_big'))
    assert 'for family, platform_keys in CONSOLE_GROUPS:' in source
    assert 'self.big_system.addItem' in source
    source=ast.unparse(main_method('sync_filter_controls'))
    assert 'self.nav.setCurrentRow(row)' in source
    assert 'self.big_system.setCurrentIndex(row)' in source


def test_fullscreen_filter_clears_hidden_search():
    source=ast.unparse(main_method('big_filter'))
    assert "self.search = ''" in source
    assert 'self.searchbar.clear()' in source
    assert 'self.refresh()' in source


def test_selection_reestablished_after_model_reset():
    source=ast.unparse(main_method('refresh_big'))
    assert 'self.big_model.set_games(self.big_games)' in source
    assert 'self.bigscroll.setCurrentIndex(idx)' in source
    assert 'self.bigscroll.scrollTo(idx' in source


def test_ps5_lookup_handles_imported_app0_path_name():
    game={'title':'Ppsa01342 App0','platform':'ps5','path':'C:/games/PPSA01342/app0'}
    assert detect_id(game)=='PPSA01342'
    data=b'titleId\tconceptId\tname\tcontentId\tregion\tpublisherId\nPPSA01342_00\t10000368\tDemon\'s Souls\tUP9000-PPSA01342_00-EXAMPLE\tUP\tUP9000\n'
    with patch('title_lookup._fetch',return_value=data):
        assert TitleResolver().resolve(game)==("Demon's Souls",'PlayStation Titles')

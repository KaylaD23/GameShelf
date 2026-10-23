"""Desktop-first startup and upgrade path, without requiring PySide6."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from core import Settings

APP=Path(__file__).resolve().parents[1]


def test_clean_install_defaults_to_desktop(tmp_path):
    path=tmp_path/'data'/'settings.json'
    settings=Settings(path)
    assert settings.values['startup_mode']=='desktop'
    assert settings.values['startup_desktop_migrated_v099'] is True
    assert settings.values['desktop_maximized'] is True
    assert not path.exists()  # No surprise filesystem write before first save.


def test_upgrade_old_big_default_to_desktop_and_persist(tmp_path):
    path=tmp_path/'data'/'settings.json'
    path.parent.mkdir()
    original={'startup_mode':'big','last_mode':'big','emulators':{'pcsx2':'C:/Emulators/PCSX2.exe'},
              'rom_roots':['D:/Games'],'desktop_rect':[21,33,1024,768]}
    path.write_text(json.dumps(original),encoding='utf-8')
    upgraded=Settings(path)
    assert upgraded.values['startup_mode']=='desktop'
    saved=json.loads(path.read_text(encoding='utf-8'))
    assert saved['startup_mode']=='desktop'
    assert saved['startup_desktop_migrated_v099'] is True
    for name in ('emulators','rom_roots','desktop_rect'):
        assert saved[name]==original[name]
    # Explicit user opt-in to Big Picture AFTER migration must survive restart.
    upgraded.values['startup_mode']='big'
    upgraded.save()
    assert Settings(path).values['startup_mode']=='big'


def test_old_missing_or_invalid_startup_setting_defaults_desktop(tmp_path):
    for old in ({'emulators':{},'last_mode':'big'},{'startup_mode':'INVALID'}):
        path=tmp_path/'settings.json'
        path.write_text(json.dumps(old),encoding='utf-8')
        assert Settings(path).values['startup_mode']=='desktop'
        path.unlink()


def test_first_gui_launch_desktop_fallback_not_big():
    main=(APP/'main.py').read_text(encoding='utf-8')
    tree=ast.parse(main)
    fn=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='main')
    code=ast.unparse(fn)
    assert "w.settings.values.get('startup_mode', 'desktop') == 'big'" in code
    assert 'w.open_desktop()' in code
    assert 'w.enter_big()' in code
    assert "get('startup_mode', 'big')" not in main
    assert "get('startup_mode','big')" not in main
    assert "QShortcut(QKeySequence('F11')" in main


def test_launcher_version_matches_release():
    version=(APP/'VERSION.txt').read_text(encoding='utf-8').strip()
    assert version == '0.9.12'
    assert f'title GameShelf v{version}' in (APP/'INSTALL_AND_RUN.bat').read_text(encoding='utf-8')
    from version_info import APP_VERSION, version_file_matches
    assert APP_VERSION == version and version_file_matches()

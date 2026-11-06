"""v0.9.26 icon, taskbar identity, theme persistence and packaging tests."""
from pathlib import Path
import ast
import importlib
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT.parent / 'update_existing_gameshelf.py'


def test_windows_icon_contains_multiple_sizes():
    path = ROOT / 'assets' / 'gameshelf.ico'
    assert path.exists() and path.stat().st_size > 20_000
    image = Image.open(path)
    sizes = image.info['sizes']
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= sizes
    assert Image.open(ROOT / 'assets' / 'gameshelf.png').size == (512, 512)


def test_taskbar_identity_applied_before_qt_application():
    main = (ROOT/'main.py').read_text(encoding='utf-8')
    ast.parse(main)
    start = main.index('def main():')
    body = main[start:]
    assert body.index('register_windows_app_id()') < body.index('app=QApplication(sys.argv)')
    assert 'app.setWindowIcon(load_icon())' in body
    assert 'self.setWindowIcon(load_icon())' in main
    identity=(ROOT/'app_identity.py').read_text(encoding='utf-8')
    assert 'SetCurrentProcessExplicitAppUserModelID' in identity
    assert 'gameshelf.png' in identity
    assert 'sys._MEIPASS' not in identity  # safely obtained via getattr


def test_portable_exe_compiles_icon_into_executable():
    build=(ROOT/'BUILD_PORTABLE_EXE.bat').read_text(encoding='utf-8')
    assert '--icon "assets\\gameshelf.ico"' in build
    assert '--add-data "assets\\gameshelf.png;assets"' in build
    assert '--add-data "assets\\gameshelf.ico;assets"' in build


def test_theme_variants_are_distinct_and_valid():
    from theme_manager import THEMES, THEME_KEYS, normalize_theme, color, activate, stylesheet
    assert len(THEMES)>=5
    assert normalize_theme('not-a-theme') == 'dark'
    assert len({value['window'] for value in THEMES.values()}) == len(THEMES)
    expected={'window','sidebar','details','panel','button','text','muted','accent','selection','grid'}
    for key, p in THEMES.items():
        assert expected <= p.keys()
        for attr in expected:
            assert p[attr].startswith('#') and len(p[attr])==7
        assert p['window'] in stylesheet('QWidget{ background:#10141d;}',key)
    activate('violet')
    assert color('#1c2635') == THEMES['violet']['grid']
    activate('dark')


def test_theme_stored_in_existing_settings(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(core, 'DATA', tmp_path)
    tmp_path.mkdir(exist_ok=True)
    settings=core.Settings()
    assert settings.values['theme'] == 'dark'
    settings.values['theme']='midnight'
    settings.save()
    reopened=core.Settings()
    assert reopened.values['theme']=='midnight'


def test_theme_comboboxes_available_in_both_screens():
    source=(ROOT/'main.py').read_text(encoding='utf-8')
    assert 'self.theme_combo=self.make_theme_combo()' in source
    assert 'self.big_theme_combo=self.make_theme_combo()' in source
    assert "self.settings.values['theme']=key" in source
    assert 'app.setStyleSheet(theme_stylesheet(STYLE, key))' in source


def test_updater_includes_new_assets_and_branding():
    text=UPDATER.read_text(encoding='utf-8')
    assert 'RELEASE = "0.9.33"' in text
    assert '"app_identity.py"' in text
    assert '"theme_manager.py"' in text
    assert '"assets/gameshelf.ico"' in text
    assert '"assets/gameshelf.png"' in text
    assert '"BUILD_PORTABLE_EXE.bat"' in text
    assert 'destination.parent.mkdir(parents=True, exist_ok=True)' in text

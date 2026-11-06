"""Regression tests for v0.9.26 transparent taskbar/window icon."""
from pathlib import Path
from PIL import Image
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets'
UPDATER = ROOT.parent / 'update_existing_gameshelf.py'

def test_png_is_transparent_at_corners_and_contains_emblem():
    image=Image.open(ASSETS/'gameshelf.png').convert('RGBA')
    assert image.size == (512,512)
    assert all(image.getpixel(pt)[3] == 0 for pt in [(0,0),(511,0),(0,511),(511,511)])
    assert image.getchannel('A').getextrema() == (0,255)
    assert image.getchannel('A').getbbox() is not None

def test_ico_slots_use_alpha_and_embed_small_taskbar_sizes():
    ico=Image.open(ASSETS/'gameshelf.ico')
    expected={(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)}
    assert expected <= ico.info['sizes']
    for size in expected:
        frame=ico.ico.getimage(size).convert('RGBA')
        assert frame.size == size
        assert frame.getpixel((0,0))[3] == 0
        assert frame.getpixel((size[0]-1,size[1]-1))[3] == 0
        assert frame.getchannel('A').getextrema()[1] == 255

def test_packager_runtime_and_windows_launcher_use_new_files():
    build=(ROOT/'BUILD_PORTABLE_EXE.bat').read_text(encoding='utf-8')
    identity=(ROOT/'app_identity.py').read_text(encoding='utf-8')
    main=(ROOT/'main.py').read_text(encoding='utf-8')
    updater=UPDATER.read_text(encoding='utf-8')
    assert '--icon "assets\\gameshelf.ico"' in build
    assert 'gameshelf.png' in identity
    assert 'app.setWindowIcon(load_icon())' in main
    assert 'self.setWindowIcon(load_icon())' in main
    assert '"assets/gameshelf.ico"' in updater
    assert '"assets/gameshelf.png"' in updater
    assert '"README_V0924.txt"' in updater
    assert 'RELEASE = "0.9.33"' in updater

"""The approved gradient wordmark must show consistently on both screens."""
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/'main.py').read_text(encoding='utf-8')
UPDATER=(ROOT.parent/'update_existing_gameshelf.py').read_text(encoding='utf-8')
BUILD=(ROOT/'BUILD_PORTABLE_EXE.bat').read_text(encoding='utf-8')

def test_wordmark_is_true_transparent_multicolor_artwork():
    image=Image.open(ROOT/'assets/gameshelf_wordmark.png').convert('RGBA')
    assert image.width>=500 and image.height>=70
    assert image.getpixel((image.width-1,image.height-1))[3]==0
    assert image.getchannel('A').getextrema() == (0,255)
    # White letters plus saturated cyan and violet, not recolored by a theme.
    pixels=[image.getpixel((x,y)) for x in range(image.width) for y in range(image.height)
        if image.getpixel((x,y))[3] > 245]
    assert any(r>220 and g>220 and b>220 for r,g,b,a in pixels)
    assert any(b>210 and g>100 and r<100 for r,g,b,a in pixels)
    assert any(r>135 and b>185 and g<145 for r,g,b,a in pixels)

def test_sidebar_and_big_picture_use_same_wordmark():
    assert 'brand_row.addWidget(GameShelfWordmark(173, 38))' in MAIN
    assert 'bar.addWidget(GameShelfWordmark(330, 58))' in MAIN
    assert "label('GameShelf','brand')" not in MAIN
    assert "label('GameShelf','bigTitle')" not in MAIN
    widget=(ROOT/'brand_wordmark.py').read_text(encoding='utf-8')
    assert 'KeepAspectRatio' in widget
    assert 'resource_path("gameshelf_wordmark.png")' in widget
    assert 'setAccessibleName("GameShelf")' in widget

def test_portable_and_updater_copy_every_wordmark_file():
    assert '--add-data "assets\\gameshelf_wordmark.png;assets"' in BUILD
    assert '"brand_wordmark.py"' in UPDATER
    assert '"assets/gameshelf_wordmark.png"' in UPDATER
    assert '"README_V0925.txt"' in UPDATER
    assert 'RELEASE = "0.9.33"' in UPDATER
    assert (ROOT/'VERSION.txt').read_text(encoding='utf-8').strip()=='0.9.33'

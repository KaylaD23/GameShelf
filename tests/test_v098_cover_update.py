"""Regressions for the installed release, updater and full-frame artwork."""
from __future__ import annotations
import ast
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

from cover_geometry import poster_fill_rect
from version_info import APP_VERSION, version_file_matches

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = ROOT.parent
MAIN = (ROOT/'main.py').read_text(encoding='utf-8')
VIEW = (ROOT/'library_view.py').read_text(encoding='utf-8')
UPDATER = ARCHIVE_ROOT/'update_existing_gameshelf.py'


@pytest.mark.parametrize('image,frame', [
    ((214,300),(173,235)),
    ((173,235),(173,235)),
    ((300,300),(173,235)),
    ((1920,1080),(205,277)),
    ((800,1200),(192,248)),
    ((256,512),(238,277)),
])
def test_poster_destination_fills_full_frame_regardless_of_source_shape(image, frame):
    assert poster_fill_rect(*frame) == (0,0,*frame)
    assert image[0]>0 and image[1]>0


def test_ui_uses_full_frame_not_letterbox_or_crop():
    assert 'p.drawPixmap(self.rect(), self.pix, self.pix.rect())' in MAIN
    assert 'crop_to_fill(' not in MAIN and 'crop_to_fill(' not in VIEW
    assert 'poster_fit_rect' not in MAIN and 'poster_fit_rect' not in VIEW
    assert 'reader.setScaledSize(QSize(width,height))' in VIEW
    assert 'pix.fill(Qt.GlobalColor.transparent)' not in VIEW
    assert 'gameshelf::edge-to-edge-v0910::' in VIEW
    assert 'painter.drawPixmap(poster,pix,pix.rect())' in VIEW


def test_title_launcher_and_version_file_agree():
    assert APP_VERSION == '0.9.12'
    assert version_file_matches()
    assert "self.setWindowTitle(f'GameShelf v{APP_VERSION} · Your Games, One Library')" in MAIN
    installer = (ROOT/'INSTALL_AND_RUN.bat').read_text(encoding='utf-8')
    assert 'title GameShelf v0.9.12' in installer
    assert 'GAMESHELF v0.9.12' in installer
    assert 'v0.9.6' not in installer
    assert '0.9.6' not in MAIN


def prepare_old_install(tmp_path):
    target=tmp_path/'Already Installed GameShelf'
    target.mkdir()
    for f in ('main.py','core.py','library_view.py'):
        (target/f).write_text('old version',encoding='utf-8')
    (target/'VERSION.txt').write_text('0.9.6\n')
    (target/'data').mkdir()
    (target/'Emulators').mkdir()
    (target/'.venv').mkdir()
    important={
        'data/library.db':b'user games here',
        'data/covers/crash.png':b'user downloaded image',
        'Emulators/PCSX2/pcsx2.exe':b'user emulator',
        '.venv/custom_marker':b'user environment',
        'GameShelf.exe':b'outdated frozen app',
    }
    for name,data in important.items():
        p=target/name
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(data)
    return target,important


def run_updater(target, *extra):
    return subprocess.run([sys.executable,str(UPDATER),'--target',str(target),*extra],
                          capture_output=True,text=True,timeout=20)


def test_update_real_install_verify_and_preserve_user_data(tmp_path):
    target,important=prepare_old_install(tmp_path)
    report=run_updater(target)
    assert report.returncode == 0,report.stderr
    assert 'UPDATE VERIFIED: GameShelf v0.9.12' in report.stdout
    assert 'outdated code' in report.stdout
    for name,original in important.items():
        assert (target/name).read_bytes() == original
    for name in ('main.py','library_view.py','cover_geometry.py','version_info.py','INSTALL_AND_RUN.bat','VERSION.txt'):
        assert hashlib.sha256((target/name).read_bytes()).digest() == hashlib.sha256((ROOT/name).read_bytes()).digest()
    assert (target/'VERSION.txt').read_text().strip() == '0.9.12'
    check=run_updater(target,'--verify')
    assert check.returncode==0 and 'UPDATE VERIFIED' in check.stdout
    (target/'main.py').write_text('old version again')
    check=run_updater(target,'--verify')
    assert check.returncode != 0 and 'main.py' in check.stderr


def test_update_rejects_invalid_install_without_creating_anything(tmp_path):
    bad=tmp_path/'wrong GameShelf'
    bad.mkdir()
    res=run_updater(bad)
    assert res.returncode!=0
    assert not list(bad.iterdir())
    assert 'not an existing GameShelf' in res.stderr


def test_update_refuses_overwriting_its_own_source():
    res=run_updater(ROOT)
    assert res.returncode !=0
    assert 'extracted update package' in res.stderr

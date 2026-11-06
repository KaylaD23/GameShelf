"""v0.9.33 new platforms, bundled executables, source validation, and safe install."""
import json
from pathlib import Path
import sys

import pytest

from core import (
    PLATFORMS, CONSOLE_GROUPS, EMULATORS, BY_KEY, detect_bundled_executables,
    launch_command, launch_args, scan_games, safe_name,
)
from libretro_art import SYSTEMS, catalog_url, image_url, matches, clear_cache

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from update_existing_gameshelf import validate_emulator_bundle, install_new_emulators


def test_new_consoles_are_in_both_shared_navigation_lists():
    assert list(PLATFORMS)==[p for _,groups in CONSOLE_GROUPS for p in groups]
    assert CONSOLE_GROUPS[1][1][0]=='n64'
    assert CONSOLE_GROUPS[-1]==('SEGA',('dreamcast',))
    assert PLATFORMS['n64']=='Nintendo 64'
    assert PLATFORMS['dreamcast']=='Sega Dreamcast'
    assert {e.key for e in EMULATORS if 'n64' in e.platforms}=={'project64','luna_project64'}
    assert {e.key for e in EMULATORS if 'dreamcast' in e.platforms}=={'flycast'}
    assert len(EMULATORS)==19


def test_emulator_executable_profiles_are_real():
    assert BY_KEY['flycast'].executable=='flycast.exe'
    assert BY_KEY['project64'].executable=='Project64.exe'
    assert BY_KEY['luna_project64'].executable=='Project64.exe'
    assert (ROOT/'Emulators'/'Flycast'/'flycast.exe').is_file()
    assert (ROOT/'Emulators'/'Project64'/'Project64.exe').is_file()
    assert (ROOT/'Emulators'/'LunasProject64'/'Project64.exe').is_file()
    detected=detect_bundled_executables(ROOT)
    assert {'flycast','project64','luna_project64'} <= detected.keys()
    assert all(Path(detected[k]).parts[0]=='Emulators' for k in ('flycast','project64','luna_project64'))


def test_n64_scan_import_formats_and_paths_with_spaces(tmp_path):
    for name in ['Super Mario 64.z64','Legend of Zelda.v64','Star Fox.n64','Conkers Bad Fur Day.zip','F Zero X.rom']:
        (tmp_path/name).write_bytes(b'test')
    (tmp_path/'unrelated.iso').write_bytes(b'no')
    result=scan_games(tmp_path,'n64')
    assert len(result)==5
    assert all(r[1]=='n64' for r in result)
    assert 'Super Mario 64' in [r[0] for r in result]


def test_dreamcast_disc_files_no_track_duplicates(tmp_path):
    for name in ['Sonic Adventure.gdi','Jet Set Radio.cdi','Crazy Taxi.chd','Shenmue.cue','track01.bin','readme.txt']:
        (tmp_path/name).write_bytes(b'fake')
    result=scan_games(tmp_path,'dreamcast')
    assert len(result)==4
    assert all(not r[2].endswith('track01.bin') for r in result)


def test_launch_arguments_do_not_assume_undocumented_fullscreen_switches(tmp_path):
    game=tmp_path/'Super Mario 64.z64';game.write_bytes(b'a')
    for key in ('project64','luna_project64'):
        exe=tmp_path/(key+'.exe');exe.write_bytes(b'a')
        assert launch_args(key,game,True)==[str(game)]
        cmd,cwd=launch_command(str(exe),key,str(game),True)
        assert cmd==[str(exe),str(game)]
        assert cwd==str(tmp_path)
    disc=tmp_path/'Sonic Adventure (USA).gdi';disc.write_bytes(b'a')
    exe=tmp_path/'flycast.exe';exe.write_bytes(b'a')
    assert launch_args('flycast',disc,True)==['-config','window:fullscreen=yes',str(disc)]
    assert launch_args('flycast',disc,False)==[str(disc)]
    assert launch_command(str(exe),'flycast',str(disc),True)[0]==[str(exe),'-config','window:fullscreen=yes',str(disc)]


def test_libretro_coverage_for_both_new_consoles():
    assert SYSTEMS['n64']==('Nintendo - Nintendo 64',)
    assert SYSTEMS['dreamcast']==('Sega - Dreamcast',)
    assert 'Nintendo%20-%20Nintendo%2064' in catalog_url('Nintendo - Nintendo 64')
    assert 'Sega%20-%20Dreamcast' in catalog_url('Sega - Dreamcast')
    clear_cache()
    def fake_fetch(url):
        return b'<a href="Sonic%20Adventure%20%28USA%29.png">Sonic Adventure</a>'
    result=matches('Sonic Adventure',{'platform':'dreamcast','path':'sonic.gdi'},fake_fetch)
    assert len(result)==1
    assert result[0][1].startswith('https://thumbnails.libretro.com/')


def test_bundle_integrity_and_non_overwriting_upgrade(tmp_path):
    manifest=validate_emulator_bundle(ROOT)
    assert set(manifest['folders'])=={'Flycast','Project64','LunasProject64','WinDurango'}
    target=tmp_path/'old';target.mkdir()
    games=target/'data'/'library.sqlite3';games.parent.mkdir();games.write_bytes(b'KEEP THIS')
    cover=target/'data'/'cover.jpg';cover.write_bytes(b'JPEG')
    added,preserved=install_new_emulators(target,ROOT)
    assert set(added)==set(manifest['folders']) and preserved==[]
    detected=detect_bundled_executables(target)
    assert {'flycast','project64','luna_project64'} <= detected.keys()
    assert games.read_bytes()==b'KEEP THIS'
    assert cover.read_bytes()==b'JPEG'
    sentinel=target/'Emulators'/'Flycast'/'save.bin';sentinel.write_bytes(b'PRIVATE SAVE')
    added,preserved=install_new_emulators(target,ROOT)
    assert added==[] and len(preserved)==4
    assert sentinel.read_bytes()==b'PRIVATE SAVE'


def test_fails_on_incomplete_emulator_folder_without_overwriting(tmp_path):
    emulator=tmp_path/'Emulators'/'Flycast';emulator.mkdir(parents=True)
    (emulator/'my_save.bin').write_bytes(b'KEEP')
    with pytest.raises(RuntimeError,match='incomplete'):
        install_new_emulators(tmp_path,ROOT)
    assert (emulator/'my_save.bin').read_bytes()==b'KEEP'

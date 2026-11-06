"""Xbox One WinDurango compatibility-layer integration and bundle safety."""
from pathlib import Path
from xml.sax.saxutils import escape
import pytest

from core import (
    PLATFORMS, CONSOLE_GROUPS, BY_KEY, EMULATORS, launch_command,
    launch_args, scan_games, detect_bundled_executables, Library,
)
from windurango_support import manifest_executable, locate_prepared_game, prepared_game_executable
from libretro_art import SYSTEMS
from update_existing_gameshelf import validate_emulator_bundle, install_new_emulators

ROOT=Path(__file__).resolve().parents[1]


def test_console_group_and_emulator_profile():
    assert PLATFORMS['xboxone']=='Xbox One'
    assert CONSOLE_GROUPS[-2]==('XBOX', ('xbox','xbox360','xboxone'))
    assert list(PLATFORMS)==[p for _, platforms in CONSOLE_GROUPS for p in platforms]
    assert {e.key for e in EMULATORS if 'xboxone' in e.platforms}=={'windurango'}
    assert BY_KEY['windurango'].executable=='WinDurango.Common.dll'
    assert BY_KEY['windurango'].status=='experimental'
    assert 'xboxone' in SYSTEMS


def test_bundled_runtime_detected_but_not_watchdog():
    detected=detect_bundled_executables(ROOT)
    assert detected['windurango']=='Emulators/WinDurango/WinDurango.Common.dll'
    assert (ROOT/'Emulators'/'WinDurango'/'WinDurango.Watchdog.exe').is_file()
    assert (ROOT/'Emulators'/'WinDurango'/'kernelx.dll').is_file()
    manifest=validate_emulator_bundle(ROOT)
    assert 'WinDurango' in manifest['folders']
    assert 'WinDurango/WinDurango.Common.dll' in manifest['executables']
    assert any(x['path']=='WinDurango/winrt_x.dll' for x in manifest['files'])


def test_prepared_game_exe_launches_directly_and_never_calls_watchdog(tmp_path):
    mark=tmp_path/'WinDurango.Common.dll';mark.write_bytes(b'runtime')
    exe=tmp_path/'My Xbox One Game.exe';exe.write_bytes(b'binary')
    loader=ROOT/'Emulators'/'WinDurango'/'WinDurango.Common.dll'
    cmd,cwd=launch_command(str(loader),'windurango',str(exe),True)
    assert cmd==[str(exe)] and cwd==str(tmp_path)
    assert 'Watchdog' not in str(cmd)
    with pytest.raises(ValueError,match='compatibility layer'):
        launch_args('windurango',exe,True)


@pytest.mark.parametrize('name', ['Game.iso','Game.xvc','AppxManifest.xml'])
def test_not_a_direct_iso_emulator(tmp_path,name):
    file=tmp_path/name;file.write_bytes(b'file')
    exe=ROOT/'Emulators'/'WinDurango'/'WinDurango.Common.dll'
    with pytest.raises(ValueError,match='cannot boot'):
        launch_command(str(exe),'windurango',str(file),True)


def test_prepared_game_missing_runtime_dll_fails(tmp_path):
    exe=tmp_path/'game.exe';exe.write_bytes(b'mock')
    with pytest.raises(ValueError,match='not installed'):
        prepared_game_executable(exe)


def test_manifest_autodetection_only_targets_listed_game_exe(tmp_path):
    game=tmp_path/'My Xbox One Game';game.mkdir()
    mount=game/'Mount';mount.mkdir()
    exe=mount/'Game.exe';exe.write_bytes(b'mock')
    (game/'AppxManifest.xml').write_text(
        '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
        '<Applications><Application Id="Game" Executable="Mount\\Game.exe" /></Applications></Package>',encoding='utf-8')
    assert manifest_executable(game/'AppxManifest.xml')==exe
    other=game/'Unrelated.exe';other.write_bytes(b'ignore')
    games=scan_games(tmp_path,'xboxone')
    assert len(games)==1
    assert games[0][0]=='My Xbox One Game'
    assert games[0][2]==str(exe.resolve())


def test_prepared_game_without_manifest_can_be_detected(tmp_path):
    game=tmp_path/'Mount';game.mkdir()
    (game/'WinDurango.Common.dll').write_bytes(b'dll')
    e=game/'Game.exe';e.write_bytes(b'game')
    assert locate_prepared_game(game, ['WinDurango.Common.dll','Game.exe'])==e
    assert len(scan_games(tmp_path,'xboxone'))==1


def test_path_traversal_in_app_manifest_not_allowed(tmp_path):
    (tmp_path/'AppxManifest.xml').write_text('<Package><Application Executable="..\\evil.exe"/></Package>', encoding='utf-8')
    (tmp_path.parent/'evil.exe').write_bytes(b'no')
    assert manifest_executable(tmp_path/'AppxManifest.xml') is None


def test_nonmanifest_exe_does_not_trigger_library_scan(tmp_path):
    (tmp_path/'unknown.exe').write_bytes(b'mock')
    (tmp_path/'not_xbox.iso').write_bytes(b'mock')
    assert scan_games(tmp_path,'xboxone')==[]


def test_upgrade_preserves_previous_folders(tmp_path):
    dest=tmp_path/'my_gameshelf';dest.mkdir()
    installed=dest/'Emulators'/'WinDurango';installed.mkdir(parents=True)
    (installed/'WinDurango.Common.dll').write_bytes(b'custom-local-version')
    (installed/'config.json').write_text('my config',encoding='utf-8')
    for folder,exe in [('Flycast','flycast.exe'),('Project64','Project64.exe'),('LunasProject64','Project64.exe')]:
        p=dest/'Emulators'/folder;p.mkdir();(p/exe).write_bytes(b'keep me')
    installed_new,preserved=install_new_emulators(dest,ROOT)
    assert installed_new==[] and set(preserved)=={'Flycast','Project64','LunasProject64','WinDurango'}
    assert (installed/'WinDurango.Common.dll').read_bytes()==b'custom-local-version'
    assert (installed/'config.json').read_text()=='my config'


def test_install_adds_windurango_once_and_preserves_data(tmp_path):
    dest=tmp_path/'app';dest.mkdir()
    db=dest/'data'/'library.sqlite3';db.parent.mkdir();db.write_bytes(b'SAVED GAMES')
    for folder,exe in [('Flycast','flycast.exe'),('Project64','Project64.exe'),('LunasProject64','Project64.exe')]:
        p=dest/'Emulators'/folder;p.mkdir(parents=True);(p/exe).write_bytes(b'keep')
    new,old=install_new_emulators(dest,ROOT)
    assert new==['WinDurango']
    assert len(old)==3
    assert db.read_bytes()==b'SAVED GAMES'
    new,old=install_new_emulators(dest,ROOT)
    assert not new and len(old)==4

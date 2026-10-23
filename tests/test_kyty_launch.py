from pathlib import Path
import json
import sys
import pytest

from core import Settings, kyty_native_launcher, launch, launch_command, scan_games


def make_kyty(tmp_path):
    exe=tmp_path/'kyty_emulator.exe'
    exe.write_bytes(b'emulator fixture')
    old=tmp_path/'launcher.exe'
    old.write_bytes(b'old gui fixture')
    current=tmp_path/'kyty_launcher.exe'
    current.write_bytes(b'new gui fixture')
    game=tmp_path/'games'/'Example'
    game.mkdir(parents=True)
    (game/'eboot.bin').write_bytes(b'game fixture')
    return exe, old, current, game


def test_native_prefers_new_launcher(tmp_path):
    exe, old, modern, game=make_kyty(tmp_path)
    assert kyty_native_launcher(exe)==modern
    cmd,cwd=launch_command(str(exe),'kyty',str(game),False,kyty_mode='native')
    assert cmd==[str(modern)]
    assert cwd==str(tmp_path)


def test_native_accepts_selected_old_launcher_but_chooses_new_one(tmp_path):
    _, old, modern, game=make_kyty(tmp_path)
    cmd,_=launch_command(str(old),'kyty',str(game),False,kyty_mode='native')
    assert cmd==[str(modern)]


def test_native_missing_launcher_fails_not_direct(tmp_path):
    exe=tmp_path/'kyty_emulator.exe';exe.write_bytes(b'x')
    game=tmp_path/'eboot.bin';game.write_bytes(b'x')
    with pytest.raises(FileNotFoundError,match='graphical launcher'):
        launch_command(str(exe),'kyty',str(game),True,kyty_mode='native')


def test_kyty_direct_uses_emulator_not_launcher(tmp_path):
    exe,old,modern,game=make_kyty(tmp_path)
    cmd,cwd=launch_command(str(modern),'kyty',str(game/'eboot.bin'),True,kyty_mode='direct')
    assert cmd==[str(exe),'--game',str(game)]
    assert cwd==str(tmp_path)
    with pytest.raises(ValueError,match='Unknown Kyty launch mode'):
        launch_command(str(exe),'kyty',str(game),True,kyty_mode='wrong')


def test_kyty_direct_mode_default_and_old_data_compatible(tmp_path):
    setting=tmp_path/'data'/'settings.json'
    setting.parent.mkdir()
    setting.write_text(json.dumps({'emulators':{'kyty':'F:/old/kyty_emulator.exe'}}))
    v=Settings(setting)
    assert v.values['kyty_launch_mode']=='direct'
    assert v.values['emulators']['kyty']=='F:/old/kyty_emulator.exe'
    v.values['kyty_launch_mode']='direct';v.save()
    assert Settings(setting).values['kyty_launch_mode']=='direct'


def test_game_scan_includes_ps5_zarchive(tmp_path):
    game=tmp_path/'Games'/'Game.zar';game.parent.mkdir();game.write_bytes(b'example')
    result=scan_games(tmp_path,'ps5')
    assert any(Path(p)==game for _,_,p in result)


def test_log_survives_process_exit(tmp_path):
    # Uses an executable stand-in; no attempt to execute Windows binaries here.
    stub=tmp_path/'test_emulator'
    stub.write_text('#!'+sys.executable+'\nprint("captured emulator output")\n',encoding='utf8')
    stub.chmod(0o755)
    game=tmp_path/'Game.iso';game.write_bytes(b'a')
    log=tmp_path/'data'/'logs'/'emulator.log'
    proc=launch(str(stub),'azahar',str(game),False,log_path=log)
    assert proc.wait(timeout=8)==0
    assert b'captured emulator output' in log.read_bytes()


def test_kyty_native_setting_from_v06_migrates_to_direct(tmp_path):
    settings_file=tmp_path/'data'/'settings.json'
    settings_file.parent.mkdir()
    settings_file.write_text(json.dumps({'kyty_launch_mode':'native',
                                         'emulators':{'kyty':'Emulators/KytyPS5/kyty_emulator.exe'}}))
    settings=Settings(settings_file)
    assert settings.values['kyty_launch_mode']=='direct'
    settings.save()
    assert json.loads(settings_file.read_text())['kyty_launch_mode']=='direct'


def test_kyty_v04_one_click_launch_command_preserved_with_spaces(tmp_path):
    emulator_dir=tmp_path/'GameShelf'/'Emulators'/'Kyty PS5'
    emulator_dir.mkdir(parents=True)
    exe=emulator_dir/'kyty_emulator.exe'
    exe.write_bytes(b'fixture')
    (emulator_dir/'kyty_launcher.exe').write_bytes(b'fixture')
    game=tmp_path/'Game Files'/'Taiko no Tatsujin Rhythm Festival 01.000 PPSA16441'
    game.mkdir(parents=True)
    eboot=game/'eboot.bin'
    eboot.write_bytes(b'fixture')
    expected=[str(exe),'--game',str(game)]
    assert launch_command(str(exe),'kyty',str(eboot),False)==(expected,str(emulator_dir))
    assert launch_command(str(exe),'kyty',str(game),True)==(expected,str(emulator_dir))


def test_game_play_is_forced_direct_even_with_legacy_native_mode():
    source=(Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8')
    assert "self.root.currentWidget()==self.big,kyty_mode='direct')" in source
    assert "self.kyty_mode=QComboBox()" not in source

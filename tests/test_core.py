from pathlib import Path
import pytest
from core import (EMULATORS,PLATFORMS,Library,Settings,detect_executables,scan_games,
                  launch_args,launch_command,title_id_from_path,executable_path,detect_bundled_executables)


def test_platforms_valid():
    assert len(EMULATORS)==15
    assert len({e.key for e in EMULATORS})==15
    assert all(p in PLATFORMS for e in EMULATORS for p in e.platforms)


def test_launcher_commands(tmp_path):
    game=tmp_path/'Game.iso';game.write_bytes(b'data')
    exe=tmp_path/'Dolphin.exe';exe.write_bytes(b'dummy')
    cmd,cwd=launch_command(str(exe),'dolphin',str(game),True)
    assert cmd[0]==str(exe)
    assert cmd[-1]==str(game)
    assert 'Dolphin.Display.Fullscreen=True' in cmd
    assert cwd==str(tmp_path)
    assert launch_args('xemu',str(game),True)[0]=='-dvd_path'
    assert '--fullscreen' in launch_args('ryujinx',str(game),True)
    assert '--fullscreen' in launch_args('cemu',str(game),True)
    assert launch_args('sharpemu',tmp_path/'eboot.bin')[0]==str(tmp_path/'eboot.bin')
    assert launch_args('kyty',tmp_path/'eboot.bin')==['--game',str(tmp_path)]
    with pytest.raises(ValueError):launch_args('rpcs3',game)


def test_ps3_folder(tmp_path):
    target=tmp_path/'game'/'PS3_GAME'/'USRDIR'/'EBOOT.BIN'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'')
    assert launch_args('rpcs3',tmp_path/'game')[-1]==str(target)
    assert scan_games(tmp_path,'ps3')[0][2]==str(tmp_path/'game')


def test_vita_title(tmp_path):
    path=tmp_path/'PCSA00001'/'eboot.bin';path.parent.mkdir();path.write_bytes(b'')
    assert title_id_from_path(path)=='PCSA00001'
    assert launch_args('vita3k',str(path),True)[-2:]==['--installed-path','PCSA00001']
    assert scan_games(tmp_path,'vita')[0][0]=='PCSA00001'


def test_system_scanners(tmp_path):
    base=tmp_path/'games';base.mkdir()
    (base/'Metroid Prime.rvz').write_bytes(b'')
    (base/'Mario.iso').write_bytes(b'')
    (base/'Game.xci').write_bytes(b'')
    (base/'Game.nsp').write_bytes(b'')
    (base/'XBOX.iso').write_bytes(b'')
    assert len(scan_games(base,'gc'))==3  # Platform is supplied explicitly, .iso alone is ambiguous
    assert len(scan_games(base,'switch'))==2
    assert len(scan_games(base,'xbox'))==2
    assert len(scan_games(base,'3ds'))==0


def test_wiiu(tmp_path):
    code=tmp_path/'Zelda'/'code';code.mkdir(parents=True)
    (code/'game.rpx').write_bytes(b'')
    games=scan_games(tmp_path,'wiiu')
    assert len(games)==1
    assert games[0][0]=='Zelda'


def test_detect(tmp_path):
    base=tmp_path/'Emulators'/'Emulators 2'/'Dolphin-x64'
    base.mkdir(parents=True);(base/'Dolphin.exe').write_bytes(b'')
    found=detect_executables([tmp_path])
    assert found['dolphin']==str(base/'Dolphin.exe')


def test_database(tmp_path):
    db=Library(tmp_path/'db.sqlite')
    game=tmp_path/'game.iso';game.write_bytes(b'')
    assert db.add('Super Game','gc','dolphin',str(game))
    assert not db.add('Super Game Duplicate','gc','dolphin',str(game))
    row=db.all()[0];identifier=row['id']
    db.edit(identifier,favorite=1,artwork='cover.png')
    db.add_playtime(identifier,125)
    assert db.get(identifier)['favorite']==1
    assert db.get(identifier)['seconds_played']==125
    assert db.get(identifier)['artwork']=='cover.png'
    db.close();db=Library(tmp_path/'db.sqlite')
    assert len(db.all())==1
    db.remove(identifier)
    assert db.all()==[]
    db.close()


def test_settings(tmp_path):
    p=tmp_path/'nested'/'settings.json'
    s=Settings(p);s.values['emulators']['rpcs3']='D:/RPCS3/rpcs3.exe';s.save()
    assert Settings(p).values['emulators']['rpcs3']=='D:/RPCS3/rpcs3.exe'


def test_bundled_emulators_are_portable(tmp_path):
    root=tmp_path/'GameShelf'
    exe=root/'Emulators'/'Emulators 2'/'Dolphin-x64'/'Dolphin.exe'
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'fixture')
    result=detect_bundled_executables(root)
    assert result['dolphin']=='Emulators/Emulators 2/Dolphin-x64/Dolphin.exe'
    assert executable_path(result['dolphin'],root)==exe

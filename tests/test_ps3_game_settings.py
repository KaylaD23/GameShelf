"""Per-game RPCS3 settings, Windows argv handling, and upgrade regressions."""
from __future__ import annotations

import ast
from pathlib import Path
import sqlite3
import subprocess

import pytest

from core import (Library, launch_command, launch, launch_args,
                  rpcs3_launch_args, parse_windows_arguments)


def ps3_fixture(tmp_path: Path):
    exe=tmp_path/'Emulator Install'/'rpcs3.exe'
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'fake emulator')
    target=tmp_path/'Game With Spaces'/'PS3_GAME'/'USRDIR'/'EBOOT.BIN'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'fake game')
    return exe,target


def test_windows_quoting_with_spaces_and_backslashes():
    assert parse_windows_arguments(r'--game-screen 1 --config "C:\RPCS3 configs\My Config.yml"') == [
        '--game-screen','1','--config',r'C:\RPCS3 configs\My Config.yml'
    ]
    assert parse_windows_arguments('   ') == []
    assert parse_windows_arguments('--foo="a b"') == ['--foo=a b']
    assert parse_windows_arguments('"" --second') == ['', '--second']
    assert parse_windows_arguments(r'--path "C:\Folder With Spaces\\"') == ['--path','C:\\Folder With Spaces\\']
    with pytest.raises(ValueError,match='Unclosed double quote'):
        parse_windows_arguments('--name "not closed')
    with pytest.raises(ValueError,match='NUL'):
        parse_windows_arguments('--flag\0bad')


@pytest.mark.parametrize('argv', [
    ['--game-screen','1'],
    ['--config',r'C:\RPCS3 Data\config.yml'],
    [r'c:\path\file', 'a b', '--switch="quoted"'],
    ['', 'value'],
    ['a\\"b', '\\', 'C:\\path\\'],
    ['äbc','Slashes\\ \\','flag'],
])
def test_parser_roundtrip_windows_list2cmdline(argv):
    assert parse_windows_arguments(subprocess.list2cmdline(argv))==argv


def test_per_game_flags_come_before_eboot_and_keep_fullscreen(tmp_path):
    exe,target=ps3_fixture(tmp_path)
    options='--game-screen 1 --config "C:\\Emulator Settings\\special.yml"'
    command,cwd=launch_command(str(exe),'rpcs3',str(target),True,ps3_args=options)
    assert command==[str(exe),'--no-gui','--fullscreen','--game-screen','1',
                     '--config',r'C:\Emulator Settings\special.yml',str(target)]
    assert cwd==str(exe.parent)
    windowed,_=launch_command(str(exe),'rpcs3',str(target),False,ps3_args='--game-screen 2')
    assert windowed==[str(exe),'--game-screen','2',str(target)]
    assert rpcs3_launch_args(str(target),False)==launch_args('rpcs3',target,False)


def test_launch_never_uses_a_shell(tmp_path,monkeypatch):
    exe,target=ps3_fixture(tmp_path)
    result=[]
    def capture(cmd,**kwargs):
        result.append((cmd,kwargs))
        return object()
    monkeypatch.setattr(subprocess,'Popen',capture)
    launch(str(exe),'rpcs3',str(target),True,ps3_args='--config "C:\\Some Folder\\custom.yml"')
    assert len(result)==1
    cmd,opts=result[0]
    assert cmd[-3:]==['--config',r'C:\Some Folder\custom.yml',str(target)]
    assert opts['shell'] is False
    assert opts['cwd']==str(exe.parent)


def test_games_have_independent_ps3_flags_and_persist_on_restart(tmp_path):
    db_path=tmp_path/'library.sqlite3'
    db=Library(db_path)
    g1=tmp_path/'A.elf';g1.write_bytes(b'')
    g2=tmp_path/'B.elf';g2.write_bytes(b'')
    db.add('One','ps3','rpcs3',str(g1))
    db.add('Two','ps3','rpcs3',str(g2))
    first,second=[game['id'] for game in db.all()]
    assert not db.get(first)['ps3_args']
    db.edit(first,ps3_args='--game-screen 1')
    assert db.get(second)['ps3_args']==''
    db.close()
    db=Library(db_path)
    assert db.get(first)['ps3_args']=='--game-screen 1'
    assert db.get(second)['ps3_args']==''
    db.edit(first,ps3_args='')
    assert db.get(first)['ps3_args']==''
    db.close()


def test_old_database_is_upgraded_without_losing_games(tmp_path):
    path=tmp_path/'old.sqlite3'
    conn=sqlite3.connect(path)
    conn.execute('''CREATE TABLE games (
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     title TEXT NOT NULL,
     platform TEXT NOT NULL,
     emulator TEXT NOT NULL,
     path TEXT NOT NULL UNIQUE,
     artwork TEXT NOT NULL DEFAULT '',
     favorite INTEGER NOT NULL DEFAULT 0,
     seconds_played INTEGER NOT NULL DEFAULT 0,
     last_played INTEGER NOT NULL DEFAULT 0,
     created_at INTEGER NOT NULL DEFAULT 0)''')
    conn.execute('INSERT INTO games (title,platform,emulator,path,artwork,favorite) VALUES (?,?,?,?,?,?)',
                 ('Old Favourite','ps3','rpcs3','C:/test/EBOOT.BIN','cover.png',1))
    conn.commit();conn.close()
    db=Library(path)
    old=db.all()
    assert len(old)==1
    assert old[0]['title']=='Old Favourite'
    assert old[0]['artwork']=='cover.png'
    assert old[0]['favorite']==1
    assert old[0]['ps3_args']==''
    db.edit(old[0]['id'],ps3_args='--game-screen 1')
    db.close()
    again=Library(path)
    assert again.all()[0]['ps3_args']=='--game-screen 1'
    assert len([row for row in again.db.execute('PRAGMA table_info(games)') if row['name']=='ps3_args'])==1
    again.close()


def test_ps3_dialog_is_accessible_from_desktop_big_picture_and_launcher():
    path=Path(__file__).resolve().parents[1]/'main.py'
    source=path.read_text(encoding='utf-8')
    tree=ast.parse(source)
    game_dialog=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='PS3GameSettingsDialog')
    assert {n.name for n in game_dialog.body if isinstance(n,ast.FunctionDef)} >= {'validate','ps3_args','update_preview'}
    main=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='Main')
    assert {n.name for n in main.body if isinstance(n,ast.FunctionDef)} >= {'edit_ps3_settings','launch_selected'}
    assert 'self.ps3_settings_btn=click(' in source
    assert 'self.big_ps3_settings_btn=click(' in source
    assert 'buttons & X and self.big_games: self.edit_ps3_settings()' in source
    assert "ps3_args=game.get('ps3_args','')" in source
    assert "game['platform']=='ps3' and game['emulator']=='rpcs3'" in source

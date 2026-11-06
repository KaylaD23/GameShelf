"""GameShelf 0.9.13 disc grouping, non-destructive migration and launch routing."""
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import pytest

from core import Library, launch_args
from multi_disc import (
    disc_identity, eligible_disc, group_candidates, write_duckstation_playlist,
    next_disc_number
)
from disc_hotkey import send_duckstation_next_disc


def test_disc_identity_recognizes_explicit_markers_and_keeps_regions():
    assert disc_identity('FFVII (Disc 1) (USA)','/games/FFVII (Disc 1) (USA).chd') == ('ffvii (usa)',1)
    assert disc_identity('FFVII (Disc 2) (USA)','/games/FFVII (Disc 2) (USA).chd') == ('ffvii (usa)',2)
    assert disc_identity('Game CD2 (Europe)','/games/Game CD2 (Europe).iso') == ('game (europe)',2)
    assert disc_identity('Discworld','/games/Discworld.iso') is None
    assert disc_identity('Cyberpunk 2077','/games/CD Projekt Red.iso') is None
    assert disc_identity('Final Fantasy VII','/games/Final Fantasy VII.iso') is None


def test_auto_group_does_not_cross_region_emulator_or_platform():
    games=[
        dict(id=1,title='Game (Disc 1) (USA)',path='/g/Game (Disc 1) (USA).chd',platform='ps1',emulator='duckstation'),
        dict(id=2,title='Game (Disc 2) (USA)',path='/g/Game (Disc 2) (USA).chd',platform='ps1',emulator='duckstation'),
        dict(id=3,title='Game (Disc 2) (Europe)',path='/g/Game (Disc 2) (Europe).chd',platform='ps1',emulator='duckstation'),
        dict(id=4,title='Game (Disc 2) (USA)',path='/g/Game (Disc 2) (USA).iso',platform='ps2',emulator='pcsx2'),
    ]
    assert [[x['id'] for x in group] for group in group_candidates(games)]==[[1,2]]
    assert eligible_disc('ps1','a.cue')
    assert not eligible_disc('ps2','a.cue')
    assert not eligible_disc('ps1','a.bin')


def make_discs(tmp_path, title='Final Fantasy VII', count=3, ext='.chd'):
    result=[]
    for i in range(1,count+1):
        file=tmp_path/f'{title} (Disc {i}) (USA){ext}'
        file.write_bytes(b'original image contents '+bytes([i]))
        result.append(file)
    return result


def test_merge_into_one_entry_preserves_stats_artwork_originals(tmp_path):
    images=make_discs(tmp_path)
    art=tmp_path/'cover.png';art.write_bytes(b'image')
    library=Library(tmp_path/'game.sqlite3')
    ids=[]
    for i,image in enumerate(images,1):
        assert library.add(image.stem,'ps1','duckstation',str(image))
        record=next(g for g in library.all() if g['path']==str(image))
        ids.append(record['id'])
        library.edit(record['id'],seconds_played=i*100,favorite=int(i==2),artwork=str(art) if i==2 else '')
    before=[image.read_bytes() for image in images]
    merged=library.auto_merge_discs()
    assert len(merged)==1
    assert len(library.all())==1
    main=library.get(ids[0])
    assert main['disc_count']==3
    assert main['selected_disc']==1
    assert [p['path'] for p in main['discs']]==[str(image) for image in images]
    assert main['seconds_played']==600
    assert main['favorite']==1
    assert main['artwork']==str(art)
    assert 'Disc 1' not in main['title']
    assert library.auto_merge_discs()==[]
    library.close()
    assert [image.read_bytes() for image in images]==before
    reopened=Library(tmp_path/'game.sqlite3')
    assert reopened.get(ids[0])['disc_count']==3
    assert reopened.get(ids[0])['artwork']==str(art)
    reopened.close()


def test_existing_db_upgrade_preserves_games_and_new_discs(tmp_path):
    db=tmp_path/'old.sqlite3'
    conn=sqlite3.connect(db)
    conn.execute('CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, platform TEXT,emulator TEXT,path TEXT UNIQUE,artwork TEXT DEFAULT \'\',favorite INTEGER DEFAULT 0,seconds_played INTEGER DEFAULT 0,last_played INTEGER DEFAULT 0,created_at INTEGER DEFAULT 0)')
    conn.execute("INSERT INTO games VALUES(1,'Legacy','ps1','duckstation','C:/old/legacy.cue','cover.png',1,40,10,7)")
    conn.commit();conn.close()
    library=Library(db)
    record=library.get(1)
    assert record['title']=='Legacy' and record['artwork']=='cover.png'
    assert record['selected_disc']==1 and record['disc_count']==1
    library.close()


def test_manual_disc_edit_and_select(tmp_path):
    images=make_discs(tmp_path,count=2,ext='.iso')
    library=Library(tmp_path/'lib.sqlite3')
    library.add('Multi','ps2','pcsx2',str(images[0]))
    identifier=library.all()[0]['id']
    library.set_discs(identifier,[str(image) for image in images])
    assert next_disc_number(library.get(identifier)['discs'],1)==2
    library.choose_disc(identifier,2)
    assert library.get(identifier)['selected_disc']==2
    with pytest.raises(ValueError):
        library.edit(identifier,path=str(images[1]))
    assert library.get(identifier)['path']==str(images[0])
    with pytest.raises(ValueError):library.choose_disc(identifier,3)
    with pytest.raises(ValueError):library.set_discs(identifier,[str(images[0]),str(images[0])])
    with pytest.raises(FileNotFoundError):write_duckstation_playlist(identifier,[str(images[0]),str(tmp_path/'missing.chd')],tmp_path/'playlists')
    library.remove(identifier)
    assert not library.db.execute('SELECT * FROM game_discs').fetchall()
    library.close()
    assert all(img.exists() for img in images)


def test_duckstation_playlist_and_args_with_spaces(tmp_path):
    directory=tmp_path/'My PS1 Games';directory.mkdir()
    images=make_discs(directory,count=2,ext='.cue')
    playlist=write_duckstation_playlist(12,[str(p) for p in images],tmp_path/'playlists')
    assert playlist.read_text(encoding='utf-8').splitlines()==[str(p) for p in images]
    assert launch_args('duckstation',playlist)==['-batch','-fullscreen','--',str(playlist)]
    assert launch_args('pcsx2',images[1])==['-batch','-fullscreen','--',str(images[1])]


def test_windows_hotkey_does_not_inject_to_unknown_process():
    assert not send_duckstation_next_disc(set(),api=lambda x:(True,'wrong'))[0]
    assert send_duckstation_next_disc({123},api=lambda x:(x=={123},'sent'))==(True,'sent')


def test_ui_paths_both_modes_and_launch_wiring():
    root=Path(__file__).resolve().parents[1]
    main=(root/'main.py').read_text(encoding='utf-8')
    assert "self.big_switch_btn=click('⇄ Switch Disc',self.switch_disc)" in main
    assert "self.swap_btn=click('⇄  Switch Disc',self.switch_disc)" in main
    assert "boot_path=str(write_duckstation_playlist" in main
    assert "self.session_disc_playlist.add(identifier)" in main
    assert 'System → Change Disc → ISO Selector' in main
    assert "'Switch to Next Disc'" not in main or 'F8' in main

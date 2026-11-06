"""v0.9.33 regressions for Xbox 360 and Dreamcast multi-disc support."""
from pathlib import Path
import ast
import pytest

from core import Library, launch_args, scan_games
from multi_disc import DISC_PLATFORMS, DISC_IMAGE_EXTS, disc_identity, group_candidates, eligible_disc
from version_info import APP_VERSION

ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/'main.py').read_text(encoding='utf-8')


def create_discs(folder, title, ext, count=2):
    result=[]
    for number in range(1, count+1):
        path=folder/f'{title} (Disc {number}) (USA){ext}'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(f'disc content {number}'.encode('ascii'))
        result.append(path)
    return result


@pytest.mark.parametrize('platform,emulator,extension',[
    ('xbox360','xenia','.iso'), ('dreamcast','flycast','.gdi'),
    ('dreamcast','flycast','.cdi'), ('dreamcast','flycast','.chd'),
    ('dreamcast','flycast','.cue'),
])
def test_scanner_merges_one_entry_and_preserves_all_discs(tmp_path,platform,emulator,extension):
    files=create_discs(tmp_path,'Three Discs',extension,count=3)
    lib=Library(tmp_path/'library.sqlite3')
    snapshots=[p.read_bytes() for p in files]
    scanned=scan_games(tmp_path,platform)
    assert len(scanned)==3
    for title,plat,path in scanned:
        assert lib.add(title,plat,emulator,path)
    ids=[g['id'] for g in lib.all()]
    lib.edit(ids[1],seconds_played=113,favorite=1,artwork='custom_cover.png')
    merged=lib.auto_merge_discs()
    assert len(merged)==1
    assert merged[0]['count']==3
    assert len(lib.all())==1
    game=lib.all()[0]
    assert game['disc_count']==3
    assert [d['path'] for d in game['discs']]==[str(file) for file in files]
    assert game['artwork']=='custom_cover.png'
    assert game['favorite']==1
    assert game['seconds_played']==113
    assert lib.auto_merge_discs()==[]
    lib.choose_disc(game['id'],3)
    assert lib.get(game['id'])['selected_disc']==3
    lib.close()
    reopened=Library(tmp_path/'library.sqlite3')
    assert reopened.get(game['id'])['selected_disc']==3
    reopened.close()
    assert snapshots==[p.read_bytes() for p in files]


def test_xenia_extracted_disc_folders_merge_based_on_scanner_labels(tmp_path):
    for number in (1,2):
        folder=tmp_path/f'Lost Odyssey (Disc {number}) (USA)'
        folder.mkdir()
        (folder/'default.xex').write_bytes(b'XEX')
    games=scan_games(tmp_path,'xbox360')
    assert len(games)==2
    lib=Library(tmp_path/'library.sqlite3')
    for title,platform,path in games:
        assert Path(path).name.lower()=='default.xex'
        assert lib.add(title,platform,'xenia',path)
    assert len(lib.auto_merge_discs())==1
    result=lib.all()[0]
    assert result['disc_count']==2
    assert all(Path(d['path']).name=='default.xex' for d in result['discs'])
    lib.close()


def test_disc_set_cannot_merge_different_regions_edition_or_emulator():
    games=[
        dict(id=1,title='Game (Disc 1) (USA)',path='/g/Game (Disc 1) (USA).iso',platform='xbox360',emulator='xenia'),
        dict(id=2,title='Game (Disc 2) (Europe)',path='/g/Game (Disc 2) (Europe).iso',platform='xbox360',emulator='xenia'),
        dict(id=3,title='Game (Disc 2) (USA)',path='/g/Game (Disc 2) (USA).iso',platform='xbox360',emulator='other'),
        dict(id=4,title='Game (Disc 2) (USA)',path='/g/Game (Disc 2) (USA).gdi',platform='dreamcast',emulator='flycast'),
    ]
    assert group_candidates(games)==[]
    assert disc_identity('Shenmue (Disc 1) (Europe)','/dc/Shenmue (Disc 1) (Europe).gdi')==('shenmue (europe)',1)
    assert disc_identity('Discworld','/dc/Discworld.gdi') is None


@pytest.mark.parametrize('platform,extension,wrong',[
    ('xbox360','.iso','.gdi'),('xbox360','.xex','.cue'),
    ('dreamcast','.gdi','.xex'),('dreamcast','.cue','.iso'),
])
def test_console_format_whitelist(platform,extension,wrong):
    assert platform in DISC_PLATFORMS
    assert extension in DISC_IMAGE_EXTS[platform]
    assert eligible_disc(platform,'disc'+extension)
    assert not eligible_disc(platform,'disc'+wrong)
    assert not eligible_disc(platform,'disc.bin')


@pytest.mark.parametrize('platform,emulator,extension',[
    ('xbox360','xenia','.iso'),('dreamcast','flycast','.gdi')
])
def test_manage_discs_and_selected_launch_without_playlist(tmp_path,platform,emulator,extension):
    files=create_discs(tmp_path,'Game',extension)
    lib=Library(tmp_path/'library.sqlite3')
    assert lib.add('Game',platform,emulator,str(files[0]))
    identifier=lib.all()[0]['id']
    lib.set_discs(identifier,[str(p) for p in files])
    with pytest.raises(ValueError,match='primary disc|primary game|Manage Discs'):
        lib.edit(identifier,path=str(files[1]))
    with pytest.raises(ValueError):
        lib.set_discs(identifier,[str(files[0]),str(tmp_path/('not-there'+extension))])
    lib.choose_disc(identifier,2)
    assert lib.get(identifier)['selected_disc']==2
    expected=launch_args(emulator,files[1])
    assert str(files[1]) in expected
    assert '.m3u' not in ' '.join(expected)
    lib.close()


def test_uses_safe_native_guidance_during_running_session():
    tree=ast.parse(MAIN)
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Main')
    swap=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='switch_disc')
    code=ast.unparse(swap)
    assert "'flycast'" in code
    assert "'xenia'" in code
    assert 'QApplication.clipboard().setText(next_image)' in code
    assert 'QMessageBox.StandardButton.Yes' in code
    assert 'self.library.choose_disc' in code
    assert 'launch_selected' not in code
    assert 'subprocess.Popen' not in code
    assert 'session_disc_playlist' in code  # PS1 behavior retained


def test_manage_disc_ui_includes_both_new_platforms():
    assert "if game['platform'] in DISC_PLATFORMS:" in MAIN
    assert 'self.discs_btn.setVisible(game[\'platform\'] in DISC_PLATFORMS)' in MAIN
    assert 'DISC_IMAGE_EXTS[self.game_platform]' in MAIN
    assert "if game['emulator']=='duckstation' and selected==1" in MAIN
    assert APP_VERSION=='0.9.33'

import hashlib
import importlib.util
from pathlib import Path
import zipfile
import pytest
from core import EMULATORS,PLATFORMS,scan_games,launch_args,detect_bundled_executables,launch_command

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bundler',HERE/'BUNDLE_EMULATORS.py')
bundler=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundler)


def test_twelve_emulators_and_new_platforms():
    assert len(EMULATORS)==15
    assert {e.key for e in EMULATORS} >= {'duckstation','pcsx2','ppsspp'}
    assert set(PLATFORMS)>={'ps1','ps2','psp'}


def test_ps1_launch_profile_with_spaces(tmp_path):
    disc=tmp_path/'Gran Turismo (Disc 1).cue';disc.write_text('FILE "track.bin" BINARY\n')
    exe=tmp_path/'duckstation-qt-x64-ReleaseLTCG.exe';exe.write_bytes(b'x')
    cmd,cwd=launch_command(str(exe),'duckstation',str(disc),True)
    assert cmd==[str(exe),'-batch','-fullscreen','--',str(disc)]
    assert cwd==str(tmp_path)
    assert launch_args('duckstation',disc,False)==['-batch','--',str(disc)]


def test_ps2_launch_profile(tmp_path):
    f=tmp_path/'GTA San Andreas.chd';f.write_bytes(b'')
    exe=tmp_path/'pcsx2-qtx64-avx2.exe';exe.write_bytes(b'')
    cmd,_=launch_command(str(exe),'pcsx2',str(f),True)
    assert cmd[-4:]==['-batch','-fullscreen','--',str(f)]


def test_psp_launch_profile(tmp_path):
    f=tmp_path/'GTA LCS.cso';f.write_bytes(b'')
    assert launch_args('ppsspp',f,True)==['--fullscreen',str(f)]
    assert launch_args('ppsspp',f,False)==[str(f)]


def test_game_scanner_systems(tmp_path):
    for name in ['MGS.cue','FF7.chd','ISO Game.iso','Game.cso','Game.pbp']:(tmp_path/name).write_bytes(b'')
    assert {p[0] for p in scan_games(tmp_path,'ps1')} >= {'Mgs','Ff7'}
    assert {x[0] for x in scan_games(tmp_path,'ps2')} >= {'Ff7','Iso Game','Game'}
    assert {x[0] for x in scan_games(tmp_path,'psp')} >= {'Iso Game','Game'}


def test_new_three_autodetected_portably(tmp_path):
    wanted={'duckstation':('duckstation','duckstation-qt-x64-ReleaseLTCG.exe'),
            'pcsx2':('pcsx2','pcsx2-qtx64-avx2.exe'),
            'ppsspp':('ppsspp','PPSSPPWindows64.exe')}
    for sub,exe in wanted.values():
        p=tmp_path/'Emulators'/sub/exe;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'')
    found=detect_bundled_executables(tmp_path)
    assert len(found)==3
    for key,(_,name) in wanted.items():assert found[key].endswith(name)


def test_bundler_rejects_unsafe_zip_path(tmp_path):
    path=tmp_path/'bad.zip'
    with zipfile.ZipFile(path,'w') as z:z.writestr('Emulators 3/pcsx2/../../malicious.exe',b'x')
    with zipfile.ZipFile(path) as z:
        with pytest.raises(ValueError,match='Unsafe'):list(bundler.checked_members(z,'Emulators 3'))


def test_bundler_rejects_case_insensitive_collisions(tmp_path):
    path=tmp_path/'bad.zip'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('Emulators 3/pcsx2/Config.ini',b'x')
        z.writestr('Emulators 3/pcsx2/config.INI',b'y')
    with zipfile.ZipFile(path) as z:
        with pytest.raises(ValueError,match='collision'):list(bundler.checked_members(z,'Emulators 3'))


def test_bundler_extracts_preserving_paths_and_crc(tmp_path):
    path=tmp_path/'sample.zip'
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('Emulators 3/pcsx2/pcsx2-qtx64-avx2.exe',b'executable')
        z.writestr('Emulators 3/pcsx2/resources/somefile.ini',b'config')
    out=tmp_path/'extracted';out.mkdir()
    assert bundler.extract_emulators(path,'Emulators 3',out)==2
    assert (out/'pcsx2'/'pcsx2-qtx64-avx2.exe').read_bytes()==b'executable'
    assert (out/'pcsx2'/'resources'/'somefile.ini').read_bytes()==b'config'


def test_bundler_sha256(tmp_path):
    p=tmp_path/'test.bin';p.write_bytes(b'abc')
    assert bundler.hash_file(p)==hashlib.sha256(b'abc').hexdigest()

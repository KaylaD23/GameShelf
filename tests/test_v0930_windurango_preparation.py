"""WinDurango game preparation must be opt-in, conservative and reversible."""
from pathlib import Path
import ast
import pytest

from core import launch_command
from windurango_support import (
    DEPLOYABLE_DLLS, preparation_plan, apply_preparation_plan,
    prepared_game_executable, find_registration_manifest,
    registration_command, validate_game_path,
)

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'Emulators'/'WinDurango'/'WinDurango.Common.dll'


def new_game(tmp_path, title='Game.exe'):
    folder=tmp_path/'A Game'/'Mount'
    folder.mkdir(parents=True)
    exe=folder/title
    exe.write_bytes(b'fake Xbox One executable')
    return exe


def fake_runtime(tmp_path, contents=None):
    root=tmp_path/'Runtime'
    root.mkdir()
    names=contents or ('WinDurango.Common.dll','kernelx.dll','winrt_x.dll')
    for n in names:
        (root/n).write_bytes(('SOURCE_'+n).encode())
    (root/'WinDurango.Watchdog.exe').write_bytes(b'never copy executable')
    (root/'WinDurango.Common.lib').write_bytes(b'never copy build tools')
    return root/'WinDurango.Common.dll'


def test_missing_dll_error_reproduced_and_preparation_resolves_it(tmp_path):
    exe=new_game(tmp_path)
    dll=fake_runtime(tmp_path)
    with pytest.raises(ValueError, match='not installed'):
        prepared_game_executable(exe)
    plan=preparation_plan(exe,dll)
    assert len(plan.pending)==3
    copied=apply_preparation_plan(plan)
    assert set(copied)=={'WinDurango.Common.dll','kernelx.dll','winrt_x.dll'}
    assert prepared_game_executable(exe)==exe
    cmd,cwd=launch_command(str(dll),'windurango',str(exe),True)
    assert cmd==[str(exe)]
    assert cwd==str(exe.parent)
    assert not (exe.parent/'WinDurango.Watchdog.exe').exists()
    assert not (exe.parent/'WinDurango.Common.lib').exists()


def test_existing_game_dll_is_not_overwritten(tmp_path):
    exe=new_game(tmp_path)
    dll=fake_runtime(tmp_path)
    existing=exe.parent/'kernelx.dll'
    existing.write_bytes(b'game already contains its own version')
    plan=preparation_plan(exe,dll)
    assert 'kernelx.dll' in plan.already_present
    assert 'kernelx.dll' not in {target.name for _, target in plan.pending}
    apply_preparation_plan(plan)
    assert existing.read_bytes()==b'game already contains its own version'


def test_second_application_is_idempotent(tmp_path):
    exe=new_game(tmp_path)
    dll=fake_runtime(tmp_path)
    first=preparation_plan(exe,dll)
    assert apply_preparation_plan(first)
    second=preparation_plan(exe,dll)
    assert not second.pending
    assert apply_preparation_plan(second)==()


def test_fails_closed_when_file_appears_after_confirmation(tmp_path):
    exe=new_game(tmp_path)
    dll=fake_runtime(tmp_path)
    plan=preparation_plan(exe,dll)
    (exe.parent/'kernelx.dll').write_bytes(b'appeared after planning')
    with pytest.raises(FileExistsError):
        apply_preparation_plan(plan)
    assert (exe.parent/'kernelx.dll').read_bytes()==b'appeared after planning'
    assert not (exe.parent/'WinDurango.Common.dll').exists() # first copy rolled back


def test_partial_copy_failure_rolls_back(monkeypatch,tmp_path):
    exe=new_game(tmp_path)
    dll=fake_runtime(tmp_path)
    plan=preparation_plan(exe,dll)
    from windurango_support import _hash_file
    import windurango_support as module
    real=module._hash_file
    def bad(path):
        if str(path).endswith('kernelx.dll') and path.parent == exe.parent:
            return 'bad hash'
        return real(path)
    monkeypatch.setattr(module,'_hash_file',bad)
    with pytest.raises(IOError,match='verification failed'):
        apply_preparation_plan(plan)
    assert not list(exe.parent.glob('*.dll'))


def test_symlink_conflicts_refused_when_supported(tmp_path):
    exe=new_game(tmp_path)
    dll=fake_runtime(tmp_path)
    target=tmp_path/'unchanged.dll'
    target.write_bytes(b'not touched')
    link=exe.parent/'kernelx.dll'
    try:link.symlink_to(target)
    except (OSError,NotImplementedError):pytest.skip('system does not support symlinks')
    with pytest.raises(ValueError,match='symbolic link'):
        preparation_plan(exe,dll)
    assert target.read_bytes()==b'not touched'


def test_case_insensitive_filename_conflicts(tmp_path):
    exe=new_game(tmp_path)
    dll=fake_runtime(tmp_path)
    collision=exe.parent/'KERNELX.DLL'
    collision.write_bytes(b'original')
    plan=preparation_plan(exe,dll)
    assert 'KERNELX.DLL' in plan.already_present
    assert 'kernelx.dll' not in [p.name for _,p in plan.pending]
    apply_preparation_plan(plan)
    assert collision.read_bytes()==b'original'


@pytest.mark.parametrize('filename',('Game.iso','Xbox.xvc','AppxManifest.xml','WinDurango.Watchdog.exe','setup.exe'))
def test_unlaunchable_inputs_are_rejected(tmp_path,filename):
    bad=tmp_path/filename
    bad.write_bytes(b'invalid')
    with pytest.raises(ValueError):validate_game_path(bad)


def test_missing_runtime_fails_without_changing_game(tmp_path):
    exe=new_game(tmp_path)
    with pytest.raises(FileNotFoundError):
        preparation_plan(exe,tmp_path/'missing'/'WinDurango.Common.dll')
    assert set(p.name for p in exe.parent.iterdir())=={'Game.exe'}


def test_manifest_command_is_manual_and_escapes_single_quote(tmp_path):
    exe=new_game(tmp_path/'Player\'s Games')
    manifest=exe.parent.parent/'AppxManifest.xml'
    manifest.write_text('<Package/>', encoding='utf-8')
    assert find_registration_manifest(exe)==manifest
    plan=preparation_plan(exe,fake_runtime(tmp_path))
    assert plan.manifest==manifest
    command=registration_command(manifest)
    assert command.startswith('Add-AppxPackage -Register -Path')
    assert "''" in command
    assert 'Player' in command


def test_no_manifest_command_for_unprepared_game(tmp_path):
    exe=new_game(tmp_path)
    assert find_registration_manifest(exe) is None


def test_ui_has_manual_preparation_and_launch_recovery():
    source=(ROOT/'main.py').read_text(encoding='utf-8')
    parsed=ast.parse(source)
    assert any(getattr(node,'name',None)=='prepare_windurango_game' for node in parsed.body)
    assert "self.windurango_prepare_btn=click('Prepare WinDurango Game…'" in source
    assert "self.windurango_prepare=click('Prepare WinDurango Game…'" in source
    assert 'QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No' in source
    assert "if game['emulator']=='windurango' and isinstance(exc,ValueError)" in source
    assert 'apply_preparation_plan(plan)' in source


def test_bundled_runtime_plan_has_real_sources(tmp_path):
    exe=new_game(tmp_path)
    plan=preparation_plan(exe,SOURCE)
    assert any(path.name=='WinDurango.Common.dll' for path,_ in plan.pending)
    assert all(path.name in DEPLOYABLE_DLLS and path.is_file() for path,_ in plan.pending)
    assert all(path.suffix.lower()=='.dll' for path,_ in plan.pending)

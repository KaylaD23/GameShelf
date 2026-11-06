"""WinDurango's per-title dependency deployment and startup failure diagnosis."""
from pathlib import Path
import ast
import pytest

from windurango_support import (
    preparation_plan, apply_preparation_plan, game_dependency_status,
    find_embedded_xvd, GAME_DEPENDENCY_DLLS,
)
import windurango_support as module
from windurango_diagnostics import (
    status_name, manifest_identity, create_diagnostic_report,
    windows_registration_status, registered_app_launch_command,
)

ROOT = Path(__file__).resolve().parents[1]


def setup_game(tmp_path, *, with_embedded=True):
    root=tmp_path/'Game'
    mount=root/'Mount'
    mount.mkdir(parents=True)
    exe=mount/'MinecraftClient.exe'
    exe.write_bytes(b'test executable')
    embedded=root/'EmbeddedXvd'
    if with_embedded:
        embedded.mkdir()
        (embedded/'xg_x.dll').write_bytes(b'game-xg')
        (embedded/'AcpHal.dll').write_bytes(b'game-acp')
    runtime=tmp_path/'Runtime'
    runtime.mkdir()
    (runtime/'WinDurango.Common.dll').write_bytes(b'runtime-marker')
    (runtime/'kernelx.dll').write_bytes(b'runtime-kernel')
    return exe, runtime/'WinDurango.Common.dll', embedded


def test_official_dependency_names():
    assert set(GAME_DEPENDENCY_DLLS)=={
        'xg_x.dll','xg.dll','AcpHal.dll','xaudio2_9.dll',
        'D3DCompiler46.dll','sc_dll.dll',
    }


def test_extra_game_dlls_are_found_and_copied_opt_in(tmp_path):
    exe,marker,embedded=setup_game(tmp_path)
    plan=preparation_plan(exe,marker)
    assert find_embedded_xvd(exe)==embedded
    assert {dst.name for _,dst in plan.game_specific_pending}=={'xg_x.dll','AcpHal.dll'}
    assert {dst.name for _,dst in plan.pending}=={
        'WinDurango.Common.dll','kernelx.dll','xg_x.dll','AcpHal.dll'}
    # Planning is read-only; installation only occurs through explicit apply.
    assert not (exe.parent/'xg_x.dll').exists()
    added=apply_preparation_plan(plan)
    assert set(added)=={'WinDurango.Common.dll','kernelx.dll','xg_x.dll','AcpHal.dll'}
    assert (exe.parent/'xg_x.dll').read_bytes()==b'game-xg'
    assert (exe.parent/'AcpHal.dll').read_bytes()==b'game-acp'
    again=preparation_plan(exe,marker)
    assert again.pending==()


def test_game_specific_existing_dll_never_overwritten(tmp_path):
    exe,marker,_=setup_game(tmp_path)
    (exe.parent/'XG_X.DLL').write_bytes(b'keep original')
    plan=preparation_plan(exe,marker)
    assert all(dst.name!='xg_x.dll' for _,dst in plan.pending)
    apply_preparation_plan(plan)
    assert (exe.parent/'XG_X.DLL').read_bytes()==b'keep original'


def test_game_specific_missing_embedded_does_not_fake_success(tmp_path):
    exe,marker,_=setup_game(tmp_path,with_embedded=False)
    state=game_dependency_status(exe)
    assert state['embedded_xvd'] is None
    assert 'xg_x.dll' in state['not_located']
    report=create_diagnostic_report(exe,marker,include_windows=False)
    assert 'EmbeddedXvd: NOT FOUND' in report
    assert 'DLL presence does not prove UWP registration' in report


def test_game_deployment_rolls_back_after_hash_failure(tmp_path,monkeypatch):
    exe,marker,_=setup_game(tmp_path)
    original=module._hash_file
    def wrong_hash(path):
        if path.parent==exe.parent and path.name.lower()=='xg_x.dll':
            return 'broken-hash'
        return original(path)
    monkeypatch.setattr(module,'_hash_file',wrong_hash)
    with pytest.raises(IOError,match='verification failed'):
        apply_preparation_plan(preparation_plan(exe,marker))
    assert not list(exe.parent.glob('*.dll'))


def test_embedded_file_symlink_is_rejected(tmp_path):
    exe,marker,embedded=setup_game(tmp_path)
    (embedded/'xg_x.dll').unlink()
    target=tmp_path/'outside.dll';target.write_bytes(b'should not copy')
    try:(embedded/'xg_x.dll').symlink_to(target)
    except (OSError,NotImplementedError):pytest.skip('symlinks unavailable')
    with pytest.raises(ValueError,match='linked game dependency'):
        preparation_plan(exe,marker)
    assert target.read_bytes()==b'should not copy'


def test_manifest_identity_and_safe_registration_diagnosis(tmp_path,monkeypatch):
    exe,marker,_=setup_game(tmp_path)
    mf=exe.parent.parent/'AppxManifest.xml'
    mf.write_text('''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">
      <Identity Name="Microsoft.Xbox.Sample" Version="1.0.0.0" Publisher="CN=Test" />
      <Applications><Application Id="SampleApp" Executable="Mount\\MinecraftClient.exe" /></Applications>
    </Package>''',encoding='utf-8')
    assert manifest_identity(mf)==('Microsoft.Xbox.Sample','SampleApp')
    import windurango_diagnostics as diag
    captured=[]
    monkeypatch.setattr(diag,'_powershell',lambda script,**k: captured.append(script) or 'NOT REGISTERED')
    assert windows_registration_status(mf)=='NOT REGISTERED'
    assert 'Get-AppxPackage' in captured[0]
    report=create_diagnostic_report(exe,marker,include_windows=False)
    assert 'Microsoft.Xbox.Sample' in report
    assert 'Add-AppxPackage -Register' in report
    assert 'Start-Process explorer.exe' in report
    assert 'shell:AppsFolder' in registered_app_launch_command(mf)
    assert 'AppxManifest.xml' in report


@pytest.mark.parametrize('code,contains',[
    (0xC0000142,'STATUS_DLL_INIT_FAILED'),
    (-1073741502,'STATUS_DLL_INIT_FAILED'),
    (0xC0000135,'STATUS_DLL_NOT_FOUND'),
    (0xC000007B,'STATUS_INVALID_IMAGE_FORMAT'),
    (1,'0x00000001'),
    (None,'unknown exit'),
])
def test_win_exit_status_explained(code,contains):
    assert contains in status_name(code)


def test_gui_handles_crash_and_contains_diagnostic_button():
    source=(ROOT/'main.py').read_text(encoding='utf-8')
    ast.parse(source)
    assert "self.windurango_diagnose_btn=click('Diagnose WinDurango Launch…'" in source
    assert 'failure=status_name(code)' in source
    assert "if answer==QMessageBox.StandardButton.Yes:" in source
    assert 'create_diagnostic_report(' in source
    assert 'startup not verified' in source


def test_new_files_registered_with_installer():
    updater=ROOT.parent/'update_existing_gameshelf.py'
    source=updater.read_text(encoding='utf-8')
    assert 'windurango_diagnostics.py' in source
    assert 'README_V0931.txt' in source
    assert 'RELEASE = "0.9.33"' in source

"""Integration regressions for a misplaced sibling EmbeddedXvd and C++ startup failures."""
from pathlib import Path
import ast
import os
import pytest

from windurango_support import (
    embedded_xvd_relocation_plan, relocate_embedded_xvd, game_dependency_status,
    preparation_plan, apply_preparation_plan,
)
from windurango_diagnostics import create_diagnostic_report, status_name

ROOT=Path(__file__).resolve().parents[1]


def fixture(tmp_path):
    root=tmp_path/'Minecraft'
    mount=root/'Mount'
    mount.mkdir(parents=True)
    exe=mount/'Minecraft.Client.exe'
    exe.write_bytes(b'test-exe')
    misplaced=root/'EmbeddedXvd'
    misplaced.mkdir()
    (misplaced/'resources.dat').write_bytes(b'unchanged game content')
    (misplaced/'xg.dll').write_bytes(b'game-specific component')
    runtime=tmp_path/'WinDurango'
    runtime.mkdir()
    marker=runtime/'WinDurango.Common.dll'
    marker.write_bytes(b'test-runtime')
    return exe, misplaced, marker


def test_fixes_exact_minecraft_sibling_layout(tmp_path):
    exe, misplaced, marker=fixture(tmp_path)
    target=exe.parent/'EmbeddedXvd'
    assert embedded_xvd_relocation_plan(exe)==(misplaced,target)
    report=create_diagnostic_report(exe,marker,include_windows=False)
    assert 'WARNING: EmbeddedXvd is not alongside the game executable' in report
    assert 'ACTION: Use GameShelf > Prepare WinDurango Game' in report
    assert relocate_embedded_xvd(exe)==(misplaced,target)
    assert not misplaced.exists()
    assert (target/'resources.dat').read_bytes()==b'unchanged game content'
    assert (target/'xg.dll').read_bytes()==b'game-specific component'
    assert embedded_xvd_relocation_plan(exe) is None
    second=create_diagnostic_report(exe,marker,include_windows=False)
    assert 'WARNING: EmbeddedXvd is not alongside' not in second
    assert 'EmbeddedXvd: '+str(target) in second
    plan=preparation_plan(exe,marker)
    assert 'xg.dll' in [x.name for x,_ in plan.game_specific_pending]
    assert 'xg.dll' in apply_preparation_plan(plan)
    assert (exe.parent/'xg.dll').read_bytes()==b'game-specific component'


def test_repeated_preparation_is_noop(tmp_path):
    exe, _, _=fixture(tmp_path)
    assert relocate_embedded_xvd(exe) is not None
    assert relocate_embedded_xvd(exe) is None


def test_never_overwrites_existing_target(tmp_path):
    exe, misplaced, _=fixture(tmp_path)
    target=exe.parent/'EmbeddedXvd'
    target.mkdir()
    (target/'existing.bin').write_bytes(b'important')
    # Already correctly placed is treated as installed, never replaced.
    assert embedded_xvd_relocation_plan(exe) is None
    assert relocate_embedded_xvd(exe) is None
    assert misplaced.exists()
    assert (target/'existing.bin').read_bytes()==b'important'


def test_case_insensitive_conflict_when_folder_is_not_named_identically(tmp_path):
    exe, misplaced, _=fixture(tmp_path)
    target=exe.parent/'embeddedXVD'
    target.mkdir()
    assert embedded_xvd_relocation_plan(exe) is None
    assert relocate_embedded_xvd(exe) is None
    assert misplaced.exists()


def test_rejects_linked_source(tmp_path):
    exe, misplaced, _=fixture(tmp_path)
    misplaced.rename(tmp_path/'actual')
    try:misplaced.symlink_to(tmp_path/'actual', target_is_directory=True)
    except (OSError,NotImplementedError):pytest.skip('directory symbolic links unavailable')
    # The discovery function intentionally rejects symlinked game directories.
    assert embedded_xvd_relocation_plan(exe) is None
    assert relocate_embedded_xvd(exe) is None
    assert (tmp_path/'actual'/'resources.dat').read_bytes()==b'unchanged game content'


def test_path_does_not_exist_no_destructive_action(tmp_path):
    exe, misplaced, _=fixture(tmp_path)
    for file in misplaced.iterdir():file.unlink()
    misplaced.rmdir()
    assert relocate_embedded_xvd(exe) is None


@pytest.mark.parametrize('code,expected',[
    (0xE06D7363,'unhandled Microsoft C++ exception'),
    (-530450845,'0xE062E063'),  # Any other code is still printed, never mislabelled.
    (0xC0000142,'STATUS_DLL_INIT_FAILED'),
])
def test_exception_classification(code,expected):
    if code==-530450845:
        assert status_name(code).startswith('0x')
    else:
        assert expected in status_name(code)


def test_ui_and_release_wiring():
    source=(ROOT/'main.py').read_text(encoding='utf-8')
    ast.parse(source)
    assert 'relocate_embedded_xvd(game_executable)' in source
    assert 'QMessageBox.question(' in source
    assert 'Close the game before proceeding.' in source
    assert 'if choice!=QMessageBox.StandardButton.Yes:' in source
    assert 'EmbeddedXvd relocation failed' in source
    updater=(ROOT.parent/'update_existing_gameshelf.py').read_text(encoding='utf-8')
    assert 'RELEASE = "0.9.33"' in updater
    assert 'README_V0932.txt' in updater

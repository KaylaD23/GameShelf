"""Regression coverage for safe RetroAchievements native setup."""
from pathlib import Path
import ast
import pytest

from retro_achievements import (SUPPORTED, configure, configure_all, paths_for,
                                apply_config, locate_config, enable_in_text)


@pytest.mark.parametrize('key,section,option,expected',[ 
 ('duckstation','Cheevos','Enabled','true'),
 ('pcsx2','Achievements','Enabled','true'),
 ('ppsspp','Achievements','AchievementsEnable','True'),
 ('dolphin','Achievements','Enabled','True'),
])
def test_known_native_fields(key,section,option,expected):
    assert SUPPORTED[key][1:]==(section,option,expected)


def test_patch_preserves_unrelated_settings_and_secrets():
    original='[Cheevos]\r\nEnabled = false\r\nUsername = player\r\nToken = SECRET\r\n[Audio]\r\nVolume = 35\r\n'
    result,changed=enable_in_text(original,'Cheevos','Enabled','true')
    assert changed
    assert result=='[Cheevos]\r\nEnabled = true\r\nUsername = player\r\nToken = SECRET\r\n[Audio]\r\nVolume = 35\r\n'
    unchanged,is_changed=enable_in_text(result,'Cheevos','Enabled','true')
    assert not is_changed and unchanged==result


def test_patch_missing_section():
    result,changed=enable_in_text('[Audio]\nVolume=35','Achievements','Enabled','True')
    assert changed and result.endswith('[Achievements]\nEnabled = True\n')


def test_file_round_trip_keeps_password_comments_and_bom(tmp_path):
    cfg=tmp_path/'settings.ini'
    cfg.write_bytes(b'\xef\xbb\xbf[Cheevos]\r\nEnabled = false  ; user note\r\nToken = real-secret\r\n')
    r=apply_config('duckstation',cfg)
    assert r.status=='enabled'
    assert cfg.read_bytes()==b'\xef\xbb\xbf[Cheevos]\r\nEnabled = true  ; user note\r\nToken = real-secret\r\n'
    assert apply_config('duckstation',cfg).status=='already_enabled'
    assert not list(tmp_path.glob('.gameshelf_ra_*'))


@pytest.mark.parametrize('key,filename,section,option',[ 
 ('pcsx2','inis/PCSX2.ini','Achievements','Enabled'),
 ('ppsspp','memstick/PSP/SYSTEM/ppsspp.ini','Achievements','AchievementsEnable'),
 ('duckstation','settings.ini','Cheevos','Enabled'),
])
def test_locates_portable_emulator_and_enables(key,filename,section,option,tmp_path):
    exe=tmp_path/'emulator.exe';exe.write_text('stub')
    cfg=tmp_path/filename;cfg.parent.mkdir(parents=True,exist_ok=True)
    cfg.write_text(f'[{section}]\n{option} = false\nOther = value\n')
    assert locate_config(key,exe,{'USERPROFILE':str(tmp_path/'u')})==cfg
    result=configure(key,exe,{'USERPROFILE':str(tmp_path/'u')})
    assert result.status=='enabled'
    assert 'Other = value' in cfg.read_text()
    assert f'{option} = true'.lower() in cfg.read_text().lower()


def test_dolphin_creates_achievements_only_for_proven_profile(tmp_path):
    exe=tmp_path/'Dolphin.exe';exe.write_bytes(b'')
    assert configure('dolphin',exe,{'USERPROFILE':str(tmp_path/'empty')}).status=='config_not_found'
    folder=tmp_path/'User'/'Config';folder.mkdir(parents=True)
    (folder/'Dolphin.ini').write_text('[Core]\nSkipIPL = True\n')
    result=configure('dolphin',exe,{'USERPROFILE':str(tmp_path/'empty')})
    assert result.status=='enabled'
    assert (folder/'Achievements.ini').read_text()=='[Achievements]\nEnabled = True\n'
    assert (folder/'Dolphin.ini').read_text()=='[Core]\nSkipIPL = True\n'


def test_missing_emulator_config_unsupported_never_creates(tmp_path):
    exe=tmp_path/'emu.exe';exe.write_text('stub')
    assert configure('rpcs3',exe).status=='unsupported'
    assert configure('duckstation',exe,{'USERPROFILE':str(tmp_path/'empty')}).status=='config_not_found'
    assert configure('pcsx2',tmp_path/'missing.exe').status=='missing_executable'
    assert sorted(p.name for p in tmp_path.iterdir())==['emu.exe']


def test_setup_all_one_failure_does_not_interrupt_rest(tmp_path):
    exe=tmp_path/'emu.exe';exe.write_text('stub')
    cfg=tmp_path/'settings.ini';cfg.write_text('[Cheevos]\nEnabled=false\n')
    results=configure_all({'duckstation':str(exe)}, {'USERPROFILE':str(tmp_path/'empty')})
    assert [r.status for r in results].count('enabled')==1
    assert [r.status for r in results].count('missing_executable')==3


def test_ui_connected_and_version():
    root=Path(__file__).resolve().parents[1]
    main=(root/'main.py').read_text()
    assert 'Auto-configure RetroAchievements' in main
    assert "row.addWidget(click('Enable RA'" in main
    assert 'self.configure_ra_all' in main
    assert "self.settings.values['ra_auto_configure']" in main
    assert "if self.settings.values.get('ra_auto_configure')" in main
    ast.parse(main)
    assert (root/'VERSION.txt').read_text().strip()=='0.9.33'
    assert '"retro_achievements.py"' in (root.parent/'update_existing_gameshelf.py').read_text()

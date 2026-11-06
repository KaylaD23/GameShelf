"""v0.9.33: registered UWP launch, exact AppX matching and process ownership."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from uwp_activation import (
    ActivationError, choose_registered_package, query_registered_package,
    app_target, launch_registered_game, ActivatedAppProcess, _guid,
)
from emulator_lifecycle import EmulatorProcessMonitor

ROOT = Path(__file__).resolve().parents[1]


def package(name='Minecraft', location=r'D:\Xbox One Games\minecraft_lce_xb1\Mount', family='Minecraft_zjr0dfhgjwvde'):
    return {'Name':name, 'InstallLocation':location, 'PackageFamilyName':family}


def test_exact_install_location_only():
    chosen=choose_registered_package([
        package(location=r'D:\other\Mount',family='Minecraft_wrong'),
        package(location=r'd:/XBOX ONE GAMES/minecraft_lce_xb1/Mount/'),
    ],'Minecraft',r'D:\Xbox One Games\minecraft_lce_xb1\Mount')
    assert chosen=='Minecraft_zjr0dfhgjwvde'
    with pytest.raises(ActivationError,match='exactly one'):
        choose_registered_package([package(location=r'D:\other\Mount')],'Minecraft',r'D:\Games\Mount')
    with pytest.raises(ActivationError,match='exactly one'):
        choose_registered_package([package(),package()], 'Minecraft',r'D:\Xbox One Games\minecraft_lce_xb1\Mount')
    with pytest.raises(ActivationError):
        choose_registered_package([package(family='not-a-package')], 'Minecraft',r'D:\Xbox One Games\minecraft_lce_xb1\Mount')


def test_windows_registration_query_does_not_register_or_execute_user_data():
    commands=[]
    def fake_runner(argv,**kwargs):
        commands.append(argv)
        return SimpleNamespace(returncode=0,stdout=json.dumps([package()]),stderr='')
    result=query_registered_package('Minecraft',r'D:\Xbox One Games\minecraft_lce_xb1\Mount',runner=fake_runner)
    assert result=='Minecraft_zjr0dfhgjwvde'
    script=commands[0][-1]
    assert 'Get-AppxPackage' in script
    assert 'Add-AppxPackage' not in script
    assert 'Start-Process' not in script
    assert 'Minecraft' in script
    with pytest.raises(ActivationError,match='Invalid'):
        query_registered_package("Minecraft'; Remove-Item C:\\ -Recurse; '",r'D:\Games',runner=fake_runner)


def test_manifest_used_for_exact_package_identity(tmp_path):
    mount=tmp_path/'minecraft'/'Mount';mount.mkdir(parents=True)
    exe=mount/'Minecraft.Client.exe';exe.write_bytes(b'test')
    (mount/'WinDurango.Common.dll').write_bytes(b'test')
    (mount/'AppxManifest.xml').write_text('''<Package><Identity Name="Minecraft" />
    <Applications><Application Id="App" Executable="Minecraft.Client.exe"/></Applications></Package>''')
    calls=[]
    def lookup(name,location):
        calls.append((name,location))
        return 'Minecraft_zjr0dfhgjwvde'
    assert app_target(exe,package_lookup=lookup)=='Minecraft_zjr0dfhgjwvde!App'
    assert calls==[('Minecraft',str(mount.resolve()))]
    seen=[]
    result=launch_registered_game(exe,package_lookup=lookup,
           activate=lambda target:seen.append(target) or 138,
           process_factory=lambda pid:SimpleNamespace(pid=pid,poll=lambda:None))
    assert seen==['Minecraft_zjr0dfhgjwvde!App']
    assert result.pid==138


def test_no_direct_exe_retry_when_activation_fails(tmp_path,monkeypatch):
    import core, uwp_activation
    marker=tmp_path/'WinDurango.Common.dll';marker.write_bytes(b'dll')
    exe=tmp_path/'Game.exe';exe.write_bytes(b'binary')
    (tmp_path/'WinDurango.Common.dll').write_bytes(b'dll')
    (tmp_path/'AppxManifest.xml').write_text('<Package><Identity Name="Game" /><Applications><Application Id="App" /></Applications></Package>')
    # Bypass the earlier Windows registration text check to isolate the launch
    # decision, and never create a real subprocess in this test.
    monkeypatch.setattr(core,'launch_command',lambda *a,**kw:([str(exe)],str(tmp_path)))
    monkeypatch.setattr(core,'os',SimpleNamespace(name='nt'))
    monkeypatch.setattr(uwp_activation,'launch_registered_game',lambda *a,**kw:(_ for _ in ()).throw(ActivationError('activation refused')))
    with pytest.raises(ActivationError,match='activation refused'):
        core.launch(str(marker),'windurango',str(exe),True)


class FakeKernel:
    def __init__(self):
        self.alive=True;self.code=0xE06D7363;self.closed=[]
        self.OpenProcess=lambda flags,inherit,pid: 1234
        self.WaitForSingleObject=lambda handle,timeout: (0x102 if self.alive else 0)
        self.GetExitCodeProcess=lambda handle,ptr:self._getexit(handle,ptr)
        self.CloseHandle=lambda handle:self.closed.append(handle) or 1
    def _getexit(self,handle,ptr):
        import ctypes
        ctypes.cast(ptr,ctypes.POINTER(ctypes.c_uint32)).contents.value=self.code
        return 1


def test_native_pid_handle_monitoring_and_exit_code():
    k=FakeKernel();proc=ActivatedAppProcess(2222,kernel=k)
    monitor=EmulatorProcessMonitor(proc,process_api=None)
    assert proc.pid==2222 and proc.poll() is None
    assert monitor.running()
    k.alive=False
    assert proc.poll()==0xE06D7363
    assert proc.poll()==0xE06D7363
    assert k.closed==[1234]
    assert not monitor.running()


def test_installer_diagnostic_and_gui_wiring():
    updated=(ROOT.parent/'update_existing_gameshelf.py').read_text(encoding='utf-8')
    assert 'RELEASE = "0.9.33"' in updated
    assert '"uwp_activation.py"' in updated
    assert '"README_V0933.txt"' in updated
    source=(ROOT/'main.py').read_text(encoding='utf-8')
    assert 'Windows accepted AppX activation' in source
    assert 'GameShelf launch mode: Windows registered-app activation' in (ROOT/'windurango_diagnostics.py').read_text(encoding='utf-8')
    assert (ROOT/'VERSION.txt').read_text().strip()=='0.9.33'
    ast.parse((ROOT/'uwp_activation.py').read_text())


def test_windows_interface_guid_structure():
    assert bytes(_guid('45BA127D-10A8-46EA-8AB7-56EA9078943C'))==__import__('uuid').UUID('45BA127D-10A8-46EA-8AB7-56EA9078943C').bytes_le

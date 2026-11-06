"""Launch registered WinDurango/UWP games using Windows package activation.

No registration, DLL writing, security changes or executable substitution occur.
The Windows activation API returns a real game PID, unlike launching explorer.exe.
"""
from __future__ import annotations

import ctypes
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import uuid

from windurango_diagnostics import manifest_identity, _ps_literal
from windurango_support import find_registration_manifest, prepared_game_executable


class ActivationError(RuntimeError):
    pass


def _norm_windows_path(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(str(path).replace('/', '\\').rstrip('\\')))


def choose_registered_package(packages, identity_name: str, installed_at: str) -> str:
    """Pick ONLY the package registered at the intended game installation path.

    Matches names exactly and refuses duplicates; never silently launches a
    different build registered elsewhere under the same package name.
    """
    if isinstance(packages, dict):
        packages=[packages]
    if not isinstance(packages,list):
        raise ActivationError('Windows returned an unexpected AppX package list.')
    matches=[]
    for record in packages:
        if not isinstance(record,dict):continue
        family=record.get('PackageFamilyName') or ''
        name=record.get('Name') or ''
        root=record.get('InstallLocation') or ''
        if (isinstance(name,str) and name.casefold()==identity_name.casefold() and
            isinstance(root,str) and root and _norm_windows_path(root)==_norm_windows_path(installed_at) and
            isinstance(family,str) and re.fullmatch(r'[A-Za-z0-9_.-]+_[A-Za-z0-9]+', family)):
            matches.append(family)
    if len(matches)!=1:
        raise ActivationError(
            'Expected exactly one registered AppX package at this game folder, '
            f'but found {len(matches)}. Check registration and InstallLocation in Diagnose WinDurango Launch. '
            'GameShelf will not launch a different game build or fall back to direct .exe startup.')
    return matches[0]


def query_registered_package(name: str, install_location: str, *, runner=None) -> str:
    """Read-only PowerShell query. Never runs a script taken from game metadata."""
    if os.name!='nt' and runner is None:
        raise ActivationError('Windows AppX activation requires Windows.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
        raise ActivationError('Invalid AppX Identity.Name in the game manifest.')
    script=("$ErrorActionPreference='Stop'; "
            "$name="+_ps_literal(name)+"; "
            "$results=@(Get-AppxPackage -Name $name | Where-Object { $_.Name -eq $name } | "
            "Select-Object Name,PackageFamilyName,InstallLocation); "
            "ConvertTo-Json -InputObject $results -Compress -Depth 4")
    runner=runner or subprocess.run
    try:
        result=runner(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
                      capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=12,
                      creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise ActivationError(f'Could not query installed AppX packages: {exc}') from exc
    if result.returncode:
        raise ActivationError('Windows AppX package lookup failed: '+(result.stderr or result.stdout).strip()[:350])
    try:
        payload=json.loads(result.stdout.strip())
    except (json.JSONDecodeError,ValueError) as exc:
        raise ActivationError('Windows returned invalid AppX registration information.') from exc
    return choose_registered_package(payload,name,install_location)


def app_target(game_path: str | Path, *, package_lookup=query_registered_package) -> str:
    exe=prepared_game_executable(game_path)
    manifest=find_registration_manifest(exe)
    ident=manifest_identity(manifest)
    if not ident or not ident[0] or not ident[1]:
        raise ActivationError('No AppxManifest.xml with Identity.Name and Application.Id found. '
                              'Use Prepare WinDurango Game and register the game in Windows.')
    # Resolve against the exact directory that Windows registered, not a similarly
    # named package in another folder. Check both alongside and above the .exe,
    # since some games put the manifest one level above Mount.
    family=package_lookup(ident[0],str(manifest.parent.resolve()))
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',ident[1]):
        raise ActivationError('Invalid Application.Id in AppxManifest.xml.')
    return family+'!'+ident[1]


class _GUID(ctypes.Structure):
    _fields_=[('Data1',ctypes.c_uint32),('Data2',ctypes.c_uint16),('Data3',ctypes.c_uint16),
              ('Data4',ctypes.c_ubyte*8)]


def _guid(value: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


def activate_registered_app(aumid: str) -> int:
    """Activate an installed package via Microsoft's IApplicationActivationManager.

    Returns the actual Windows app PID for session monitoring. This function is
    Windows-only and intentionally never executes a game's .exe directly.
    """
    if os.name!='nt':
        raise ActivationError('AppX activation is only available on Windows.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+_[A-Za-z0-9]+![A-Za-z0-9_.-]+',aumid):
        raise ActivationError('Invalid Windows AppUserModelID.')
    ole32=ctypes.OleDLL('ole32')
    ole32.CoInitializeEx.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
    ole32.CoInitializeEx.restype=ctypes.c_long
    ole32.CoCreateInstance.argtypes=[ctypes.POINTER(_GUID),ctypes.c_void_p,ctypes.c_uint32,
                                     ctypes.POINTER(_GUID),ctypes.POINTER(ctypes.c_void_p)]
    ole32.CoCreateInstance.restype=ctypes.c_long
    ole32.CoUninitialize.argtypes=[]
    ole32.CoUninitialize.restype=None
    init=ole32.CoInitializeEx(None,2) # COINIT_APARTMENTTHREADED
    # RPC_E_CHANGED_MODE means COM is already initialised in a different mode;
    # it is safe to use COM but we must not call CoUninitialize ourselves.
    owned=init in (0,1)
    if init not in (0,1,-2147417850):
        raise ActivationError(f'CoInitializeEx failed: 0x{init&0xffffffff:08X}')
    interface=ctypes.c_void_p()
    try:
        clsid=_guid('45BA127D-10A8-46EA-8AB7-56EA9078943C')
        iid=_guid('2E941141-7F97-4756-BA1D-9DECDE894A3D')
        hr=ole32.CoCreateInstance(ctypes.byref(clsid),None,4,ctypes.byref(iid),ctypes.byref(interface))
        if hr<0 or not interface.value:
            raise ActivationError(f'Windows application activation service unavailable: 0x{hr&0xffffffff:08X}')
        vtable=ctypes.cast(interface,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        act=ctypes.WINFUNCTYPE(ctypes.c_long,ctypes.c_void_p,ctypes.c_wchar_p,
                              ctypes.c_wchar_p,ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32))(vtable[3])
        pid=ctypes.c_uint32()
        hr=act(interface,aumid,None,0,ctypes.byref(pid))
        if hr<0 or not pid.value:
            raise ActivationError('Windows rejected registered-app activation: '
                                  f'0x{hr&0xffffffff:08X}. Check package registration and WinDurango compatibility.')
        return int(pid.value)
    finally:
        if interface.value:
            vtable=ctypes.cast(interface,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            release=ctypes.WINFUNCTYPE(ctypes.c_uint32,ctypes.c_void_p)(vtable[2])
            release(interface)
        if owned:ole32.CoUninitialize()


class ActivatedAppProcess:
    """Popen-like non-child process wrapper backed by a real Windows PID handle.

    Works with GameShelf's existing EmulatorProcessMonitor without claiming that
    Windows package activation proves a game has rendered or begun gameplay.
    """
    def __init__(self,pid:int,*,kernel=None):
        if pid<=0:raise ActivationError('Invalid application process ID returned by Windows.')
        if os.name!='nt' and kernel is None:
            raise ActivationError('Windows process monitoring requires Windows.')
        self.pid=pid
        self._kernel=kernel or ctypes.WinDLL('kernel32',use_last_error=True)
        k=self._kernel
        k.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]
        k.OpenProcess.restype=ctypes.c_void_p
        k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
        k.WaitForSingleObject.restype=ctypes.c_uint32
        k.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)]
        k.GetExitCodeProcess.restype=ctypes.c_int
        k.CloseHandle.argtypes=[ctypes.c_void_p]
        k.CloseHandle.restype=ctypes.c_int
        self._handle=k.OpenProcess(0x00101000,False,pid) # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
        if not self._handle:
            raise ActivationError('Windows activated the app but denied GameShelf access to its process handle. '
                                  'Check Windows permissions and GameShelf logs.')
        self._exit_code=None
    def poll(self):
        if self._exit_code is not None:return self._exit_code
        if not self._handle:return self._exit_code
        wait=self._kernel.WaitForSingleObject(self._handle,0)
        if wait==0x102:return None # WAIT_TIMEOUT
        if wait==0: # WAIT_OBJECT_0
            code=ctypes.c_uint32()
            if self._kernel.GetExitCodeProcess(self._handle,ctypes.byref(code)):
                self._exit_code=code.value
                self.close()
                return self._exit_code
        # Do not falsely report successful termination on an API error.
        raise ActivationError(f'Could not monitor registered game process PID {self.pid} (wait result 0x{wait:08X}).')
    def close(self):
        if getattr(self,'_handle',None):
            self._kernel.CloseHandle(self._handle)
            self._handle=None
    def __del__(self):
        try:self.close()
        except (OSError,AttributeError):pass


def launch_registered_game(game_path: str | Path,*,package_lookup=query_registered_package,
                           activate=activate_registered_app,process_factory=ActivatedAppProcess):
    target=app_target(game_path,package_lookup=package_lookup)
    pid=activate(target)
    return process_factory(pid)

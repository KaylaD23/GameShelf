"""Read-only Windows startup diagnostics for WinDurango game executables.

No package registration, installation, network access, or security setting
changes are performed here. PowerShell is only invoked for read-only
Get-AppxPackage and Get-WinEvent queries on Windows.
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree
import os
import subprocess
import sys

from windurango_support import (
    preparation_plan, prepared_game_executable, game_dependency_status, embedded_xvd_relocation_plan,
    registration_command, find_registration_manifest, GAME_DEPENDENCY_DLLS,
)


def status_name(exit_code: int | None) -> str:
    if exit_code is None:
        return 'unknown exit status'
    value = int(exit_code) & 0xFFFFFFFF
    if value == 0xE06D7363:
        return '0xE06D7363 (unhandled Microsoft C++ exception; inspect the crash dump for the throwing module)'
    if value == 0xC0000142:
        return '0xC0000142 (STATUS_DLL_INIT_FAILED: a DLL failed to initialise)'
    if value == 0xC0000135:
        return '0xC0000135 (STATUS_DLL_NOT_FOUND: required DLL not found)'
    if value == 0xC000007B:
        return '0xC000007B (STATUS_INVALID_IMAGE_FORMAT: potentially wrong DLL architecture)'
    return f'0x{value:08X}'


def manifest_identity(manifest: Path | None) -> tuple[str, str] | None:
    """Read package Identity.Name and the first Application.Id, if present."""
    if manifest is None or not manifest.is_file() or manifest.stat().st_size > 2*1024*1024:
        return None
    try:
        root=ElementTree.parse(manifest).getroot()
        name='';app_id=''
        for elem in root.iter():
            local=elem.tag.rsplit('}',1)[-1]
            if local=='Identity' and not name:
                name=elem.attrib.get('Name','')
            if local=='Application' and not app_id:
                app_id=elem.attrib.get('Id','')
        return (name,app_id) if name else None
    except (OSError,ValueError,ElementTree.ParseError):
        return None


def _ps_literal(value: str) -> str:
    """Literal PowerShell single-quoted expression, never executable source."""
    return "'"+value.replace("'","''")+"'"


def _powershell(script: str, *, timeout: float = 12) -> str:
    if os.name != 'nt':
        return 'Unavailable: Windows-only check.'
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    try:
        completed=subprocess.run(
            ['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,encoding='utf-8',errors='replace',timeout=timeout,
            creationflags=flags,
        )
        output=completed.stdout.strip()
        if completed.returncode:
            error=completed.stderr.strip()[:500]
            return f'PowerShell query exited {completed.returncode}: {error or output}'
        return output or '(nothing returned)'
    except (OSError,subprocess.TimeoutExpired) as exc:
        return f'Unable to query Windows: {exc}'


def registered_app_launch_command(manifest: Path | None) -> str | None:
    """PowerShell one-liner to open an already registered UWP application.

    Only displayed for the user to run manually. It never launches or registers
    an app, and resolves PackageFamilyName from Windows rather than guessing it.
    """
    identity=manifest_identity(manifest)
    if not identity or not identity[1]:
        return None
    name,app_id=identity
    return ("$p=Get-AppxPackage -Name "+_ps_literal(name)+" | "
            "Where-Object { $_.Name -eq "+_ps_literal(name)+" } | "
            "Select-Object -First 1; "
            "if (!$p) { throw 'Game not registered for current Windows user' }; "
            "Start-Process explorer.exe (('shell:AppsFolder\\' + $p.PackageFamilyName + '!') + "
            +_ps_literal(app_id)+")")


def windows_registration_status(manifest: Path | None) -> str:
    ident=manifest_identity(manifest)
    if not ident:
        return 'Unverified: no readable AppxManifest.xml with package identity found.'
    name,_=ident
    # Query exact package name; do not interpolate an arbitrary manifest as code.
    query=("$name="+_ps_literal(name)+"; "
           "$match = Get-AppxPackage | Where-Object {$_.Name -eq $name} | Select-Object -First 1; "
           "if ($match) { 'Registered: ' + $match.PackageFamilyName + ' (install: ' + $match.InstallLocation + ')' } "
           "else { 'NOT REGISTERED for current Windows user' }")
    return _powershell(query,timeout=6)


def windows_error_events(exe: Path) -> str:
    # Only recent Application Errors / Windows Error Reporting events concerning
    # this executable. Never dump unrelated Windows Application event entries.
    query=("$exe="+_ps_literal(exe.name)+"; "
           "$events = Get-WinEvent -FilterHashtable @{LogName='Application'; "
           "Id=1000,1001; StartTime=(Get-Date).AddMinutes(-30)} "
           "-ErrorAction SilentlyContinue | Where-Object { $_.Message -and "
           "$_.Message.IndexOf($exe,[StringComparison]::OrdinalIgnoreCase) -ge 0 } | "
           "Select-Object -First 4; "
           "if ($events) { $events | ForEach-Object { "
           "'[' + $_.TimeCreated + '] ' + $_.Message } } "
           "else { 'No recent Application Error events mention this executable.' }")
    return _powershell(query,timeout=14)


def create_diagnostic_report(game_path: str | Path, runtime_path: str | Path,
                             *, include_windows: bool = True) -> str:
    """Report concrete state without promising that the game can boot."""
    exe=Path(game_path)
    marker=Path(runtime_path)
    lines=[
        'GameShelf WinDurango launch diagnostic (read-only)',
        'Game executable: '+str(exe),
        'GameShelf runtime: '+str(marker),
        'NOTE: DLL presence does not prove UWP registration or game compatibility.',
    ]
    if not exe.is_file() or exe.suffix.casefold()!='.exe':
        lines.append('ERROR: Game executable missing or not a .exe file.')
        return '\n'.join(lines)
    manifest=find_registration_manifest(exe)
    lines.append('AppxManifest: '+(str(manifest) if manifest else 'NOT FOUND near game'))
    ident=manifest_identity(manifest)
    if ident:
        lines.append('AppX Identity.Name: '+ident[0])
        lines.append('AppX Application.Id: '+(ident[1] or '(not specified)'))
    if manifest:
        lines.append('Optional manual AppX registration command (requires your approval):')
        lines.append('  '+registration_command(manifest))
        activate=registered_app_launch_command(manifest)
        if activate:
            lines.append('Optional manual launch through Windows registration (after successful registration):')
            lines.append('  '+activate)
    try:
        plan=preparation_plan(exe,marker)
        lines.append('WinDurango game-folder DLLs present: '+str(len(plan.already_present)))
        lines.append('WinDurango/game DLL files available to copy safely: '+str(len(plan.pending)))
        for src,dest in plan.pending:
            lines.append('  COPYABLE (not yet installed): '+dest.name+'  from '+str(src.parent))
    except (ValueError,OSError) as exc:
        lines.append('WinDurango preparation check: '+str(exc))
    try:
        status=game_dependency_status(exe)
        lines.append('EmbeddedXvd: '+(str(status['embedded_xvd']) if status['embedded_xvd'] else 'NOT FOUND'))
        if status['embedded_xvd'] and status['embedded_xvd'].parent.resolve()!=exe.parent.resolve():
            lines.append('WARNING: EmbeddedXvd is not alongside the game executable. '
                         'The official instructions require it in that folder.')
            try:
                relocation=embedded_xvd_relocation_plan(exe)
                if relocation:
                    lines.append('ACTION: Use GameShelf > Prepare WinDurango Game to approve relocating '
                                 +str(relocation[0])+' into '+str(relocation[1]))
            except (OSError,ValueError) as exc:
                lines.append('EmbeddedXvd relocation blocked: '+str(exc))
        lines.append('Game-specific DLLs already installed: '+(', '.join(status['installed']) or 'none recognised'))
        lines.append('Game-specific DLLs supplied in EmbeddedXvd: '+(', '.join(status['available']) or 'none recognised'))
        lines.append('Game-specific DLLs not found in either location (game-dependent): '
                     +(', '.join(status['not_located']) or 'none'))
    except (ValueError,OSError) as exc:
        lines.append('Game dependency check: '+str(exc))
    try:
        prepared_game_executable(exe)
        lines.append('GameShelf DLL marker check: PASS (not proof of a successful boot)')
    except (ValueError,OSError) as exc:
        lines.append('GameShelf DLL marker check: '+str(exc))
    lines.append('Windows AppX registration:')
    lines.append('  '+(windows_registration_status(manifest) if include_windows else 'Not queried.'))
    lines.append('GameShelf launch mode: Windows registered-app activation (never direct .exe for manifest games).')
    if include_windows and os.name=='nt' and ident and ident[1] and manifest:
        try:
            from uwp_activation import query_registered_package
            family=query_registered_package(ident[0],str(manifest.parent.resolve()))
            lines.append('Verified AppUserModelID: '+family+'!'+ident[1])
        except (ValueError,OSError,RuntimeError) as exc:
            lines.append('Windows registered-app activation blocked: '+str(exc))
    lines.append('NOTE: 0xE06D7363 denotes a C++ exception; KERNELBASE.dll alone does not identify its root cause.')
    lines.append('NOTE: A blank faulting package name from Windows may indicate direct .exe startup rather than UWP activation.')
    lines.append('Windows application errors (last 30 minutes):')
    lines.append('  '+(windows_error_events(exe) if include_windows else 'Not queried.'))
    lines.append('If the game still fails, check game build compatibility and use the official WinDurango installation guide:')
    lines.append('https://github.com/WinDurango/WinDurango#installation')
    return '\n'.join(lines)

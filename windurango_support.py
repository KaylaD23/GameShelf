"""WinDurango: Xbox One UWP translation layer integration.

WinDurango is not an ISO emulator. Runtime DLLs from the official project must
be installed into a compatible, legally obtained game's Mount directory and
the game must be configured/registered as required by WinDurango. This module
never registers packages or copies DLLs into a game without user consent.
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree
from dataclasses import dataclass
import hashlib
import os
import shutil

RUNTIME_MARKER = 'WinDurango.Common.dll'
# Microsoft's Xbox One game runtime components, as listed in WinDurango's
# official game preparation instructions. These are NOT included in the generic
# bundled WinDurango runtime: each game supplies its own EmbeddedXvd contents.
GAME_DEPENDENCY_DLLS = ('xg_x.dll', 'xg.dll', 'AcpHal.dll',
                        'xaudio2_9.dll', 'D3DCompiler46.dll', 'sc_dll.dll')

SUPPORT_URL = 'https://github.com/WinDurango/WinDurango#installation'


def manifest_executable(manifest: Path) -> Path | None:
    """Find the relative Application Executable in a UWP manifest (no traversal)."""
    if not manifest.is_file() or manifest.stat().st_size > 2 * 1024 * 1024:
        return None
    try:
        tree=ElementTree.parse(manifest)
        for element in tree.iter():
            if element.tag.rsplit('}',1)[-1] != 'Application':
                continue
            name=element.attrib.get('Executable','').replace('\\','/')
            if not name or name.startswith('/') or ':' in name or '\x00' in name:
                continue
            segments=name.split('/')
            if any(seg in ('','.', '..') for seg in segments):
                continue
            candidate=manifest.parent.joinpath(*segments)
            if candidate.suffix.lower()=='.exe' and candidate.is_file():
                return candidate
    except (ElementTree.ParseError, OSError, ValueError):
        return None
    return None


def locate_prepared_game(folder: Path, filenames: list[str]) -> Path | None:
    """Identify Xbox One games without mistaking every Windows program for one.

    Accept a game with AppxManifest.xml or a WinDurango-patched game folder with
    one clear executable candidate. Do not import WinDurango's own watchdog.
    """
    filenames_lower={name.casefold():name for name in filenames}
    manifest=filenames_lower.get('appxmanifest.xml')
    if manifest:
        exe=manifest_executable(folder/manifest)
        if exe is not None:
            return exe
    if RUNTIME_MARKER.casefold() in filenames_lower:
        candidates=[folder/name for name in filenames if name.lower().endswith('.exe')
                    and not name.lower().endswith(('.watchdog.exe','setup.exe','uninstall.exe'))]
        if len(candidates)==1:
            return candidates[0]
    return None


def prepared_game_executable(path: str | Path) -> Path:
    """Validate a game executable that is already prepared with WinDurango.

    Never assume a raw ISO, XVC package, directory or AppxManifest can simply
    be passed to a standalone emulator process.
    """
    p=validate_game_path(path)
    # A present runtime marker means only that these DLLs were deployed; it
    # does NOT prove package registration or per-title game compatibility.
    if not (p.parent/RUNTIME_MARKER).is_file():
        raise ValueError('WinDurango is not installed into this game folder. Follow the official WinDurango game preparation and Windows app registration instructions first.')
    return p


# Only DLLs supplied with WinDurango and intended for game-folder deployment.
# Never install its watchdog, .lib, .exp, or .pri files.
DEPLOYABLE_DLLS = (
    'WinDurango.Common.dll', 'WinDurango.Implementation.WinRT.dll',
    'kernelx.dll', 'winrt_x.dll', 'd3d11_x.dll', 'd3d12_x.dll',
    'DirectXTex.dll', 'etwplus.dll', 'pixEvt.dll', 'toolhelpx.dll',
    'mfplat.dll', 'mmdevapi.dll', 'windows.kinect.dll',
    'Microsoft.WindowsAppRuntime.Bootstrap.dll', 'avcodec-62.dll',
    'avutil-60.dll', 'zlib1.dll',
)


def validate_game_path(path: str | Path) -> Path:
    """Accept a candidate Xbox One application exe, not a disc or the watchdog.

    Preparation does not imply the game is compatible or Windows-registered.
    """
    p=Path(path)
    if not p.is_file() or p.suffix.casefold()!='.exe':
        raise ValueError('WinDurango cannot boot ISO/XVC files or arbitrary folders. Choose the Xbox One game executable (.exe) inside its extracted Mount folder.')
    if p.name.casefold() in ('windurango.watchdog.exe','setup.exe','uninstall.exe'):
        raise ValueError('Select the game executable, not a WinDurango or setup utility.')
    return p


def _casefold_files(folder: Path) -> dict[str, Path]:
    return {item.name.casefold(): item for item in folder.iterdir() if item.is_file() or item.is_symlink()}


@dataclass(frozen=True)
class PreparationPlan:
    executable: Path
    runtime_root: Path
    pending: tuple[tuple[Path,Path],...]
    already_present: tuple[str,...]
    manifest: Path | None
    embedded_xvd: Path | None = None
    game_specific_pending: tuple[tuple[Path, Path], ...] = ()


def find_registration_manifest(executable: str | Path) -> Path | None:
    """Find an AppxManifest alongside the game or in its immediate parents."""
    p=validate_game_path(executable)
    for folder in (p.parent, *list(p.parent.parents)[:3]):
        try:
            for file in folder.iterdir():
                if file.is_file() and file.name.casefold()=='appxmanifest.xml':
                    return file
        except OSError:
            continue
    return None


def registration_command(manifest: Path) -> str:
    """Display-only PowerShell command; never silently register a UWP package."""
    if manifest.name.casefold()!='appxmanifest.xml' or not manifest.is_file():
        raise ValueError('No valid AppxManifest.xml was found.')
    # Escape PowerShell single-quoted literals without evaluating user input.
    return "Add-AppxPackage -Register -Path '"+str(manifest.resolve()).replace("'", "''")+"'"


def find_embedded_xvd(executable: str | Path) -> Path | None:
    """Locate game-provided EmbeddedXvd folder, not from GameShelf's bundle.

    Search only the Mount/executable folder and immediate parent. Never follow
    folder symlinks when preparing content into a game directory.
    """
    p = validate_game_path(executable)
    for folder in (p.parent, p.parent.parent):
        try:
            matches=[child for child in folder.iterdir()
                     if child.name.casefold()=='embeddedxvd' and
                     child.is_dir() and not child.is_symlink()]
        except OSError:
            continue
        if matches:
            return matches[0]
    return None



def embedded_xvd_relocation_plan(game_path: str | Path) -> tuple[Path, Path] | None:
    """Return the sibling-to-Mount folder move required by WinDurango, if any.

    No disk modifications. The caller must obtain approval before invoking the
    relocation function. Reject symbolic links and non-empty or empty targets
    alike. No copying of game content or creation of substitute Xbox DLLs.
    """
    exe = validate_game_path(game_path)
    embedded = find_embedded_xvd(exe)
    if embedded is None:
        return None
    if embedded.parent.resolve() == exe.parent.resolve():
        return None
    # Only the sibling path adjacent to Mount is ever considered.
    if embedded.parent.resolve() != exe.parent.parent.resolve():
        raise ValueError('Unexpected EmbeddedXvd location; refusing automatic relocation')
    target = exe.parent / 'EmbeddedXvd'
    if embedded.is_symlink() or exe.parent.is_symlink():
        raise ValueError('Refusing to relocate symbolic-link game directories')
    if any(child.name.casefold() == target.name.casefold() for child in exe.parent.iterdir()):
        raise FileExistsError('An EmbeddedXvd entry already exists inside the game executable folder; it will not be overwritten')
    return embedded, target


def relocate_embedded_xvd(game_path: str | Path) -> tuple[Path, Path] | None:
    """Carry out an already-approved, same-volume directory move.

    No recursive copy; move the original directory atomically when possible.
    Never overwrite a destination. Intended only for the GUI confirmation path.
    """
    plan = embedded_xvd_relocation_plan(game_path)
    if plan is None:
        return None
    source, target = plan
    # Both directories share the same game root, so rename is normally atomic.
    # os.rename does not silently fall back to a cross-volume copy.
    if target.exists() or target.is_symlink():
        raise FileExistsError('EmbeddedXvd target appeared; nothing was moved')
    os.rename(source, target)
    return source, target

def game_dependency_status(game_path: str | Path) -> dict[str, object]:
    """Read-only check; absence isn't proof of incompatibility for every title."""
    exe=validate_game_path(game_path)
    installed=_casefold_files(exe.parent)
    embedded=find_embedded_xvd(exe)
    available=_casefold_files(embedded) if embedded else {}
    return {
        'embedded_xvd': embedded,
        'installed': tuple(name for name in GAME_DEPENDENCY_DLLS if name.casefold() in installed),
        'available': tuple(name for name in GAME_DEPENDENCY_DLLS if name.casefold() in available),
        'copyable': tuple(name for name in GAME_DEPENDENCY_DLLS
                          if name.casefold() in available and name.casefold() not in installed),
        'not_located': tuple(name for name in GAME_DEPENDENCY_DLLS
                             if name.casefold() not in installed and name.casefold() not in available),
    }


def preparation_plan(game_path: str | Path, runtime_marker: str | Path) -> PreparationPlan:
    exe=validate_game_path(game_path)
    marker=Path(runtime_marker)
    if marker.name.casefold()!='windurango.common.dll' or not marker.is_file():
        raise FileNotFoundError('GameShelf cannot find its WinDurango.Common.dll. Configure the bundled WinDurango runtime in Emulator Manager.')
    root=marker.parent
    if exe.parent.resolve()==root.resolve():
        raise ValueError('Select the Xbox One game executable, not an executable inside the WinDurango runtime folder.')
    existing=_casefold_files(exe.parent)
    pending=[];present=[]
    for name in DEPLOYABLE_DLLS:
        source=root/name
        if not source.is_file() or source.is_symlink():
            continue
        candidate=existing.get(name.casefold())
        if candidate is not None:
            if candidate.is_symlink():
                raise ValueError('Refusing to install beside a symbolic link named '+name)
            present.append(candidate.name)
        else:
            pending.append((source,exe.parent/name))
    if not (root/RUNTIME_MARKER).is_file():
        raise ValueError('WinDurango runtime is incomplete: missing '+RUNTIME_MARKER)
    # Generic WinDurango DLLs alone do NOT complete a game install. The game
    # itself may include proprietary EmbeddedXvd DLLs which must be supplied
    # by that game, never downloaded or substituted with arbitrary system DLLs.
    embedded=find_embedded_xvd(exe)
    extras=[]
    if embedded:
        contents=_casefold_files(embedded)
        for name in GAME_DEPENDENCY_DLLS:
            available=contents.get(name.casefold())
            if available is None or name.casefold() in existing:
                continue
            if available.is_symlink():
                raise ValueError('Refusing to use a linked game dependency: '+name)
            extras.append((available,exe.parent/name))
    return PreparationPlan(exe,root,tuple(pending+extras),tuple(present),
                           find_registration_manifest(exe),embedded,tuple(extras))


def _hash_file(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576),b''):
            digest.update(block)
    return digest.hexdigest()


def apply_preparation_plan(plan: PreparationPlan) -> tuple[str,...]:
    """User-approved deployment: never overwrite; roll back new files on error.

    Does not enable Developer Mode or register an AppX package automatically.
    """
    if not plan.executable.is_file():
        raise FileNotFoundError('The game executable was moved or deleted.')
    deployed=[]
    try:
        for source,destination in plan.pending:
            is_runtime=(source.parent.resolve()==plan.runtime_root.resolve() and
                        source.name in DEPLOYABLE_DLLS)
            is_game_dependency=(plan.embedded_xvd is not None and
                                source.parent.resolve()==plan.embedded_xvd.resolve() and
                                source in {src for src,_ in plan.game_specific_pending} and
                                source.name.casefold() in {n.casefold() for n in GAME_DEPENDENCY_DLLS})
            if not (is_runtime or is_game_dependency):
                raise ValueError('Invalid WinDurango preparation source')
            if source.is_symlink() or not source.is_file():
                raise FileNotFoundError(source)
            # Reject conflicting Windows case-insensitive names even on Linux.
            if destination.name.casefold() in _casefold_files(destination.parent):
                raise FileExistsError('DLL already exists; nothing will be overwritten: '+destination.name)
            with source.open('rb') as reader, destination.open('xb') as writer:
                deployed.append(destination)
                shutil.copyfileobj(reader,writer,1048576)
            if _hash_file(source)!=_hash_file(destination):
                raise IOError('DLL verification failed: '+destination.name)
        if not (plan.executable.parent/RUNTIME_MARKER).is_file():
            raise RuntimeError('WinDurango runtime marker was not installed')
        return tuple(x.name for x in deployed)
    except Exception:
        for file in reversed(deployed):
            try:file.unlink()
            except OSError:pass
        raise

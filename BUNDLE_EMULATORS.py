"""GameShelf v0.6 offline emulator bundler.

Takes the user's *original* Emulators 1.zip, Emulators 2.zip and the five
Emulators 3.zip.001..005 byte parts. Installs complete emulator trees inside
GameShelf/Emulators. All programs are launched by GameShelf only on demand.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
PART_HASHES = [
    '24df1acdac2fb5f3b9cc99de1ddbf03c9cb75811b73ac95debe7d3d713c6a852',
    'a0467b4bbca3359ae9e8753523860e65dfb84255221b0e98522dd3b1bb6fe8cb',
    '575558d01cf1096348d9d7b1ad4da6bff8670e58a989cfd7675ea5a1c07505d2',
    '9cfc955c5b6611f676cb42543a3489e1029b9dc84f9a4859c32de67acd7dcb1c',
    'b4c9df18458e6c80f01b787c0fc0a58eda6f0d639acf59792088ad7090cf6b75',
]
SOURCE_1 = 'Emulators 1.zip'
SOURCE_2 = 'Emulators 2.zip'
SOURCE_3 = [f'Emulators 3.zip.{n:03d}' for n in range(1, 6)]


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(4 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def find_source_dir(explicit: Path | None = None) -> Path:
    places = [explicit] if explicit else [HERE, HERE.parent, Path.cwd(), Path.home() / 'Downloads']
    for path in places:
        if path is not None and path.is_dir() and all((path / x).is_file() for x in SOURCE_3):
            return path
    if explicit:
        raise FileNotFoundError(f'The five Emulators 3.zip parts were not all present in: {explicit}')
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw()
        selected = filedialog.askdirectory(title='Choose folder containing Emulators 3.zip.001 through .005')
        root.destroy()
        if selected:
            return find_source_dir(Path(selected))
    except Exception as exc:
        print('Folder selection is unavailable:', exc)
    entered = input('Folder containing Emulators 3.zip.001..005: ').strip().strip('"')
    if not entered:
        raise RuntimeError('No source directory selected.')
    return find_source_dir(Path(entered).expanduser())


def checked_members(z: zipfile.ZipFile, expected_prefix: str):
    names = set()
    for info in z.infolist():
        path = info.filename.replace('\\', '/')
        bits = path.split('/')
        if info.is_dir():
            continue
        if len(bits) < 3 or bits[0] != expected_prefix or not bits[-1]:
            raise ValueError(f'Unexpected path in archive: {path}')
        internal = bits[1:]
        if any(bit in ('.','..','') or ':' in bit for bit in internal):
            raise ValueError(f'Unsafe ZIP path: {path}')
        if any(re.match(r'(?i)^(con|prn|nul|aux|com[1-9]|lpt[1-9])(?:\..*)?$', bit) for bit in internal):
            raise ValueError(f'Windows-reserved ZIP path: {path}')
        normalized = '/'.join(internal).casefold()
        if normalized in names:
            raise ValueError(f'Windows filename collision in archive: {path}')
        names.add(normalized)
        yield info, internal


def extract_emulators(archive: Path, expected_prefix: str, root: Path):
    """Extract complete emulator directories into private staging; no overwrite."""
    count = 0; total = 0
    with zipfile.ZipFile(archive, 'r') as z:
        for info, parts in checked_members(z, expected_prefix):
            target = root.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            # ZipFile.open checks its member's CRC32 at end of stream.
            with z.open(info) as source, target.open('xb') as dest:
                shutil.copyfileobj(source, dest, length=1 << 20)
            if target.stat().st_size != info.file_size:
                raise IOError(f'Extracted size mismatch: {info.filename}')
            count += 1; total += info.file_size
    print(f'Extracted and CRC-verified {expected_prefix}: {count:,} files, {total:,} bytes', flush=True)
    return count


def join_parts(source_dir: Path, joined_path: Path):
    for part, expected_hash in zip(SOURCE_3, PART_HASHES):
        path = source_dir / part
        digest = hash_file(path)
        if digest.lower() != expected_hash:
            raise ValueError(f'{part} is incomplete/modified. Expected SHA-256 {expected_hash}, found {digest}')
        print('Validated', part, flush=True)
    with joined_path.open('wb') as dest:
        for name in SOURCE_3:
            with (source_dir / name).open('rb') as source:
                shutil.copyfileobj(source, dest, length=4 << 20)
    if not zipfile.is_zipfile(joined_path):
        raise ValueError('The reconstructed Emulators 3 archive is not a valid ZIP.')


def install(source_dir: Path, include_older: bool = True):
    print('GameShelf v0.6 - bundling supplied emulator installations', flush=True)
    selected = []
    for source_name, prefix in [(SOURCE_1, 'Emulators 1'), (SOURCE_2, 'Emulators 2')]:
        if include_older and (source_dir/source_name).is_file():
            selected.append((source_dir/source_name,prefix))
    remaining = shutil.disk_usage(HERE).free
    if remaining < (3 << 30):
        raise OSError(f'Not enough free disk space: {remaining/(1<<30):.1f} GiB available; at least 3 GiB needed for extraction. For all 12 emulators allow approximately 6 GiB.')
    target_root = HERE / 'Emulators'
    target_root.mkdir(exist_ok=True)
    # One stage per run; the final directory is never reported complete on failure.
    with tempfile.TemporaryDirectory(prefix='_bundle_stage_', dir=HERE) as temporary:
        stage = Path(temporary)
        work = stage / 'joined3.zip'
        join_parts(source_dir, work)
        selected.append((work, 'Emulators 3'))
        extracted = stage / 'extracted'
        extracted.mkdir()
        for path,prefix in selected:
            extract_emulators(path,prefix,extracted)
        moved=[];skipped=[]
        for folder in extracted.iterdir():
            if not folder.is_dir():
                raise ValueError(f'Unexpected loose file in emulator bundle: {folder.name}')
            destination = target_root/folder.name
            if destination.exists():
                skipped.append(folder.name)
                print('Existing directory preserved (NOT overwritten):',destination,flush=True)
                continue
            folder.replace(destination)
            moved.append(folder.name)
    from core import EMULATORS,detect_bundled_executables
    detected=detect_bundled_executables(HERE)
    print('Installed folders:', ', '.join(moved) if moved else 'none')
    print('Existing folders preserved:', ', '.join(skipped) if skipped else 'none')
    print('Detected bundled emulators:',len(detected),'of',len(EMULATORS))
    for emulator in EMULATORS:
        print('  ', 'OK' if emulator.key in detected else 'MISSING',emulator.name)
    print('Expected original source archives are not modified.')
    if len(detected)<len(EMULATORS):
        print('Some earlier emulators are not bundled yet. Install from Emulators 1/2 or migrate from your previous GameShelf.')
    print('Open INSTALL_AND_RUN.bat to start GameShelf.')
    return detected


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,help='Folder containing all five Emulators 3.zip.* parts, and optionally Emulators 1.zip and Emulators 2.zip')
    parser.add_argument('--only-new',action='store_true',help='Install DuckStation, PCSX2 and PPSSPP only')
    args=parser.parse_args()
    directory=find_source_dir(args.source_dir)
    return 0 if install(directory, include_older=not args.only_new) else 1

if __name__=='__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('INSTALLATION FAILED:',type(exc).__name__,str(exc),flush=True)
        sys.exit(1)

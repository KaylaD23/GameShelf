"""GameShelf v0.9 — verify and integrate user's Emulators 4 split ZIP.

No game files are touched; older emulator folders are not overwritten.
"""
from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

HERE=Path(__file__).resolve().parent
PARTS=('Emulators 4.zip.001','Emulators 4.zip.002')
EXPECTED_SHA256=(
  'f730b91d5fa634aecc1cd4609defe9f87645881903a512b9530ed5203754ffc2',
  '7a0c49adc8aec5c5750dd305b1abc7dd9bdedce3ebfc6b75c19331356e97e0b3',
)
REQUIRED={
  'citron':'Citron/citron.exe',
  'xenia':'Xenia Canary/xenia_canary.exe',
  'shadps4':'shadps4/Versions/Pre-release/shadPS4.exe',
}


def rename_old_variants(directory:Path)->None:
    """Normalise a Windows duplicate-download suffix without overwriting files."""
    for canonical in PARTS:
        dest=directory/canonical
        original=directory/canonical.replace('.zip.', '.zip(1).')
        if not dest.exists() and original.is_file():
            original.rename(dest)
            print(f'Renamed: {original.name} -> {dest.name}',flush=True)


def find_source_dir(explicit:Path|None=None)->Path:
    roots=[explicit] if explicit else [HERE,HERE.parent,Path.cwd(),Path.home()/'Downloads']
    for candidate in roots:
        if candidate and candidate.is_dir():
            rename_old_variants(candidate)
            if all((candidate/name).is_file() for name in PARTS):return candidate
    if explicit:raise FileNotFoundError('Emulators 4.zip.001 and .002 not found in '+str(explicit))
    try:
        from tkinter import Tk,filedialog
        root=Tk();root.withdraw()
        directory=filedialog.askdirectory(title='Select folder containing Emulators 4.zip.001 and .002')
        root.destroy()
        if directory:return find_source_dir(Path(directory))
    except Exception:pass
    answer=input('Folder with Emulators 4.zip.001 and .002: ').strip().strip('"')
    if not answer:raise FileNotFoundError('No archive folder selected.')
    return find_source_dir(Path(answer).expanduser())


def sha256(path:Path)->str:
    hash=hashlib.sha256()
    with path.open('rb') as f:
        for buf in iter(lambda:f.read(4<<20),b''):hash.update(buf)
    return hash.hexdigest()


def checked_members(z:zipfile.ZipFile):
    names=set()
    for entry in z.infolist():
        if entry.is_dir():continue
        parts=entry.filename.replace('\\','/').split('/')
        if len(parts)<3 or parts[0]!='Emulators 4' or any(not x or x in ('.','..') or ':' in x for x in parts):
            raise ValueError('Unsafe archive member: '+entry.filename)
        if any(re.match(r'(?i)^(con|prn|nul|aux|com[1-9]|lpt[1-9])(?:\..*)?$',p) for p in parts):
            raise ValueError('Windows-reserved filename: '+entry.filename)
        norm='/'.join(parts[1:]).casefold()
        if norm in names:raise ValueError('Windows filename collision: '+entry.filename)
        names.add(norm)
        yield entry,parts[1:]


def sync_existing_directory(source:Path,destination:Path)->int:
    """Repair missing bundled files, but never overwrite user-modified files.

    Compare the complete staged tree before writing anything. A damaged file
    raises a useful error rather than silently claiming all files were bundled.
    """
    staged=[p for p in source.rglob('*') if p.is_file()]
    missing=[]
    for p in staged:
        rel=p.relative_to(source)
        target=destination/rel
        if target.is_file():
            if target.stat().st_size!=p.stat().st_size or sha256(target)!=sha256(p):
                raise ValueError('Existing emulator file differs; refusing to overwrite: '+str(target))
        elif target.exists():
            raise ValueError('Existing path is not a regular file: '+str(target))
        else:
            missing.append((p,target))
    for p,target in missing:
        target.parent.mkdir(parents=True,exist_ok=True)
        with p.open('rb') as input_file,target.open('xb') as output_file:
            shutil.copyfileobj(input_file,output_file,length=1<<20)
    return len(missing)


def integrate(source_dir:Path,target_root:Path=HERE)->dict:
    print('GameShelf 0.9 — installing the complete Emulators 4 archive',flush=True)
    for name,expected in zip(PARTS,EXPECTED_SHA256):
        source=source_dir/name
        if not source.is_file():raise FileNotFoundError(source)
        found=sha256(source)
        if found!=expected:raise ValueError(f'{name} is incomplete or modified (SHA256 mismatch).')
        print('Verified',name,flush=True)
    if shutil.disk_usage(target_root).free < (2<<30):
        raise OSError('At least 2 GiB of free disk space is required during extraction.')
    bundle=target_root/'Emulators';bundle.mkdir(exist_ok=True)
    installed=[];existing=[]
    with tempfile.TemporaryDirectory(prefix='_gameshelf_emu4_',dir=target_root) as td:
        scratch=Path(td)
        joined=scratch/'complete.zip'
        with joined.open('wb') as output:
            for name in PARTS:
                with (source_dir/name).open('rb') as data:
                    shutil.copyfileobj(data,output,length=4<<20)
        with zipfile.ZipFile(joined) as z:
            members=list(checked_members(z))
            stage=scratch/'staging';stage.mkdir()
            count=0
            for info,parts in members:
                dest=stage.joinpath(*parts)
                dest.parent.mkdir(parents=True,exist_ok=True)
                with z.open(info) as input_file, dest.open('xb') as out:
                    shutil.copyfileobj(input_file,out,length=1<<20)
                if dest.stat().st_size!=info.file_size:raise IOError('Wrong extracted size: '+info.filename)
                count+=1
            for key,relpath in REQUIRED.items():
                if not (stage/relpath).is_file():
                    raise FileNotFoundError('Required '+key+' executable is absent from archive: '+relpath)
            for sub in stage.iterdir():
                if not sub.is_dir():raise ValueError('Unexpected archive file in root: '+sub.name)
                final=bundle/'Emulators 4'/sub.name
                if final.exists():
                    repaired=sync_existing_directory(sub,final)
                    existing.append(sub.name)
                    print(f'Existing folder verified, repaired {repaired} missing files:',final,flush=True)
                else:
                    final.parent.mkdir(parents=True,exist_ok=True)
                    sub.replace(final)
                    installed.append(sub.name)
            print('Extracted and CRC-checked',count,'files.',flush=True)
    from core import detect_bundled_executables
    detected=detect_bundled_executables(target_root)
    missing=[key for key in REQUIRED if key not in detected]
    if missing:raise RuntimeError('Emulator executables not detected after extraction: '+', '.join(missing))
    print('Installed folders:',installed,'Existing preserved:',existing,flush=True)
    print('Newly supported emulators registered:',', '.join(REQUIRED),flush=True)
    print('Bundled emulator executables detected:',len(detected),'/ 15',flush=True)
    return detected


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path)
    args=parser.parse_args()
    integrate(find_source_dir(args.source_dir))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('INSTALL FAILED:',type(exc).__name__,str(exc),flush=True)
        sys.exit(1)

"""Safely unpack the user's own emulator archives without modifying the originals.

Usage: python unpack_emulators.py [--archive1 PATH] [--archive2 PATH] [--destination DIR]
"""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import stat
import sys
import zipfile
from core import BASE, Settings, detect_executables, detect_bundled_executables


def extract_safe(archive:Path,destination:Path):
    destination=destination.resolve()
    with zipfile.ZipFile(archive,'r') as z:
        members=z.infolist();total=sum(x.file_size for x in members)
        if total>20_000_000_000:raise ValueError('Archive unexpectedly large')
        print(f'Validating {archive.name} ({len(members)} members, {total/1e6:.1f} MB)…')
        # Validate ALL members and archive CRC before creating any output files.
        for info in members:
            if info.flag_bits & 1:raise ValueError('Encrypted ZIP members are not supported')
            target=(destination/info.filename).resolve(strict=False)
            if not target.is_relative_to(destination):raise ValueError(f'Unsafe archive path: {info.filename}')
            unix_mode=info.external_attr>>16
            if stat.S_ISLNK(unix_mode):raise ValueError(f'Archive contains a symlink: {info.filename}')
        bad=z.testzip()
        if bad is not None:raise ValueError(f'ZIP CRC check failed: {bad}')
        usage=shutil.disk_usage(destination.parent if destination.parent.exists() else Path.cwd())
        if usage.free<total+100_000_000:
            raise OSError(f'Insufficient disk space: need at least {total/1e9:.2f} GB free')
        done=0
        for i,info in enumerate(members):
            target=(destination/info.filename).resolve(strict=False)
            if info.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():
                if target.stat().st_size==info.file_size:
                    done+=1;continue
                raise FileExistsError(f'Refusing to overwrite an existing file: {target}')
            with z.open(info) as source, open(target,'xb') as sink:
                shutil.copyfileobj(source,sink,1024*1024)
            done+=1
            if i%400==0:print(f'  extracted {done} files',flush=True)
    print(f'Completed {archive.name}: {done} files')


def choose(name:str)->Path:
    from tkinter import Tk,filedialog
    root=Tk();root.withdraw();root.attributes('-topmost',True)
    value=filedialog.askopenfilename(title=f'Choose {name}',filetypes=[('ZIP archives','*.zip')])
    root.destroy()
    if not value:raise RuntimeError(f'No file selected for {name}')
    return Path(value)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--archive1',type=Path)
    parser.add_argument('--archive2',type=Path)
    parser.add_argument('--destination',type=Path,default=Path(__file__).resolve().parent/'Emulators')
    args=parser.parse_args()
    archives=[args.archive1,args.archive2]
    for idx,a in enumerate(archives):
        if a is None:
            possible=[Path.cwd()/f'Emulators {idx+1}.zip',Path(__file__).resolve().parent.parent/f'Emulators {idx+1}.zip']
            a=next((p for p in possible if p.is_file()),None) or choose(f'Emulators {idx+1}.zip')
            archives[idx]=a
        if not a.is_file():parser.error(f'Archive not found: {a}')
    args.destination.mkdir(parents=True,exist_ok=True)
    for a in archives:extract_safe(a,args.destination)
    found=detect_bundled_executables(BASE) if args.destination.resolve() == (BASE / "Emulators").resolve() else detect_executables([args.destination])
    settings=Settings()
    settings.values['emulators'].update(found)
    settings.save()
    print(f'Configured {len(found)} of 9 emulator executables in GameShelf.')
    for name,path in found.items():print(' -',name,':',path)

if __name__=='__main__':
    try:main()
    except Exception as ex:
        print(f'ERROR: {ex}',file=sys.stderr);sys.exit(1)

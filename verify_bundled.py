"""Verify the original emulator file tree shipped beside the GameShelf frontend.

Use --deep for CRC32 validation of every file. Requires Python only.
This tool does not execute any bundled Windows programs.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import zlib
from core import BASE, EMULATORS, detect_bundled_executables, executable_path


def run(deep: bool=False) -> bool:
    manifest_path = BASE / 'BUNDLED_MANIFEST.json'
    if not manifest_path.is_file():
        print('MISSING: BUNDLED_MANIFEST.json; this may be the lightweight/source-only release.')
        return False
    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    errors = []
    base = BASE / 'Emulators'
    files = data['files']
    total_size = 0
    for index, info in enumerate(files):
        path = base / info['path']
        if not path.is_file():
            errors.append(f'Missing file: {info["path"]}')
            continue
        size = path.stat().st_size
        total_size += size
        if size != info['size']:
            errors.append(f'Wrong size: {info["path"]} ({size} != {info["size"]})')
            continue
        if deep:
            crc = 0
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(1 << 20), b''):
                    crc = zlib.crc32(chunk,crc)
            if (crc & 0xffffffff) != info['crc32']:
                errors.append(f'Bad CRC: {info["path"]}')
    detected = detect_bundled_executables(BASE)
    for emu in EMULATORS:
        value = detected.get(emu.key)
        if not value or not executable_path(value).is_file():
            errors.append(f'Emulator not detected: {emu.name}')
    for err in errors[:40]:
        print('ERROR:', err)
    if len(errors) > 40:
        print('...and',len(errors)-40,'more errors.')
    print(f'Files checked: {len(files)}; bytes present: {total_size:,} / {data["total_uncompressed_bytes"]:,}')
    print(f'Bundled emulators detected: {len(detected)} / {len(EMULATORS)}')
    print('Verification mode:', 'full CRC32' if deep else 'files and sizes')
    print('Result:', 'PASS' if not errors else f'FAIL ({len(errors)} errors)')
    return not errors


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deep',action='store_true',help='Read all bundled files and validate ZIP CRC32 values.')
    args=parser.parse_args()
    sys.exit(0 if run(args.deep) else 1)

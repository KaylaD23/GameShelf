"""Independent GameShelf adapter for xlenore's PSX/PS2 artwork collections.

PSCoverDL's README documents these public serial-based GitHub image repositories.
No PSCoverDL source code is copied. The serial-to-image URL convention is used
with attribution; images remain owned/licensed by their respective creators.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

REPOSITORIES = {'ps1': 'psx-covers', 'ps2': 'ps2-covers'}
SERIAL_IN_NAME = re.compile(r'(?<![A-Za-z0-9])([A-Za-z]{4})[-_. ]*(\d{3})[._ -]?(\d{2})(?!\d)')
SERIAL_ONLY = re.compile(r'[A-Z]{4}-\d{5}\Z')


def serial_from_text(value: str) -> str | None:
    """Find a disc's printed serial in a file name/title, not arbitrary digits."""
    match = SERIAL_IN_NAME.search(value)
    return f'{match[1].upper()}-{match[2]}{match[3]}' if match else None


def explicit_serial(title: str, game: dict | None = None) -> str | None:
    """Game filenames take precedence over guesses from similarly titled games."""
    game = game or {}
    path = str(game.get('path') or '')
    for value in (Path(path).stem, Path(path).name, str(title)):
        serial = serial_from_text(value)
        if serial:
            return serial
    return None


def normalized_game_title(title: str) -> str:
    # Remove only conventional bracketed region/revision/disc markings.
    title = re.sub(r'\s*[\[(](?:USA|Europe|Japan|World|Disc\s*\d+|Disk\s*\d+|CD\s*\d+|Rev\s*[A-Z0-9]+)[\])]\s*', ' ', title, flags=re.I)
    return re.sub(r'[^a-z0-9]+', ' ', title.casefold()).strip()


@lru_cache(maxsize=2)
def _title_index(platform: str) -> dict[str, list[str]]:
    """Reverse-index the emulator databases once, never scrape fuzzy search results.

    Failed retrieval returns an empty index and doesn't fabricate serials. Cache
    on disk belongs to GameShelf's existing title-resolver database subsystem.
    """
    if platform not in REPOSITORIES:
        return {}
    from title_lookup import URLS, _fetch, parse_ps_game_database
    raw = _fetch(URLS[platform], ttl=7*86400, cache_name=platform+'_gamedb.yaml')
    if not raw:
        return {}
    records = parse_ps_game_database(raw.decode('utf-8-sig', 'replace'), platform)
    index: dict[str, list[str]] = {}
    for serial, name in records.items():
        title = normalized_game_title(name)
        if title and SERIAL_ONLY.fullmatch(serial):
            index.setdefault(title, []).append(serial)
    return index


def candidate_serials(title: str, platform: str, game: dict | None = None, *, max_candidates: int = 8) -> list[str]:
    """Require an actual PS1/PS2 serial, from the filename or an exact DB name."""
    if platform not in REPOSITORIES:
        return []
    serial = explicit_serial(title, game)
    if serial:
        return [serial]
    requested = normalized_game_title(title)
    if not requested:
        return []
    serials = _title_index(platform).get(requested, [])
    # Deterministic ordering; do not assume the game's disc region is US.
    return sorted(set(serials))[:max_candidates]


def cover_url(platform: str, serial: str, style: str = 'default') -> str:
    if platform not in REPOSITORIES:
        raise ValueError('Covers are available only for PlayStation 1 and 2')
    if not SERIAL_ONLY.fullmatch(serial) or style not in ('default', '3d'):
        raise ValueError('Invalid serial or cover style')
    ext = 'jpg' if style == 'default' else 'png'
    return (f'https://raw.githubusercontent.com/xlenore/{REPOSITORIES[platform]}'
            f'/main/covers/{style}/{serial}.{ext}')


def cover_repository_url(platform: str) -> str:
    if platform not in REPOSITORIES:
        raise ValueError('Invalid platform')
    return 'https://github.com/xlenore/' + REPOSITORIES[platform]

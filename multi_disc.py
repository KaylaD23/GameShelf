"""Non-destructive multi-disc library support for PS1, PS2, Xbox 360 and Dreamcast.

The library combines entries and remembers which disc should boot next. Only
DuckStation is launched using GameShelf's M3U playlist. Flycast standalone and
Xenia are launched with a selected disc image, not unsupported playlist flags.
"""
from __future__ import annotations

from pathlib import Path
import os
import re

# Match obvious numbered discs only. Do not turn e.g. "Discworld" or "CD Projekt"
# into fake multi-disc games, or group different regional editions together.
DISC_MARKER = re.compile(r'(?i)(?<![a-z0-9])(?:disc|disk|cd|dvd)\s*[-_#.: ]*\s*(0?[1-9]|1[0-9])\b')
DISC_WRAPPER = re.compile(r'\s*[\(\[\{]\s*(?:disc|disk|cd|dvd)\s*[-_#.: ]*\s*(?:0?[1-9]|1[0-9])\s*[\)\]\}]', re.IGNORECASE)
PS1_IMAGE_EXTS = {'.cue', '.chd', '.iso', '.ccd', '.mds', '.img'}
PS2_IMAGE_EXTS = {'.iso', '.chd', '.cso', '.zso', '.gz'}
XBOX360_IMAGE_EXTS = {'.iso', '.xex'}
DREAMCAST_IMAGE_EXTS = {'.gdi', '.cdi', '.chd', '.cue'}
DISC_PLATFORMS = frozenset(('ps1', 'ps2', 'xbox360', 'dreamcast'))
DISC_IMAGE_EXTS = {
    'ps1': PS1_IMAGE_EXTS, 'ps2': PS2_IMAGE_EXTS,
    'xbox360': XBOX360_IMAGE_EXTS, 'dreamcast': DREAMCAST_IMAGE_EXTS,
}



def disc_identity(title: str, path: str) -> tuple[str, int] | None:
    """Return stable comparison key and disc number for a clearly labelled image.

    Prefer path filename: cover-scraper-renamed game titles needn't include CD 1.
    Region and edition markers remain in identity so USA/EUR sets cannot mix.
    """
    name = Path(path).stem
    # The filename, not the file extension, contains the disc marker.
    match = DISC_MARKER.search(name)
    if not match:
        name = title
        match = DISC_MARKER.search(name)
    if not match:
        return None
    number = int(match.group(1))
    cleaned = DISC_WRAPPER.sub(' ', name)
    cleaned = DISC_MARKER.sub(' ', cleaned)
    cleaned = re.sub(r'[\s._-]+', ' ', cleaned).strip().casefold()
    if not cleaned:
        return None
    return cleaned, number


def eligible_disc(platform: str, path: str) -> bool:
    return Path(path).suffix.lower() in DISC_IMAGE_EXTS.get(platform, set())


def group_candidates(games: list[dict]) -> list[list[dict]]:
    """Only same-platform, same-emulator games with distinct numbered discs merge.

    A numbered disc 1 must exist. Ambiguous duplicate disc numbers are skipped,
    and existing multi-disc primary games are excluded from remerging.
    """
    groups: dict[tuple[str, str, str], list[tuple[int, dict]]] = {}
    for game in games:
        path = game['path']
        if not eligible_disc(game['platform'], path) or game.get('disc_count', 1) > 1:
            continue
        identity = disc_identity(game['title'], path)
        if identity:
            title, number = identity
            groups.setdefault((game['platform'],game['emulator'],title),[]).append((number,game))
    result=[]
    for members in groups.values():
        numbers=[x[0] for x in members]
        if len(numbers)<2 or 1 not in numbers or len(set(numbers)) != len(numbers):
            continue
        result.append([game for _,game in sorted(members,key=lambda t:t[0])])
    return result


def write_duckstation_playlist(game_id: int, paths: list[str], directory: str | Path) -> Path:
    """Generate a local playlist of ABSOLUTE cue/chd/etc paths; never touch ISOs."""
    if len(paths)<2:
        raise ValueError('Multi-disc playlist requires at least two discs')
    normalized=[]
    for path in paths:
        p=Path(path).expanduser().resolve()
        if '\n' in str(p) or '\r' in str(p):
            raise ValueError('A game filename contains a newline')
        if not p.is_file():
            raise FileNotFoundError(str(p))
        normalized.append(str(p))
    if len({os.path.normcase(p) for p in normalized}) != len(normalized):
        raise ValueError('The playlist contains a duplicate image')
    folder=Path(directory);folder.mkdir(parents=True,exist_ok=True)
    output=folder/f'gameshelf_{int(game_id)}.m3u'
    temp=output.with_suffix('.m3u.tmp')
    try:
        temp.write_text('\n'.join(normalized)+'\n',encoding='utf-8')
        temp.replace(output)
    finally:
        temp.unlink(missing_ok=True)
    return output


def next_disc_number(discs: list[dict], selected: int) -> int:
    values=sorted(int(d['disc_number']) for d in discs)
    if not values:
        raise ValueError('No discs configured')
    return values[(values.index(selected)+1) % len(values)] if selected in values else values[0]

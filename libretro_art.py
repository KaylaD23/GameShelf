"""Libretro official thumbnail catalogue adapter.

Uses the per-console public directory listings on thumbnails.libretro.com.
A candidate comes from an *existing listed filename*, never from a guessed URL.
Only Named_Boxarts are offered as covers. Works with the public server and
requires no RetroArch installation, account, or API key.
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import PurePosixPath
from threading import RLock
from time import monotonic
from urllib.parse import quote, unquote, urlparse
import re

ROOT = 'https://thumbnails.libretro.com'
PROVIDER = 'Libretro Thumbnails'
# Actual Libretro playlist/database directories, not GameShelf's display labels.
SYSTEMS = {
    'ps1': ('Sony - PlayStation',),
    'ps2': ('Sony - PlayStation 2',),
    'ps3': ('Sony - PlayStation 3', 'Sony - PlayStation 3 (Downloadable)'),
    'ps4': ('Sony - PlayStation 4',),
    'psp': ('Sony - PlayStation Portable',),
    'vita': ('Sony - PlayStation Portable Vita',),
    'n64': ('Nintendo - Nintendo 64',),
    'dreamcast': ('Sega - Dreamcast',),
    'gc': ('Nintendo - GameCube',),
    'wii': ('Nintendo - Wii',),
    'wiiu': ('Nintendo - Wii U',),
    '3ds': ('Nintendo - Nintendo 3DS',),
    'xbox': ('Microsoft - Xbox',),
    'xbox360': ('Microsoft - Xbox 360',),
    'xboxone': ('Microsoft - Xbox One',),
}
VALID_SYSTEMS = frozenset(system for systems in SYSTEMS.values() for system in systems)
REGIONS = ('USA', 'Europe', 'World', 'Japan', 'Australia', 'Korea', 'Asia', 'Brazil', 'China', 'France', 'Germany', 'Spain', 'Italy')
# Cache directory listings so bulk scanning never downloads a large HTML index
# separately for every game. Failure is not cached permanently.
_cache: dict[str, tuple[float, tuple[str, ...]]] = {}
_lock = RLock()
CACHE_SECONDS = 24 * 60 * 60


def catalog_url(system: str) -> str:
    if system not in VALID_SYSTEMS:
        raise ValueError('Unsupported Libretro thumbnail system')
    return ROOT + '/' + quote(system, safe='') + '/Named_Boxarts/'


def image_url(system: str, filename: str) -> str:
    if not safe_filename(filename):
        raise ValueError('Invalid Libretro artwork filename')
    return catalog_url(system) + quote(filename, safe="")


def safe_filename(value: str) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= 235
            and value.lower().endswith('.png')
            and not value.startswith('.')
            and all(ord(ch) >= 32 for ch in value)
            and not any(ch in value for ch in '/\\<>|:?*\x00')
            and not value.endswith((' ', '.')))


def valid_url(url: str) -> bool:
    """Permit only HTTPS listings and PNG files for known console systems."""
    try:
        p = urlparse(url)
        if (p.scheme != 'https' or p.hostname != 'thumbnails.libretro.com'
                or p.username or p.password or p.port not in (None, 443)
                or p.query or p.fragment):
            return False
        if re.search(r'%2f|%5c', p.path, re.I):
            return False
        parts = unquote(p.path).split('/')
        if len(parts) == 4 and parts[0] == '' and parts[1] in VALID_SYSTEMS and parts[2] == 'Named_Boxarts' and parts[3] == '':
            return True
        return (len(parts) == 4 and parts[0] == ''
                and parts[1] in VALID_SYSTEMS and parts[2] == 'Named_Boxarts'
                and safe_filename(parts[3]))
    except (ValueError, UnicodeError):
        return False


class DirectoryParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.names: set[str] = set()

    def handle_starttag(self, tag, attrs):
        if tag != 'a':
            return
        href = dict(attrs).get('href', '')
        if not isinstance(href, str) or '/' in href or '\\' in href or '#' in href or '?' in href:
            return
        if re.search(r'%2f|%5c', href, re.I):
            return
        filename = unquote(href)
        if safe_filename(filename):
            self.names.add(filename)


def parse_index(data: bytes) -> tuple[str, ...]:
    parser = DirectoryParser()
    parser.feed(data.decode('utf-8', errors='replace'))
    return tuple(sorted(parser.names, key=str.casefold))


def filenames_for(system: str, fetch) -> tuple[str, ...]:
    """Fetch one public directory index per supported system per day.

    fetch(url) is supplied by cover_downloader so network settings, HTTPS
    validation and rate-limit feedback remain centralised.
    """
    if system not in VALID_SYSTEMS:
        return ()
    now = monotonic()
    with _lock:
        cached = _cache.get(system)
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
        names = parse_index(fetch(catalog_url(system)))
        # An empty list likely means blocked/changed HTML; retry next time.
        if names:
            _cache[system] = (now, names)
        return names


def region_in(text: str) -> str:
    """Recognise explicit region tags (filename or manually tagged game path)."""
    for region in REGIONS:
        if re.search(r'\(\s*' + re.escape(region) + r'(?:\s*[,)]|\s*\))', text, re.I):
            return region
    return ''


def _strip_tags(title: str) -> str:
    # Remove only machine metadata, not meaningful subtitle/episode parentheses.
    title = re.sub(r'\s*\[(?:[^]\r\n]{1,120})\]', ' ', title)
    title = re.sub(r'\s*\((?:(?:USA|Europe|World|Japan|Australia|Korea|Asia|Brazil|China|France|Germany|Spain|Italy)(?:[,+][^()]*)?|En(?:,[A-Za-z]+)*|(?:Disc|Disk|CD)\s*\d+|v\d+(?:\.\d+)+|Rev\s*\d+)\)', ' ', title, flags=re.I)
    return title.strip()


def title_key(title: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', _strip_tags(title).casefold()).strip()


def _unwanted(name: str) -> bool:
    # Never silently replace a retail game with a prototype/trial.
    return bool(re.search(r'\((?:Demo|Beta|Proto(?:type)?|Sample|Promo|Trial|Not\s+for\s+Resale)\b', name, re.I))


def matches(title: str, game: dict | None, fetch, *, limit: int = 16):
    """Return verified (display title, public image URL, page URL, region) tuples.

    Exact normalised base titles only. No fuzzy sequel matching; a requested
    special edition is not quietly replaced with a different release.
    """
    platform = (game or {}).get('platform', '')
    systems = SYSTEMS.get(platform, ())
    requested = title_key(title)
    if not requested or not systems:
        return []
    # Path tags provide a fallback hint when the UI title omits the region.
    desired = region_in(title) or region_in(str((game or {}).get('path', '')))
    found = []
    for system in systems:
        for filename in filenames_for(system, fetch):
            basename = filename[:-4]
            if _unwanted(basename) or title_key(basename) != requested:
                continue
            region = region_in(basename)
            if desired and region and region != desired:
                continue
            # An exact selected region outranks neutral/all-region artwork;
            # otherwise prefer USA and Europe but expose others to the picker.
            rank = (0 if desired and region == desired else
                    1 if desired and not region else
                    {'USA': 1, 'World': 2, 'Europe': 3, 'Australia': 4, 'Japan': 5, '': 6}.get(region, 7))
            found.append((rank, basename, image_url(system, filename), catalog_url(system), region))
    found.sort(key=lambda item: (item[0], item[1].casefold()))
    return [(name, url, page, region) for _, name, url, page, region in found[:limit]]


def clear_cache():
    with _lock:
        _cache.clear()

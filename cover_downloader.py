"""Cover search and safe on-disk image downloads for GameShelf.

No dependencies outside Python's standard library. Wikimedia search needs no key;
SteamGridDB requires a user-supplied API key, kept in the OS credential vault.
Network operations belong to background Qt workers, NEVER the GUI thread.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pscovers import candidate_serials, cover_url, cover_repository_url, explicit_serial
import libretro_art
from html.parser import HTMLParser
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse
from urllib.error import HTTPError, URLError
import socket
import ssl
from urllib.request import Request, urlopen, build_opener, ProxyHandler
import json
import os
import re
import tempfile

AGENT = 'GameShelf/0.9.22 (personal game library cover finder)'
MAX_IMAGE = 12 * 1024 * 1024


class CoverError(Exception):
    """A user-facing cover provider/download failure."""


@dataclass(frozen=True)
class CoverCandidate:
    title: str
    url: str
    preview: str
    provider: str
    page_url: str = ''
    score: float = 0.0
    redump_reference: str = ''


def clean_title(title: str) -> str:
    title = re.sub(r'\b(?:PPSA|CUSA|PCSA|PCSE|NPUB|NPEB|BLUS|BLES|SLUS|SLES)\s*\d{4,6}\b', '', title, flags=re.I)
    title = re.sub(r'\b(?:v\d+(?:\.\d+)+|\d{2}\.\d{3}\.\d{3})\b', '', title, flags=re.I)
    title = re.sub(r'\[[^]]+\]', ' ', title)
    return re.sub(r'\s+', ' ', title.replace('_', ' ')).strip(' -_.')


def normalized(title: str) -> str:
    title = re.sub(r'\([^)]*(?:video game|game|\d{4})[^)]*\)', '', title, flags=re.I)
    return re.sub(r'[^a-z0-9]+', ' ', title.casefold()).strip()


def similarity(first: str, second: str) -> float:
    a, b = normalized(clean_title(first)), normalized(clean_title(second))
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _valid_host(url: str, provider: str) -> bool:
    try:
        parts = urlparse(url)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
            return False
        host = parts.hostname.lower()
        if provider == 'SteamGridDB':
            return host == 'steamgriddb.com' or host.endswith('.steamgriddb.com')
        if provider == 'Wikipedia':
            return host in {'upload.wikimedia.org', 'en.wikipedia.org'}
        if provider == 'Steam Store':
            return host in {'store.steampowered.com', 'cdn.cloudflare.steamstatic.com',
                            'cdn.akamai.steamstatic.com', 'shared.akamai.steamstatic.com',
                            'shared.cloudflare.steamstatic.com'}
        if provider == 'GOG':
            return host in {'catalog.gog.com', 'images.gog-statics.com'}
        if provider == libretro_art.PROVIDER:
            return libretro_art.valid_url(url)
        if provider == 'Redump':
            return host == 'redump.info'
        if provider in ('PS Covers (Standard)', 'PS Covers (3D)'):
            return (host == 'raw.githubusercontent.com' and
                    re.fullmatch(r'/xlenore/(?:psx-covers|ps2-covers)/main/covers/'
                                 r'(?:default/[A-Z]{4}-\d{5}\.jpg|3d/[A-Z]{4}-\d{5}\.png)',
                                 parts.path) is not None)

        return False
    except ValueError:
        return False


def normalise_api_key(raw: str) -> str:
    """Permit common paste wrappers, never silently edit a token's interior."""
    key = raw.strip().strip('\ufeff\u200b\u200c\u200d')
    if key.lower().startswith('bearer '):
        key = key[7:].strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
        key = key[1:-1].strip()
    if not key:
        raise CoverError('API key is empty.')
    if any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise CoverError('The API key contains whitespace or an invisible character. Paste only the plain token.')
    return key


def _http_problem(exc: Exception, *, tried_direct: bool = False) -> CoverError:
    """Categorise failures without leaking Authorization headers, URLs or tokens."""
    if isinstance(exc, CoverError):
        return exc
    if isinstance(exc, HTTPError):
        if exc.code == 401:
            return CoverError('Artwork provider returned HTTP 401 (authorization rejected). If using SteamGridDB, check its API key.')
        if exc.code == 403:
            return CoverError('The artwork provider returned HTTP 403 (access denied). The server may be blocking this request.')
        if exc.code == 429:
            return CoverError('The artwork provider returned HTTP 429 (rate limit). Try again later.')
        if exc.code == 400:
            return CoverError('The artwork provider returned HTTP 400 (bad request). This may be an application/API issue.')
        if exc.code == 404:
            return CoverError('The provider returned HTTP 404 (endpoint or game not found). Try a different title.')
        if exc.code >= 500:
            return CoverError(f'The artwork server returned HTTP {exc.code}. Try again later.')
        return CoverError(f'The artwork provider returned HTTP {exc.code}.')
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return CoverError('The artwork service timed out. Check network access and try again.')
    if isinstance(exc, ssl.SSLCertVerificationError):
        return CoverError('HTTPS certificate verification failed. Check the Windows date, certificate store, or HTTPS proxy.')
    if isinstance(exc, URLError):
        reason = exc.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            return _http_problem(reason)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return _http_problem(reason)
        return CoverError('The artwork service could not be reached (network, DNS, or proxy failure).')
    if isinstance(exc, (ValueError, UnicodeError)):
        if tried_direct:
            return CoverError('Windows HTTPS request configuration failed, including a retry without the system proxy. Check your proxy settings.')
        return CoverError('An HTTPS request could not be constructed. Check the configured Windows proxy and pasted key.')
    if isinstance(exc, OSError):
        return CoverError('Network connection failed. Check firewall, VPN, DNS or Windows proxy settings.')
    return CoverError(f'Cover request failed ({type(exc).__name__}).')


def _read_response(response, limit: int, provider: str | None, authenticated: bool) -> bytes:
    url = response.geturl()
    if provider is not None and not _valid_host(url, provider):
        raise CoverError('Image redirected to an untrusted website.')
    if authenticated and not _valid_host(url, 'SteamGridDB'):
        raise CoverError('SteamGridDB API redirected outside its HTTPS host. Refusing to transmit credentials.')
    declared = response.headers.get('Content-Length')
    if declared and declared.isdecimal() and int(declared) > limit:
        raise CoverError('The downloaded file is too large.')
    data = response.read(limit + 1)
    if len(data) > limit:
        raise CoverError('Download exceeded size limit.')
    return data


def _get(url: str, *, headers: dict | None = None, limit: int = 2 * 1024 * 1024,
         provider: str | None = None) -> bytes:
    """Fetch securely; retry direct HTTPS if Windows system proxy raises ValueError."""
    authenticated = bool(headers and 'Authorization' in headers)
    if provider is not None and not _valid_host(url, provider):
        raise CoverError('Unexpected image host. Download refused.')
    if authenticated and not _valid_host(url, 'SteamGridDB'):
        raise CoverError('Refusing to send API credentials to an unexpected host.')
    try:
        request = Request(url, headers={'User-Agent': AGENT, 'Accept': '*/*', **(headers or {})})
    except (ValueError, UnicodeError) as exc:
        raise _http_problem(exc) from None
    try:
        try:
            with urlopen(request, timeout=15) as response:
                return _read_response(response, limit, provider, authenticated)
        except ValueError:
            # Malformed Windows proxy settings sometimes raise ValueError.
            try:
                with build_opener(ProxyHandler({})).open(request, timeout=15) as response:
                    return _read_response(response, limit, provider, authenticated)
            except Exception as fallback:
                raise _http_problem(fallback, tried_direct=True) from None
    except CoverError:
        raise
    except Exception as exc:
        raise _http_problem(exc) from None


def _json(url: str, headers: dict | None = None, *, provider: str | None = None) -> dict:
    data = _get(url, headers=headers, limit=1024*1024, provider=provider)
    try:
        response = json.loads(data)
        if not isinstance(response, dict):
            raise ValueError('Not a JSON object')
        return response
    except (ValueError, UnicodeError):
        raise CoverError('The cover provider returned an invalid response.') from None


def search_wikipedia(title: str) -> list[CoverCandidate]:
    query = clean_title(title)
    if not query:
        return []
    params = dict(action='query', format='json', formatversion=2,
                  generator='search', gsrsearch=f'{query} video game', gsrlimit=12,
                  gsrnamespace=0, prop='pageimages', piprop='thumbnail',
                  pithumbsize=700, pilicense='any')
    data = _json('https://en.wikipedia.org/w/api.php?' + urlencode(params))
    pages = data.get('query', {}).get('pages', [])
    output = []
    for page in pages:
        image = page.get('thumbnail', {}).get('source', '')
        if not image or not _valid_host(image, 'Wikipedia'):
            continue
        name = page.get('title', '')
        pid = page.get('pageid')
        if not name or not isinstance(pid, int):
            continue
        output.append(CoverCandidate(name, image, image, 'Wikipedia',
                       f'https://en.wikipedia.org/?curid={pid}', similarity(query, name)))
    return sorted(output, key=lambda c: c.score, reverse=True)[:12]


def search_steamgriddb(title: str, api_key: str) -> list[CoverCandidate]:
    if not api_key.strip():
        raise CoverError('SteamGridDB requires an API key. Enter one or use Wikipedia.')
    api_key = normalise_api_key(api_key)
    query = clean_title(title)
    if not query:
        return []
    headers = {'Authorization': 'Bearer ' + api_key.strip()}
    root = 'https://www.steamgriddb.com/api/v2'
    found = _json(root + '/search/autocomplete/' + quote(query, safe=''), headers)
    if not found.get('success'):
        raise CoverError('SteamGridDB could not search this title.')
    matches = found.get('data') or []
    matches = sorted((m for m in matches if isinstance(m, dict) and isinstance(m.get('id'), int)),
                     key=lambda m: similarity(query, m.get('name', '')), reverse=True)
    result = []
    # Limit artwork requests to the two most relevant games to avoid hammering the API.
    for item in matches[:2]:
        response = _json(root + '/grids/game/' + str(item['id']) + '?' +
                         urlencode({'dimensions': '600x900,342x482,660x930', 'types': 'static', 'nsfw': 'false'}), headers)
        for grid in response.get('data') or []:
            if not isinstance(grid, dict):
                continue
            image = grid.get('url', '')
            preview = grid.get('thumb', image) or image
            if not _valid_host(image, 'SteamGridDB') or not _valid_host(preview, 'SteamGridDB'):
                continue
            result.append(CoverCandidate(item.get('name', query), image, preview, 'SteamGridDB',
                                         f'https://www.steamgriddb.com/game/{item["id"]}',
                                         similarity(query, item.get('name', ''))))
            if len(result) >= 15:
                return result
    return result



# Public storefronts provide additional artwork without credentials.
FREE_SOURCES = ('GOG', 'Steam Store', 'Wikipedia', libretro_art.PROVIDER)
PROVIDERS = ('All Free Sources', libretro_art.PROVIDER, 'PS Covers (Standard)', 'PS Covers (3D)', 'Redump-assisted', 'SteamGridDB', 'GOG', 'Steam Store', 'Wikipedia')


def search_steam_store(title: str) -> list[CoverCandidate]:
    """Look up official Steam library portrait capsules by Steam app ID.

    The public storesearch JSON supplies the ID. Steam's 600x900 library image
    is fetched lazily when the user previews or downloads the candidate.
    Some delisted titles do not have a public portrait, so preview may fail.
    """
    query = clean_title(title)
    if not query:
        return []
    endpoint = 'https://store.steampowered.com/api/storesearch/?' + urlencode(
        {'term': query, 'l': 'english', 'cc': 'US'})
    payload = _json(endpoint, provider='Steam Store')
    results = []
    for item in payload.get('items') or []:
        if not isinstance(item, dict):
            continue
        name, appid = item.get('name'), item.get('id')
        if not isinstance(name, str) or not isinstance(appid, int) or not (0 < appid < 2**32):
            continue
        if item.get('type') not in (None, 'app', 'game'):
            continue
        score = similarity(query, name)
        if score < 0.5:
            continue
        cover = f'https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg'
        results.append(CoverCandidate(name, cover, cover, 'Steam Store',
                                      f'https://store.steampowered.com/app/{appid}/', score))
    return sorted(results, key=lambda item: item.score, reverse=True)[:12]


def search_gog(title: str) -> list[CoverCandidate]:
    """Search GOG's publicly accessible catalog for official vertical covers."""
    query = clean_title(title)
    if not query:
        return []
    endpoint = 'https://catalog.gog.com/v1/catalog?' + urlencode(
        {'limit': 24, 'locale': 'en-US', 'query': query})
    payload = _json(endpoint, provider='GOG')
    results = []
    for item in payload.get('products') or []:
        if not isinstance(item, dict) or item.get('productType') not in (None, 'game', 'pack'):
            continue
        name, cover, slug = item.get('title'), item.get('coverVertical'), item.get('slug')
        if not isinstance(name, str) or not isinstance(cover, str) or not _valid_host(cover, 'GOG'):
            continue
        score = similarity(query, name)
        if score < 0.5:
            continue
        page = ('https://www.gog.com/en/game/' + slug) if isinstance(slug, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,160}', slug) else ''
        results.append(CoverCandidate(name, cover, cover, 'GOG', page, score))
    return sorted(results, key=lambda item: item.score, reverse=True)[:15]


def search_pscovers(title: str, provider: str, game: dict | None = None) -> list[CoverCandidate]:
    """Search xlenore's serial-indexed PSX and PS2 images without an API key.

    Exact filename IDs are preferred; otherwise resolve *exact game titles* with
    the official PCSX2 or DuckStation game-index databases. A candidate is only
    returned after its remote bytes are verified as an image, not for a guessed URL.
    """
    style = {'PS Covers (Standard)': 'default', 'PS Covers (3D)': '3d'}.get(provider)
    if style is None:
        raise CoverError('Unknown PlayStation cover style.')
    platform = (game or {}).get('platform', '')
    if platform not in ('ps1', 'ps2'):
        # Standalone serial queries can select either via supplied game metadata;
        # a non-PS game must never receive a mislabelled PlayStation cover.
        return []
    ids = candidate_serials(title, platform, game)
    matches = []
    for serial in ids:
        url = cover_url(platform, serial, style)
        try:
            payload = _get(url, limit=MAX_IMAGE, provider=provider)
            image_type(payload)
        except CoverError as exc:
            if 'HTTP 404' in str(exc):
                continue
            # Other failures (e.g. network outage, invalid file) should not
            # be presented as downloadable candidates.
            continue
        label = f'{clean_title(title)} [{serial}]'
        matches.append(CoverCandidate(label, url, url, provider,
                                      cover_repository_url(platform), 1.0))
    return matches

def search_libretro(title: str, game: dict | None = None) -> list[CoverCandidate]:
    """Find existing box-art filenames in the official Libretro per-system index.

    Directory listings are cached, and only URLs from the actual listing are
    returned. The UI downloads thumbnails lazily using the existing workers.
    """
    if (game or {}).get('platform', '') not in libretro_art.SYSTEMS:
        return []
    def load_index(url: str) -> bytes:
        return _get(url, provider=libretro_art.PROVIDER, limit=12 * 1024 * 1024)
    found = libretro_art.matches(title, game, load_index)
    return [CoverCandidate(name, url, url, libretro_art.PROVIDER, page, 1.0)
            for name, url, page, region in found]


def best_libretro_bulk(title: str, game: dict | None = None) -> CoverCandidate | None:
    """Prefer exact in-region box art; never bulk-pick a known wrong region."""
    candidates = search_libretro(title, game)
    if not candidates:
        return None
    desired = libretro_art.region_in(title) or libretro_art.region_in(str((game or {}).get('path', '')))
    if desired:
        for candidate in candidates:
            if libretro_art.region_in(candidate.title) == desired:
                return candidate
        return next((candidate for candidate in candidates if not libretro_art.region_in(candidate.title)), None)
    # For untagged titles, prefer a single US cover, then World or Europe.
    # All candidates have an exactly matched base title (never a fuzzy sequel).
    for region in ('USA', 'World', 'Europe'):
        for candidate in candidates:
            if libretro_art.region_in(candidate.title) == region:
                return candidate
    return candidates[0] if len(candidates) == 1 else None


def search_all_free(title: str, game: dict | None = None) -> list[CoverCandidate]:
    """Combine free catalogs; provider failures do not hide other results."""
    found, errors = [], []
    successful = False
    if (game or {}).get('platform') in ('ps1', 'ps2'):
        try:
            found.extend(search_pscovers(title, 'PS Covers (Standard)', game))
        except CoverError:
            pass
    if (game or {}).get('platform') in libretro_art.SYSTEMS:
        try:
            found.extend(search_libretro(title, game))
            successful = True
        except CoverError as exc:
            errors.append((libretro_art.PROVIDER, str(exc)))
    for provider, lookup in (('GOG', search_gog), ('Steam Store', search_steam_store), ('Wikipedia', search_wikipedia)):
        try:
            found.extend(lookup(title))
            successful = True
        except CoverError as exc:
            errors.append((provider, str(exc)))
    if not successful and errors:
        raise CoverError('All free cover services failed: ' + '; '.join(f'{name}: {error}' for name, error in errors))
    unique = {}
    for candidate in found:
        # Providers may change endpoints or return malformed external links.
        # Never offer their results without validating both image hosts.
        if not (_valid_host(candidate.url, candidate.provider) and
                _valid_host(candidate.preview, candidate.provider)):
            continue
        unique.setdefault(candidate.url, candidate)
    return sorted(unique.values(), key=lambda c: c.score, reverse=True)[:30]


def automatic_bulk_match(title: str, game: dict | None = None) -> CoverCandidate | None:
    """Use serial-confirmed PS art first, then free storefronts."""
    if (game or {}).get('platform') in ('ps1', 'ps2'):
        candidates = search_pscovers(title, 'PS Covers (Standard)', game)
        if candidates:
            # An exact disc code is reliable. Otherwise bulk must not silently
            # pick a region when several serials share the same title.
            if explicit_serial(title, game) or len(candidates) == 1:
                return candidates[0]
    errors = []
    successful = False
    if (game or {}).get('platform') in libretro_art.SYSTEMS:
        try:
            candidate = best_libretro_bulk(title, game)
            successful = True
            if candidate:
                return candidate
        except CoverError as exc:
            errors.append(f'Libretro Thumbnails: {exc}')
    for provider, lookup in (('GOG', search_gog), ('Steam Store', search_steam_store), ('Wikipedia', search_wikipedia)):
        try:
            candidates = lookup(title)
            successful = True
        except CoverError as exc:
            errors.append(f'{provider}: {exc}')
            continue
        candidate = best_bulk_match(title, candidates, provider)
        if candidate:
            return candidate
    if not successful and errors:
        raise CoverError('All free cover services failed: ' + '; '.join(errors))
    return None



@dataclass(frozen=True)
class RedumpMatch:
    title: str
    disc_url: str
    confidence: float


class _RedumpLinkParser(HTMLParser):
    """Read public disc-result links without scraping arbitrary image URLs.

    Redump is a checksum/serial database, NOT a box-art image host. We only
    extract actual /disc/<number> links from HTML, without running scripts.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self.disc_url = ''
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag != 'a' or self.disc_url:
            return
        href = dict(attrs).get('href', '')
        if not isinstance(href, str):
            return
        match = re.fullmatch(r'(?:https://redump\.info)?/disc/(\d{1,12})/?', href)
        if match:
            self.disc_url = 'https://redump.info/disc/' + match.group(1)
            self.parts = []

    def handle_data(self, data):
        if self.disc_url:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.disc_url:
            title = re.sub(r'\s+', ' ', ''.join(self.parts)).strip()
            if title and len(title) <= 260:
                self.results.append((title, self.disc_url))
            self.disc_url = ''
            self.parts = []


def redump_search_url(title: str) -> str:
    """HTTPS-only Redump disc lookup (the project's current official domain)."""
    query = clean_title(title)
    if not query or len(query) > 180:
        raise CoverError('Enter a shorter game title to search Redump.')
    return 'https://redump.info/discs/quicksearch/' + quote(query, safe='')


def search_redump_matches(title: str) -> list[RedumpMatch]:
    """Find disc metadata titles; does not claim Redump provides cover images.

    The HTML listing on redump.info can evolve, so parsing failure is treated as
    an unavailable metadata search, never as a fabricated box-art result.
    """
    requested = clean_title(title)
    if not requested:
        return []
    page = _get(redump_search_url(requested), provider='Redump', limit=1024 * 1024)
    parser = _RedumpLinkParser()
    try:
        parser.feed(page.decode('utf-8', errors='replace'))
    except (ValueError, RuntimeError) as exc:
        raise CoverError('Could not read Redump disc search results.') from exc
    results = {}
    for disc_title, url in parser.results:
        # Common Redump region, disc and revision suffixes aren't part of the
        # base game title, but beta/demo entries must not masquerade as retail.
        cleaned = re.sub(r'\s*\((?:Disc|Disk|CD)\s*\d+\)\s*$', '', disc_title, flags=re.I)
        cleaned = re.sub(r'\s*\((?:USA|Europe|Japan|World)(?:,\s*[^()]*)?\)\s*$', '', cleaned, flags=re.I)
        if re.search(r'\((?:beta|demo|prototype|promo|sample)\b', cleaned, re.I):
            continue
        score = similarity(requested, cleaned)
        if score < 0.90:
            continue
        match = RedumpMatch(cleaned, url, score)
        previous = results.get(normalized(cleaned))
        if previous is None or score > previous.confidence:
            results[normalized(cleaned)] = match
    return sorted(results.values(), key=lambda m: m.confidence, reverse=True)[:3]


@dataclass
class RedumpLookupState:
    """Per-batch circuit breaker for broken Redump metadata lookups.

    The Redump server is optional metadata: losing it must not disable covers.
    Kept per worker, never globally, so the next search can retry normally.
    """
    unavailable: bool = False
    reason: str = ''


def search_redump_assisted(title: str, game: dict | None = None,
                           state: RedumpLookupState | None = None) -> list[CoverCandidate]:
    """Find Redump disc matches, falling back to real cover hosts if unavailable.

    For individual cover searches, show direct artwork matches on a missing,
    blocked or unavailable Redump endpoint. For bulk callers, the per-job state
    avoids repeatedly querying a Redump endpoint already known to be broken.
    Redump is never treated as an artwork/image host.
    """
    if state is not None and state.unavailable:
        return search_all_free(title, game)
    try:
        matches = search_redump_matches(title)
    except CoverError as exc:
        if state is not None:
            state.unavailable = True
            state.reason = str(exc)
        return search_all_free(title, game)
    items = []
    failures = []
    for match in matches[:2]:
        for source, lookup in (('GOG', search_gog), ('Steam Store', search_steam_store), ('Wikipedia', search_wikipedia)):
            try:
                covers = lookup(match.title)
            except CoverError as exc:
                failures.append(f'{source}: {exc}')
                continue
            for cover in covers:
                # Redump metadata is not permission to use a loosely matched cover.
                if similarity(match.title, cover.title) < 0.90:
                    continue
                if not _valid_host(cover.url, cover.provider) or not _valid_host(cover.preview, cover.provider):
                    continue
                items.append(replace(cover, redump_reference=match.disc_url,
                                     score=min(match.confidence, similarity(title, cover.title))))
            if items:
                break
        if items:
            break
    if items:
        unique = {item.url: item for item in items}
        return sorted(unique.values(), key=lambda c: c.score, reverse=True)[:20]
    # A valid Redump search with no disc entry (or no image on stores) is a
    # normal occurrence. Try Libretro and PS serial artwork for the real game.
    return search_all_free(title, game)


def choose_bulk_cover(title: str, provider: str, api_key: str = '',
                      game: dict | None = None,
                      redump_state: RedumpLookupState | None = None) -> CoverCandidate | None:
    """Select only a confident, platform-appropriate cover for a bulk run."""
    if provider == 'All Free Sources':
        return automatic_bulk_match(title, game)
    if provider == 'Redump-assisted':
        # If Redump went offline during this run, prefer the strict automatic
        # selector directly, rather than repeating a known failed metadata URL.
        if redump_state is not None and redump_state.unavailable:
            return automatic_bulk_match(title, game)
        covers = search_redump_assisted(title, game, redump_state)
        if redump_state is not None and redump_state.unavailable:
            return automatic_bulk_match(title, game)
        # If Redump has no usable art, use platform-specific free sources.
        candidate = best_bulk_match(title, covers, provider)
        return candidate if candidate is not None else automatic_bulk_match(title, game)
    if provider == libretro_art.PROVIDER:
        return best_libretro_bulk(title, game)
    covers = find_covers(title, provider, api_key, game)
    if provider in ('PS Covers (Standard)', 'PS Covers (3D)'):
        # Never choose one of several ambiguous disc regions automatically.
        return covers[0] if covers and (len(covers) == 1 or explicit_serial(title, game)) else None
    return best_bulk_match(title, covers, provider)


def test_steamgriddb_key(api_key: str) -> bool:
    """Verify authentication via a harmless title search, without saving the token."""
    key = normalise_api_key(api_key)
    response = _json('https://www.steamgriddb.com/api/v2/search/autocomplete/Mario',
                     {'Authorization': 'Bearer ' + key})
    if not response.get('success'):
        raise CoverError('SteamGridDB replied, but did not accept the API search. Try again later.')
    return True


def find_covers(title: str, provider: str, api_key: str = '', game: dict | None = None) -> list[CoverCandidate]:
    if provider == libretro_art.PROVIDER:
        return search_libretro(title, game)
    if provider in ('PS Covers (Standard)', 'PS Covers (3D)'):
        return search_pscovers(title, provider, game)
    if provider == 'Wikipedia':
        return search_wikipedia(title)
    if provider == 'Redump-assisted':
        return search_redump_assisted(title, game)
    if provider == 'SteamGridDB':
        return search_steamgriddb(title, api_key)
    if provider == 'GOG':
        return search_gog(title)
    if provider == 'Steam Store':
        return search_steam_store(title)
    if provider == 'All Free Sources':
        return search_all_free(title, game)
    raise CoverError('Unknown cover provider.')


def image_type(data: bytes) -> str:
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if data.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if len(data) > 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp'
    raise CoverError('Provider returned unsupported image data.')


def preview_bytes(candidate: CoverCandidate) -> bytes:
    payload = _get(candidate.preview, limit=2*1024*1024, provider=candidate.provider)
    image_type(payload)
    return payload


def save_cover(candidate: CoverCandidate, game_id: int, folder: Path) -> Path:
    if game_id <= 0:
        raise ValueError('Invalid game id')
    payload = _get(candidate.url, limit=MAX_IMAGE, provider=candidate.provider)
    extension = image_type(payload)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'{game_id}{extension}'
    fd, tempname = tempfile.mkstemp(prefix=f'.{game_id}-', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tempname, target)
    finally:
        if os.path.exists(tempname):
            os.unlink(tempname)
    return target


def best_bulk_match(title: str, candidates: list[CoverCandidate], provider: str) -> CoverCandidate | None:
    """Bulk never assumes loose search matches are the correct game."""
    if not candidates:
        return None
    candidate = max(candidates, key=lambda c: c.score)
    # Wikipedia can surface generic series/films: require essentially exact page title.
    threshold = 0.98 if candidate.provider == 'Wikipedia' else 0.94
    return candidate if candidate.score >= threshold else None

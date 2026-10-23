"""Cover search and safe on-disk image downloads for GameShelf.

No dependencies outside Python's standard library. Wikimedia search needs no key;
SteamGridDB requires a user-supplied API key, kept in the OS credential vault.
Network operations belong to background Qt workers, NEVER the GUI thread.
"""
from __future__ import annotations

from dataclasses import dataclass
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

AGENT = 'GameShelf/0.7.1 (personal game library cover finder)'
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
        raise CoverError('SteamGridDB API key is empty.')
    if any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise CoverError('The API key contains whitespace or an invisible character. Paste only the plain token.')
    return key


def _http_problem(exc: Exception, *, tried_direct: bool = False) -> CoverError:
    """Categorise failures without leaking Authorization headers, URLs or tokens."""
    if isinstance(exc, CoverError):
        return exc
    if isinstance(exc, HTTPError):
        if exc.code == 401:
            return CoverError('SteamGridDB returned HTTP 401 (authorization rejected). Check the API key in your SteamGridDB preferences.')
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
            # urllib on Windows inherits proxy settings. A malformed proxy URL can
            # raise ValueError before any request reaches SteamGridDB. Try once
            # with the local proxy bypassed instead of treating it as a bad key.
            try:
                with build_opener(ProxyHandler({})).open(request, timeout=15) as response:
                    return _read_response(response, limit, provider, authenticated)
            except Exception as fallback:
                raise _http_problem(fallback, tried_direct=True) from None
    except CoverError:
        raise
    except Exception as exc:
        raise _http_problem(exc) from None


def _json(url: str, headers: dict | None = None) -> dict:
    data = _get(url, headers=headers, limit=1024*1024)
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



def test_steamgriddb_key(api_key: str) -> bool:
    """Verify authentication via a harmless title search, without saving the token."""
    key = normalise_api_key(api_key)
    response = _json('https://www.steamgriddb.com/api/v2/search/autocomplete/Mario',
                     {'Authorization': 'Bearer ' + key})
    if not response.get('success'):
        raise CoverError('SteamGridDB replied, but did not accept the API search. Try again later.')
    return True


def find_covers(title: str, provider: str, api_key: str = '') -> list[CoverCandidate]:
    if provider == 'Wikipedia':
        return search_wikipedia(title)
    if provider == 'SteamGridDB':
        return search_steamgriddb(title, api_key)
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
    threshold = 0.98 if provider == 'Wikipedia' else 0.94
    return candidate if candidate.score >= threshold else None

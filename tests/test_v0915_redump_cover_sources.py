"""Disc metadata/cover provider contract tests for GameShelf v0.9.16.

Network is mocked, so these are deterministic unit tests, not a live API audit.
"""

from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

import pytest

import cover_downloader as art


REDUMP_HTML = b'''<html><body><table><tr><td><a href="/disc/1234">Crash Bandicoot</a></td>
<td>PSX</td></tr><tr><td><a href="/disc/1235">Crash Bandicoot (Beta)</a></td></tr>
<tr><td><a href="/disc/1236">Crash Bandicoot (Disc 2)</a></td></tr>
<tr><td><a href="https://attacker.invalid/disc/1237">Crash Bandicoot</a></td></tr>
<tr><td><a href="/disc/1238">Crash Team Racing</a></td></tr></table></body></html>'''


def test_redump_domain_is_official_and_secure():
    assert art._valid_host('https://redump.info/discs', 'Redump')
    assert not art._valid_host('http://redump.org/discs', 'Redump')
    assert not art._valid_host('https://redump.info.attacker.invalid/discs', 'Redump')
    assert 'Crash%20Bandicoot' in art.redump_search_url('Crash Bandicoot')
    with pytest.raises(art.CoverError):
        art.redump_search_url('  ')


def test_redump_disc_metadata_parsing_disc_names_and_beta_filter():
    with patch.object(art, '_get', return_value=REDUMP_HTML) as getter:
        matches=art.search_redump_matches('Crash Bandicoot')
    assert matches
    assert matches[0].title=='Crash Bandicoot'
    assert matches[0].disc_url=='https://redump.info/disc/1234'
    assert all('Beta' not in m.title for m in matches)
    assert all('Racing' not in m.title for m in matches)
    assert getter.call_args.kwargs['provider']=='Redump'


def test_redump_assisted_gets_cover_from_licensed_host_not_redump():
    expected=art.CoverCandidate('Crash Bandicoot',
        'https://images.gog-statics.com/crash.jpg',
        'https://images.gog-statics.com/crash.jpg', 'GOG',
        'https://www.gog.com/en/game/crash_bandicoot', 1.0)
    with patch.object(art,'search_redump_matches',return_value=[
        art.RedumpMatch('Crash Bandicoot','https://redump.info/disc/1234',1.0)]), \
        patch.object(art,'search_gog',return_value=[expected]), \
        patch.object(art,'search_steam_store',side_effect=AssertionError('should stop after successful provider')):
        items=art.find_covers('Crash Bandicoot','Redump-assisted')
    assert len(items)==1
    assert items[0].provider=='GOG'
    assert items[0].redump_reference=='https://redump.info/disc/1234'
    assert items[0].url.startswith('https://images.gog-statics.com/')


def test_redump_assisted_never_invents_cover_or_uses_attacker_host():
    with patch.object(art,'search_redump_matches',return_value=[
        art.RedumpMatch('Crash Bandicoot','https://redump.info/disc/1234',1.0)]), \
        patch.object(art,'search_gog',return_value=[]), \
        patch.object(art,'search_steam_store',return_value=[]), \
        patch.object(art,'search_wikipedia',return_value=[]):
        assert art.find_covers('Crash Bandicoot','Redump-assisted') == []
    unsafe=art.CoverCandidate('Crash Bandicoot','https://evil.example/x.png',
        'https://evil.example/x.png','GOG')
    with patch.object(art,'search_redump_matches',return_value=[
        art.RedumpMatch('Crash Bandicoot','https://redump.info/disc/1234',1.0)]), \
        patch.object(art,'search_gog',return_value=[unsafe]), \
        patch.object(art,'search_steam_store',return_value=[]), \
        patch.object(art,'search_wikipedia',return_value=[]):
        assert art.search_redump_assisted('Crash Bandicoot')==[]


def test_additional_cover_sources_without_retired_providers():
    assert 'GOG' in art.PROVIDERS
    assert 'Steam Store' in art.PROVIDERS
    assert 'Giant Bomb Tracker' not in art.PROVIDERS
    assert 'MobyGames' not in art.PROVIDERS
    assert 'Redump-assisted' in art.PROVIDERS
    assert art._valid_host('https://images.gog-statics.com/cover.jpg','GOG')
    assert not art._valid_host('https://www.giantbomb.com/a/uploads/cover.jpg','Giant Bomb Tracker')


def test_ui_redump_attribution_and_no_cover_overwrite(tmp_path):
    ui=(Path(__file__).resolve().parents[1]/'cover_ui.py').read_text()
    assert 'Disc match: <a href=' in ui
    assert 'Redump tracks disc metadata, not cover images' in ui
    # Failed or missing remote data must never delete or replace existing artwork.
    folder=tmp_path/'covers'
    folder.mkdir()
    current=folder/'9.png'
    current.write_bytes(b'current-cover')
    with patch.object(art,'_get',return_value=b'<html>not an image</html>'):
        with pytest.raises(art.CoverError):
            art.save_cover(art.CoverCandidate('Bad', 'https://images.gog-statics.com/invalid.png',
                                             'https://images.gog-statics.com/invalid.png', 'GOG'),9,folder)
    assert current.read_bytes()==b'current-cover'

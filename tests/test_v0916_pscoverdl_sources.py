"""PSCoverDL-style serial cover repositories. No live network dependency."""
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

import pscovers
import cover_downloader as art

JPEG = b'\xff\xd8\xff\xe0' + b'test-jpeg-bytes'
PNG = b'\x89PNG\r\n\x1a\n' + b'test-png-bytes'


def test_both_psx_ps2_cover_repos_are_direct_and_standard_or_3d():
    assert pscovers.cover_url('ps1', 'SLUS-00594') == (
        'https://raw.githubusercontent.com/xlenore/psx-covers/main/covers/default/SLUS-00594.jpg')
    assert pscovers.cover_url('ps2', 'SLUS-20312', '3d') == (
        'https://raw.githubusercontent.com/xlenore/ps2-covers/main/covers/3d/SLUS-20312.png')
    assert 'PS Covers (Standard)' in art.PROVIDERS
    assert 'PS Covers (3D)' in art.PROVIDERS
    for invalid in ('SLUS-20312/../../../etc', 'malware.png', 'SLUS-203120'):
        with pytest.raises(ValueError):
            pscovers.cover_url('ps2', invalid)


@pytest.mark.parametrize('text,expected', [
    ('SLUS_203.12.iso', 'SLUS-20312'),
    ('C:/Games/Final Fantasy X (USA) [SLUS-20312].iso', 'SLUS-20312'),
    ('SLUS-00594.bin', 'SLUS-00594'),
    ('SCES_003.44.cue', 'SCES-00344'),
    ('No Serial Here.iso', None),
])
def test_serial_names(text, expected):
    assert pscovers.serial_from_text(text) == expected


def test_serials_from_official_emulator_database_not_fuzzy_guesses():
    pscovers._title_index.cache_clear()
    data = 'SLUS-20312:\n  name: Final Fantasy X\nSLES-50490:\n  name: Final Fantasy X\nSLUS-11111:\n  name: Crash Bandicoot\n'
    with patch('title_lookup._fetch', return_value=data.encode()) as fetch:
        assert pscovers.candidate_serials('Final Fantasy X', 'ps2') == ['SLES-50490','SLUS-20312']
        assert pscovers.candidate_serials('Final Fantasy X Remake', 'ps2') == []
        assert pscovers.candidate_serials('Final Fantasy X', 'psp') == []
        assert pscovers.candidate_serials('Final Fantasy X', 'ps2', {'path':'C:/Games/SLUS-20312.iso'}) == ['SLUS-20312']
        assert fetch.call_count == 1
    pscovers._title_index.cache_clear()


def test_single_cover_provider_filters_404_and_checks_image_bytes():
    game = {'platform':'ps2', 'path':'C:/Games/Final Fantasy X SLUS-20312.iso'}
    with patch.object(art, '_get', return_value=JPEG) as get:
        results = art.find_covers('Final Fantasy X', 'PS Covers (Standard)', game=game)
        assert len(results)==1
        assert results[0].provider == 'PS Covers (Standard)'
        assert results[0].page_url == 'https://github.com/xlenore/ps2-covers'
        assert results[0].url.endswith('/default/SLUS-20312.jpg')
        assert get.call_args.kwargs['provider']=='PS Covers (Standard)'
    with patch.object(art, '_get', return_value=PNG):
        results = art.find_covers('Final Fantasy X', 'PS Covers (3D)', game=game)
        assert len(results)==1 and results[0].url.endswith('/3d/SLUS-20312.png')

    error=HTTPError('https://raw.githubusercontent.com/',404,'Not Found',{},None)
    with patch.object(art, '_get', side_effect=art._http_problem(error)):
        assert art.find_covers('Final Fantasy X', 'PS Covers (Standard)', game=game)==[]
    with patch.object(art, '_get', return_value=b'404 page: <html>'):
        assert art.find_covers('Final Fantasy X', 'PS Covers (Standard)', game=game)==[]


def test_rejects_untrusted_redirects_and_bad_platforms():
    safe='https://raw.githubusercontent.com/xlenore/ps2-covers/main/covers/default/SLUS-20312.jpg'
    assert art._valid_host(safe,'PS Covers (Standard)')
    assert not art._valid_host(safe.replace('raw.githubusercontent.com','raw.githubusercontent.com.attacker.invalid'), 'PS Covers (Standard)')
    assert not art._valid_host(safe.replace('https:', 'http:'), 'PS Covers (Standard)')
    assert not art._valid_host(safe.replace('SLUS-20312.jpg', '../SLUS-20312.jpg'), 'PS Covers (Standard)')
    assert art.find_covers('Final Fantasy X','PS Covers (Standard)',game={'platform':'xbox'}) == []


def test_bulk_only_auto_picks_unambiguous_serial_match():
    game={'platform':'ps1','path':'C:/Games/Metal Gear Solid SLUS-00594.cue'}
    with patch.object(art, '_get', return_value=JPEG), \
         patch.object(art,'search_gog',side_effect=AssertionError('should not search after direct match')):
        result=art.automatic_bulk_match('Metal Gear Solid',game)
        assert result is not None and result.url.endswith('/SLUS-00594.jpg')

    unknown={'platform':'ps1','path':'C:/Games/Metal Gear Solid.cue'}
    two=[art.CoverCandidate('Metal Gear Solid [SLUS-00594]','https://raw.githubusercontent.com/xlenore/psx-covers/main/covers/default/SLUS-00594.jpg','', 'PS Covers (Standard)',score=1),
         art.CoverCandidate('Metal Gear Solid [SLES-11111]','https://raw.githubusercontent.com/xlenore/psx-covers/main/covers/default/SLES-11111.jpg','', 'PS Covers (Standard)',score=1)]
    with patch.object(art,'search_pscovers',return_value=two), \
         patch.object(art,'search_gog',return_value=[]), \
         patch.object(art,'search_steam_store',return_value=[]), \
         patch.object(art,'search_wikipedia',return_value=[]):
        assert art.automatic_bulk_match('Metal Gear Solid',unknown) is None


def test_cover_ui_passes_game_metadata_and_updater_copies_adapter():
    root=Path(__file__).resolve().parents[1]
    ui=(root/'cover_ui.py').read_text(encoding='utf-8')
    assert "find_covers(self.title, self.provider, self.key, self.game)" in ui
    assert "choose_bulk_cover(game['title'], self.provider, self.api_key," in ui
    assert "return automatic_bulk_match(title, game)" in (root/"cover_downloader.py").read_text(encoding="utf-8")
    installer=(root.parent/'update_existing_gameshelf.py').read_text(encoding='utf-8')
    assert '"pscovers.py"' in installer
    assert '"README_V0916.txt"' in installer

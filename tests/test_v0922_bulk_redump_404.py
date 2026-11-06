"""v0.9.26: Redump metadata outages and actual bulk progress regression tests."""
from pathlib import Path
from unittest.mock import patch

import pytest

import cover_downloader as art
from cover_batch import run_batch

GAME = {'id':1,'title':'Crash Bandicoot','platform':'ps1','path':'C:/PS1/Crash Bandicoot.cue'}
COVER = art.CoverCandidate('Crash Bandicoot',
    'https://thumbnails.libretro.com/Sony%20-%20PlayStation/Named_Boxarts/Crash%20Bandicoot%20%28USA%29.png',
    'https://thumbnails.libretro.com/Sony%20-%20PlayStation/Named_Boxarts/Crash%20Bandicoot%20%28USA%29.png',
    'Libretro Thumbnails',score=1.0)


def test_redump_404_goes_to_cover_sources_without_returning_a_404():
    with patch.object(art, 'search_redump_matches', side_effect=art.CoverError('The provider returned HTTP 404')), \
         patch.object(art, 'search_libretro', return_value=[COVER]), \
         patch.object(art, 'search_pscovers', return_value=[]), \
         patch.object(art, 'search_gog', return_value=[]), \
         patch.object(art, 'search_steam_store', return_value=[]), \
         patch.object(art, 'search_wikipedia', return_value=[]):
        found = art.find_covers('Crash Bandicoot', 'Redump-assisted', game=GAME)
    assert found == [COVER]
    assert all(c.provider != 'Redump' for c in found)


def test_redump_batch_circuit_breaker_calls_metadata_only_once():
    with patch.object(art, 'search_redump_matches', side_effect=art.CoverError('HTTP 404')) as search, \
         patch.object(art, 'automatic_bulk_match', return_value=COVER), \
         patch.object(art, 'search_all_free', return_value=[COVER]):
        state = art.RedumpLookupState()
        for _ in range(5):
            assert art.choose_bulk_cover(GAME['title'], 'Redump-assisted', '', GAME, state) == COVER
        assert search.call_count == 1
        assert state.unavailable


def test_live_batch_processing_count_not_max_after_cancellation():
    games=[{**GAME, 'id':i} for i in range(1,205)]
    events=[]
    saved=[]
    result=run_batch(
        games,
        lambda game: COVER,
        lambda game, candidate: saved.append(game['id']),
        lambda n, message: events.append((n,message)),
        lambda: len(saved) >= 3,
        lambda exc: str(exc),
    )
    assert result.processed == 3
    assert result.saved == 3
    assert result.cancelled
    assert events[-1][0] == 3
    assert '204' in events[-1][1]
    assert result.processed < len(games)


def test_one_404_failure_does_not_stop_204_game_batch():
    games=[{**GAME, 'id':i} for i in range(1,205)]
    events=[]
    saved=[]
    def choose(game):
        if game['id'] == 1:
            raise art.CoverError('HTTP 404 (no cover for this game)')
        return COVER if game['id'] in (5,204) else None
    result=run_batch(
        games,choose,
        lambda game, candidate: saved.append(game['id']),
        lambda n, message: events.append((n,message)),
        lambda: False,
        lambda exc: str(exc),
    )
    assert result.processed==204
    assert result.saved==2
    assert result.failed==1
    assert result.skipped==201
    assert saved == [5,204]
    assert events[-1][0] == 204
    assert result.last_error.startswith('HTTP 404')


def test_redump_batch_fallback_works_even_if_other_services_fail():
    with patch.object(art, 'search_redump_matches', side_effect=art.CoverError('HTTP 404')), \
         patch.object(art, 'search_pscovers', return_value=[]), \
         patch.object(art, 'search_libretro', return_value=[COVER]), \
         patch.object(art, 'search_gog', side_effect=art.CoverError('unavailable')), \
         patch.object(art, 'search_steam_store', side_effect=art.CoverError('unavailable')), \
         patch.object(art, 'search_wikipedia', side_effect=art.CoverError('unavailable')):
        state=art.RedumpLookupState()
        result=art.choose_bulk_cover(GAME['title'], 'Redump-assisted', '', GAME, state)
    assert result == COVER
    assert state.unavailable


def test_untrusted_fallback_images_are_rejected():
    unsafe=art.CoverCandidate('Crash Bandicoot', 'https://evil.invalid/x.png', 'https://evil.invalid/x.png','GOG',score=1)
    with patch.object(art,'search_pscovers',return_value=[]), \
         patch.object(art,'search_libretro',return_value=[]), \
         patch.object(art,'search_gog',return_value=[unsafe]), \
         patch.object(art,'search_steam_store',return_value=[]), \
         patch.object(art,'search_wikipedia',return_value=[]):
        assert art.search_all_free('Crash Bandicoot',GAME)==[]


def test_packaged_ui_has_correct_progress_logic():
    ui=Path(__file__).resolve().parents[1].joinpath('cover_ui.py').read_text()
    assert 'run_batch(' in ui
    assert 'self.bar.setValue(processed)' in ui
    assert 'self.bar.setValue(self.bar.maximum())' not in ui
    assert 'choose_bulk_cover' in ui

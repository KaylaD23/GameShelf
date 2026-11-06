"""Regression tests for the real Libretro thumbnail-directory integration."""
from pathlib import Path
from unittest.mock import patch
import pytest
import cover_downloader as art
import libretro_art as lib


def index_html(*filenames):
    from html import escape
    from urllib.parse import quote
    entries='\n'.join(f'<a href="{quote(name, safe="")}">{escape(name)}</a>' for name in filenames)
    return f'<!doctype html><html><body><h1>Index</h1>{entries}</body></html>'.encode()


@pytest.fixture(autouse=True)
def clear():
    lib.clear_cache()
    yield
    lib.clear_cache()


def test_actual_official_server_path_and_console_mapping():
    assert lib.catalog_url('Sony - PlayStation') == 'https://thumbnails.libretro.com/Sony%20-%20PlayStation/Named_Boxarts/'
    assert lib.image_url('Sony - PlayStation', 'Crash Bandicoot (USA).png') == 'https://thumbnails.libretro.com/Sony%20-%20PlayStation/Named_Boxarts/Crash%20Bandicoot%20%28USA%29.png'
    assert lib.SYSTEMS['ps2'] == ('Sony - PlayStation 2',)
    assert 'xbox360' in lib.SYSTEMS
    assert 'switch' not in lib.SYSTEMS


def test_parser_only_accepts_real_png_file_links():
    html=index_html('Crash Bandicoot (USA).png', 'Crash Bandicoot (Europe).png', 'Crash Bandicoot (USA).jpg')
    html+=b'<a href="../">bad</a><a href="https://bad.example/evil.png">bad</a><a href="%2e%2e%2fsecret.png">bad</a>'
    assert set(lib.parse_index(html)) == {'Crash Bandicoot (USA).png','Crash Bandicoot (Europe).png'}


def test_region_match_and_no_wrong_sequel():
    html=index_html('Crash Bandicoot (USA).png','Crash Bandicoot (Europe).png',
                    'Crash Bandicoot 2 (USA).png','Crash Bandicoot (USA) (Demo).png')
    loads=[]
    def fetch(url):
        loads.append(url)
        return html
    candidates=lib.matches('Crash Bandicoot',{'platform':'ps1','path':'C:/Roms/Crash Bandicoot (Europe).cue'},fetch)
    assert len(candidates)==1
    assert candidates[0][0]=='Crash Bandicoot (Europe)'
    assert len(loads)==1
    # Cached same console, even when requesting another title.
    assert lib.matches('Crash Bandicoot 2',{'platform':'ps1'},fetch)[0][0] == 'Crash Bandicoot 2 (USA)'
    assert len(loads)==1


def test_unknown_console_does_not_fetch_or_offer_another_platform_art():
    def forbidden(_):
        raise AssertionError('should not hit network')
    assert lib.matches('Crash Bandicoot',{'platform':'switch'},forbidden)==[]
    assert lib.matches('Crash Bandicoot',None,forbidden)==[]


def test_index_for_different_consoles_is_separate():
    seen=[]
    def fetch(url):
        seen.append(url)
        if 'PlayStation%202' in url:
            return index_html('187 Ride or Die (USA).png')
        return index_html('Crash Bandicoot (USA).png')
    assert lib.matches('Crash Bandicoot',{'platform':'ps1'},fetch)
    assert lib.matches('187 Ride or Die',{'platform':'ps2'},fetch)
    assert not lib.matches('Crash Bandicoot',{'platform':'ps2'},fetch)
    assert len(seen)==2


def test_security_blocks_hosts_redirects_traversal_and_nonboxart():
    okay=lib.image_url('Sony - PlayStation','Crash Bandicoot (USA).png')
    assert art._valid_host(okay,'Libretro Thumbnails')
    assert art._valid_host(lib.catalog_url('Sony - PlayStation'),'Libretro Thumbnails')
    for url in ('http://thumbnails.libretro.com/Sony%20-%20PlayStation/Named_Boxarts/a.png',
                'https://thumbnails.libretro.com.evil.example/Sony%20-%20PlayStation/Named_Boxarts/a.png',
                'https://thumbnails.libretro.com/Sony%20-%20PlayStation/Named_Snaps/a.png',
                'https://thumbnails.libretro.com/Sony%20-%20PlayStation/Named_Boxarts/..%2fsecret.png',
                'https://thumbnails.libretro.com/Sony%20-%20PlayStation/Named_Boxarts/a.jpg',
                'https://thumbnails.libretro.com/Sony%20-%20PlayStation/Named_Boxarts/a.png?redirect=1'):
        assert not art._valid_host(url,'Libretro Thumbnails'),url


def test_picker_results_and_bulk_download_use_console_index(monkeypatch):
    def fake_get(url, **kwargs):
        assert kwargs['provider']=='Libretro Thumbnails'
        return index_html('Crash Bandicoot (USA).png','Crash Bandicoot (Europe).png')
    monkeypatch.setattr(art,'_get',fake_get)
    game={'platform':'ps1','path':'C:/Games/Crash Bandicoot (USA).cue'}
    results=art.find_covers('Crash Bandicoot','Libretro Thumbnails',game=game)
    assert [r.title for r in results]==['Crash Bandicoot (USA)']
    assert all(r.provider=='Libretro Thumbnails' for r in results)
    assert art.best_libretro_bulk('Crash Bandicoot',game)==results[0]
    assert 'Libretro Thumbnails' in art.PROVIDERS
    assert 'Giant Bomb Tracker' not in art.PROVIDERS


def test_all_free_uses_libretro_even_when_other_providers_fail(monkeypatch):
    monkeypatch.setattr(art,'_get',lambda url,**kwargs:index_html('Crash Bandicoot (USA).png'))
    monkeypatch.setattr(art,'search_pscovers',lambda *args:[])
    monkeypatch.setattr(art,'search_gog',lambda *args: (_ for _ in ()).throw(art.CoverError('unavailable')))
    monkeypatch.setattr(art,'search_steam_store',lambda *args: (_ for _ in ()).throw(art.CoverError('unavailable')))
    monkeypatch.setattr(art,'search_wikipedia',lambda *args: (_ for _ in ()).throw(art.CoverError('unavailable')))
    items=art.search_all_free('Crash Bandicoot',{'platform':'ps1'})
    assert len(items)==1 and items[0].provider=='Libretro Thumbnails'
    best=art.automatic_bulk_match('Crash Bandicoot',{'platform':'ps1'})
    assert best is not None and best.provider=='Libretro Thumbnails'


def test_update_contains_new_module_and_version():
    root=Path(__file__).resolve().parents[1]
    updater=(root.parent/'update_existing_gameshelf.py').read_text()
    assert '"libretro_art.py"' in updater
    assert '"README_V0921.txt"' in updater
    assert 'RELEASE = "0.9.33"' in updater
    assert (root/'VERSION.txt').read_text().strip()=='0.9.33'

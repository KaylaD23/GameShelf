import json
from pathlib import Path
from unittest import mock

import pytest
from core import EMULATORS, PLATFORMS, detect_bundled_executables, launch_args, scan_games
from title_lookup import TitleResolver, parse_ps_titles_tsv, parse_ps5_param_json, normalize_id, detect_id


def test_fifteen_emulators_and_separate_tabs():
    assert len(EMULATORS)==15
    assert list(PLATFORMS).index('xbox360')==list(PLATFORMS).index('xbox')+1
    assert PLATFORMS['ps4']=='PlayStation 4'
    assert PLATFORMS['ps5']=='PlayStation 5'
    assert {e.key for e in EMULATORS}>={'citron','xenia','shadps4'}
    assert [e.key for e in EMULATORS if 'switch' in e.platforms]==['ryujinx','citron']


def test_emulator_four_directory_detection(tmp_path):
    for directory, exe in [('Citron','citron.exe'),('Xenia Canary','xenia_canary.exe'),('shadps4/Versions/Pre-release','shadPS4.exe')]:
        target=tmp_path/'Emulators'/'Emulators 4'/directory/exe
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(b'EXE')
    detected=detect_bundled_executables(tmp_path)
    assert {'citron','xenia','shadps4'}<=set(detected)
    assert all('Emulators 4' in p for p in detected.values())


def test_new_launch_profiles(tmp_path):
    rom=tmp_path/'Mario Kart 8.xci';rom.write_bytes(b'fixture')
    assert launch_args('citron',rom,True)==['-f','-g',str(rom)]
    assert launch_args('xenia',tmp_path/'xbox 360.iso',True)==[str(tmp_path/'xbox 360.iso')]
    game=tmp_path/'CUSA00900'; game.mkdir()
    assert launch_args('shadps4',game,False)==['CUSA00900']
    assert launch_args('shadps4',game,True)==['--fullscreen','true','CUSA00900']
    with pytest.raises(ValueError):launch_args('shadps4',tmp_path/'unknown',True)


def test_ps5_database_exact_and_missing(tmp_path):
    tsv='titleId\tconceptId\tname\tcontentId\tregion\tpublisherId\nPPSA01880_00\t101\tQuake\tUP0000\tUP\tUP0000\nPPSA01342_00\t102\tDemon’s Souls\tUP0000\tUP\tUP0000\n'
    assert parse_ps_titles_tsv(tsv,'ps5')['PPSA01880']=='Quake'
    assert normalize_id('PPSA01880','ps4') is None
    assert normalize_id('CUSA00900','ps5') is None
    record={'title':'Ppsa01880','platform':'ps5','path':str(tmp_path/'PPSA01880')}
    with mock.patch('title_lookup._fetch',return_value=tsv.encode()):
        assert TitleResolver().resolve(record)==('Quake','PlayStation Titles')
        assert TitleResolver().resolve({'title':'Ppsa99999','platform':'ps5','path':str(tmp_path/'PPSA99999')}) is None
    assert detect_id({'title':'Ppsa01342 App0','platform':'ps5','path':str(tmp_path/'PPSA01342')})=='PPSA01342'
    assert detect_id({'title':'An Actual Game PPSA01342','platform':'ps5','path':str(tmp_path/'PPSA01342')}) is None


def test_ps5_embedded_title_metadata(tmp_path):
    game=tmp_path/'PPSA01880';meta=game/'sce_sys'/'param.json'
    meta.parent.mkdir(parents=True)
    meta.write_text(json.dumps({'titleId':'PPSA01880','defaultLanguage':'en-US','localizedParameters':{'en-US':{'titleName':'Quake (PS5)'},'ja-JP':{'titleName':'別名'}}}))
    assert parse_ps5_param_json(meta)['TITLE']=='Quake (PS5)'
    assert TitleResolver().resolve({'title':'PPSA01880','platform':'ps5','path':str(game)})==('Quake (PS5)','Local param.json')


def test_xbox360_import(tmp_path):
    rom=tmp_path/'Games'/'Game A'/'default.xex';rom.parent.mkdir(parents=True);rom.write_bytes(b'')
    result=scan_games(tmp_path,'xbox360')
    assert len(result)==1
    assert result[0][1]=='xbox360'
    assert result[0][2]==str(rom)


def test_ps_title_source_network_failure_keeps_id(tmp_path):
    record={'title':'PPSA01880','platform':'ps5','path':str(tmp_path/'PPSA01880')}
    with mock.patch('title_lookup._fetch',return_value=b''):
        assert TitleResolver().resolve(record) is None


def test_source_archive_names_match_renamed_files():
    from BUNDLE_EMULATORS4 import PARTS
    assert PARTS==('Emulators 4.zip.001','Emulators 4.zip.002')


def test_renaming_archive_suffix_safely(tmp_path):
    from BUNDLE_EMULATORS4 import rename_old_variants
    for n in (1,2):
        (tmp_path/f'Emulators 4.zip(1).00{n}').write_bytes(bytes([n]))
    rename_old_variants(tmp_path)
    assert (tmp_path/'Emulators 4.zip.001').read_bytes()==b'\x01'
    assert (tmp_path/'Emulators 4.zip.002').read_bytes()==b'\x02'
    # Never clobber an existing canonical name.
    (tmp_path/'Emulators 4.zip(1).001').write_bytes(b'other')
    rename_old_variants(tmp_path)
    assert (tmp_path/'Emulators 4.zip.001').read_bytes()==b'\x01'
    assert (tmp_path/'Emulators 4.zip(1).001').exists()


def test_existing_bundle_repair_never_overwrites(tmp_path):
    from BUNDLE_EMULATORS4 import sync_existing_directory
    source=tmp_path/'source'; destination=tmp_path/'destination'
    source.mkdir();destination.mkdir()
    (source/'needed.dll').write_bytes(b'original')
    assert sync_existing_directory(source,destination)==1
    assert sync_existing_directory(source,destination)==0
    (destination/'needed.dll').write_bytes(b'modified')
    with pytest.raises(ValueError,match='refusing to overwrite'):
        sync_existing_directory(source,destination)
    assert (destination/'needed.dll').read_bytes()==b'modified'

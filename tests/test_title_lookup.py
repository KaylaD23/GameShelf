import tempfile
import struct
from pathlib import Path
from unittest import mock
from title_lookup import normalize_id, detect_id, parse_ps_game_database, parse_param_sfo, TitleResolver, local_sfo_title
from cover_geometry import fit_inside


def test_id_recognition():
    assert normalize_id('SLUS_209.86', 'ps2')=='SLUS-20986'
    assert normalize_id('SCES-50916','ps2')=='SCES-50916'
    assert normalize_id('PCSE00120','vita')=='PCSE00120'
    assert normalize_id('PPSA16441','ps5')=='PPSA16441'
    assert normalize_id('1234 Game','ps2') is None
    assert detect_id({'title':'SLUS 209 86','platform':'ps2','path':'C:/ROMs/SLUS_209.86.iso'})=='SLUS-20986'
    assert detect_id({'title':'Already Named Game','platform':'ps2','path':'C:/ROMs/SLUS_209.86.iso'}) is None


def test_parse_pcsx2_and_duckstation_game_databases():
    sample='''slus-20986:\n  name: "Test Game"\n  compat: 5\nSCUS-94194: # comment\n  name: Gran Turismo\n  region: NTSC-U\nother:\n  name: "Ignored"\n'''
    got=parse_ps_game_database(sample,'ps2')
    assert got=={'SLUS-20986':'Test Game','SCUS-94194':'Gran Turismo'}


def test_official_lookup_is_exact_and_source_annotated():
    record={'title':'SLUS-20986','platform':'ps2','path':'Z:/SLUS-20986.iso'}
    with mock.patch('title_lookup._fetch',return_value=b'SLUS-20986:\n  name: "Example: Final Release"\n') as fetch:
        result=TitleResolver().resolve(record)
    assert result==('Example: Final Release','PCSX2 GameIndex')
    assert fetch.call_count==1


def test_no_guess_when_not_found():
    record={'title':'SLUS-20986','platform':'ps2','path':'Z:/SLUS-20986.iso'}
    with mock.patch('title_lookup._fetch',return_value=b'SLUS-20190:\n  name: Wrong Game\n'):
        assert TitleResolver().resolve(record) is None


def test_vita_issues_require_exact_code():
    payload=b'{"items":[{"title":"Other [PCSE00235]"},{"title":"Persona 4 Golden [PCSE00120]"}]}'
    with mock.patch('title_lookup._fetch',return_value=payload):
        assert TitleResolver().resolve({'title':'PCSE00120','platform':'vita','path':'Z:/PCSE00120'})==('Persona 4 Golden','Vita3K compatibility')


def make_sfo(path):
    keys=b'TITLE\x00TITLE_ID\x00'; data=b'The Proper Title\x00PCSE00120\x00'
    key_off=20+32; data_off=key_off+len(keys)
    header=struct.pack('<5I',0x46535000,0x101,key_off,data_off,2)
    entries=struct.pack('<HHIII',0,0x204,17,17,0)+struct.pack('<HHIII',6,0x204,10,10,17)
    path.write_bytes(header+entries+keys+data)


def test_sfo_local_metadata():
    with tempfile.TemporaryDirectory() as temp:
        folder=Path(temp)/'PCSE00120';folder.mkdir()
        make_sfo(folder/'PARAM.SFO')
        assert parse_param_sfo(folder/'PARAM.SFO')['TITLE']=='The Proper Title'
        assert local_sfo_title({'title':'PCSE00120','platform':'vita','path':str(folder)})=='The Proper Title'
        assert TitleResolver().resolve({'title':'PCSE00120','platform':'vita','path':str(folder)})==('The Proper Title','Local PARAM.SFO')


def test_cover_geometry_portrait_and_landscape_and_square():
    assert fit_inside(170,235,170,235)==(0,0,170,235)
    assert fit_inside(680,940,170,235)==(0,0,170,235)
    assert fit_inside(1600,900,170,235)==(0,69,170,96)
    assert fit_inside(300,300,170,235)==(0,32,170,170)
    assert all(v>=0 for v in fit_inside(1400,600,192,248))


def test_rpcs3_exact_id_only():
    record={'title':'BLUS30418','platform':'ps3','path':'Z:/BLUS30418'}
    payload=b'{"results":{"BLUS30418":{"title":"Game One"},"BLUS99999":{"title":"Incorrect"}}}'
    with mock.patch('title_lookup._fetch',return_value=payload):
        assert TitleResolver().resolve(record)==('Game One','RPCS3 compatibility')
    with mock.patch('title_lookup._fetch',return_value=b'{"results":[{"serial":"BLUS99999","title":"Incorrect"}]}'):
        assert TitleResolver().resolve(record) is None


def test_dolphin_requires_plausible_id():
    assert normalize_id('GALE01','gc')=='GALE01'
    assert normalize_id('RMGE01','wii')=='RMGE01'
    assert normalize_id('BATMAN','gc') is None
    assert normalize_id('Mario','gc') is None


def test_psp_iso9660_metadata_with_synthetic_fixture():
    from title_lookup import parse_psp_iso_metadata
    def record(name,block,size,flags):
        raw=name if isinstance(name,bytes) else name.encode('ascii')
        length=33+len(raw)+(len(raw)%2==0)
        entry=bytearray(length)
        entry[0]=length
        struct.pack_into('<I',entry,2,block)
        struct.pack_into('<I',entry,10,size)
        entry[25]=flags
        entry[32]=len(raw)
        entry[33:33+len(raw)]=raw
        return bytes(entry)
    with tempfile.TemporaryDirectory() as temp:
        p=Path(temp)/'ULUS10466.iso'
        block=bytearray(22*2048)
        pvd=16*2048
        block[pvd]=1;block[pvd+1:pvd+6]=b'CD001'
        block[pvd+156:pvd+190]=record(b'\x00',17,2048,2)[:34]
        root=record('PSP_GAME',18,2048,2)
        block[17*2048:17*2048+len(root)]=root
        # Reuse valid PARAM.SFO fixture.
        temp_sfo=Path(temp)/'PARAM.SFO'
        make_sfo(temp_sfo)
        sfo=temp_sfo.read_bytes()
        inner=record('PARAM.SFO;1',19,len(sfo),0)
        block[18*2048:18*2048+len(inner)]=inner
        block[19*2048:19*2048+len(sfo)]=sfo
        p.write_bytes(block)
        assert parse_psp_iso_metadata(p)['TITLE']=='The Proper Title'
        assert TitleResolver().resolve({'title':'ULUS10466','platform':'psp','path':str(p)})==('The Proper Title','Local PARAM.SFO')

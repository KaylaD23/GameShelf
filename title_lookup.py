"""GameShelf game-title resolver (stdlib only).

Sources: PCSX2 GameIndex.yaml, DuckStation gamedb.yaml, Vita3K compatibility
issue titles and local PARAM.SFO. No guessed matches, no game-file mutation.
"""
from __future__ import annotations

import json
import re
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from core import DATA

CACHE = DATA / 'title_databases'
URLS = {
    'ps2': 'https://raw.githubusercontent.com/PCSX2/pcsx2/master/bin/resources/GameIndex.yaml',
    'ps1': 'https://raw.githubusercontent.com/stenzek/duckstation/master/data/resources/gamedb.yaml',
    'ps4': 'https://raw.githubusercontent.com/andshrew/PlayStation-Titles/main/PS4_Titles.tsv',
    'ps5': 'https://raw.githubusercontent.com/andshrew/PlayStation-Titles/main/PS5_Titles.tsv',
}
MAX_DOWNLOAD = 9 * 1024 * 1024
SERIAL_PS = re.compile(r'^(?:S[LC][AUEIP][SCE]?|SLUS|SCUS|SLES|SCES|SLPS|SLPM|SCPS|SCED|SLED|SCED|PBPX|PAPX)[-_. ]*\d{2,5}(?:[._-]\d{2})?$', re.I)
SERIAL_PORTABLE = re.compile(r'^(?:[UN][LC][UEJP]S|ULUS|ULES|UCUS|UCES|ULJS|ULJM|NPJH|NPUH|NPEH|NPEG|NPUG|NPJG|PC[A-Z]{2}|PPSA|CUSA)[-_ .]*\d{4,6}$', re.I)
SERIAL_PS3 = re.compile(r'^(?:BLUS|BLES|BCUS|BCES|BLJS|BLJM|NPUB|NPEB|NPEA|NPJA|BCJS|BLAS|BCAS|NPHA|NPHB)[-_. ]*\d{5}$', re.I)
SERIAL_NINTENDO = re.compile(r'^(?=[A-Z0-9]{4}(?:[A-Z0-9]{2})?$)(?=.*[0-9])[A-Z0-9]+$',re.I)
SERIAL_SWITCH = re.compile(r'^01[0-9A-F]{14}$',re.I)


def normalize_id(text: str, platform: str) -> str | None:
    value = text.strip().upper()
    if platform in ('ps1','ps2'):
        if not SERIAL_PS.fullmatch(value):
            return None
        # SLUS_209.86 / SLUS-20986 / SLUS 209 86 -> SLUS-20986.
        compact = re.sub(r'[^A-Z0-9]', '', value)
        match = re.fullmatch(r'([A-Z]{4})(\d{5})',compact)
        return f'{match[1]}-{match[2]}' if match else None
    if platform == 'ps3' and SERIAL_PS3.fullmatch(value):
        return re.sub(r'[^A-Z0-9]', '', value)
    if platform in ('vita','psp','ps4','ps5') and SERIAL_PORTABLE.fullmatch(value):
        compact=re.sub(r'[^A-Z0-9]', '', value)
        if platform=='ps4' and not re.fullmatch(r'CUSA\d{5}',compact):return None
        if platform=='ps5' and not re.fullmatch(r'PPSA\d{5}',compact):return None
        return compact
    if platform in ('gc','wii') and SERIAL_NINTENDO.fullmatch(value):
        return value
    if platform == 'switch' and SERIAL_SWITCH.fullmatch(value):
        return value
    return None


def detect_id(game: dict) -> str | None:
    """Only return an ID if the displayed title is itself an ID.

    Never overwrite meaningful manually assigned titles merely because an ID is
    embedded somewhere in the filename or directory.
    """
    platform = game.get('platform','')
    title = game.get('title','')
    candidate = normalize_id(title,platform)
    if candidate is None and platform in ('ps4','ps5'):
        # Earlier imports used safe_name() on PPSA/CUSA directory names,
        # producing "Ppsa01342 App0" rather than a bare serial.
        cleaned=re.sub(r'[_ .-]+','',title.upper())
        match=re.fullmatch(r'((?:PPSA|CUSA)\d{5})(?:APP\d*|GAME)?',cleaned)
        if match:candidate=normalize_id(match[1],platform)
    if candidate:
        return candidate
    path = Path(game.get('path',''))
    # safe_name() converts punctuation to spaces, so accept it when the raw
    # filename/dirname is explicitly a serial and no unrelated words appear.
    stems = [path.stem,path.name,path.parent.name]
    for stem in stems:
        code = normalize_id(stem,platform)
        if code and re.sub(r'[^A-Z0-9]','',title.upper()) == re.sub(r'[^A-Z0-9]','',stem.upper()):
            return code
    return None


def parse_ps_game_database(text: str, platform: str) -> dict[str,str]:
    """Extract only root-level SERIAL and their nested name/title from YAML.

    Avoids adding PyYAML to the frontend and ignores unrelated config fields.
    """
    result: dict[str,str] = {}
    current: str | None = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if line[0] not in ' \t':
            match = re.match(r'^([A-Za-z0-9_-]{4,25}):\s*(?:#.*)?$',line)
            current = normalize_id(match.group(1),platform) if match else None
            continue
        if not current:
            continue
        match = re.match(r'^\s{2,}(?:name|title):\s*(.*?)\s*$',line)
        if not match:
            continue
        value = match.group(1).strip()
        if value.startswith(('"',"'")) and value.endswith(value[0]):
            value=value[1:-1]
        else:
            value=re.split(r'\s+#',value,maxsplit=1)[0].strip()
        if value and not value.startswith(('|','>','[','{')) and len(value)<250:
            result.setdefault(current,value)
    return result


def parse_ps_titles_tsv(text:str,platform:str) -> dict[str,str]:
    """Parse exact PlayStation title-ID mappings from andshrew's public TSV.

    A region code suffix such as PPSA01880_00 is not part of the title ID.
    """
    result={}
    rows=iter(text.splitlines())
    try: header=next(rows).split('\t')
    except StopIteration:return result
    if 'titleId' not in header or 'name' not in header:return result
    id_idx=header.index('titleId');name_idx=header.index('name')
    for line in rows:
        cols=line.split('\t')
        if len(cols)<=max(id_idx,name_idx):continue
        raw_id=cols[id_idx].split('_',1)[0].strip().upper()
        name=cols[name_idx].strip()
        if (normalize_id(raw_id,platform)==raw_id and name and len(name)<250
                and not normalize_id(name,platform)):
            result.setdefault(raw_id,name)
    return result


def parse_ps5_param_json(path:Path)->dict[str,str]:
    """Parse metadata from PS5 sce_sys/param.json, without mutating files."""
    try:
        if path.stat().st_size>4*1024*1024:return {}
        obj=json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError,UnicodeError,ValueError):return {}
    if not isinstance(obj,dict):return {}
    result={}
    title_id=obj.get('titleId')
    if isinstance(title_id,str):result['TITLE_ID']=title_id
    localized=obj.get('localizedParameters',{})
    if isinstance(localized,dict):
        default=obj.get('defaultLanguage')
        items=[localized.get(default)] if default else []
        items.extend(localized.values())
        for item in items:
            if isinstance(item,dict) and isinstance(item.get('titleName'),str) and item['titleName'].strip():
                result['TITLE']=item['titleName'].strip();break
    if 'TITLE' not in result and isinstance(obj.get('titleName'),str):result['TITLE']=obj['titleName'].strip()
    return result


def parse_param_sfo(path: Path) -> dict[str,str]:
    """Read Sony PARAM.SFO strings; never writes to the supplied file."""
    try:
        with path.open('rb') as f:
            data=f.read(4*1024*1024)
    except OSError:
        return {}
    return parse_param_sfo_data(data)


def parse_param_sfo_data(data:bytes) -> dict[str,str]:
    if len(data)<20 or data[:4]!=b'\x00PSF':
        return {}
    try:
        _,_,key_base,data_base,count=struct.unpack_from('<5I',data)
        if count>4096 or data_base>=len(data) or key_base>=len(data):
            return {}
        result={}
        for i in range(count):
            key_offset,fmt,length,maximum,value_offset=struct.unpack_from('<HHIII',data,20+16*i)
            start=key_base+key_offset
            end=data.find(b'\x00',start,min(start+100,len(data)))
            if not (0<=start<end<len(data)):
                continue
            key=data[start:end].decode('ascii','ignore')
            if key not in ('TITLE','TITLE_ID','DISC_ID') or fmt not in (0x0204,0x0004):
                continue
            off=data_base+value_offset
            if not (0<=off<len(data)):
                continue
            value=data[off:off+min(length,512)].split(b'\x00',1)[0].decode('utf-8','replace').strip()
            if value:
                result[key]=value
        return result
    except (ValueError,struct.error):
        return {}


def parse_psp_iso_metadata(iso: Path) -> dict[str,str]:
    """Read PSP_GAME/PARAM.SFO from a plain ISO9660 image without copying it.

    Doesn't support compressed CSO or CHD; malformed files fail closed.
    """
    try:
        with iso.open('rb') as f:
            f.seek(16*2048)
            pvd=f.read(2048)
            if len(pvd)!=2048 or pvd[0]!=1 or pvd[1:6]!=b'CD001':
                return {}
            def entries(rec:bytes):
                extent=int.from_bytes(rec[2:6],'little')
                size=int.from_bytes(rec[10:14],'little')
                if extent<=0 or size<=0 or size>8*1024*1024:
                    return []
                f.seek(extent*2048)
                directory=f.read(size)
                result=[];i=0
                while i<len(directory):
                    length=directory[i]
                    if not length:
                        i=((i//2048)+1)*2048
                        continue
                    if i+length>len(directory) or length<34:break
                    item=directory[i:i+length]
                    name_len=item[32]
                    name=item[33:33+name_len].decode('ascii','ignore').upper().split(';',1)[0]
                    if name and name not in ('\x00','\x01'):result.append((name,item))
                    i+=length
                return result
            root=pvd[156:190]
            game_folder=next((rec for name,rec in entries(root) if name=='PSP_GAME'),None)
            if game_folder is None:return {}
            entry=next((rec for name,rec in entries(game_folder) if name=='PARAM.SFO'),None)
            if entry is None:return {}
            extent=int.from_bytes(entry[2:6],'little')
            size=int.from_bytes(entry[10:14],'little')
            if not 0<size<=4*1024*1024:return {}
            f.seek(extent*2048)
            return parse_param_sfo_data(f.read(size))
    except (OSError,ValueError,OverflowError):
        return {}


def local_sfo_title(game:dict) -> str | None:
    path=Path(game.get('path',''))
    if game.get('platform')=='psp' and path.is_file() and path.suffix.lower()=='.iso':
        metadata=parse_psp_iso_metadata(path)
        if metadata.get('TITLE') and not normalize_id(metadata['TITLE'],'psp'):
            return metadata['TITLE']
    root=path if path.is_dir() else path.parent
    if game.get('platform')=='ps5':
        for folder in (root,root.parent):
            result=parse_ps5_param_json(folder/'sce_sys'/'param.json')
            if result.get('TITLE') and not normalize_id(result['TITLE'],'ps5'):
                return result['TITLE']
    paths=[root/'PARAM.SFO',root/'sce_sys'/'param.sfo',root/'PS3_GAME'/'PARAM.SFO',root/'sce_sys'/'PARAM.SFO',root.parent/'PARAM.SFO']
    for p in paths:
        metadata=parse_param_sfo(p)
        title=metadata.get('TITLE','').strip()
        if title and not normalize_id(title,game.get('platform','')):
            return title
    return None


def _fetch(url:str,*,ttl:int,cache_name:str)->bytes:
    CACHE.mkdir(parents=True,exist_ok=True)
    dest=CACHE/cache_name
    if dest.is_file() and time.time()-dest.stat().st_mtime < ttl:
        return dest.read_bytes()
    req=urllib.request.Request(url,headers={'User-Agent':'GameShelf/0.9 (personal game library)','Accept':'application/json, text/plain, */*'})
    try:
        try:
            response=urllib.request.urlopen(req,timeout=12)
        except ValueError:
            # A malformed Windows proxy environment raises ValueError before
            # any HTTP request occurs. Retry once without inherited proxies.
            response=urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=12)
        with response as r:
            chunks=[];size=0
            while True:
                part=r.read(65536)
                if not part:break
                size+=len(part)
                if size>MAX_DOWNLOAD:raise ValueError('Database download exceeds size limit')
                chunks.append(part)
            data=b''.join(chunks)
        if data:
            temp=dest.with_suffix('.tmp')
            temp.write_bytes(data)
            temp.replace(dest)
            return data
    except (OSError,ValueError,urllib.error.URLError):
        if dest.is_file():return dest.read_bytes()
    return b''


class TitleResolver:
    """Session-cached exact mappings. Misses never turn into invented names."""
    def __init__(self):
        self.maps: dict[str,dict[str,str]]={}
        self.vita_misses=set()
        self.count=0
        self.online_failures=set()
    def _lookup_yaml(self,platform:str,serial:str)->str|None:
        if platform not in self.maps:
            raw=_fetch(URLS[platform],ttl=7*86400,cache_name=platform+'_gamedb.yaml')
            self.maps[platform]=(parse_ps_titles_tsv(raw.decode('utf-8-sig','replace'),platform)
                                 if platform in ('ps4','ps5') else parse_ps_game_database(raw.decode('utf-8','replace'),platform))
        return self.maps[platform].get(serial)
    def _lookup_vita_issue(self,serial:str)->str|None:
        if serial in self.vita_misses:return None
        self.vita_misses.add(serial)
        # Exact title-ID match in Vita3K's official public compatibility issues.
        # A failed request leaves the old title untouched. Cache each response.
        query=urllib.parse.quote(f'repo:Vita3K/compatibility is:issue "{serial}"')
        url=f'https://api.github.com/search/issues?q={query}&per_page=20'
        if 'vita' in self.online_failures or self.count >= 30:
            return None
        self.count+=1
        raw=_fetch(url,ttl=3*86400,cache_name=f'vita_{serial}.json')
        if not raw:
            self.online_failures.add('vita')
            return None
        try:
            records=json.loads(raw).get('items',[])
        except (ValueError,AttributeError):return None
        for record in records:
            title=record.get('title','') if isinstance(record,dict) else ''
            match=re.fullmatch(r'(.{2,220}?)\s*\[([A-Z]{4}\d{5})\]\s*',title)
            if match and match.group(2)==serial:
                return match.group(1).strip()
        return None
    def _lookup_rpcs3(self,serial:str)->str|None:
        """Exact RPCS3 compatibility API lookup; never accept a mismatching ID."""
        if 'rpcs3' in self.online_failures or self.count >= 30:
            return None
        self.count+=1
        url='https://rpcs3.net/compatibility?api=v1&g='+urllib.parse.quote(serial)
        raw=_fetch(url,ttl=5*86400,cache_name=f'rpcs3_{serial}.json')
        if not raw:
            self.online_failures.add('rpcs3')
            return None
        try:payload=json.loads(raw)
        except ValueError:return None
        possible=[]
        if isinstance(payload,dict):
            for key in ('results','games','data'):
                obj=payload.get(key)
                if isinstance(obj,dict):
                    possible.extend(({'serial':k,**v} for k,v in obj.items() if isinstance(v,dict)))
                elif isinstance(obj,list):possible.extend(x for x in obj if isinstance(x,dict))
            possible.append(payload)
            for key,val in payload.items():
                if isinstance(val,dict) and normalize_id(key,'ps3')==serial:
                    possible.append({'serial':key,**val})
        elif isinstance(payload,list):possible=payload
        for item in possible:
            if not isinstance(item,dict):continue
            code=next((item.get(k) for k in ('serial','title_id','titleId','game_id','product_code','id') if item.get(k)),None)
            if not isinstance(code,str) or normalize_id(code,'ps3')!=serial:continue
            title=next((item.get(k) for k in ('title','name','game_title') if item.get(k)),None)
            if isinstance(title,str) and title.strip() and len(title)<250 and not normalize_id(title,'ps3'):
                return title.strip()
        return None

    def _lookup_dolphin(self,serial:str)->str|None:
        """Use Dolphin's documented titles.txt overrides when installed."""
        if 'dolphin' not in self.maps:
            from core import BASE, detect_bundled_executables, executable_path
            entries={}
            exe=detect_bundled_executables(BASE).get('dolphin')
            candidates=[]
            if exe:
                root=executable_path(exe).parent
                candidates.extend([root/'Load'/'titles.txt',root/'User'/'Load'/'titles.txt'])
            candidates.append(Path.home()/'Documents'/'Dolphin Emulator'/'Load'/'titles.txt')
            for candidate in candidates:
                try:content=candidate.read_text(encoding='utf-8-sig')
                except OSError:continue
                for line in content.splitlines():
                    if '=' not in line or line.lstrip().startswith(('#',';')):continue
                    code,title=(part.strip() for part in line.split('=',1))
                    norm=normalize_id(code,'gc')
                    if norm and title:entries.setdefault(norm,title[:250])
            self.maps['dolphin']=entries
        return self.maps['dolphin'].get(serial)

    def resolve(self,game:dict)->tuple[str,str]|None:
        serial=detect_id(game)
        if not serial:return None
        local=local_sfo_title(game)
        if local:return local,'Local param.json' if game.get('platform')=='ps5' else 'Local PARAM.SFO'
        platform=game.get('platform','')
        if platform in URLS:
            title=self._lookup_yaml(platform,serial)
            if title:return title,({'ps2':'PCSX2 GameIndex','ps1':'DuckStation GameDB',
                                    'ps4':'PlayStation Titles','ps5':'PlayStation Titles'}[platform])
        if platform=='vita':
            title=self._lookup_vita_issue(serial)
            if title:return title,'Vita3K compatibility'
        if platform=='ps3':
            title=self._lookup_rpcs3(serial)
            if title:return title,'RPCS3 compatibility'
        if platform in ('gc','wii'):
            title=self._lookup_dolphin(serial)
            if title:return title,'Dolphin titles.txt'
        return None

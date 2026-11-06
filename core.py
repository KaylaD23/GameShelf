"""GameShelf library, launcher profiles and inventory. 100% standard library.

Never executes untrusted shell commands. Emulator paths remain user-configurable.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from typing import Iterable

from multi_disc import DISC_PLATFORMS, disc_identity, eligible_disc, group_candidates

APP_NAME = 'GameShelf'
BASE = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
DATA = BASE / 'data'
# Canonical console order for the sidebar and platform selectors. Keeping this
# list separate from the emulator profiles prevents newly added emulators from
# scrambling the order of the game-library tabs.
PLATFORMS = {
    'ps1': 'PlayStation 1',
    'ps2': 'PlayStation 2',
    'ps3': 'PlayStation 3',
    'ps4': 'PlayStation 4',
    'ps5': 'PlayStation 5',
    'psp': 'PlayStation Portable',
    'vita': 'PlayStation Vita',
    'n64': 'Nintendo 64',
    'gc': 'GameCube',
    'wii': 'Nintendo Wii',
    'wiiu': 'Nintendo Wii U',
    '3ds': 'Nintendo 3DS',
    'switch': 'Nintendo Switch',
    'xbox': 'Original Xbox',
    'xbox360': 'Xbox 360',
    'xboxone': 'Xbox One',
    'dreamcast': 'Sega Dreamcast',
}

# Family headings are display-only. Each platform remains its own filter,
# including the separate PlayStation 4/5 and Xbox/360 entries.
CONSOLE_GROUPS = (
    ('PLAYSTATION', ('ps1','ps2','ps3','ps4','ps5','psp','vita')),
    ('NINTENDO', ('n64','gc','wii','wiiu','3ds','switch')),
    ('XBOX', ('xbox','xbox360','xboxone')),
    ('SEGA', ('dreamcast',)),
)

@dataclass(frozen=True)
class Emulator:
    key: str
    name: str
    platforms: tuple[str, ...]
    executable: str
    folder: str
    status: str = 'supported'

EMULATORS = (
    Emulator('rpcs3','RPCS3',('ps3',),'rpcs3.exe','RPCS3'),
    Emulator('vita3k','Vita3K',('vita',),'Vita3K.exe','Vita3K'),
    Emulator('kyty','KytyPS5',('ps5',),'kyty_emulator.exe','KytyPS5-2026-09-23-fc86509-Windows-x64','experimental'),
    Emulator('dolphin','Dolphin',('gc','wii'),'Dolphin.exe','Dolphin-x64'),
    Emulator('cemu','Cemu',('wiiu',),'Cemu.exe','cemu-2.6-windows-x64/Cemu_2.6'),
    Emulator('azahar','Azahar',('3ds',),'azahar.exe','Azahar'),
    Emulator('ryujinx','Ryujinx Canary',('switch',),'Ryujinx.exe','ryujinx-canary-1.3.27-win_x64/publish'),
    Emulator('citron','Citron',('switch',),'citron.exe','Citron'),
    Emulator('xemu','xemu',('xbox',),'xemu.exe','Xemu'),
    Emulator('xenia','Xenia Canary',('xbox360',),'xenia_canary.exe','Xenia Canary'),
    # WinDurango is a compatibility DLL layer, NOT a traditional emulator GUI.
    # This file is a presence marker; never execute the DLL or its watchdog.
    Emulator('windurango','WinDurango (compatibility layer)',('xboxone',),'WinDurango.Common.dll','WinDurango','experimental'),
    Emulator('shadps4','shadPS4',('ps4',),'shadPS4.exe','shadps4/Versions/Pre-release','experimental'),
    Emulator('sharpemu','SharpEmu',('ps5',),'SharpEmu.exe','sharpemu-0.0.3-release.2-win-x64','experimental'),
    Emulator('duckstation','DuckStation',('ps1',),'duckstation-qt-x64-ReleaseLTCG.exe','duckstation'),
    Emulator('pcsx2','PCSX2',('ps2',),'pcsx2-qtx64-avx2.exe','pcsx2'),
    Emulator('ppsspp','PPSSPP',('psp',),'PPSSPPWindows64.exe','ppsspp'),
    Emulator('project64','Project64',('n64',),'Project64.exe','Project64'),
    Emulator('luna_project64',"Luna's Project64",('n64',),'Project64.exe','LunasProject64'),
    Emulator('flycast','Flycast',('dreamcast',),'flycast.exe','Flycast'),
)
BY_KEY={e.key:e for e in EMULATORS}


def executable_path(value: str | Path, base: Path = BASE) -> Path:
    """Resolve an emulator setting. Bundled executables use portable relative paths."""
    p = Path(value)
    return p if p.is_absolute() else base / p


def detect_bundled_executables(base: Path = BASE) -> dict[str, str]:
    """Register emulators shipped within GameShelf/Emulators without user import.

    Store relative paths so moving the whole installation to another disk works.
    External executables are never silently chosen by this function.
    """
    bundle = base / 'Emulators'
    if not bundle.is_dir():
        return {}
    detected = detect_executables([bundle])
    result = {}
    for key, full_path in detected.items():
        path = Path(full_path)
        try:
            relative = path.relative_to(base)
        except ValueError:
            continue
        result[key] = relative.as_posix()
    return result
SUFFIXES = {
    'n64':{'.z64','.n64','.v64','.zip','.rom','.ndd','.d64'},
    'dreamcast':{'.gdi','.cdi','.chd','.cue'},
    'gc':{'.iso','.gcm','.rvz','.gcz','.wia','.nkit.iso'},
    'wii':{'.iso','.wbfs','.rvz','.gcz','.wia','.nkit.iso'},
    'wiiu':{'.wud','.wux','.rpx','.wua'},
    '3ds':{'.3ds','.cci','.cxi','.3dsx'},
    'switch':{'.nsp','.xci','.nro','.nca'},
    'xbox':{'.iso','.xiso'},
    'xbox360':{'.iso','.xex'},
    # Xbox One requires an installed/prepared Windows game, not a raw disc ISO.
    'xboxone':set(),
    'ps3':{'.self','.elf'},
    'ps4':{'.elf','.self'},
    'ps5':{'.zar','.elf'},
    'ps1':{'.cue','.chd','.m3u','.pbp','.ccd','.iso','.img','.ecm'},
    'ps2':{'.iso','.chd','.cso','.zso','.gz'},
    'psp':{'.iso','.cso','.chd','.pbp'},
}
GAME_PREFIXES = ('PCSA','PCSB','PCSC','PCSE','PCSG','PCSH','PCSI','PCSF')


def path_norm(value: str | Path) -> str:
    return str(Path(value).expanduser().resolve(strict=False))


def _filename_words(path: str | Path) -> str:
    """Apply the established filename cleanup before display casing."""
    name = Path(path).stem
    name = re.sub(r'\([^)]*\)|\[[^]]*\]', ' ', name)
    name = re.sub(r'[_\-.]+', ' ', name)
    return re.sub(r'\s+', ' ', name).strip()


# Valid standalone Roman numerals (not arbitrary acronyms containing I or V).
_ROMAN_NUMERAL = re.compile(
    r'M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})'
)


def _is_game_sequel_numeral(word: str) -> bool:
    """Limit preservation to plausible sequel numbers, not words like MIX.

    MIX also happens to be a valid Roman number (1009), but game titles use
    it as an ordinary word far more often than as an installment number.
    """
    if len(word) < 2 or word != word.upper() or not _ROMAN_NUMERAL.fullmatch(word):
        return False
    values = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    total = 0
    for index, letter in enumerate(word):
        value = values[letter]
        total += -value if index + 1 < len(word) and value < values[word[index + 1]] else value
    return 2 <= total <= 50


def _legacy_safe_name(path: str | Path) -> str:
    """v0.9.13 formatting, used ONLY to identify previously auto-named titles."""
    return _filename_words(path).title() or 'Untitled'


def safe_name(path: str | Path) -> str:
    """Create a game title without lowercasing Roman numerals in filenames.

    For example, `Phantasy Star Online Episode I & II.iso` must display `II`,
    not `Ii`. Preserve originally UPPERCASE Roman numerals only; other words
    continue to use the same title-casing behaviour as earlier releases.
    """
    name = _filename_words(path)
    if not name:
        return 'Untitled'

    def case_word(match: re.Match) -> str:
        word = match.group(0)
        if _is_game_sequel_numeral(word):
            return word
        return word.title()

    return re.sub(r'[^\W\d_]+', case_word, name)


def detect_executables(roots: Iterable[str | Path]) -> dict[str,str]:
    """Search only known paths and bounded depths; do not recursively wander whole drives."""
    found={}
    for root in roots:
        p=Path(root).expanduser()
        parents = [p, p/'Emulators', p/'Emulators 1', p/'Emulators 2', p/'Emulators 3', p/'Emulators 4',
                   p/'Emulators'/'Emulators 1',p/'Emulators'/'Emulators 2',p/'Emulators'/'Emulators 3',p/'Emulators'/'Emulators 4']
        for e in EMULATORS:
            if e.key in found: continue
            for parent in parents:
                candidate=parent/e.folder/e.executable
                if candidate.is_file():
                    found[e.key]=path_norm(candidate)
                    break
    return found


def title_id_from_path(path: str | Path) -> str | None:
    for part in reversed(Path(path).parts):
        up=part.upper()
        if re.fullmatch(r'PC[A-Z]{2}[0-9]{5}',up): return up
    return None



def parse_windows_arguments(options: str) -> list[str]:
    """Parse an RPCS3 argument field using Windows command-line quote rules.

    The result is an argv list passed directly to subprocess (never to a shell).
    Double quotes group spaces; backslashes remain intact, including in paths.
    """
    if not isinstance(options, str):
        raise ValueError('RPCS3 arguments must be text.')
    if '\0' in options:
        raise ValueError('RPCS3 arguments cannot contain NUL characters.')
    parts=[]
    length=len(options)
    i=0
    while i<length:
        while i<length and options[i] in ' \t\r\n':
            i+=1
        if i>=length:
            break
        arg=[]
        quoted=False
        while i<length:
            if options[i] in ' \t\r\n' and not quoted:
                break
            if options[i]=='\\':
                start=i
                while i<length and options[i]=='\\':
                    i+=1
                slashes=i-start
                if i<length and options[i]=='"':
                    arg.append('\\'*(slashes//2))
                    if slashes%2:
                        arg.append('"')
                    else:
                        quoted=not quoted
                    i+=1
                else:
                    arg.append('\\'*slashes)
                continue
            if options[i]=='"':
                if quoted and i+1<length and options[i+1]=='"':
                    arg.append('"')
                    i+=2
                else:
                    quoted=not quoted
                    i+=1
                continue
            arg.append(options[i])
            i+=1
        if quoted:
            raise ValueError('Unclosed double quote in RPCS3 arguments.')
        parts.append(''.join(arg))
    return parts


def rpcs3_launch_args(content: str | Path, fullscreen: bool, extra_args: str='') -> list[str]:
    """Put per-title emulator flags before the game target, per RPCS3 CLI syntax."""
    base=launch_args('rpcs3',content,fullscreen)
    return [*base[:-1], *parse_windows_arguments(extra_args), base[-1]]


def launch_args(key:str, content: str | Path, fullscreen: bool=True) -> list[str]:
    """Build a safe subprocess argument vector, not a shell command.
    Unsupported formats fail rather than pretending a boot method is available.
    """
    p=Path(content)
    if key=='windurango':
        raise ValueError('WinDurango is a compatibility layer. Select a prepared Xbox One game executable; do not launch the runtime DLL.')
    if key=='flycast':
        # Standard standalone Flycast accepts the image file as positional argv.
        return [*(['-config','window:fullscreen=yes'] if fullscreen else []),str(p)]
    if key in ('project64','luna_project64'):
        # Project64 forks accept a positional ROM/disk path. Fullscreen is
        # configured inside the emulator; no invented command-line switches.
        return [str(p)]
    if key=='dolphin':
        args=['--batch','--exec',str(p)]
        if fullscreen: args=['--config','Dolphin.Display.Fullscreen=True',*args]
        return args
    if key=='cemu': return ['--game',str(p),*(['--fullscreen'] if fullscreen else [])]
    if key=='azahar': return [str(p)]  # Configure fullscreen in Azahar's own settings.
    if key=='ryujinx': return [*(['--fullscreen'] if fullscreen else []),str(p)]
    if key=='citron': return [*(['-f'] if fullscreen else []),'-g',str(p)]
    if key=='xemu': return ['-dvd_path',str(p),*(['-full-screen'] if fullscreen else [])]
    if key=='xenia': return [str(p)]  # Xenia Canary handles game selection by positional file argument.
    if key=='shadps4':
        # Prefer shadPS4's documented title-ID launch for installed games.
        game_id=next((part.upper() for part in reversed(p.parts) if re.fullmatch(r'CUSA\d{5}',part.upper())),None)
        if game_id:return [*(['--fullscreen','true'] if fullscreen else []),game_id]
        if p.is_file() and p.suffix.lower() in ('.elf','.self'):
            return [str(p)]
        raise ValueError('shadPS4 needs an installed CUSA game ID or ELF/SELF file.')
    if key=='rpcs3':
        if p.is_dir():
            eboot=p/'PS3_GAME'/'USRDIR'/'EBOOT.BIN'
            if not eboot.is_file(): eboot=p/'USRDIR'/'EBOOT.BIN'
            if not eboot.is_file(): raise ValueError('RPCS3 disc folder needs PS3_GAME/USRDIR/EBOOT.BIN')
            p=eboot
        if p.suffix.lower()=='.iso':
            raise ValueError('RPCS3 ISO boot is not configured; import an extracted/decrypted PS3_GAME folder instead.')
        return [*(['--no-gui','--fullscreen'] if fullscreen else []),str(p)]
    if key=='vita3k':
        title=title_id_from_path(p) or (str(content).upper() if re.fullmatch(r'PC[A-Z]{2}\d{5}',str(content).upper()) else None)
        if title is None: raise ValueError('Vita3K requires an installed title ID (e.g. PCSA00001) or a path containing one.')
        return [*(['--fullscreen'] if fullscreen else []),'--installed-path',title]
    if key=='kyty':
        if p.name.lower()=='eboot.bin':p=p.parent
        return ['--game',str(p)]
    if key=='duckstation':
        return ['-batch',*(['-fullscreen'] if fullscreen else []),'--',str(p)]
    if key=='pcsx2':
        return ['-batch',*(['-fullscreen'] if fullscreen else []),'--',str(p)]
    if key=='ppsspp':
        return [*(['--fullscreen'] if fullscreen else []),str(p)]
    if key=='sharpemu':
        if p.is_dir():p=p/'eboot.bin'
        if p.name.lower()!='eboot.bin':raise ValueError('SharpEmu requires a game eboot.bin file or its parent folder.')
        return [str(p)]
    raise ValueError(f'Unknown emulator: {key}')


def kyty_native_launcher(executable: str | Path) -> Path:
    """Find the *same build's* launcher, preferring its current filename.

    Newer Kyty releases ship kyty_launcher.exe while leaving a stale
    launcher.exe behind during some in-place upgrades. Avoid the old binary.
    """
    exe=Path(executable)
    if exe.name.lower()=='kyty_launcher.exe' and exe.is_file():
        return exe
    modern=exe.parent/'kyty_launcher.exe'
    if modern.is_file():
        return modern
    if exe.name.lower()=='launcher.exe' and exe.is_file():
        return exe
    legacy=exe.parent/'launcher.exe'
    if legacy.is_file():
        return legacy
    raise FileNotFoundError(
        f'No Kyty graphical launcher alongside {exe}. '        'Select kyty_emulator.exe from the same installation that works standalone.'
    )


def launch_command(executable:str, emulator:str, content:str, fullscreen:bool,
                   *, kyty_mode:str='direct', ps3_args:str='') -> tuple[list[str],str]:
    e=Path(executable)
    if not e.is_file():raise FileNotFoundError(f'Emulator executable not found: {e}')
    if emulator not in BY_KEY: raise ValueError('Invalid emulator')
    p=Path(content)
    if emulator!='vita3k' and not p.exists(): raise FileNotFoundError(f'Game path not found: {p}')
    if emulator=='windurango':
        from windurango_support import prepared_game_executable
        if e.name.lower() != 'windurango.common.dll':
            raise ValueError('Choose the WinDurango.Common.dll runtime marker, not WinDurango.Watchdog.exe.')
        game_exe=prepared_game_executable(p)
        if os.name == 'nt':
            # A DLL marker isn't a valid Windows AppX registration. For UWP
            # games the WinDurango guide explicitly requires registration.
            from windurango_support import find_registration_manifest
            from windurango_diagnostics import windows_registration_status
            manifest=find_registration_manifest(game_exe)
            if manifest is not None and windows_registration_status(manifest).startswith('NOT REGISTERED'):
                raise ValueError('Xbox One game is not registered for this Windows account. '
                                 'Use Diagnose WinDurango Launch for the exact manual '
                                 'AppX registration command; GameShelf will not change '
                                 'Windows registration without your approval.')
        return [str(game_exe)], str(game_exe.parent)
    if emulator=='kyty':
        if kyty_mode=='native':
            gui=kyty_native_launcher(e)
            # Native launcher maintains its own game list, settings, and profiles.
            return [str(gui)],str(gui.parent)
        if kyty_mode!='direct':
            raise ValueError(f'Unknown Kyty launch mode: {kyty_mode}')
        if e.name.lower() in ('launcher.exe','kyty_launcher.exe'):
            e=e.parent/'kyty_emulator.exe'
            if not e.is_file():raise FileNotFoundError(f'Kyty emulator executable missing: {e}')
    if emulator=='rpcs3':
        return [str(e),*rpcs3_launch_args(content,fullscreen,ps3_args)],str(e.parent)
    return [str(e),*launch_args(emulator,content,fullscreen)],str(e.parent)


def launch(executable:str, emulator:str, content:str, fullscreen:bool,
           *, kyty_mode:str='direct', ps3_args:str='', log_path:str | Path | None=None) -> subprocess.Popen:
    cmd,cwd=launch_command(executable,emulator,content,fullscreen,kyty_mode=kyty_mode,ps3_args=ps3_args)
    if emulator=='windurango' and os.name=='nt':
        from windurango_support import find_registration_manifest
        from uwp_activation import launch_registered_game, ActivationError
        if not find_registration_manifest(cmd[0]):
            raise ActivationError('WinDurango game has no AppxManifest.xml. GameShelf cannot activate '
                                  'it as a registered UWP application. Prepare/register the game first.')
        return launch_registered_game(cmd[0])
    if log_path is None:
        return subprocess.Popen(cmd,cwd=cwd,shell=False)
    # Capture direct-mode stdout/stderr, even if the Kyty process terminates instantly.
    out=Path(log_path)
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('wb') as f:
        return subprocess.Popen(cmd,cwd=cwd,shell=False,stdout=f,stderr=subprocess.STDOUT)


def scan_games(root: str | Path, platform: str, *, max_games:int=5000) -> list[tuple[str,str,str]]:
    """Return (title, platform, game path). Does not follow symbolic links.

    Platform selection is explicit to avoid incorrectly classifying .iso files.
    """
    if platform not in PLATFORMS:raise ValueError('Unknown platform')
    root=Path(root).expanduser()
    if not root.is_dir():raise FileNotFoundError(root)
    results=[]; seen=set()
    def add(p:Path, label: str | None=None):
        if len(results)>=max_games:return
        normalized=path_norm(p)
        if normalized.casefold() not in seen:
            seen.add(normalized.casefold())
            results.append((label or safe_name(p),platform,normalized))
    for directory, folders, files in os.walk(root,followlinks=False):
        if len(results)>=max_games:break
        loc=Path(directory)
        dirs={d.lower():d for d in folders}
        filemap={f.lower():f for f in files}
        # Limit scan of hidden data, system/firmware folders; regular game folders remain traversable.
        folders[:]=[d for d in folders if not d.startswith('.') and d.lower() not in
                    {'$recycle.bin','system volume information','shadercache','cache','shaderlog','firmware'}]
        if platform=='ps3':
            if 'ps3_game' in dirs and (loc/dirs['ps3_game']/'USRDIR'/'EBOOT.BIN').is_file():
                add(loc); folders[:]=[]; continue
            if loc.name.upper()=='PS3_GAME' and (loc/'USRDIR'/'EBOOT.BIN').is_file():
                add(loc.parent); folders[:]=[]; continue
        if platform=='vita':
            if title_id_from_path(loc)==loc.name.upper() and 'eboot.bin' in filemap:
                add(loc,loc.name.upper()); folders[:]=[]; continue
        if platform in ('ps4','ps5'):
            if 'eboot.bin' in filemap and 'demo' not in {p.lower() for p in loc.parts}:
                # eboot.bin may be a PS4 or PS5 dump. Import only into the selected console.
                add(loc); folders[:]=[]; continue
        if platform=='xboxone':
            from windurango_support import locate_prepared_game
            game=locate_prepared_game(loc,files)
            if game is not None:
                add(game,loc.name if loc.name.lower() != 'mount' else loc.parent.name)
                folders[:]=[]
                continue
        if platform=='xbox360' and 'default.xex' in filemap:
            add(loc / filemap['default.xex'],loc.name)
            folders[:]=[]
            continue
        if platform=='wiiu' and 'code' in dirs:
            code=loc/dirs['code']
            for rp in code.glob('*.rpx'):
                add(rp,loc.name)
            if any(code.glob('*.rpx')):
                folders[:]=[]; continue
        for filename in files:
            f=loc/filename
            # '.nkit.iso' is explicitly recognized, not treated as a normal ISO by default.
            ext='.nkit.iso' if filename.lower().endswith('.nkit.iso') else f.suffix.lower()
            if ext in SUFFIXES.get(platform,set()):
                add(f)
    return results


class Library:
    def __init__(self, db_path:Path | str | None=None):
        self.path=Path(db_path) if db_path is not None else DATA/'library.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(str(self.path))
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS games(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          platform TEXT NOT NULL,
          emulator TEXT NOT NULL,
          path TEXT NOT NULL UNIQUE,
          artwork TEXT NOT NULL DEFAULT '',
          favorite INTEGER NOT NULL DEFAULT 0,
          seconds_played INTEGER NOT NULL DEFAULT 0,
          last_played INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL DEFAULT 0,
          ps3_args TEXT NOT NULL DEFAULT '',
          selected_disc INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS game_title ON games(title);
        CREATE TABLE IF NOT EXISTS game_discs(
          game_id INTEGER NOT NULL,
          disc_number INTEGER NOT NULL,
          path TEXT NOT NULL,
          PRIMARY KEY(game_id, disc_number),
          FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE
        );
        ''')
        # Older installs already have their library.sqlite3. Add just this one
        # column in place, without deleting game records or resetting artwork.
        columns={row['name'] for row in self.db.execute('PRAGMA table_info(games)')}
        if 'ps3_args' not in columns:
            self.db.execute("ALTER TABLE games ADD COLUMN ps3_args TEXT NOT NULL DEFAULT ''")
        if 'selected_disc' not in columns:
            self.db.execute('ALTER TABLE games ADD COLUMN selected_disc INTEGER NOT NULL DEFAULT 1')
        self.db.execute('CREATE INDEX IF NOT EXISTS game_discs_by_game ON game_discs(game_id)')
        self.db.commit()
        self._repair_legacy_roman_titles()

    def _repair_legacy_roman_titles(self) -> None:
        """Repair exact auto-generated v0.9.13 names, not user-edited names.

        A title qualifies only if it still exactly matches the previous
        filename-to-title converter and the original filename contains an
        uppercase Roman numeral. Never change a title from a compatibility
        database or one manually edited to something different.
        """
        repairs = []
        for row in self.db.execute('SELECT id,title,path FROM games'):
            before = _legacy_safe_name(row['path'])
            if row['title'] != before:
                continue
            after = safe_name(row['path'])
            if after != before:
                repairs.append((after, row['id'], before))
        if repairs:
            with self.db:
                self.db.executemany(
                    'UPDATE games SET title=? WHERE id=? AND title=?', repairs
                )

    def all(self)->list[dict]:
        games=[dict(row) for row in self.db.execute('SELECT * FROM games ORDER BY title COLLATE NOCASE')]
        # One extra query for all disc rows. Never one query per thumbnail.
        discs={}
        for row in self.db.execute('SELECT * FROM game_discs ORDER BY game_id,disc_number'):
            discs.setdefault(row['game_id'],[]).append(dict(row))
        for game in games:
            game['discs']=discs.get(game['id'],[])
            game['disc_count']=len(game['discs']) or 1
        return games
    def get(self,identifier:int)->dict | None:
        row=self.db.execute('SELECT * FROM games WHERE id=?',(identifier,)).fetchone()
        if row is None:return None
        game=dict(row)
        game['discs']=[dict(d) for d in self.db.execute(
            'SELECT * FROM game_discs WHERE game_id=? ORDER BY disc_number',(identifier,))]
        game['disc_count']=len(game['discs']) or 1
        return game

    def set_discs(self,identifier:int, paths:list[str]):
        """Manual disc list; never deletes/modifies ISO/CUE/CHD files."""
        game=self.get(identifier)
        if game is None:raise ValueError('Unknown game')
        if game['emulator'] not in BY_KEY or game['platform'] not in BY_KEY[game['emulator']].platforms:
            raise ValueError('The selected emulator cannot launch this console')
        if game['platform'] not in DISC_PLATFORMS:raise ValueError('This platform does not support disc lists')
        paths=[path_norm(p) for p in paths]
        if len(paths)<2 or len(set(p.casefold() for p in paths))!=len(paths):
            raise ValueError('Select at least two distinct disc images')
        if not all(eligible_disc(game['platform'],p) and Path(p).is_file() for p in paths):
            raise ValueError('All disc images must exist and use supported disc formats for this console')
        if paths[0].casefold()!=game['path'].casefold():
            raise ValueError('Disc 1 must be the current primary game path')
        with self.db:
            self.db.execute('DELETE FROM game_discs WHERE game_id=?',(identifier,))
            self.db.executemany('INSERT INTO game_discs(game_id,disc_number,path) VALUES(?,?,?)',
                                ((identifier,i,path) for i,path in enumerate(paths,1)))
            self.db.execute('UPDATE games SET selected_disc=1 WHERE id=?',(identifier,))

    def choose_disc(self,identifier:int,number:int):
        game=self.get(identifier)
        if not game or len(game['discs'])<2 or number not in [d['disc_number'] for d in game['discs']]:
            raise ValueError('Disc is not present in this game')
        with self.db:self.db.execute('UPDATE games SET selected_disc=? WHERE id=?',(number,identifier))

    def auto_merge_discs(self)->list[dict]:
        """Merge only unambiguous numbered sets of the same platform/emulator.

        All game image files remain unchanged; duplicate library rows are
        removed, but their playtime and favourites are carried into disc 1.
        """
        result=[]
        candidates=group_candidates(self.all())
        for group in candidates:
            primary=group[0]
            # Files must exist; this is an explicit library operation.
            if not all(Path(g['path']).is_file() for g in group):continue
            with self.db:
                for g in group:
                    disc_number=disc_identity(g['title'],g['path'])[1]
                    self.db.execute('INSERT OR REPLACE INTO game_discs(game_id,disc_number,path) VALUES(?,?,?)',
                                    (primary['id'],disc_number,g['path']))
                for game in group[1:]:
                    self.db.execute('UPDATE games SET seconds_played=seconds_played+?,favorite=MAX(favorite,?),last_played=MAX(last_played,?) WHERE id=?',
                                    (game['seconds_played'],game['favorite'],game['last_played'],primary['id']))
                    if not primary['artwork'] and game['artwork']:
                        self.db.execute('UPDATE games SET artwork=? WHERE id=?',(game['artwork'],primary['id']))
                        primary['artwork']=game['artwork']
                    self.db.execute('DELETE FROM games WHERE id=?',(game['id'],))
                self.db.execute('UPDATE games SET selected_disc=1 WHERE id=?',(primary['id'],))
                # Only strip an unambiguous disc marker; preserve region text.
                base=disc_identity(primary['title'],primary['path'])
                if base:
                    import re
                    from multi_disc import DISC_MARKER, DISC_WRAPPER
                    clean=DISC_WRAPPER.sub(' ',primary['title'])
                    clean=DISC_MARKER.sub(' ',clean)
                    clean=re.sub(r'\s+', ' ',clean).strip(' -_')
                    if clean:self.db.execute('UPDATE games SET title=? WHERE id=?',(clean,primary['id']))
            result.append({'id':primary['id'],'count':len(group),'title':primary['title']})
        return result
    def add(self,title:str,platform:str,emulator:str,path:str)->bool:
        if platform not in PLATFORMS or emulator not in BY_KEY:raise ValueError('Invalid platform/emulator')
        normalized=path_norm(path) if not re.fullmatch(r'PC[A-Z]{2}\d{5}',path.upper()) else path.upper()
        with self.db:
            c=self.db.execute('INSERT OR IGNORE INTO games(title,platform,emulator,path,created_at) VALUES(?,?,?,?,?)',
                              (title.strip() or safe_name(path),platform,emulator,normalized,int(time.time())))
        return bool(c.rowcount)
    def edit(self,identifier:int,**fields):
        allowed={'title','emulator','platform','path','artwork','favorite','seconds_played','last_played','ps3_args','selected_disc'}
        if not fields or not set(fields)<=allowed:raise ValueError('Invalid fields')
        if any(k in fields for k in ('path','platform','emulator')):
            game=self.get(identifier)
            if game and game['disc_count']>1:
                for key in ('path','platform','emulator'):
                    if key in fields and fields[key]!=game[key]:
                        raise ValueError('Use Manage Discs for multi-disc games; changing the primary disc or emulator here would break the set')
        cols=', '.join(f'{key}=?' for key in fields)
        with self.db:self.db.execute(f'UPDATE games SET {cols} WHERE id=?',(*fields.values(),identifier))
    def remove(self,identifier:int):
        with self.db:
            self.db.execute('DELETE FROM game_discs WHERE game_id=?',(identifier,))
            self.db.execute('DELETE FROM games WHERE id=?',(identifier,))
    def add_playtime(self,identifier:int,seconds:int):
        with self.db:self.db.execute('UPDATE games SET seconds_played=seconds_played+?,last_played=? WHERE id=?',
                                     (max(0,seconds),int(time.time()),identifier))
    def close(self):self.db.close()


class Settings:
    def __init__(self,path:Path | None=None):
        self.path=path or DATA/'settings.json'
        self.values={'emulators':{},'rom_roots':[],'last_mode':'desktop','startup_mode':'desktop','desktop_maximized':True,'kyty_launch_mode':'direct','ra_auto_configure':False,'theme':'dark'}
        if self.path.is_file():
            try:
                loaded=json.loads(self.path.read_text(encoding='utf-8'))
                if isinstance(loaded,dict):self.values.update(loaded)
            except (OSError,ValueError):pass
        if not isinstance(self.values.get('emulators'),dict):self.values['emulators']={}
        if not isinstance(self.values.get('rom_roots'),list):self.values['rom_roots']=[]
        # In v0.9.3-0.9.8 Big Picture was silently made the default.
        # Existing settings therefore often contain 'big' without any user
        # ever opting in. On the first run after upgrading, restore Desktop as
        # the default. After that, respect a deliberate startup-mode change.
        if self.values.get('startup_desktop_migrated_v099') is not True:
            self.values['startup_mode']='desktop'
            self.values['startup_desktop_migrated_v099']=True
            if self.path.is_file():
                self.save()  # persist once so later user opt-in is not reset
        elif self.values.get('startup_mode') not in ('big','desktop'):
            self.values['startup_mode']='desktop'
        # Migrate the v0.5/v0.6 default: PLAY should launch the game, never the GUI.
        self.values['kyty_launch_mode']='direct'
    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.values,indent=2,ensure_ascii=False),encoding='utf-8')
        tmp.replace(self.path)

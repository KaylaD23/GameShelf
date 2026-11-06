"""Safe RetroAchievements enablement for supported standalone emulators.

This does not log users in, share credentials, or touch unsupported emulators.
Only *existing* emulator config files are changed, once the emulator has created
its own settings. All unrelated config settings are preserved.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import tempfile

SUPPORTED = {
    'duckstation': ('DuckStation', 'Cheevos', 'Enabled', 'true'),
    'pcsx2': ('PCSX2', 'Achievements', 'Enabled', 'true'),
    'ppsspp': ('PPSSPP', 'Achievements', 'AchievementsEnable', 'True'),
    'dolphin': ('Dolphin', 'Achievements', 'Enabled', 'True'),
}


@dataclass(frozen=True)
class Result:
    key: str
    status: str  # enabled, already_enabled, config_not_found, missing_executable, unsupported, error
    message: str
    config_path: Path | None = None


def paths_for(key: str, executable: str | Path, env=None) -> list[Path]:
    """Known Windows portable/standard paths. Never search arbitrary drives."""
    if key not in SUPPORTED:
        return []
    p=Path(executable).expanduser()
    home=p.parent
    env=os.environ if env is None else env
    profile=Path(env.get('USERPROFILE') or str(Path.home()))
    docs=profile/'Documents'
    appdata=Path(env.get('APPDATA') or (profile/'AppData'/'Roaming'))
    local=Path(env.get('LOCALAPPDATA') or (profile/'AppData'/'Local'))
    mapping={
        'duckstation': [
            home/'settings.ini', home/'portable'/'settings.ini', home/'user'/'settings.ini',
            docs/'DuckStation'/'settings.ini', appdata/'DuckStation'/'settings.ini',
            local/'DuckStation'/'settings.ini',
        ],
        'pcsx2': [
            home/'inis'/'PCSX2.ini', home/'PCSX2.ini',
            docs/'PCSX2'/'inis'/'PCSX2.ini', appdata/'PCSX2'/'inis'/'PCSX2.ini',
        ],
        'ppsspp': [
            home/'memstick'/'PSP'/'SYSTEM'/'ppsspp.ini',
            home/'PSP'/'SYSTEM'/'ppsspp.ini',
            docs/'PPSSPP'/'PSP'/'SYSTEM'/'ppsspp.ini',
            appdata/'PPSSPP'/'PSP'/'SYSTEM'/'ppsspp.ini',
        ],
        'dolphin': [
            home/'User'/'Config'/'Achievements.ini',
            docs/'Dolphin Emulator'/'Config'/'Achievements.ini',
            appdata/'Dolphin Emulator'/'Config'/'Achievements.ini',
        ],
    }
    return list(dict.fromkeys(mapping[key]))


def locate_config(key: str, executable: str | Path, env=None) -> Path | None:
    """Use existing config only. Don't silently write into wrong user directories."""
    candidates=paths_for(key, executable, env)
    existing=next((p for p in candidates if p.is_file()), None)
    if existing:
        return existing
    # Dolphin's Achievements config can legitimately be missing on first setup.
    # Only create it in a proven Dolphin profile containing Dolphin.ini.
    if key=='dolphin':
        return next((p for p in candidates if (p.parent/'Dolphin.ini').is_file()), None)
    return None


def enable_in_text(text: str, section: str, option: str, value: str) -> tuple[str, bool]:
    """Patch one INI field preserving comments, casing, whitespace, order and EOL."""
    newline='\r\n' if '\r\n' in text else '\n'
    lines=text.splitlines(keepends=True)
    start=None
    end=len(lines)
    for i,line in enumerate(lines):
        match=re.match(r'^\s*\[([^\]]+)\]\s*(?:[;#].*)?$',line.rstrip('\r\n'))
        if match:
            if start is not None:
                end=i
                break
            if match.group(1).lower()==section.lower():
                start=i
    if start is None:
        prefix='' if not text else ('' if text.endswith(('\r','\n')) else newline)
        return text+prefix+f'[{section}]{newline}{option} = {value}{newline}',True
    # Check the existing key without clobbering adjacent unrelated fields.
    pattern=re.compile(r'^(\s*'+re.escape(option)+r'\s*=\s*)([^;#\r\n]*?)(\s*(?:[;#].*)?)$',re.I)
    for i in range(start+1,end):
        raw=lines[i].rstrip('\r\n')
        m=pattern.match(raw)
        if m:
            if m.group(2).strip().lower()==value.lower():
                return text,False
            eol=lines[i][len(raw):]
            lines[i]=m.group(1)+value+m.group(3)+eol
            return ''.join(lines),True
    lines.insert(end, ('' if end==0 or lines[end-1].endswith(('\r','\n')) else newline)+f'{option} = {value}{newline}')
    return ''.join(lines),True


def apply_config(key: str, config_path: str | Path) -> Result:
    if key not in SUPPORTED:
        return Result(key,'unsupported','This emulator does not have verified native RetroAchievements support.')
    path=Path(config_path)
    if not path.is_file() and not (key=='dolphin' and (path.parent/'Dolphin.ini').is_file()):
        return Result(key,'config_not_found','Open and close the emulator once to create its settings.',path)
    try:
        raw=path.read_bytes() if path.is_file() else b''
        if b'\0' in raw:
            return Result(key,'error','Config is not a text INI file.',path)
        bom=b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
        content=raw[len(bom):].decode('utf-8')
        _,section,option,value=SUPPORTED[key]
        changed,needed=enable_in_text(content,section,option,value)
        if not needed:
            return Result(key,'already_enabled','Achievements already enabled. Sign in inside the emulator.',path)
        temp=None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.gameshelf_ra_',delete=False) as f:
                temp=Path(f.name)
                f.write(bom+changed.encode('utf-8'))
            # Match original read/write permissions where possible.
            if path.exists(): os.chmod(temp,path.stat().st_mode)
            os.replace(temp,path)
        finally:
            if temp and temp.exists():temp.unlink()
        return Result(key,'enabled','Enabled. Sign in via the emulator’s Achievements menu.',path)
    except (OSError,UnicodeError) as exc:
        return Result(key,'error',str(exc),path)


def configure(key: str, executable: str | Path, env=None) -> Result:
    if key not in SUPPORTED:
        return Result(key,'unsupported','Native RetroAchievements integration is not verified for this emulator.')
    exe=Path(executable)
    if not exe.is_file():
        return Result(key,'missing_executable','Emulator executable not found.')
    cfg=locate_config(key,exe,env)
    if cfg is None:
        return Result(key,'config_not_found','Launch this emulator once, close it, then configure again.')
    return apply_config(key,cfg)


def configure_all(executables: dict[str,str], env=None) -> list[Result]:
    return [configure(key, executables.get(key,'') or '',env) for key in SUPPORTED]

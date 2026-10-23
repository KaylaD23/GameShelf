"""Copy earlier GameShelf emulators and library into v0.6 without overwriting files."""
from pathlib import Path
import shutil
import sys
HERE = Path(__file__).resolve().parent


def choose_source():
    if len(sys.argv)>1:
        return Path(sys.argv[1].strip('"')).expanduser().resolve()
    try:
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk();root.withdraw()
        selection=filedialog.askdirectory(title='Choose your OLD GameShelf folder')
        root.destroy()
        if selection:return Path(selection).resolve()
    except Exception:
        pass
    return Path(input('Path to old GameShelf: ').strip().strip('"')).expanduser().resolve()


def copy_nonoverwriting(src:Path,dst:Path):
    copied=0;preserved=0
    if not src.is_dir():return copied,preserved
    for f in src.rglob('*'):
        # Never traverse symlinks from user-selected folder
        if f.is_symlink():continue
        rel=f.relative_to(src);target=dst/rel
        if f.is_dir():target.mkdir(parents=True,exist_ok=True)
        elif f.is_file():
            if target.exists():preserved+=1
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(f,target)
                copied+=1
    return copied,preserved


def main():
    old=choose_source()
    if old==HERE:raise RuntimeError('Choose your previous GameShelf, not this one')
    if not old.is_dir() or not (old/'Emulators').is_dir():raise RuntimeError('Old GameShelf/Emulators directory not found')
    for name in ('Emulators','data'):
        n,k=copy_nonoverwriting(old/name,HERE/name)
        print(f'{name}: copied {n} files; preserved {k} existing files')
    from core import EMULATORS, detect_bundled_executables
    found=detect_bundled_executables(HERE)
    print(f'Bundled emulator executables detected: {len(found)}/{len(EMULATORS)}')
    print('Existing files and old installation were left untouched.')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Migration failed:',exc);sys.exit(1)

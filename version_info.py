"""GameShelf release identity shared by GUI and release verifier."""
from pathlib import Path

APP_VERSION = '0.9.12'

def version_file_matches() -> bool:
    return Path(__file__).with_name('VERSION.txt').read_text(encoding='utf-8').strip() == APP_VERSION

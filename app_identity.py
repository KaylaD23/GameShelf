"""Shared Windows/Qt application identity for taskbar, alt-tab, and title bars."""
from __future__ import annotations
import ctypes
from pathlib import Path
import sys

APP_ID = "KayakosMods.GameShelf.Frontend"


def resource_path(name: str) -> Path:
    """Resolve bundled assets in Python mode and a PyInstaller-built executable."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / name


def register_windows_app_id() -> bool:
    """Assign a stable Windows taskbar identity before QApplication is created."""
    if sys.platform != "win32":
        return False
    try:
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        return int(result) == 0
    except (AttributeError, OSError, TypeError):
        return False


def load_icon():
    """Provide one icon shared by QApplication, top-level windows and dialogs."""
    from PySide6.QtGui import QIcon
    path = resource_path("gameshelf.png")
    if not path.is_file():
        path = resource_path("gameshelf.ico")
    return QIcon(str(path))

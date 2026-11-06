"""GameShelf — unified emulator frontend."""
from __future__ import annotations

import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time

try:
    from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QRect
    from PySide6.QtGui import QPainter, QPixmap, QColor, QFont, QBrush, QPen, QLinearGradient, QKeySequence, QShortcut, QIcon
    from PySide6.QtWidgets import (
        QApplication,QMainWindow,QWidget,QFrame,QLabel,QPushButton,QLineEdit,
        QVBoxLayout,QHBoxLayout,QGridLayout,QScrollArea,QListWidget,QListWidgetItem,
        QFileDialog,QDialog,QDialogButtonBox,QFormLayout,QComboBox,QMessageBox,
        QStackedWidget,QSplitter,QSizePolicy,QInputDialog,QMenu,QAbstractItemView,QPlainTextEdit,QCheckBox
    )
except ImportError:
    print('PySide6 is required. On Windows, run INSTALL_AND_RUN.bat',file=sys.stderr)
    raise

from app_identity import register_windows_app_id, load_icon, resource_path
from windurango_support import validate_game_path, preparation_plan, apply_preparation_plan, embedded_xvd_relocation_plan, relocate_embedded_xvd, registration_command, SUPPORT_URL
from windurango_diagnostics import create_diagnostic_report, status_name
from brand_wordmark import GameShelfWordmark
from theme_manager import THEMES, THEME_KEYS, normalize_theme, activate as activate_theme, stylesheet as theme_stylesheet, color as theme_color
from multi_disc import DISC_PLATFORMS, DISC_IMAGE_EXTS, write_duckstation_playlist, next_disc_number
from disc_hotkey import send_duckstation_next_disc
from cover_geometry import poster_fill_rect
from version_info import APP_VERSION
from retro_achievements import SUPPORTED as RA_SUPPORTED, configure as configure_ra, configure_all as configure_ra_all
from controller_input import Controller, UP, DOWN, LEFT, RIGHT, A, B, X, Y, LB, RB, START, BACK
from emulator_lifecycle import EmulatorProcessMonitor
from window_geometry import safe_desktop_rect
from library_view import make_game_view
from wheel_scroll import enable_smooth_wheel
from title_lookup import TitleResolver, detect_id

from core import (
    DATA,BASE,EMULATORS,BY_KEY,PLATFORMS,CONSOLE_GROUPS,Library,Settings,detect_executables,
    launch,rpcs3_launch_args,parse_windows_arguments,scan_games,path_norm,safe_name,title_id_from_path,executable_path,detect_bundled_executables
)

STYLE='''
* { font-family: "Segoe UI", "Arial"; font-size: 13px; color: #e5eaf3; }
QMainWindow, QWidget#root, QWidget#desktop, QWidget#bigpicture { background: #10141d; }
QFrame#sidebar { background: #131a25; border-right: 1px solid #293345; }
QFrame#details { background: #151c28; border-left: 1px solid #293345; }
QLabel#brand { font-size: 25px; font-weight: 800; color: #f8fbff; }
QLabel#headline { font-size: 25px; font-weight: 800; }
QLabel#detailsTitle { font-size: 21px; font-weight: 800; color: #f7faff; }
QLabel#detailsInfo { font-size: 12px; color: #a8bad0; }
QLabel#detailsPath { font-size: 11px; color: #7893b0; }
QLabel#bigTitle { font-size: 39px; font-weight: 800; }
QLabel#muted { color: #98a6bd; }
QLabel#section { font-size: 17px; font-weight: 700; }
QLineEdit, QComboBox { background: #1d2735; border: 1px solid #35465d; border-radius: 9px; padding: 10px; selection-background-color: #277cbd; }
QLineEdit:focus, QComboBox:focus { border-color: #69baf4; }
QPushButton { background: #273448; padding: 10px 13px; border: 1px solid #3b4b5f; border-radius: 9px; font-weight: 600; }
QPushButton:hover { background: #34465e; border-color: #6ebcf3; }
QPushButton:focus { border: 2px solid #9ed9ff; }
QPushButton#accent { background: #58adeb; color: #081421; font-weight: 800; border-color: #58adeb; }
QPushButton#accent:hover { background: #9ad5ff; }
QPushButton#danger { background: #3c2530; color: #ffc6ce; }
QListWidget { background: transparent; border: none; outline: 0; }
QListWidget::item { margin: 2px 6px; padding: 11px; border-radius: 9px; color: #b3c0d3; }
QListWidget::item:selected { background: #28435c; color: white; font-weight: 750; }
QScrollArea { border: none; background: transparent; }
QScrollArea#detailsScroll { background: #151c28; border-left: 1px solid #293345; }
QScrollArea#detailsScroll > QWidget > QWidget { background: #151c28; }
QScrollBar:horizontal { height: 8px; background: transparent; }
QScrollBar:vertical { width: 10px; background: transparent; }
QScrollBar::handle:vertical { background: #34465c; border-radius: 5px; min-height: 32px; }
QDialog { background: #171f2b; }
QMenu { background: #1f2b3c; border: 1px solid #415675; }
QMenu::item { padding: 9px 20px; }
QMenu::item:selected { background: #345d7c; }
'''


def label(text,object_name=None,word_wrap=False):
    w=QLabel(text)
    if object_name:w.setObjectName(object_name)
    w.setWordWrap(word_wrap)
    return w


def click(text,callback,accent=False):
    w=QPushButton(text)
    if accent:w.setObjectName('accent')
    w.clicked.connect(callback)
    return w


class Poster(QWidget):
    """Fill the poster rectangle with every pixel of the source image."""
    def __init__(self, game:dict, width=175,height=235,parent=None):
        super().__init__(parent)
        self.game=game
        self.setFixedSize(width,height)
        self.pix=QPixmap(game.get('artwork') or '')

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w=self.width();h=self.height()
        p.setClipRect(self.rect())
        # Match the card background. The card already owns the selection outline.
        # Do not draw another frame, shadow, enlarged backdrop or overlaid copy.
        p.fillRect(self.rect(), QColor(theme_color('#1c2635')))
        if not self.pix.isNull():
            # Map the complete source bitmap directly into the full poster box.
            # Slight distortion beats either cutting off text or dark side bars.
            p.drawPixmap(self.rect(), self.pix, self.pix.rect())
        else:
            gradients=[('#12364a','#162137'),('#46304a','#1b243a'),('#31524b','#15283b'),('#3c374f','#17263a'),('#3d494f','#1b2537')]
            a,b=gradients[sum(ord(c) for c in self.game['title'])%len(gradients)]
            gradient=QLinearGradient(0,0,w,h);gradient.setColorAt(0,QColor(a));gradient.setColorAt(1,QColor(b))
            p.fillRect(self.rect(),gradient)
            p.setPen(QPen(QColor(255,255,255,17),2))
            p.drawEllipse(int(w*.12),int(h*.1),int(w*.94),int(h*.67))
            p.drawEllipse(int(w*.37),int(h*.47),int(w*.86),int(h*.57))
            p.setPen(QColor(theme_color('#b6dfff')))
            font=QFont('Segoe UI',11);font.setBold(True);p.setFont(font)
            p.drawText(self.rect().adjusted(14,12,-10,-20),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop,PLATFORMS.get(self.game['platform'],'GAME').upper())
            p.setPen(QColor(theme_color('#f6fbff')))
            font=QFont('Segoe UI',max(12,min(22,w//10)));font.setBold(True);p.setFont(font)
            p.drawText(self.rect().adjusted(13,40,-13,-18), Qt.TextFlag.TextWordWrap|Qt.AlignmentFlag.AlignBottom,self.game['title'])
        p.end()


def multiline_title(text, metrics, width, maximum_lines=3):
    """Wrap to a predictable number of lines, eliding only genuinely long titles.

    Normal QLabel word wrapping can silently clip the last line inside a fixed tile.
    """
    words=text.split()
    if not words:
        return ''
    lines=[]
    current=''
    for index,word in enumerate(words):
        candidate=(current+' '+word).strip()
        if metrics.horizontalAdvance(candidate)<=width:
            current=candidate
            continue
        if current:
            lines.append(current)
            current=word
        else:
            # An unusually long unbroken title cannot be word wrapped.
            lines.append(metrics.elidedText(word,Qt.TextElideMode.ElideRight,width))
            current=''
        if len(lines)==maximum_lines-1:
            remainder=' '.join(([current] if current else [])+words[index+1:])
            lines.append(metrics.elidedText(remainder,Qt.TextElideMode.ElideRight,width))
            return '\n'.join(lines)
    if current:
        lines.append(metrics.elidedText(current,Qt.TextElideMode.ElideRight,width))
    return '\n'.join(lines[:maximum_lines])


class Tile(QPushButton):
    def __init__(self,game:dict,callback,scale='desktop',parent=None):
        super().__init__(parent)
        self.game=game
        large=scale=='big'
        tw,th=(205,277) if large else (173,235)
        self.setFixedWidth(tw+16)
        self.setMinimumHeight(th+(110 if large else 103))
        self.setObjectName('gameTile')
        self.setStyleSheet('QPushButton#gameTile { background: #1c2635; border: 2px solid #26374a; border-radius: 13px; padding: 4px; text-align: left; } QPushButton#gameTile:hover { border-color: #66bafa; background: #283b51; } QPushButton#gameTile:focus { border: 3px solid #fff2a8; }')
        inner=QVBoxLayout(self)
        inner.setSpacing(4)
        inner.setContentsMargins(5,6,5,7)
        self.poster=Poster(game,tw,th)
        inner.addWidget(self.poster,alignment=Qt.AlignmentFlag.AlignHCenter)
        self.title_label=label('',word_wrap=True)
        self.title_label.setStyleSheet(f'font-size: {14 if large else 12}px; font-weight: 750; border:none; background:transparent;')
        self.title_label.setFixedHeight(61 if large else 54)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop)
        self.title_label.setToolTip(game['title'])
        self.title_label.setText(multiline_title(game['title'],self.title_label.fontMetrics(),tw-10,3))
        inner.addWidget(self.title_label)
        platform=label(PLATFORMS.get(game['platform'],game['platform']))
        platform.setStyleSheet('color:#8fa8c2; font-size:11px; background: transparent; border:none')
        platform.setText(platform.fontMetrics().elidedText(platform.text(),Qt.TextElideMode.ElideRight,tw-10))
        platform.setToolTip(PLATFORMS.get(game['platform'],game['platform']))
        platform.setFixedHeight(18)
        inner.addWidget(platform)
        inner.addStretch(1)
        self.clicked.connect(lambda:callback(game['id']))


class ScanWorker(QThread):
    done=Signal(list)
    failed=Signal(str)
    def __init__(self,root,platform):
        super().__init__();self.root=root;self.platform=platform
    def run(self):
        try:self.done.emit(scan_games(self.root,self.platform))
        except Exception as exc:self.failed.emit(str(exc))


class TitleLookupWorker(QThread):
    """Network/metadata lookups stay outside the Qt UI and its SQLite connection."""
    matched=Signal(int,str,str,str)
    done=Signal(int)
    def __init__(self,games):
        super().__init__()
        self.games=list(games)
    def run(self):
        try:
            resolver=TitleResolver()
            for game in self.games:
                try:
                    result=resolver.resolve(game)
                    if result:
                        name,source=result
                        if name.strip() and name.casefold()!=game['title'].casefold():
                            self.matched.emit(game['id'],game['title'],name.strip(),source)
                except Exception:
                    # Bad metadata or unreachable sources must not interrupt an import.
                    continue
            self.done.emit(len(self.games))
        except Exception:
            self.done.emit(len(self.games))



class EmulatorDialog(QDialog):
    def __init__(self,settings,parent=None):
        super().__init__(parent)
        self.settings=settings;self.edits={}
        self.setWindowTitle('Emulator Manager');self.resize(880,550)
        outer=QVBoxLayout(self)
        outer.addWidget(label('Detected emulators','headline'))
        outer.addWidget(label('Bundled emulators are registered automatically. You can also choose an external installation if preferred.','muted',True))
        bar=QHBoxLayout();outer.addLayout(bar)
        bar.addWidget(click('Detect from extracted folder…',self.autodetect))
        bar.addStretch()
        bar.addWidget(click('Auto-configure RetroAchievements',self.configure_ra_all))
        sc=QScrollArea();sc.setWidgetResizable(True);outer.addWidget(sc)
        body=QWidget();sc.setWidget(body);lay=QVBoxLayout(body)
        for e in EMULATORS:
            row=QHBoxLayout();lay.addLayout(row)
            n=label(e.name+('  · experimental' if e.status!='supported' else ''));n.setFixedWidth(210);row.addWidget(n)
            edit=QLineEdit(self.settings.values['emulators'].get(e.key,''));edit.setPlaceholderText(e.executable)
            row.addWidget(edit,1);self.edits[e.key]=edit
            row.addWidget(click('Browse…',lambda checked=False,key=e.key:self.browse(key)))
            row.addWidget(click('Open',lambda checked=False,key=e.key:self.open_gui(key)))
            if e.key in RA_SUPPORTED:
                row.addWidget(click('Enable RA',lambda checked=False,key=e.key:self.configure_ra_one(key)))
        self.ra_autoconfigure=QCheckBox('Keep RetroAchievements enabled for detected emulators on future launches')
        self.ra_autoconfigure.setChecked(bool(self.settings.values.get('ra_auto_configure',False)))
        outer.addWidget(self.ra_autoconfigure)
        outer.addWidget(label('Supports DuckStation, PCSX2, PPSSPP and Dolphin. GameShelf enables their native feature; '
                              'you must sign in through each emulator using its Achievements menu. '
                              'Close the emulator before changing its settings.', 'muted',True))
        outer.addWidget(label('Xbox One · WinDurango compatibility layer','section'))
        outer.addWidget(label('WinDurango has no standalone launcher. The bundled WinDurango.Common.dll is a detection marker, not an executable. Add a prepared game .exe from its Mount folder; Xbox One ISO/XVC files are not directly bootable. Follow the official game registration/setup instructions before launching.','muted',True))
        outer.addWidget(label('Kyty PS5 launching','section'))
        outer.addWidget(label('PLAY launches the selected game directly through kyty_emulator.exe, as in GameShelf v0.4. To open Kyty’s library manually, use the Open button above.','muted',True))
        outer.addWidget(label('The frontend will not alter emulator firmware, system settings, save files or game data.','muted',True))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);outer.addWidget(buttons)
    def ra_path(self,key):
        return executable_path(self.edits[key].text().strip()) if self.edits[key].text().strip() else BASE/'__emulator_not_configured__'
    def configure_ra_one(self,key):
        result=configure_ra(key,self.ra_path(key))
        title='RetroAchievements · '+RA_SUPPORTED[key][0]
        content=result.message+(f'\nSettings: {result.config_path}' if result.config_path else '')
        (QMessageBox.information if result.status in ('enabled','already_enabled') else QMessageBox.warning)(self,title,content)
    def configure_ra_all(self):
        paths={key:str(self.ra_path(key)) for key in RA_SUPPORTED}
        results=configure_ra_all(paths)
        message='\n'.join(f'{RA_SUPPORTED[r.key][0]}: {r.status.replace("_"," ")} - {r.message}' for r in results)
        QMessageBox.information(self,'RetroAchievements configuration',message)
    def browse(self,key):
        chosen,_=QFileDialog.getOpenFileName(self,'Choose WinDurango runtime' if key=='windurango' else 'Choose emulator executable',str(BASE),'WinDurango runtime (WinDurango.Common.dll);;DLL files (*.dll)' if key=='windurango' else 'Executable (*.exe);;All files (*)')
        if chosen:self.edits[key].setText(chosen)
    def autodetect(self):
        directory=QFileDialog.getExistingDirectory(self,'Select a folder holding both extracted archives',str(BASE))
        if not directory:return
        found=detect_executables([directory])
        for key,path in found.items():self.edits[key].setText(path)
        QMessageBox.information(self,'Detection',f'Found {len(found)} of {len(EMULATORS)} emulator executables.')
    def open_gui(self,key):
        path=executable_path(self.edits[key].text().strip())
        if not path.is_file():
            QMessageBox.warning(self,'Missing executable','Choose an existing executable first.');return
        if key=='windurango':
            from windurango_support import SUPPORT_URL
            QMessageBox.information(self,'WinDurango setup','WinDurango is a compatibility DLL layer, not a standalone emulator.\n\nCopy/install the DLLs as required by its official guide, register compatible games in Windows, then select their prepared .exe in GameShelf.\n\n'+SUPPORT_URL)
            return
        import subprocess
        try:
            if key=='kyty':
                from core import kyty_native_launcher
                path=kyty_native_launcher(path)
            subprocess.Popen([str(path)],cwd=str(path.parent),shell=False)
        except Exception as exc:QMessageBox.critical(self,'Launch failed',str(exc))
    def save(self):
        self.settings.values['emulators']={k:e.text().strip() for k,e in self.edits.items() if e.text().strip()}
        self.settings.values['kyty_launch_mode']='direct'  # Keep old profiles from switching PLAY to Kyty's library.
        self.settings.values['ra_auto_configure']=self.ra_autoconfigure.isChecked()
        self.settings.save();self.accept()


def prepare_windurango_game(game_executable: str, configured_runtime: str, parent=None) -> bool:
    """Explicitly approved game-folder DLL deployment; no silent AppX changes."""
    try:
        plan=preparation_plan(game_executable, configured_runtime)
    except (OSError, ValueError) as exc:
        QMessageBox.warning(parent,'WinDurango preparation unavailable',str(exc))
        return False
    # WinDurango requires EmbeddedXvd inside the folder holding the executable.
    # If it is immediately above Mount, offer an explicit, non-overwriting move.
    moved_embedded=None
    try:
        relocation=embedded_xvd_relocation_plan(game_executable)
    except (OSError, ValueError) as exc:
        QMessageBox.warning(parent,'EmbeddedXvd location conflict',str(exc))
        return False
    if relocation:
        source, target=relocation
        choice=QMessageBox.question(
            parent,'Place EmbeddedXvd in the game folder',
            f'WinDurango requires EmbeddedXvd next to the game executable.\n\n'
            f'Current: {source}\nRequired: {target}\n\n'
            'Move this folder to the required location?\n'
            'This moves the original folder on the same drive; existing files will not be overwritten.\n'
            'Close the game before proceeding. GameShelf will not change Windows registration.',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if choice!=QMessageBox.StandardButton.Yes:
            return False
        try:
            moved_embedded=relocate_embedded_xvd(game_executable)
            plan=preparation_plan(game_executable,configured_runtime)
        except (OSError,ValueError,RuntimeError) as exc:
            QMessageBox.critical(parent,'EmbeddedXvd relocation failed',str(exc))
            return False
    names=', '.join(source.name for source,_ in plan.pending)
    if plan.pending:
        choice=QMessageBox.question(
            parent,'Prepare Xbox One game for WinDurango',
            f'Game folder: {plan.executable.parent}\n\n'
            f'Copy {len(plan.pending)} missing DLLs into the game folder?\n'
            f'Existing DLLs ({len(plan.already_present)}) will NOT be overwritten.\n\n'
            f'Files: {names}\n\n'
            f'Game-specific EmbeddedXvd dependencies available: {len(plan.game_specific_pending)}\n\n'
            'The game may still need Windows Developer Mode, AppX registration and '
            'game-specific EmbeddedXvd dependencies. This does not guarantee compatibility.',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if choice!=QMessageBox.StandardButton.Yes:
            return False
        try:
            copied=apply_preparation_plan(plan)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.critical(parent,'WinDurango preparation failed',str(exc))
            return False
    else:
        copied=()
    if plan.manifest:
        cmd=registration_command(plan.manifest)
        msg=QMessageBox(parent)
        msg.setWindowTitle('WinDurango runtime copied')
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(f'{len(copied)} WinDurango DLLs installed.\n'
                    f'EmbeddedXvd: {"moved into game folder" if moved_embedded else "unchanged"}.\n\n'
                    'If this app is not yet registered, enable Windows Developer Mode '
                    'and run the following in PowerShell (you must choose to do this yourself):\n\n'+cmd)
        copy=msg.addButton('Copy registration command',QMessageBox.ButtonRole.ActionRole)
        msg.addButton('Close',QMessageBox.ButtonRole.AcceptRole)
        msg.exec()
        if msg.clickedButton()==copy:QApplication.clipboard().setText(cmd)
    else:
        QMessageBox.information(parent,'WinDurango runtime copied',
            f'{len(copied)} DLLs installed. EmbeddedXvd: {"moved into game folder" if moved_embedded else "unchanged"}. No AppxManifest.xml was found near the executable. '
            'If this is an Xbox One UWP game, it may still need app registration, '
            'Developer Mode and game-specific EmbeddedXvd DLLs.\n\n'
            f'Official guide: {SUPPORT_URL}')
    return True


class GameDialog(QDialog):
    def __init__(self,existing=None,parent=None):
        super().__init__(parent);self.setWindowTitle('Edit game' if existing else 'Add game')
        self.resize(620,310);form=QFormLayout(self)
        self.title=QLineEdit(existing['title'] if existing else '')
        self.path=QLineEdit(existing['path'] if existing else '')
        self.platform=QComboBox()
        for k,v in PLATFORMS.items():self.platform.addItem(v,k)
        self.emulator=QComboBox()
        for e in EMULATORS:self.emulator.addItem(e.name,e.key)
        form.addRow('Title',self.title)
        browse_row=QHBoxLayout();browse_row.addWidget(self.path);browse_row.addWidget(click('File…',self.choose_file));browse_row.addWidget(click('Folder…',self.choose_dir))
        form.addRow('Game path / Vita title ID',browse_row)
        form.addRow('Platform',self.platform)
        form.addRow('Emulator',self.emulator)
        self.windurango_prepare=click('Prepare WinDurango Game…',self.prepare_windurango)
        form.addRow('',self.windurango_prepare)
        self.windurango_prepare.setVisible(self.emulator.currentData()=='windurango')
        self.emulator.currentIndexChanged.connect(lambda:self.windurango_prepare.setVisible(self.emulator.currentData()=='windurango'))
        form.addRow(label('Vita3K: installed title IDs. Dreamcast: GDI/CDI/CHD/CUE. N64: Z64/N64/V64/ZIP. Xbox One / WinDurango: already prepared game executable (.exe), not ISO/XVC.','muted',True))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate);buttons.rejected.connect(self.reject);form.addRow(buttons)
        self.platform.currentIndexChanged.connect(self.suggest_emulator)
        if existing:
            idx=self.platform.findData(existing['platform']);self.platform.setCurrentIndex(idx)
            idx=self.emulator.findData(existing['emulator']);self.emulator.setCurrentIndex(idx)
    def prepare_windurango(self):
        if self.emulator.currentData()!='windurango':return
        parent=self.parent()
        configured=(parent.settings.values.get('emulators',{}).get('windurango')
                    if parent is not None and hasattr(parent,'settings') else None)
        marker=executable_path(configured) if configured else BASE/'Emulators'/'WinDurango'/'WinDurango.Common.dll'
        prepare_windurango_game(self.path.text().strip(),str(marker),self)

    def choose_file(self):
        chosen,_=QFileDialog.getOpenFileName(self,'Choose game file',str(BASE))
        if chosen:
            self.path.setText(chosen)
            if not self.title.text().strip():self.title.setText(safe_name(chosen))
    def choose_dir(self):
        chosen=QFileDialog.getExistingDirectory(self,'Choose game directory',str(BASE))
        if chosen:
            self.path.setText(chosen)
            if not self.title.text().strip():self.title.setText(safe_name(chosen))
    def suggest_emulator(self):
        p=self.platform.currentData()
        for e in EMULATORS:
            if p in e.platforms:self.emulator.setCurrentIndex(self.emulator.findData(e.key));break
    def validate(self):
        value=self.path.text().strip()
        if not self.title.text().strip() or not value:
            QMessageBox.warning(self,'Missing details','Enter both a title and a game path or Vita title ID.');return
        if self.emulator.currentData() not in [e.key for e in EMULATORS if self.platform.currentData() in e.platforms]:
            QMessageBox.warning(self,'Platform mismatch','Choose an emulator compatible with the selected platform.');return
        if self.emulator.currentData()!='vita3k' and not Path(value).exists():
            QMessageBox.warning(self,'Missing file','The selected game path does not exist.');return
        if self.emulator.currentData()=='windurango':
            try:
                validate_game_path(value)
            except ValueError as exc:
                QMessageBox.warning(self,'WinDurango preparation required',str(exc));return
        self.accept()
    def game_data(self):
        return dict(title=self.title.text().strip(),path=self.path.text().strip(),platform=self.platform.currentData(),emulator=self.emulator.currentData())


class PS3GameSettingsDialog(QDialog):
    """Edit per-game RPCS3 CLI flags without changing RPCS3's own config files."""
    def __init__(self,game:dict,executable:str='',parent=None,fullscreen:bool=True):
        super().__init__(parent)
        self.fullscreen=fullscreen
        self.game=game
        self.executable=executable or 'rpcs3.exe'
        self.setWindowTitle('PS3 Game Settings · '+game['title'])
        self.resize(760,405)
        layout=QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(label('PlayStation 3 · Game Settings','headline'))
        layout.addWidget(label(game['title'],'section',True))
        layout.addWidget(label('Custom RPCS3 command-line arguments for this game only. '
                               'GameShelf adds these before the game path when you press PLAY.', 'muted', True))
        layout.addWidget(label('Additional RPCS3 arguments'))
        self.arguments=QLineEdit(game.get('ps3_args','') or '')
        self.arguments.setObjectName('ps3Arguments')
        self.arguments.setPlaceholderText('e.g. --game-screen 1')
        self.arguments.setToolTip('Use double quotes for paths with spaces. These options are sent to RPCS3, not to cmd.exe.')
        layout.addWidget(self.arguments)
        layout.addWidget(label('Launch command preview ('+('Big Picture' if fullscreen else 'Desktop')+' mode)', 'muted'))
        self.preview=QPlainTextEdit()
        self.preview.setObjectName('ps3CommandPreview')
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(95)
        layout.addWidget(self.preview)
        layout.addWidget(label('RPCS3 supports a version-specific set of options; check RPCS3 --help '
                               'for supported flags. For CPU, GPU and other emulator tweaks, use '
                               'RPCS3\'s native per-game Custom Configuration.', 'muted', True))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton('Clear Arguments',QDialogButtonBox.ButtonRole.ResetRole).clicked.connect(self.arguments.clear)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.arguments.textChanged.connect(self.update_preview)
        self.update_preview()

    def update_preview(self,*unused):
        try:
            pieces=[self.executable,*rpcs3_launch_args(self.game['path'], self.fullscreen, self.arguments.text())]
            self.preview.setPlainText(subprocess.list2cmdline(pieces))
        except (ValueError,OSError) as exc:
            self.preview.setPlainText('Preview unavailable: '+str(exc))

    def validate(self):
        try:parse_windows_arguments(self.arguments.text())
        except ValueError as exc:
            QMessageBox.warning(self,'Invalid RPCS3 arguments',str(exc))
            return
        self.accept()

    def ps3_args(self)->str:
        return self.arguments.text().strip()


class DiscManagerDialog(QDialog):
    """Attach ordered disc images to a supported multi-disc library entry."""
    def __init__(self,game,parent=None):
        super().__init__(parent)
        self.game_platform=game['platform']
        self.setWindowTitle('Manage Discs · '+game['title'])
        self.resize(760,420)
        layout=QVBoxLayout(self)
        layout.addWidget(label('These discs remain separate files, but appear as one game in GameShelf. The Switch Disc button remembers the next boot disc.', 'muted', True))
        self.paths=QListWidget()
        self.paths.addItem(game['path'])
        discs=game.get('discs',[])
        for entry in discs:
            if entry['path'].casefold()!=game['path'].casefold():self.paths.addItem(entry['path'])
        layout.addWidget(self.paths,1)
        row=QHBoxLayout()
        row.addWidget(click('+ Add discs',self.add_paths))
        row.addWidget(click('Remove selected',self.remove_selected))
        row.addWidget(click('Move up',self.move_up))
        row.addWidget(click('Move down',self.move_down))
        layout.addLayout(row)
        layout.addWidget(label('Disc 1 must be the original game path. Only move or remove the other discs.', 'muted', True))
        actions=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)
    def all_paths(self):
        return [self.paths.item(i).text() for i in range(self.paths.count())]
    def add_paths(self):
        chosen,_=QFileDialog.getOpenFileNames(self,'Add disc images',str(Path(self.paths.item(0).text()).parent),
                                        'Supported disc images (' + ' '.join('*'+ext for ext in sorted(DISC_IMAGE_EXTS[self.game_platform])) + ')')
        known={path.casefold() for path in self.all_paths()}
        for path in chosen:
            if path.casefold() not in known:
                self.paths.addItem(path);known.add(path.casefold())
    def remove_selected(self):
        row=self.paths.currentRow()
        if row>0:self.paths.takeItem(row)
    def move_up(self):
        row=self.paths.currentRow()
        if row>1:
            item=self.paths.takeItem(row);self.paths.insertItem(row-1,item);self.paths.setCurrentRow(row-1)
    def move_down(self):
        row=self.paths.currentRow()
        if 0<row<self.paths.count()-1:
            item=self.paths.takeItem(row);self.paths.insertItem(row+1,item);self.paths.setCurrentRow(row+1)
    def accept(self):
        if self.paths.count()<2:
            QMessageBox.warning(self,'Missing discs','Add at least one extra disc before saving.');return
        super().accept()


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'GameShelf v{APP_VERSION} · Your Games, One Library');self.resize(1500,920)
        self.setWindowIcon(load_icon())
        self.setMinimumSize(900,600)
        self.settings=Settings();self.library=Library();self.controller=Controller()
        self.theme=normalize_theme(self.settings.values.get('theme'))
        activate_theme(self.theme)
        QApplication.instance().setStyleSheet(theme_stylesheet(STYLE, self.theme))
        self.selected=None;self.filter='all';self.search='';self.big_index=0;self.big_games=[]
        self.sessions={};self.session_monitors={};self.session_disc_playlist=set();self._game_input_paused=False;self.scanner=None;self.title_worker=None;self.title_scan_again=False;self.title_changed=0
        self.root=QStackedWidget();self.root.setObjectName('root');self.setCentralWidget(self.root)
        self.desktop=self.make_desktop();self.big=self.make_big()
        self.root.addWidget(self.desktop);self.root.addWidget(self.big)
        QShortcut(QKeySequence('F11'),self).activated.connect(self.toggle_big)
        QShortcut(QKeySequence('Ctrl+O'),self).activated.connect(self.add_game)
        QShortcut(QKeySequence('Ctrl+I'),self).activated.connect(self.import_folder)
        self.big_shortcuts=[]
        big_keys=[('Left',lambda:self.big_move(-1)),
                  ('Right',lambda:self.big_move(1)),
                  ('Up',lambda:self.big_move(-self.big_columns())),
                  ('Down',lambda:self.big_move(self.big_columns())),
                  ('Escape',self.leave_big),
                  ('S',self.edit_ps3_settings),
                  ('Return',lambda:self.launch_selected(self.big_games[self.big_index]['id']) if self.big_games else None)]
        for key,action in big_keys:
            # Arrows and S are scoped to the grid so they don't intercept
            # console dropdown navigation or editing text in dialogs.
            arrows={'Left','Right','Up','Down','S'}
            shortcut=QShortcut(QKeySequence(key),self.bigscroll if key in arrows else self)
            if key in arrows:
                shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(action)
            shortcut.setEnabled(False);self.big_shortcuts.append(shortcut)
        self.metadata_refresh=QTimer(self);self.metadata_refresh.setSingleShot(True)
        self.metadata_refresh.timeout.connect(self.refresh)
        self.search_debounce=QTimer(self);self.search_debounce.setSingleShot(True)
        self.search_debounce.timeout.connect(self.refresh)
        self.big_dirty=True
        self.tick=QTimer(self);self.tick.timeout.connect(self.poll);self.tick.start(100)
        self.refresh()
        # Prefer packaged emulator executables, even when an older version saved an
        # absolute external path. This makes the app + Emulators folder portable.
        bundled=detect_bundled_executables(BASE)
        found=detect_executables([BASE,BASE.parent])
        updated=False
        for key,path in {**found,**bundled}.items():
            saved=self.settings.values['emulators'].get(key,'')
            if key in bundled or not executable_path(saved).is_file():
                if saved!=path:
                    self.settings.values['emulators'][key]=path
                    updated=True
        if updated:self.settings.save()
        if self.settings.values.get('ra_auto_configure'):
            # Opt-in: restore enable flags for emulators that have already generated configs.
            # No authentication credentials are copied or written by GameShelf.
            configure_ra_all({key:str(executable_path(self.settings.values['emulators'].get(key,'')))
                              for key in RA_SUPPORTED if self.settings.values['emulators'].get(key)})
        self.update_summary()
        self.migrate_legacy_platforms()
        QTimer.singleShot(1200,self.resolve_title_ids)

    def make_theme_combo(self):
        combo=QComboBox()
        combo.setToolTip('Theme is saved and applies to both Desktop and Big Picture')
        for key in THEME_KEYS:
            combo.addItem(THEMES[key]['label'], key)
        combo.setCurrentIndex(combo.findData(self.theme))
        combo.currentIndexChanged.connect(lambda _index, widget=combo: self.change_theme(widget.currentData()))
        return combo

    def update_footer_theme(self):
        if hasattr(self,'big_footer'):
            self.big_footer.setStyleSheet(
                f"font-size: 15px; color:{theme_color('#becbe0')}; padding:12px; "
                f"background:{theme_color('#172131')}; border-radius:12px;")

    def change_theme(self, selected):
        key=normalize_theme(selected)
        if key==self.theme:
            return
        self.theme=activate_theme(key)
        self.settings.values['theme']=key
        self.settings.save()
        app=QApplication.instance()
        if app:
            app.setStyleSheet(theme_stylesheet(STYLE, key))
        for combo_name in ('theme_combo','big_theme_combo'):
            combo=getattr(self,combo_name,None)
            if combo is not None and combo.currentData()!=key:
                combo.blockSignals(True)
                combo.setCurrentIndex(combo.findData(key))
                combo.blockSignals(False)
        self.update_footer_theme()
        if hasattr(self,'scroller'): self.scroller.viewport().update()
        if hasattr(self,'bigscroll'): self.bigscroll.viewport().update()
        if hasattr(self,'details_poster'): self.details_poster.update()

    def make_desktop(self):
        w=QWidget();w.setObjectName('desktop');outer=QHBoxLayout(w);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        side=QFrame();side.setObjectName('sidebar');side.setFixedWidth(248);outer.addWidget(side)
        sl=QVBoxLayout(side);sl.setContentsMargins(16,28,13,20);sl.setSpacing(13)
        brand_row=QHBoxLayout()
        brand_icon=QLabel(); brand_icon.setPixmap(load_icon().pixmap(38,38))
        brand_row.addWidget(brand_icon)
        brand_row.addWidget(GameShelfWordmark(173, 38))
        brand_row.addStretch(1)
        sl.addLayout(brand_row)
        sl.addWidget(label('YOUR UNIFIED GAME LIBRARY','muted'))
        sl.addSpacing(14)
        self.nav=QListWidget()
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        enable_smooth_wheel(self.nav)
        self.nav.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.nav.setWordWrap(False)
        sl.addWidget(self.nav,1)
        # Fixed order by console family, independent of emulator install order.
        # Section headings are deliberately not selectable game filters.
        for title,key in [('▦  All Games','all'),('★  Favourites','favorites'),('◷  Recently Played','recent')]:
            item=QListWidgetItem(title)
            item.setToolTip(title.strip())
            item.setData(Qt.ItemDataRole.UserRole,key)
            self.nav.addItem(item)
        for family,platform_keys in CONSOLE_GROUPS:
            heading=QListWidgetItem('  ' + family)
            heading.setFlags(Qt.ItemFlag.NoItemFlags)
            heading.setForeground(QColor('#8197b5'))
            font=heading.font()
            font.setBold(True)
            font.setPointSize(9)
            heading.setFont(font)
            heading.setSizeHint(QSize(0,32))
            self.nav.addItem(heading)
            for key in platform_keys:
                title=PLATFORMS[key]
                item=QListWidgetItem('  ' + title)
                item.setToolTip(title)
                item.setData(Qt.ItemDataRole.UserRole,key)
                self.nav.addItem(item)
        self.nav.setCurrentRow(0);self.nav.currentItemChanged.connect(self.change_filter)
        sl.addWidget(click('⚙  Emulator Manager',self.manage_emulators))
        sl.addWidget(label('APPEARANCE','muted'))
        self.theme_combo=self.make_theme_combo()
        sl.addWidget(self.theme_combo)
        self.startup_btn=click('',self.toggle_startup_mode)
        sl.addWidget(self.startup_btn)
        self.update_startup_label()
        sl.addWidget(click('⛶  Big Picture  ·  F11',self.enter_big,True))
        self.emucount=label('','muted',True);sl.addWidget(self.emucount)
        content=QWidget();outer.addWidget(content,1)
        cl=QVBoxLayout(content);cl.setContentsMargins(28,24,23,20);cl.setSpacing(14)
        top=QHBoxLayout();cl.addLayout(top)
        intro=QVBoxLayout();top.addLayout(intro,2)
        intro.addWidget(label('Your Library','headline'))
        intro.addWidget(label('All of your worlds, one place.','muted'))
        top.addWidget(click('ID → Names',self.resolve_title_ids))
        top.addWidget(click('↓ Missing Covers',self.download_missing_covers))
        top.addWidget(click('+ Add Game',self.add_game))
        top.addWidget(click('Merge Discs',self.merge_multi_discs))
        top.addWidget(click('Import Folder',self.import_folder,True))
        search=QHBoxLayout();cl.addLayout(search)
        self.searchbar=QLineEdit();self.searchbar.setPlaceholderText('⌕  Search games, platforms, and emulators…');self.searchbar.textChanged.connect(self.set_search)
        search.addWidget(self.searchbar,1)
        self.counter=label('0 games','muted');search.addWidget(self.counter)
        self.div=QSplitter(Qt.Orientation.Horizontal);cl.addWidget(self.div,1)
        # QListView uses one delegate rather than constructing one widget per game.
        # Only tiles inside the viewport are painted and covers are thumbnail-cached.
        self.scroller,self.desktop_model=make_game_view()
        self.scroller.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.scroller.customContextMenuRequested.connect(self.desktop_game_menu)
        self.scroller.clicked.connect(self.on_desktop_index)
        self.scroller.selectionModel().currentChanged.connect(self.on_desktop_index)
        self.div.addWidget(self.scroller)
        # QScrollArea owns the details card so smaller screens / DPI scaling cannot
        # stack labels on top of the cover or push action buttons out of view.
        self.details_scroller=QScrollArea()
        self.details_scroller.setObjectName('detailsScroll')
        self.details_scroller.setWidgetResizable(True)
        enable_smooth_wheel(self.details_scroller)
        self.details_scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.details_scroller.setMinimumWidth(300)
        detail=QFrame()
        detail.setObjectName('details')
        dl=QVBoxLayout(detail)
        dl.setContentsMargins(17,16,17,17)
        dl.setSpacing(9)
        self.details_title=label('Choose a game','detailsTitle',True)
        dl.addWidget(self.details_title)
        self.details_poster=Poster({'title':'YOUR NEXT ADVENTURE','platform':'gc'},192,248)
        dl.addWidget(self.details_poster,alignment=Qt.AlignmentFlag.AlignHCenter)
        self.details_info=label('Import a game folder to get started.','detailsInfo',True)
        dl.addWidget(self.details_info)
        self.details_path=label('','detailsPath')
        self.details_path.setToolTip('The selected game file or folder')
        dl.addWidget(self.details_path)
        self.play_btn=click('▶  PLAY',self.play_selected,True)
        dl.addWidget(self.play_btn)
        self.fav_btn=click('☆  Add to Favourites',self.toggle_favorite)
        dl.addWidget(self.fav_btn)
        self.find_cover_btn=click('Find Online Cover…',self.find_cover)
        self.cover_btn=click('Change Cover Art…',self.change_cover)
        self.discs_btn=click('💿 Manage Discs…',self.manage_discs)
        self.swap_btn=click('⇄  Switch Disc',self.switch_disc)
        self.ps3_settings_btn=click('⚙  PS3 Game Settings…',self.edit_ps3_settings)
        self.ps3_settings_btn.setToolTip('Set RPCS3 command-line arguments for this particular game')
        dl.addWidget(self.ps3_settings_btn)
        dl.addWidget(self.discs_btn)
        dl.addWidget(self.swap_btn)
        self.edit_btn=click('Edit Game…',self.edit_game)
        self.windurango_prepare_btn=click('Prepare WinDurango Game…',self.prepare_selected_windurango)
        self.windurango_diagnose_btn=click('Diagnose WinDurango Launch…',self.diagnose_selected_windurango)
        self.remove_btn=click('Remove from Library',self.remove_game)
        dl.addWidget(self.find_cover_btn)
        dl.addWidget(self.cover_btn)
        dl.addWidget(self.edit_btn)
        dl.addWidget(self.windurango_prepare_btn)
        dl.addWidget(self.windurango_diagnose_btn)
        dl.addWidget(self.remove_btn)
        dl.addStretch(1)
        self.details_scroller.setWidget(detail)
        self.div.addWidget(self.details_scroller)
        self.div.setCollapsible(1,False)
        self.div.setStretchFactor(0,1)
        self.div.setStretchFactor(1,0)
        self.div.setSizes([780,325])
        self.statusBar().showMessage('Ready')
        return w

    def make_big(self):
        w=QWidget();w.setObjectName('bigpicture');lay=QVBoxLayout(w)
        lay.setContentsMargins(46,28,46,30);lay.setSpacing(15)
        bar=QHBoxLayout();lay.addLayout(bar)
        big_icon=QLabel();big_icon.setPixmap(load_icon().pixmap(56,56))
        bar.addWidget(big_icon)
        bar.addWidget(GameShelfWordmark(330, 58));bar.addStretch(1)
        bar.addWidget(click('All',lambda:self.big_filter('all')))
        bar.addWidget(click('Favourites',lambda:self.big_filter('favorites')))
        # Console filters are available directly in fullscreen mode, not only
        # behind the Desktop sidebar. These are the same canonical groups.
        self.big_system=QComboBox()
        self.big_system.setMinimumWidth(240)
        self.big_system.setToolTip('Filter your games by console')
        for key, title in [('all','All consoles'),('favorites','Favourites'),('recent','Recently played')]:
            self.big_system.addItem(title,key)
        for family, platform_keys in CONSOLE_GROUPS:
            self.big_system.insertSeparator(self.big_system.count())
            for key in platform_keys:
                self.big_system.addItem(f'{family.title()} · {PLATFORMS[key]}',key)
        self.big_system.currentIndexChanged.connect(self.on_big_system)
        bar.addWidget(self.big_system)
        self.big_theme_combo=self.make_theme_combo()
        self.big_theme_combo.setMinimumWidth(156)
        self.big_theme_combo.setToolTip('Change GameShelf theme')
        bar.addWidget(self.big_theme_combo)
        self.big_ps3_settings_btn=click('⚙ PS3 Settings',self.edit_ps3_settings)
        self.big_ps3_settings_btn.setVisible(False)
        bar.addWidget(self.big_ps3_settings_btn)
        self.big_switch_btn=click('⇄ Switch Disc',self.switch_disc)
        self.big_switch_btn.setVisible(False)
        bar.addWidget(self.big_switch_btn)
        bar.addWidget(click('Desktop  ·  F11',self.leave_big))
        self.big_sub=label('SELECT A GAME  ·  PRESS A TO PLAY','muted');lay.addWidget(self.big_sub)
        self.bigscroll,self.big_model=make_game_view(large=True)
        self.bigscroll.clicked.connect(self.on_big_index)
        self.bigscroll.selectionModel().currentChanged.connect(self.on_big_current)
        lay.addWidget(self.bigscroll,1)
        self.big_footer=label('', 'muted',True)
        self.update_gamepad_footer()
        self.update_footer_theme()
        lay.addWidget(self.big_footer)
        return w

    def items(self):
        games=self.library.all()
        if self.filter=='favorites':games=[x for x in games if x['favorite']]
        elif self.filter=='recent':games=[x for x in games if x['last_played']>0];games.sort(key=lambda x:-x['last_played'])
        elif self.filter in PLATFORMS:games=[x for x in games if x['platform']==self.filter]
        if self.search.strip():
            needle=self.search.casefold().strip()
            games=[x for x in games if needle in (x['title']+' '+PLATFORMS.get(x['platform'],'')+' '+BY_KEY[x['emulator']].name).casefold()]
        return games
    def sync_filter_controls(self):
        """Desktop and fullscreen must never claim different console filters."""
        for row in range(self.nav.count()):
            item=self.nav.item(row)
            if item.data(Qt.ItemDataRole.UserRole)==self.filter:
                self.nav.blockSignals(True)
                try:self.nav.setCurrentRow(row)
                finally:self.nav.blockSignals(False)
                break
        for row in range(self.big_system.count()):
            if self.big_system.itemData(row)==self.filter:
                self.big_system.blockSignals(True)
                try:self.big_system.setCurrentIndex(row)
                finally:self.big_system.blockSignals(False)
                break

    def change_filter(self,current,previous):
        if current and current.data(Qt.ItemDataRole.UserRole) is not None:
            new_filter=current.data(Qt.ItemDataRole.UserRole)
            if new_filter!=self.filter:
                self.filter=new_filter
                if self.search_debounce.isActive():self.search_debounce.stop()
                self.sync_filter_controls()
                self.refresh()

    def on_big_system(self,index):
        key=self.big_system.itemData(index)
        if key is not None:self.big_filter(key)
    def set_search(self,value):
        self.search=value
        # Do not rebuild the model 12 times while someone types a title.
        self.search_debounce.start(180)
    def big_filter(self,key):
        if key not in ('all','favorites','recent') and key not in PLATFORMS:
            return
        # The fullscreen All button must really show everything, even if the
        # user previously entered a Desktop-only search query.
        if self.search:
            self.search=''
            self.search_debounce.stop()
            self.searchbar.blockSignals(True)
            try:self.searchbar.clear()
            finally:self.searchbar.blockSignals(False)
        self.filter=key
        self.sync_filter_controls()
        # A single model refresh handles both the mode and any cleared search.
        self.refresh()
    def desktop_game_menu(self,position):
        index=self.scroller.indexAt(position)
        if not index.isValid():return
        game=index.data(Qt.ItemDataRole.UserRole)
        if not game:return
        self.choose(game['id'])
        menu=QMenu(self)
        menu.addAction('▶  Play',lambda:self.launch_selected(game['id']))
        if game['platform']=='ps3':
            menu.addAction('⚙  PS3 Game Settings…',self.edit_ps3_settings)
        if game['platform'] in DISC_PLATFORMS:
            menu.addAction('💿 Manage Discs…',self.manage_discs)
            if game.get('disc_count',1)>1:
                menu.addAction('⇄ Switch Disc',self.switch_disc)
        if game['emulator']=='windurango':
            menu.addAction('Prepare WinDurango Game…',self.prepare_selected_windurango)
            menu.addAction('Diagnose WinDurango Launch…',self.diagnose_selected_windurango)
        menu.addAction('Edit Game…',self.edit_game)
        menu.exec(self.scroller.viewport().mapToGlobal(position))

    def on_desktop_index(self,index):
        game=index.data(Qt.ItemDataRole.UserRole)
        if game:
            self.choose(game['id'])
    def on_big_index(self,index):
        game=index.data(Qt.ItemDataRole.UserRole)
        if game:
            self.big_choose(game['id'])
    def on_big_current(self,index,previous):
        game=index.data(Qt.ItemDataRole.UserRole)
        if game:
            self.big_index=index.row()
            self.selected=game['id']
            self.big_sub.setText(f'{len(self.big_games)} GAMES     ·     {game["title"].upper()}')
            self.big_ps3_settings_btn.setVisible(game['platform']=='ps3')
            self.big_switch_btn.setVisible(game.get('disc_count',1)>1)
    def refresh(self):
        games=self.items()
        self.counter.setText(f'{len(games)} game'+('' if len(games)==1 else 's'))
        # One model reset, not thousands of QLabel, Poster and QPushButton allocations.
        self.desktop_model.set_games(games)
        visible_ids=self.desktop_model.positions
        if self.selected not in visible_ids:
            self.selected=games[0]['id'] if games else None
        index=self.desktop_model.row_for(self.selected)
        if index>=0:
            self.scroller.setCurrentIndex(self.desktop_model.index(index,0))
        self.show_details()
        # Desktop navigation never renders the hidden fullscreen list.
        self.big_dirty=True
        if self.root.currentWidget()==self.big:
            self.refresh_big(games)
    def resizeEvent(self,event):
        # QListView reflows lightweight delegate cards automatically on resize.
        super().resizeEvent(event)
    def update_game_in_views(self,identifier,cover_changed=False):
        """Repaint only an edited cover/favourite/playtime row, not the whole library."""
        game=self.library.get(identifier)
        if game is None:
            self.refresh()
            return
        self.desktop_model.update_game(game)
        self.big_model.update_game(game)
        if self.selected==identifier:
            if cover_changed:
                self.details_poster_game=None
            self.show_details()
    def choose(self,identifier):
        if self.selected!=identifier:
            self.selected=identifier
            self.show_details()
    def show_details(self):
        game=self.library.get(self.selected) if self.selected else None
        if game is None:
            self.details_title.setText('Choose a game');self.details_info.setText('No game selected.');self.details_path.setText('')
            for btn in (self.play_btn,self.fav_btn,self.find_cover_btn,self.cover_btn,self.edit_btn,self.remove_btn):
                btn.setEnabled(False)
            self.ps3_settings_btn.setVisible(False)
            self.big_ps3_settings_btn.setVisible(False)
            self.big_switch_btn.setVisible(False)
            self.discs_btn.setVisible(False)
            self.swap_btn.setVisible(False)
            self.windurango_prepare_btn.setVisible(False)
            self.windurango_diagnose_btn.setVisible(False)
            return
        for btn in (self.play_btn,self.fav_btn,self.find_cover_btn,self.cover_btn,self.edit_btn,self.remove_btn):
            btn.setEnabled(True)
        self.windurango_prepare_btn.setVisible(game['emulator']=='windurango')
        self.windurango_diagnose_btn.setVisible(game['emulator']=='windurango')
        self.ps3_settings_btn.setVisible(game['platform']=='ps3')
        self.big_ps3_settings_btn.setVisible(game['platform']=='ps3')
        self.discs_btn.setVisible(game['platform'] in DISC_PLATFORMS)
        self.swap_btn.setVisible(game.get('disc_count',1)>1)
        self.big_switch_btn.setVisible(game.get('disc_count',1)>1)
        self.details_title.setText(game['title'])
        disc_details=(f"\n{game['disc_count']} discs · Selected Disc {game['selected_disc']}" if game.get('disc_count',1)>1 else '')
        self.details_info.setText(f"{PLATFORMS[game['platform']]}  ·  {BY_KEY[game['emulator']].name}\nPlaytime: {game['seconds_played']//3600}h {(game['seconds_played']%3600)//60}m"+disc_details)
        path=game['path']
        self.details_path.setText('Location: '+self.details_path.fontMetrics().elidedText(Path(path).name or path,Qt.TextElideMode.ElideMiddle,246))
        self.details_path.setToolTip(path)
        self.fav_btn.setText('★  In Favourites' if game['favorite'] else '☆  Add to Favourites')
        # Reuse the poster if its content has not changed.
        if getattr(self,'details_poster_game',None)==(game['id'],game.get('artwork',''),game['title']):
            return
        self.details_poster_game=(game['id'],game.get('artwork',''),game['title'])
        layout=self.details_poster.parentWidget().layout()
        idx=layout.indexOf(self.details_poster)
        layout.removeWidget(self.details_poster)
        self.details_poster.deleteLater()
        self.details_poster=Poster(game,192,248)
        layout.insertWidget(idx,self.details_poster,alignment=Qt.AlignmentFlag.AlignHCenter)

    def refresh_big(self,games=None):
        if not self.big_dirty:
            return
        self.big_games=games if games is not None else self.items()
        self.big_model.set_games(self.big_games)
        if self.big_games:
            selected_row=self.big_model.row_for(self.selected)
            self.big_index=selected_row if selected_row>=0 else min(self.big_index,len(self.big_games)-1)
            idx=self.big_model.index(self.big_index,0)
            self.bigscroll.setCurrentIndex(idx)
            self.bigscroll.scrollTo(idx,QAbstractItemView.ScrollHint.EnsureVisible)
            self.big_sub.setText(f'{len(self.big_games)} GAMES     ·     {self.big_games[self.big_index]["title"].upper()}')
        else:
            self.big_index=0
            self.big_ps3_settings_btn.setVisible(False)
            self.big_switch_btn.setVisible(False)
            self.big_sub.setText('No games in this collection. Import some games in desktop mode.')
        self.big_dirty=False
    def big_choose(self,identifier):
        self.selected=identifier
        for i,g in enumerate(self.big_games):
            if g['id']==identifier:self.big_index=i;break
        self.launch_selected(identifier)
    def remember_desktop_window(self):
        """Persist the real windowed geometry before entering fullscreen."""
        if not self.isVisible() or self.isFullScreen() or self.root.currentWidget()!=self.desktop:
            return
        maximized=self.isMaximized()
        self.settings.values['desktop_maximized']=maximized
        if not maximized:
            rect=self.geometry()
            self.settings.values['desktop_rect']=[rect.x(),rect.y(),rect.width(),rect.height()]

    def open_desktop(self):
        """Start maximized by default; restore clamped custom bounds if chosen."""
        # Transitioning away from fullscreen requires leaving its window state.
        if self.isFullScreen():self.showNormal()
        if self.settings.values.get('desktop_maximized',True):
            self.showMaximized()
        else:
            screen=self.screen() or QApplication.primaryScreen()
            available=screen.availableGeometry() if screen else QRect(0,0,1600,900)
            x,y,w,h=safe_desktop_rect(
                (available.x(),available.y(),available.width(),available.height()),
                self.settings.values.get('desktop_rect'))
            self.showNormal()
            self.setGeometry(x,y,w,h)
            self.show()
        if self.root.currentWidget()==self.desktop:
            self.statusBar().show()
            self.statusBar().showMessage('Desktop mode')

    def update_gamepad_footer(self):
        if self.sessions:
            self.big_footer.setText('Game running in emulator  ·  GameShelf controller controls paused until emulator exits')
            return
        status=('Connected: '+self.controller.device) if self.controller.connected else 'Controller not detected'
        self.big_footer.setText('D-PAD / LEFT STICK   Browse     A / ✕   Play     X / □   PS3 Settings     '
            'Y / △   Favourite     LB/RB   Console     B / ○   Desktop     ·     '+status)

    def change_big_console(self,step):
        indexes=[i for i in range(self.big_system.count())
                 if self.big_system.itemData(i) is not None]
        if not indexes:return
        current=self.big_system.currentIndex()
        position=indexes.index(current) if current in indexes else 0
        self.big_system.setCurrentIndex(indexes[(position+step)%len(indexes)])

    def enter_big(self):
        self.remember_desktop_window()
        self.sync_filter_controls()
        self.root.setCurrentWidget(self.big);self.settings.values['last_mode']='big';self.settings.save()
        for shortcut in self.big_shortcuts:shortcut.setEnabled(not self.sessions)
        # Qt's QMainWindow status bar belongs to Desktop mode. Otherwise it
        # remains visible in fullscreen, incorrectly saying "Desktop mode".
        self.statusBar().showMessage('Big Picture mode')
        self.statusBar().hide()
        self.showFullScreen();self.refresh_big();self.focus_big();self.bigscroll.setFocus()
        self.update_gamepad_footer()
    def leave_big(self):
        self.root.setCurrentWidget(self.desktop);self.settings.values['last_mode']='desktop';self.settings.save()
        for shortcut in self.big_shortcuts:shortcut.setEnabled(False)
        row=self.desktop_model.row_for(self.selected)
        if row>=0:self.scroller.setCurrentIndex(self.desktop_model.index(row,0))
        self.show_details()
        self.open_desktop();self.statusBar().show()
        self.statusBar().showMessage('Desktop mode')
    def toggle_big(self):
        if self.root.currentWidget()==self.big:self.leave_big()
        else:self.enter_big()
    def update_startup_label(self):
        mode=self.settings.values.get('startup_mode','desktop')
        self.startup_btn.setText('Startup: Big Picture' if mode=='big' else 'Startup: Desktop')
        self.startup_btn.setToolTip('Click to choose which mode opens next launch')
    def toggle_startup_mode(self):
        current=self.settings.values.get('startup_mode','desktop')
        self.settings.values['startup_mode']='desktop' if current=='big' else 'big'
        self.settings.save()
        self.update_startup_label()
    def focus_big(self):
        if not self.big_games:return
        idx=self.big_model.index(self.big_index,0)
        self.bigscroll.setCurrentIndex(idx)
        self.bigscroll.scrollTo(idx,QAbstractItemView.ScrollHint.EnsureVisible)
        self.big_sub.setText(f'{len(self.big_games)} GAMES     ·     {self.big_games[self.big_index]["title"].upper()}')
    def big_move(self,step):
        if not self.big_games:return
        self.big_index=(self.big_index+step)%len(self.big_games);self.focus_big()
    def big_columns(self):
        return max(1,self.bigscroll.viewport().width()//self.bigscroll.gridSize().width())
    def keyPressEvent(self,event):
        if self.root.currentWidget()==self.big and not self.sessions:
            columns=self.big_columns()
            key=event.key()
            if key==Qt.Key.Key_Escape:self.leave_big();return
            if key==Qt.Key.Key_Left:self.big_move(-1);return
            if key==Qt.Key.Key_Right:self.big_move(1);return
            if key==Qt.Key.Key_Up:self.big_move(-columns);return
            if key==Qt.Key.Key_Down:self.big_move(columns);return
            if key in (Qt.Key.Key_Return,Qt.Key.Key_Enter):
                if self.big_games:self.launch_selected(self.big_games[self.big_index]['id'])
                return
        super().keyPressEvent(event)
    def poll(self):
        for key, (proc, start, track, log_path) in list(self.sessions.items()):
            monitor = self.session_monitors.get(key)
            running = monitor.running() if monitor is not None else proc.poll() is None
            if running:
                continue
            code = proc.poll()
            if track:
                self.library.add_playtime(key, int(max(0, time.monotonic()-start)))
            del self.sessions[key]
            self.session_monitors.pop(key, None)
            getattr(self,'session_disc_playlist',set()).discard(key)
            if log_path is not None and code not in (None, 0):
                try:
                    with Path(log_path).open('rb') as f:
                        f.seek(0, 2); f.seek(max(0, f.tell()-3000))
                        tail = f.read().decode('utf-8', errors='replace')[-1800:]
                except OSError:
                    tail = '(No emulator output was saved.)'
                QMessageBox.warning(self, 'Kyty exited with an error',
                    f'Exit code: 0x{code & 0xffffffff:08X}\n'
                    f'Full launch log: {log_path}\n\nLast output:\n{tail}')
            elif code not in (None,0) and self.library.get(key) and self.library.get(key)['emulator']=='windurango':
                failure=status_name(code)
                self.statusBar().showMessage('WinDurango game failed to start: '+failure,10000)
                answer=QMessageBox.question(self,'WinDurango startup failed',
                    f'The Xbox One game process exited with {failure}.\n\n'
                    'The WinDurango DLLs being present does not confirm game readiness.\n'
                    'Check EmbeddedXvd dependencies, Windows AppX registration, '
                    'and the version supported by WinDurango.\n\n'
                    'Run the read-only diagnosis now?',
                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes)
                if answer==QMessageBox.StandardButton.Yes:
                    self.selected=key
                    self.diagnose_selected_windurango()
            else:
                self.statusBar().showMessage('Game closed. Playtime recorded.' if track else 'Kyty launcher closed.', 6000)
            self.update_game_in_views(key)

        if self.sessions:
            # The emulator must receive the gamepad. Do not even poll controller
            # state, let alone navigate Big Picture or launch another game.
            return
        if self._game_input_paused:
            self._game_input_paused = False
            self.controller.require_release()
            for shortcut in self.big_shortcuts:
                shortcut.setEnabled(self.root.currentWidget() == self.big)
            self.update_gamepad_footer()
            if self.root.currentWidget() == self.big:
                self.bigscroll.setFocus()
        if self.root.currentWidget() != self.big or QApplication.activeModalWidget() is not None:
            return
        old_state = (self.controller.connected, self.controller.device)
        buttons = self.controller.pressed()
        if old_state != (self.controller.connected, self.controller.device):
            self.update_gamepad_footer()
        if buttons & UP: self.big_move(-self.big_columns())
        elif buttons & DOWN: self.big_move(self.big_columns())
        elif buttons & LEFT: self.big_move(-1)
        elif buttons & RIGHT: self.big_move(1)
        elif buttons & LB: self.change_big_console(-1)
        elif buttons & RB: self.change_big_console(1)
        elif buttons & (A | START) and self.big_games:
            self.launch_selected(self.big_games[self.big_index]['id'])
        elif buttons & (B | BACK): self.leave_big()
        elif buttons & X and self.big_games: self.edit_ps3_settings()
        elif buttons & Y and self.big_games:
            self.favorite_id(self.big_games[self.big_index]['id'])
    def update_summary(self):
        found=sum(executable_path(path).is_file() for path in self.settings.values['emulators'].values())
        bundled=len(detect_bundled_executables(BASE))
        external=max(0,found-bundled)
        self.emucount.setText(f'{found}/{len(EMULATORS)} ready  ·  {bundled} bundled')
        self.emucount.setToolTip(f'{bundled} emulator executables found inside GameShelf/Emulators; {external} configured from other folders.')
    def manage_emulators(self):
        if EmulatorDialog(self.settings,self).exec():self.update_summary()
    def migrate_legacy_platforms(self):
        """Correct old PS4/5 merged records only when their PS4 identity is certain."""
        for game in self.library.all():
            if game['platform']!='ps5':continue
            path=Path(game['path'])
            upper=(' '.join((game['title'],path.name,path.parent.name))).upper()
            ps4_metadata=(path if path.is_dir() else path.parent)/'sce_sys'/'param.sfo'
            ps5_metadata=(path if path.is_dir() else path.parent)/'sce_sys'/'param.json'
            if (re.search(r'\bCUSA\d{5}\b',upper) or ps4_metadata.is_file()) and not ps5_metadata.is_file():
                self.library.edit(game['id'],platform='ps4',emulator='shadps4' if 'shadps4' in self.settings.values['emulators'] else game['emulator'])

    def resolve_title_ids(self):
        """Automatically resolve imported/old ID-named games without changing paths."""
        if self.title_worker is not None and self.title_worker.isRunning():
            self.title_scan_again=True
            return
        pending=[g for g in self.library.all() if detect_id(g)]
        if not pending:
            self.statusBar().showMessage('No unresolved title-ID-only names in the library.',4000)
            return
        self.statusBar().showMessage(f'Looking up official game titles for {len(pending)} entries…')
        self.title_changed=0
        self.title_worker=TitleLookupWorker(pending)
        self.title_worker.matched.connect(self.apply_resolved_title)
        self.title_worker.done.connect(self.title_lookup_done)
        self.title_worker.finished.connect(self.title_lookup_finished)
        self.title_worker.start()

    def apply_resolved_title(self,game_id,original,title,source):
        current=self.library.get(game_id)
        # Apply each confirmed match immediately as it arrives, on the UI thread.
        # Respect manual edits, even when the lookup finishes later.
        if current and current['title']==original and detect_id(current):
            self.library.edit(game_id,title=title)
            self.title_changed+=1
            self.statusBar().showMessage(f'Renamed {original} → {title} ({source})',5000)
            self.metadata_refresh.start(250)  # batch expensive grid redraws

    def title_lookup_done(self,checked):
        if self.title_changed:self.metadata_refresh.start(100)
        self.statusBar().showMessage(f'Title ID lookup: {self.title_changed} updated, {checked-self.title_changed} unchanged.',10000)

    def title_lookup_finished(self):
        self.title_worker=None
        if self.title_scan_again:
            self.title_scan_again=False
            QTimer.singleShot(100,self.resolve_title_ids)

    def import_folder(self):
        if self.scanner is not None and self.scanner.isRunning():
            QMessageBox.information(self,'Scan in progress','Finish the existing scan before starting another.')
            return
        platform,ok=QInputDialog.getItem(self,'Import game folder','Choose the console platform:',list(PLATFORMS.values()),0,False)
        if not ok:return
        key=next(k for k,v in PLATFORMS.items() if v==platform)
        directory=QFileDialog.getExistingDirectory(self,'Choose game library folder',str(BASE))
        if not directory:return
        self.statusBar().showMessage('Scanning game folder…')
        self.scanner=ScanWorker(directory,key)
        self.scanner.done.connect(self.on_scanned)
        self.scanner.failed.connect(lambda s:QMessageBox.warning(self,'Scan failed',s))
        self.scanner.finished.connect(lambda:self.statusBar().showMessage('Scan finished',4000))
        self.scanner.start()
    def on_scanned(self,games):
        count=0
        for title,platform,path in games:
            emulator=next(e.key for e in EMULATORS if platform in e.platforms)
            if self.library.add(title,platform,emulator,path):count+=1
        merged=self.library.auto_merge_discs()
        self.refresh()
        self.resolve_title_ids()
        QMessageBox.information(self,'Import complete',f'Scanned {len(games)} entries and added {count} new games.\nMerged {len(merged)} numbered multi-disc sets.\n\nDuplicate game paths were skipped.')
    def add_game(self):
        dialog=GameDialog(parent=self)
        if dialog.exec():
            try:
                g=dialog.game_data()
                if not self.library.add(**g):QMessageBox.information(self,'Already added','That path is already in your library.')
                self.refresh()
                self.resolve_title_ids()
            except Exception as exc:QMessageBox.warning(self,'Cannot add game',str(exc))
    def edit_game(self):
        game=self.library.get(self.selected) if self.selected else None
        if not game:return
        d=GameDialog(game,self)
        if d.exec():
            try:self.library.edit(game['id'],**d.game_data());self.refresh()
            except Exception as exc:QMessageBox.warning(self,'Edit failed',str(exc))
    def edit_ps3_settings(self):
        # Both Desktop and Big Picture use the SAME library record and launch field.
        identifier=self.selected
        if self.root.currentWidget()==self.big and self.big_games:
            identifier=self.big_games[self.big_index]['id']
        game=self.library.get(identifier) if identifier else None
        if not game or game['platform']!='ps3':
            return
        executable=self.settings.values['emulators'].get('rpcs3','rpcs3.exe')
        dialog=PS3GameSettingsDialog(game,str(executable_path(executable)),self,
                                      fullscreen=self.root.currentWidget()==self.big)
        if dialog.exec():
            self.library.edit(identifier,ps3_args=dialog.ps3_args())
            self.update_game_in_views(identifier)
            self.statusBar().showMessage('Saved PS3 launch arguments for '+game['title'],5000)
            if self.root.currentWidget()==self.big:self.focus_big()

    def current_game_for_action(self):
        identifier=self.selected
        if self.root.currentWidget()==self.big and self.big_games:
            identifier=self.big_games[self.big_index]['id']
        return self.library.get(identifier) if identifier else None

    def merge_multi_discs(self):
        try:
            merged=self.library.auto_merge_discs()
            self.refresh()
            if merged:
                QMessageBox.information(self,'Multi-disc library',
                    f'Merged {len(merged)} game sets into single entries.\n\n'
                    'All original disc image files are untouched; favourites and playtime were preserved.')
            else:
                QMessageBox.information(self,'Multi-disc library',
                    'No unambiguous numbered disc sets found. Use Manage Discs to add discs manually.')
        except Exception as exc:
            QMessageBox.warning(self,'Merge failed',str(exc))

    def manage_discs(self):
        game=self.current_game_for_action()
        if not game or game['platform'] not in DISC_PLATFORMS:return
        if game['id'] in self.sessions:
            QMessageBox.information(self,'Game running','Close the emulator before editing the disc list.')
            return
        dialog=DiscManagerDialog(game,self)
        if dialog.exec():
            try:
                self.library.set_discs(game['id'],dialog.all_paths())
                self.refresh()
            except Exception as exc:QMessageBox.warning(self,'Cannot save discs',str(exc))

    def switch_disc(self):
        game=self.current_game_for_action()
        if not game or game.get('disc_count',1)<2:return
        number=next_disc_number(game['discs'],int(game['selected_disc']))
        next_image=next(d['path'] for d in game['discs'] if d['disc_number']==number)
        if not Path(next_image).is_file():
            QMessageBox.warning(self,'Missing disc',f'Disc {number} is missing:\n{next_image}')
            return
        running=game['id'] in self.sessions
        if not running:
            self.library.choose_disc(game['id'],number)
            self.update_game_in_views(game['id'])
            QMessageBox.information(self,'Disc selected',
                f'Disc {number} is selected for the next launch.\n\n'
                + ('DuckStation starts the selected disc directly; Disc 1 starts the complete M3U playlist.'
                   if game['emulator']=='duckstation' else f'{BY_KEY[game["emulator"]].name} will boot the selected disc image on its next launch.'))
            return
        if game['emulator']=='duckstation':
            if game['id'] not in self.session_disc_playlist:
                QMessageBox.warning(self,'Playlist needed',
                    'Live Next Disc works when DuckStation was launched from the M3U playlist (start on Disc 1).\n'
                    'This session was started from a single disc. Use DuckStation’s own Change Disc → From File menu.')
                return
            if not self.settings.values.get('duckstation_f8_configured',False):
                reply=QMessageBox.question(self,'Configure DuckStation once',
                    'In DuckStation, assign the F8 key to Settings → Hotkeys → Switch to Next Disc.\n\n'
                    'After configuring that hotkey, click Yes to send F8 to the running emulator.\n'
                    'This requires the game to have launched through its multi-disc M3U playlist.',
                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if reply!=QMessageBox.StandardButton.Yes:return
                self.settings.values['duckstation_f8_configured']=True
                self.settings.save()
            proc=self.sessions[game['id']][0]
            monitor=self.session_monitors.get(game['id'])
            pids={proc.pid}
            if monitor:
                pids.update(monitor.process_ids())
            sent,message=send_duckstation_next_disc(pids)
            if sent:
                self.library.choose_disc(game['id'],number)
                self.update_game_in_views(game['id'])
                self.statusBar().showMessage(message,6000)
            else:
                QMessageBox.warning(self,'Disc hotkey not sent',message)
        else:
            # No verified GameShelf live-swap interface for these emulators.
            # Keep the emulator and gameplay running; never silently restart.
            instructions={
                'pcsx2': 'In PCSX2 open System → Change Disc → ISO Selector, choose the image, and resume the game.',
                'flycast': 'In standalone Flycast, use the emulator’s quick menu/disc controls to change the loaded disc. Flycast’s RetroArch-core M3U integration does not apply to this bundled standalone build.',
                'xenia': 'Xenia cannot load M3U playlists. Some Xbox 360 games handle disc transitions internally. If your build supports opening the next image while the game is active, change it there. Otherwise save in-game, close Xenia, select the disc in GameShelf, and start it again.',
            }
            QApplication.clipboard().setText(next_image)
            reply=QMessageBox.question(self, f'{BY_KEY[game["emulator"]].name}: Change Disc',
                f'Disc {number} image path copied to clipboard:\n{next_image}\n\n'
                + instructions.get(game['emulator'], 'Use the emulator’s native disc-change controls where available.')
                + '\n\nClick Yes only if you successfully changed discs in the emulator. '
                + 'No keeps GameShelf’s current disc selection unchanged.',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply==QMessageBox.StandardButton.Yes:
                self.library.choose_disc(game['id'], number)
                self.update_game_in_views(game['id'])

    def remove_game(self):
        game=self.library.get(self.selected) if self.selected else None
        if not game:return
        if QMessageBox.question(self,'Remove game?',f'Remove {game["title"]} from this library?\n\nThe game files will NOT be deleted.')==QMessageBox.StandardButton.Yes:
            self.library.remove(game['id']);self.selected=None;self.refresh()
    def cover_saved(self, game_id, path):
        # All database changes happen on the UI thread. Cover workers do not use SQLite.
        if self.library.get(game_id):
            self.library.edit(game_id, artwork=path)
            self.update_game_in_views(game_id,cover_changed=True)
            self.statusBar().showMessage('Game cover saved.', 5000)

    def find_cover(self):
        game = self.library.get(self.selected) if self.selected else None
        if not game:
            QMessageBox.information(self, 'No game selected', 'Select a game before searching for its cover.')
            return
        from cover_ui import CoverBrowser
        dialog = CoverBrowser(game, self.cover_saved, self)
        dialog.exec()

    def download_missing_covers(self):
        from cover_ui import BulkCoverDialog
        dialog = BulkCoverDialog(self.library, self.cover_saved, self)
        dialog.exec()

    def change_cover(self):
        game=self.library.get(self.selected) if self.selected else None
        if not game:return
        path,_=QFileDialog.getOpenFileName(self,'Choose cover art',str(BASE),'Pictures (*.png *.jpg *.jpeg *.webp *.bmp)')
        if path:
            target=DATA/'covers'/f'{game["id"]}{Path(path).suffix.lower()}'
            target.parent.mkdir(parents=True,exist_ok=True)
            try:shutil.copy2(path,target);self.library.edit(game['id'],artwork=str(target));self.update_game_in_views(game['id'],cover_changed=True)
            except Exception as exc:QMessageBox.warning(self,'Cover import failed',str(exc))
    def favorite_id(self,identifier):
        game=self.library.get(identifier)
        if game:
            self.library.edit(identifier,favorite=0 if game['favorite'] else 1)
            if self.filter=='favorites':self.refresh()
            else:self.update_game_in_views(identifier)
            if self.root.currentWidget()==self.big:self.focus_big()
    def toggle_favorite(self):
        if self.selected:self.favorite_id(self.selected)
    def prepare_selected_windurango(self):
        game=self.library.get(self.selected) if self.selected else None
        if not game or game['emulator']!='windurango':return
        configured=self.settings.values.get('emulators',{}).get('windurango')
        marker=executable_path(configured) if configured else BASE/'Emulators'/'WinDurango'/'WinDurango.Common.dll'
        prepare_windurango_game(game['path'],str(marker),self)

    def diagnose_selected_windurango(self):
        game=self.library.get(self.selected) if self.selected else None
        if not game or game['emulator']!='windurango':return
        configured=self.settings.values.get('emulators',{}).get('windurango')
        marker=executable_path(configured) if configured else BASE/'Emulators'/'WinDurango'/'WinDurango.Common.dll'
        try:
            report=create_diagnostic_report(game['path'],str(marker))
        except Exception as exc:
            report='WinDurango diagnosis failed: '+str(exc)
        message=QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Information)
        message.setWindowTitle('WinDurango launch diagnostics')
        message.setText('Read-only preparation and Windows registration check complete.\n'
                        'This is a diagnostic, not proof that the game is compatible.')
        message.setDetailedText(report)
        save=message.addButton('Save report…',QMessageBox.ButtonRole.ActionRole)
        message.addButton('Close',QMessageBox.ButtonRole.AcceptRole)
        message.exec()
        if message.clickedButton()==save:
            path,_=QFileDialog.getSaveFileName(self,'Save WinDurango diagnostic',
                         'WinDurango_Diagnostic.txt','Text files (*.txt)')
            if path:
                try:Path(path).write_text(report,encoding='utf-8')
                except OSError as exc:QMessageBox.warning(self,'Save failed',str(exc))

    def play_selected(self):
        if self.selected:self.launch_selected(self.selected)
    def launch_selected(self,identifier):
        game=self.library.get(identifier)
        if game is None:return
        if identifier in self.sessions:
            QMessageBox.information(self,'Already running','This game is already running.');return
        executable=self.settings.values['emulators'].get(game['emulator'],'')
        if not executable or not executable_path(executable).is_file():
            QMessageBox.warning(self,'Emulator not configured',f'Choose the location of {BY_KEY[game["emulator"]].name} first.')
            self.manage_emulators();return
        try:
            # The PLAY action always starts the selected game. Never substitute Kyty's GUI,
            # including when upgrading a v0.5/v0.6 library with a saved native preference.
            # Keep stdout/stderr inherited just as in the known-working v0.4 launch path.
            boot_path=game['path']
            if game.get('disc_count',1)>1:
                numbered=game['discs']
                selected=int(game.get('selected_disc',1))
                selected_path=next((d['path'] for d in numbered if d['disc_number']==selected),None)
                if selected_path is None:raise ValueError('Selected disc is missing from this game')
                if game['emulator']=='duckstation' and selected==1:
                    boot_path=str(write_duckstation_playlist(identifier,
                        [d['path'] for d in numbered],DATA/'playlists'))
                else:
                    boot_path=selected_path
            if game['platform']=='ps3' and game['emulator']=='rpcs3':
                proc=launch(str(executable_path(executable)),game['emulator'],game['path'],
                            self.root.currentWidget()==self.big,kyty_mode='direct',
                            ps3_args=game.get('ps3_args',''))
            else:
                proc=launch(str(executable_path(executable)),game['emulator'],boot_path,
                            self.root.currentWidget()==self.big,kyty_mode='direct')
            self.sessions[identifier]=(proc,time.monotonic(),True,None)
            if Path(boot_path).suffix.lower()=='.m3u' and game['emulator']=='duckstation':
                self.session_disc_playlist.add(identifier)
            self.session_monitors[identifier]=EmulatorProcessMonitor(proc)
            self._game_input_paused=True
            for shortcut in self.big_shortcuts:shortcut.setEnabled(False)
            if self.root.currentWidget()==self.big:self.update_gamepad_footer()
            if game['emulator']=='windurango':
                self.statusBar().showMessage(f'Windows accepted AppX activation for {game["title"]}; gameplay not yet verified')
            else:
                self.statusBar().showMessage(f'Started {game["title"]} through {BY_KEY[game["emulator"]].name} (startup not verified)')
        except Exception as exc:
            if game['emulator']=='windurango' and isinstance(exc,ValueError) and 'not installed into this game folder' in str(exc):
                answer=QMessageBox.question(self,'WinDurango setup required',
                    'The WinDurango DLLs are not installed beside this game executable.\n\n'
                    'Would you like to prepare this game using GameShelf’s bundled WinDurango runtime? '
                    'No existing game files will be overwritten. Windows registration may still be needed.',
                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer==QMessageBox.StandardButton.Yes:
                    self.prepare_selected_windurango()
                return
            QMessageBox.critical(self,'Could not launch game',str(exc))
    def closeEvent(self,event):
        if self.scanner is not None and self.scanner.isRunning():
            if not self.scanner.wait(2000):
                QMessageBox.information(self,'Scan in progress','A game scan is still running. Close the application after it completes.')
                event.ignore();return
        if self.title_worker is not None and self.title_worker.isRunning():
            QMessageBox.information(self,'Title lookup running','A game title lookup is still running. Close after the lookup completes.')
            event.ignore();return
        # Do not kill the user's emulators. Record accrued session time instead.
        for identifier,(proc,start,track,log_path) in self.sessions.items():
            if track:self.library.add_playtime(identifier,int(max(0,time.monotonic()-start)))
        self.remember_desktop_window()
        self.settings.save();self.library.close();super().closeEvent(event)


def main():
    # Windows taskbar identity must be set BEFORE QApplication exists.
    register_windows_app_id()
    app=QApplication(sys.argv)
    app.setApplicationName('GameShelf')
    app.setWindowIcon(load_icon())
    app.setStyle('Fusion')
    w=Main()
    # Desktop starts by default; Big Picture requires explicit opt-in
    # through the startup setting or opening it manually with F11.
    if w.settings.values.get('startup_mode','desktop')=='big':w.enter_big()
    else:w.open_desktop()
    sys.exit(app.exec())

if __name__=='__main__':main()

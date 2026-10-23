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
    from PySide6.QtGui import QPainter, QPixmap, QColor, QFont, QBrush, QPen, QLinearGradient, QKeySequence, QShortcut
    from PySide6.QtWidgets import (
        QApplication,QMainWindow,QWidget,QFrame,QLabel,QPushButton,QLineEdit,
        QVBoxLayout,QHBoxLayout,QGridLayout,QScrollArea,QListWidget,QListWidgetItem,
        QFileDialog,QDialog,QDialogButtonBox,QFormLayout,QComboBox,QMessageBox,
        QStackedWidget,QSplitter,QSizePolicy,QInputDialog,QMenu,QAbstractItemView,QPlainTextEdit
    )
except ImportError:
    print('PySide6 is required. On Windows, run INSTALL_AND_RUN.bat',file=sys.stderr)
    raise

from cover_geometry import poster_fill_rect
from version_info import APP_VERSION
from controller_input import Controller, UP, DOWN, LEFT, RIGHT, A, B, X, Y, LB, RB, START, BACK
from emulator_lifecycle import EmulatorProcessMonitor
from window_geometry import safe_desktop_rect
from library_view import make_game_view
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
        p.fillRect(self.rect(), QColor('#1c2635'))
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
            p.setPen(QColor('#b6dfff'))
            font=QFont('Segoe UI',11);font.setBold(True);p.setFont(font)
            p.drawText(self.rect().adjusted(14,12,-10,-20),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop,PLATFORMS.get(self.game['platform'],'GAME').upper())
            p.setPen(QColor('#f6fbff'))
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
        sc=QScrollArea();sc.setWidgetResizable(True);outer.addWidget(sc)
        body=QWidget();sc.setWidget(body);lay=QVBoxLayout(body)
        for e in EMULATORS:
            row=QHBoxLayout();lay.addLayout(row)
            n=label(e.name+('  · experimental' if e.status!='supported' else ''));n.setFixedWidth(180);row.addWidget(n)
            edit=QLineEdit(self.settings.values['emulators'].get(e.key,''));edit.setPlaceholderText(e.executable)
            row.addWidget(edit,1);self.edits[e.key]=edit
            row.addWidget(click('Browse…',lambda checked=False,key=e.key:self.browse(key)))
            row.addWidget(click('Open',lambda checked=False,key=e.key:self.open_gui(key)))
        outer.addWidget(label('Kyty PS5 launching','section'))
        outer.addWidget(label('PLAY launches the selected game directly through kyty_emulator.exe, as in GameShelf v0.4. To open Kyty’s library manually, use the Open button above.','muted',True))
        outer.addWidget(label('The frontend will not alter emulator firmware, system settings, save files or game data.','muted',True))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);outer.addWidget(buttons)
    def browse(self,key):
        chosen,_=QFileDialog.getOpenFileName(self,'Choose emulator executable',str(BASE),'Executable (*.exe);;All files (*)')
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
        self.settings.save();self.accept()


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
        form.addRow(label('Vita3K uses installed title IDs. PS1: CUE/CHD; PS2: ISO/CHD; PSP: ISO/CSO. PS3/PS5 game folders are supported.','muted',True))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate);buttons.rejected.connect(self.reject);form.addRow(buttons)
        self.platform.currentIndexChanged.connect(self.suggest_emulator)
        if existing:
            idx=self.platform.findData(existing['platform']);self.platform.setCurrentIndex(idx)
            idx=self.emulator.findData(existing['emulator']);self.emulator.setCurrentIndex(idx)
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


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'GameShelf v{APP_VERSION} · Your Games, One Library');self.resize(1500,920)
        self.setMinimumSize(900,600)
        self.settings=Settings();self.library=Library();self.controller=Controller()
        self.selected=None;self.filter='all';self.search='';self.big_index=0;self.big_games=[]
        self.sessions={};self.session_monitors={};self._game_input_paused=False;self.scanner=None;self.title_worker=None;self.title_scan_again=False;self.title_changed=0
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
        self.update_summary()
        self.migrate_legacy_platforms()
        QTimer.singleShot(1200,self.resolve_title_ids)

    def make_desktop(self):
        w=QWidget();w.setObjectName('desktop');outer=QHBoxLayout(w);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        side=QFrame();side.setObjectName('sidebar');side.setFixedWidth(248);outer.addWidget(side)
        sl=QVBoxLayout(side);sl.setContentsMargins(16,28,13,20);sl.setSpacing(13)
        sl.addWidget(label('◈  GameShelf','brand'))
        sl.addWidget(label('YOUR UNIFIED GAME LIBRARY','muted'))
        sl.addSpacing(14)
        self.nav=QListWidget()
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        self.ps3_settings_btn=click('⚙  PS3 Game Settings…',self.edit_ps3_settings)
        self.ps3_settings_btn.setToolTip('Set RPCS3 command-line arguments for this particular game')
        dl.addWidget(self.ps3_settings_btn)
        self.edit_btn=click('Edit Game…',self.edit_game)
        self.remove_btn=click('Remove from Library',self.remove_game)
        dl.addWidget(self.find_cover_btn)
        dl.addWidget(self.cover_btn)
        dl.addWidget(self.edit_btn)
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
        bar.addWidget(label('◈  GameShelf','bigTitle'));bar.addStretch(1)
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
        self.big_ps3_settings_btn=click('⚙ PS3 Settings',self.edit_ps3_settings)
        self.big_ps3_settings_btn.setVisible(False)
        bar.addWidget(self.big_ps3_settings_btn)
        bar.addWidget(click('Desktop  ·  F11',self.leave_big))
        self.big_sub=label('SELECT A GAME  ·  PRESS A TO PLAY','muted');lay.addWidget(self.big_sub)
        self.bigscroll,self.big_model=make_game_view(large=True)
        self.bigscroll.clicked.connect(self.on_big_index)
        self.bigscroll.selectionModel().currentChanged.connect(self.on_big_current)
        lay.addWidget(self.bigscroll,1)
        self.big_footer=label('', 'muted',True)
        self.update_gamepad_footer()
        self.big_footer.setStyleSheet('font-size: 15px; color:#becbe0; padding:12px; background:#172131; border-radius:12px;')
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
            return
        for btn in (self.play_btn,self.fav_btn,self.find_cover_btn,self.cover_btn,self.edit_btn,self.remove_btn):
            btn.setEnabled(True)
        self.ps3_settings_btn.setVisible(game['platform']=='ps3')
        self.big_ps3_settings_btn.setVisible(game['platform']=='ps3')
        self.details_title.setText(game['title'])
        self.details_info.setText(f"{PLATFORMS[game['platform']]}  ·  {BY_KEY[game['emulator']].name}\nPlaytime: {game['seconds_played']//3600}h {(game['seconds_played']%3600)//60}m")
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
        self.refresh()
        self.resolve_title_ids()
        QMessageBox.information(self,'Import complete',f'Scanned {len(games)} entries and added {count} new games.\n\nDuplicate game paths were skipped.')
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
            if game['platform']=='ps3' and game['emulator']=='rpcs3':
                proc=launch(str(executable_path(executable)),game['emulator'],game['path'],
                            self.root.currentWidget()==self.big,kyty_mode='direct',
                            ps3_args=game.get('ps3_args',''))
            else:
                proc=launch(str(executable_path(executable)),game['emulator'],game['path'],
                            self.root.currentWidget()==self.big,kyty_mode='direct')
            self.sessions[identifier]=(proc,time.monotonic(),True,None)
            self.session_monitors[identifier]=EmulatorProcessMonitor(proc)
            self._game_input_paused=True
            for shortcut in self.big_shortcuts:shortcut.setEnabled(False)
            if self.root.currentWidget()==self.big:self.update_gamepad_footer()
            self.statusBar().showMessage(f'Launched {game["title"]} through {BY_KEY[game["emulator"]].name}')
        except Exception as exc:QMessageBox.critical(self,'Could not launch game',str(exc))
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
    app=QApplication(sys.argv)
    app.setApplicationName('GameShelf')
    app.setStyle('Fusion');app.setStyleSheet(STYLE)
    w=Main()
    # Desktop starts by default; Big Picture requires explicit opt-in
    # through the startup setting or opening it manually with F11.
    if w.settings.values.get('startup_mode','desktop')=='big':w.enter_big()
    else:w.open_desktop()
    sys.exit(app.exec())

if __name__=='__main__':main()

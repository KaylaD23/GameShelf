"""GameShelf cover finder dialogs. All HTTP/image decoding work stays off the UI thread."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QWidget,
    QLabel, QPushButton, QToolButton, QLineEdit, QComboBox, QCheckBox, QMessageBox,
    QDialogButtonBox, QProgressBar
)

from cover_downloader import (
    find_covers, preview_bytes, save_cover, best_bulk_match, CoverError, test_steamgriddb_key
)
from core import DATA
from api_key_store import KeyStoreError, load_api_key, save_api_key, forget_api_key


def new_label(text, wrap=False):
    widget = QLabel(text)
    widget.setWordWrap(wrap)
    return widget


class SearchWorker(QThread):
    found = Signal(object)
    thumb = Signal(int, bytes)
    problem = Signal(str)

    def __init__(self, title, provider, key, parent=None):
        super().__init__(parent)
        self.title, self.provider, self.key = title, provider, key

    def run(self):
        try:
            results = find_covers(self.title, self.provider, self.key)
            if self.isInterruptionRequested():
                return
            self.found.emit(results)
            for index, candidate in enumerate(results):
                if self.isInterruptionRequested():
                    return
                try:
                    data = preview_bytes(candidate)
                except (CoverError, OSError):
                    continue
                if not self.isInterruptionRequested():
                    self.thumb.emit(index, data)
        except CoverError as exc:
            self.problem.emit(str(exc))
        except Exception as exc:
            self.problem.emit(f'Cover search failed ({type(exc).__name__}).')


class KeyTestWorker(QThread):
    success = Signal()
    problem = Signal(str)

    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.key = key

    def run(self):
        try:
            test_steamgriddb_key(self.key)
            self.success.emit()
        except CoverError as exc:
            self.problem.emit(str(exc))
        except Exception as exc:
            self.problem.emit(f'API key test failed ({type(exc).__name__}).')


class SaveWorker(QThread):
    saved = Signal(str)
    problem = Signal(str)

    def __init__(self, candidate, game_id, parent=None):
        super().__init__(parent)
        self.candidate, self.game_id = candidate, game_id

    def run(self):
        try:
            path = save_cover(self.candidate, self.game_id, DATA / 'covers')
            self.saved.emit(str(path))
        except CoverError as exc:
            self.problem.emit(str(exc))
        except Exception as exc:
            self.problem.emit(f'Saving the cover failed ({type(exc).__name__}).')


def initial_api_key() -> str:
    try:
        return load_api_key()
    except KeyStoreError:
        # Never crash the cover browser because the OS vault is locked.
        return os.environ.get('STEAMGRIDDB_API_KEY', '')


def store_field_key(field: QLineEdit, status: QLabel) -> str | None:
    """User explicitly saved the key or started a SteamGridDB operation."""
    try:
        token = save_api_key(field.text())
    except (KeyStoreError, CoverError) as exc:
        status.setText(str(exc))
        return None
    field.setText(token)
    status.setText('SteamGridDB API key saved securely for future sessions.')
    return token


def forget_field_key(field: QLineEdit, status: QLabel) -> None:
    try:
        forget_api_key()
    except KeyStoreError as exc:
        status.setText(str(exc))
        return
    field.clear()
    status.setText('Saved SteamGridDB key removed from this computer.')


class CoverBrowser(QDialog):
    """Preview artwork, explicitly choose one image, then download it."""

    def __init__(self, game, on_saved, parent=None):
        super().__init__(parent)
        self.game, self.on_saved = game, on_saved
        self.candidates = []
        self.selected = None
        self.tiles = []
        self.search_worker = None
        self.save_worker = None
        self.key_test_worker = None
        self._closing = False
        self._pending_success = False
        self.setWindowTitle(f'Find Cover Art — {game["title"]}')
        self.resize(885, 685)
        root = QVBoxLayout(self)
        root.addWidget(new_label('FIND COVER ART'))
        root.addWidget(new_label('Search for a game and click the cover you want. Existing covers are unchanged until you choose Download.', True))

        search = QHBoxLayout()
        root.addLayout(search)
        self.title = QLineEdit(game['title'])
        self.title.setPlaceholderText('Search game title')
        self.title.returnPressed.connect(self.search)
        search.addWidget(self.title, 2)
        self.provider = QComboBox()
        self.provider.addItems(['Wikipedia', 'SteamGridDB'])
        self.provider.currentTextChanged.connect(self.switch_provider)
        search.addWidget(self.provider)
        self.search_btn = QPushButton('Search Covers')
        self.search_btn.clicked.connect(self.search)
        search.addWidget(self.search_btn)

        key_row = QHBoxLayout()
        root.addLayout(key_row)
        self.key_label = new_label('SteamGridDB API key (only needed for SteamGridDB):')
        self.key_input = QLineEdit(initial_api_key())
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText('Enter once, saved securely on this computer')
        key_row.addWidget(self.key_label)
        key_row.addWidget(self.key_input, 1)
        self.key_test_btn = QPushButton('Test Key')
        self.key_test_btn.clicked.connect(self.test_key)
        key_row.addWidget(self.key_test_btn)
        self.key_save_btn = QPushButton('Save Key')
        self.key_save_btn.clicked.connect(lambda: store_field_key(self.key_input, self.status))
        key_row.addWidget(self.key_save_btn)
        self.key_forget_btn = QPushButton('Forget Key')
        self.key_forget_btn.clicked.connect(lambda: forget_field_key(self.key_input, self.status))
        key_row.addWidget(self.key_forget_btn)
        self.key_label.hide()
        self.key_input.hide()
        self.key_test_btn.hide()
        self.key_save_btn.hide()
        self.key_forget_btn.hide()
        self.status = new_label('Wikipedia is available without an API key. SteamGridDB offers portrait-style game covers.', True)
        root.addWidget(self.status)
        if self.key_input.text().strip():
            self.provider.setCurrentText('SteamGridDB')

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        root.addWidget(sc, 1)
        content = QWidget()
        sc.setWidget(content)
        self.grid = QGridLayout(content)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid.setSpacing(12)

        buttons = QHBoxLayout()
        root.addLayout(buttons)
        self.selection_label = new_label('No artwork selected')
        buttons.addWidget(self.selection_label, 1)
        self.download_btn = QPushButton('Download Selected Cover')
        self.download_btn.setObjectName('accent')
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self.download)
        buttons.addWidget(self.download_btn)
        self.close_btn = QPushButton('Close')
        self.close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.close_btn)
        self.search()

    def switch_provider(self):
        uses_key = self.provider.currentText() == 'SteamGridDB'
        self.key_label.setVisible(uses_key)
        self.key_input.setVisible(uses_key)
        self.key_test_btn.setVisible(uses_key)
        self.key_save_btn.setVisible(uses_key)
        self.key_forget_btn.setVisible(uses_key)

    def test_key(self):
        if self.busy():
            return
        token = store_field_key(self.key_input, self.status)
        if token is None:
            return
        self.key_test_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        self.status.setText('Testing SteamGridDB API access...')
        worker = KeyTestWorker(token, self)
        self.key_test_worker = worker
        worker.success.connect(lambda: self.status.setText('SteamGridDB accepted the API key and returned a successful response.'))
        worker.problem.connect(self.search_failed)
        worker.finished.connect(lambda: self.key_test_btn.setEnabled(True))
        worker.finished.connect(lambda: self.search_btn.setEnabled(True))
        worker.finished.connect(self.finish_close)
        worker.start()

    def clear_tiles(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.tiles.clear()

    def search(self):
        if self.busy():
            return
        title = self.title.text().strip()
        if not title:
            self.status.setText('Enter the game title before searching.')
            return
        provider = self.provider.currentText()
        token = ''
        if provider == 'SteamGridDB':
            token = store_field_key(self.key_input, self.status)
            if token is None:
                return
        self.clear_tiles()
        self.candidates = []
        self.selected = None
        self.download_btn.setEnabled(False)
        self.selection_label.setText('No artwork selected')
        self.status.setText(f'Searching {provider} for "{title}"...')
        self.search_btn.setEnabled(False)
        worker = SearchWorker(title, provider, token, self)
        self.search_worker = worker
        worker.found.connect(self.display_results)
        worker.thumb.connect(self.show_preview)
        worker.problem.connect(self.search_failed)
        worker.finished.connect(lambda: self.search_btn.setEnabled(True))
        worker.finished.connect(self.finish_close)
        worker.start()

    def search_failed(self, error):
        self.status.setText(error)

    def display_results(self, candidates):
        self.candidates = candidates
        if not candidates:
            self.status.setText('No suitable images found. Try another title or provider.')
            return
        self.status.setText(f'{len(candidates)} candidate covers. Click to select one, then Download.')
        for index, candidate in enumerate(candidates):
            btn = QToolButton()
            btn.setText(candidate.title)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            btn.setCheckable(True)
            btn.setFixedSize(187, 245)
            btn.setIconSize(QSize(166, 194))
            btn.setToolTip(f'{candidate.provider}: {candidate.title}\nMatch confidence: {candidate.score:.0%}')
            btn.setStyleSheet('QToolButton { text-align: center; padding: 6px; } QToolButton:checked { border: 3px solid #62b7f4; background: #234b6b; }')
            btn.clicked.connect(lambda checked=False, i=index: self.choose(i))
            self.tiles.append(btn)
            self.grid.addWidget(btn, index // 4, index % 4)

    def show_preview(self, index, data):
        if index >= len(self.tiles):
            return
        pix = QPixmap()
        if pix.loadFromData(data):
            # Qt widgets and pixmaps remain exclusively on the GUI thread.
            self.tiles[index].setIcon(QIcon(pix.scaled(165, 185,
                 Qt.AspectRatioMode.KeepAspectRatio,
                 Qt.TransformationMode.SmoothTransformation)))

    def choose(self, index):
        self.selected = index
        for i, button in enumerate(self.tiles):
            button.setChecked(i == index)
        candidate = self.candidates[index]
        self.selection_label.setText(f'Selected: {candidate.title} ({candidate.provider})')
        self.download_btn.setEnabled(True)

    def download(self):
        if self.selected is None or (self.save_worker and self.save_worker.isRunning()):
            return
        self.download_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        self.status.setText('Downloading the selected cover...')
        worker = SaveWorker(self.candidates[self.selected], self.game['id'], self)
        self.save_worker = worker
        worker.saved.connect(self.saved)
        worker.problem.connect(self.save_failed)
        worker.finished.connect(self.finish_close)
        worker.start()

    def saved(self, path):
        try:
            self.on_saved(self.game['id'], path)
        except Exception as exc:
            self.status.setText(f'Cover saved, but library update failed: {exc}')
            return
        self.status.setText('Cover saved to the library.')
        self._pending_success = True
        self.finish_close()

    def save_failed(self, message):
        self.status.setText(message)
        self.download_btn.setEnabled(self.selected is not None)
        self.search_btn.setEnabled(True)

    def finish_close(self):
        if not self.busy():
            if self._pending_success:
                self.accept()
            elif self._closing:
                self.reject()

    def busy(self):
        return bool((self.search_worker and self.search_worker.isRunning()) or
                    (self.save_worker and self.save_worker.isRunning()) or
                    (self.key_test_worker and self.key_test_worker.isRunning()))

    def reject(self):
        if self.busy():
            self._closing = True
            if self.search_worker and self.search_worker.isRunning():
                self.search_worker.requestInterruption()
            if self.key_test_worker and self.key_test_worker.isRunning():
                self.key_test_worker.requestInterruption()
            self.hide()  # Worker finishes safely before the dialog is destroyed.
            return
        super().reject()

    def closeEvent(self, event):
        if self.busy():
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)


class BulkWorker(QThread):
    progress = Signal(int, str)
    cover_saved = Signal(int, str)
    complete = Signal(int, int, int, str)

    def __init__(self, games, provider, api_key, parent=None):
        super().__init__(parent)
        self.games, self.provider, self.api_key = games, provider, api_key

    def run(self):
        saved = skipped = failed = 0
        last_error = ''
        for number, game in enumerate(self.games, 1):
            if self.isInterruptionRequested():
                break
            self.progress.emit(number - 1, f'Checking {number}/{len(self.games)}: {game["title"]}')
            try:
                candidates = find_covers(game['title'], self.provider, self.api_key)
                chosen = best_bulk_match(game['title'], candidates, self.provider)
                if chosen is None:
                    skipped += 1
                else:
                    path = save_cover(chosen, game['id'], DATA / 'covers')
                    self.cover_saved.emit(game['id'], str(path))
                    saved += 1
            except Exception as exc:
                failed += 1
                last_error = str(exc) if isinstance(exc, CoverError) else type(exc).__name__
                if isinstance(exc, CoverError):
                    self.progress.emit(number, last_error)
                    break
            self.progress.emit(number, f'Processed {number}/{len(self.games)} games')
        self.complete.emit(saved, skipped, failed, last_error)


class BulkCoverDialog(QDialog):
    def __init__(self, library, on_saved, parent=None):
        super().__init__(parent)
        self.library, self.on_saved = library, on_saved
        self.worker = None
        self.setWindowTitle('Download Missing Game Covers')
        self.resize(700, 340)
        lay = QVBoxLayout(self)
        lay.addWidget(new_label('DOWNLOAD MISSING COVERS'))
        self.games = [g for g in library.all() if not g.get('artwork') or not Path(g['artwork']).is_file()]
        lay.addWidget(new_label(f'{len(self.games)} games currently have no cover. Existing artwork will never be overwritten.', True))
        row = QHBoxLayout()
        lay.addLayout(row)
        self.provider = QComboBox()
        self.provider.addItems(['Wikipedia', 'SteamGridDB'])
        row.addWidget(self.provider)
        self.key = QLineEdit(initial_api_key())
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText('Saved securely for next time')
        row.addWidget(self.key, 1)
        self.key_save_btn = QPushButton('Save Key')
        self.key_save_btn.clicked.connect(lambda: store_field_key(self.key, self.status))
        row.addWidget(self.key_save_btn)
        self.key_forget_btn = QPushButton('Forget Key')
        self.key_forget_btn.clicked.connect(lambda: forget_field_key(self.key, self.status))
        row.addWidget(self.key_forget_btn)
        self.key.setVisible(False)
        self.key_save_btn.setVisible(False)
        self.key_forget_btn.setVisible(False)
        self.provider.currentTextChanged.connect(self.switch_provider)
        lay.addWidget(new_label('Only close title matches are downloaded automatically. Ambiguous results are skipped for manual review.', True))
        self.bar = QProgressBar()
        self.bar.setRange(0, len(self.games))
        lay.addWidget(self.bar)
        self.status = new_label('Ready')
        lay.addWidget(self.status)
        if self.key.text().strip():
            self.provider.setCurrentText('SteamGridDB')
        row2 = QHBoxLayout()
        lay.addLayout(row2)
        self.start_btn = QPushButton('Download Missing')
        self.start_btn.setObjectName('accent')
        self.start_btn.setEnabled(bool(self.games))
        self.start_btn.clicked.connect(self.start)
        row2.addWidget(self.start_btn)
        self.cancel_btn = QPushButton('Close')
        self.cancel_btn.clicked.connect(self.reject)
        row2.addWidget(self.cancel_btn)

    def switch_provider(self, provider):
        for widget in (self.key, self.key_save_btn, self.key_forget_btn):
            widget.setVisible(provider == 'SteamGridDB')

    def start(self):
        if self.worker and self.worker.isRunning():
            return
        provider = self.provider.currentText()
        token = ''
        if provider == 'SteamGridDB':
            token = store_field_key(self.key, self.status)
            if token is None:
                return
        self.start_btn.setEnabled(False)
        self.cancel_btn.setText('Cancel Download')
        self.status.setText('Searching for covers...')
        worker = BulkWorker(self.games, provider, token, self)
        self.worker = worker
        worker.progress.connect(lambda n, msg: (self.bar.setValue(n), self.status.setText(msg)))
        worker.cover_saved.connect(self.on_saved)
        worker.complete.connect(self.finished_batch)
        worker.start()

    def finished_batch(self, saved, skipped, failed, error):
        self.bar.setValue(self.bar.maximum())
        self.status.setText(f'Downloaded {saved}; skipped {skipped}; failed {failed}.' +
                            (f' Last error: {error}' if error else ''))
        self.cancel_btn.setText('Close')
        self.start_btn.setText('Finished')

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.status.setText('Cancelling after the current request...')
            self.cancel_btn.setEnabled(False)
            # Do not destroy a running QThread.
            self.worker.finished.connect(super().reject)
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)

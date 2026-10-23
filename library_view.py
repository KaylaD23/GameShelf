"""Fast, virtualized, cover-art game library for GameShelf.

QListView + delegates only paint items in the viewport. Never allocate a tile
widget per game or decode full-size artwork just to render a thumbnail.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, QSize, QRect, QRectF
from PySide6.QtGui import QColor, QFont, QImageReader, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPixmapCache
from PySide6.QtWidgets import QListView, QStyledItemDelegate, QStyle

from cover_geometry import poster_fill_rect
from core import PLATFORMS

DESKTOP_GRID = QSize(205, 354)
BIG_GRID = QSize(238, 404)


class GameModel(QAbstractListModel):
    """A light view on game records; resetting it never creates 700 widgets."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.games = []
        self.positions = {}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.games)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.games):
            return None
        game = self.games[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return game['title']
        if role == Qt.ItemDataRole.UserRole:
            return game
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{game['title']}\n{PLATFORMS.get(game['platform'], game['platform'])}"
        return None

    def set_games(self, games):
        self.beginResetModel()
        self.games = list(games)
        self.positions = {game['id']: row for row, game in enumerate(self.games)}
        self.endResetModel()

    def row_for(self, identifier):
        return self.positions.get(identifier, -1)

    def update_game(self, game):
        row = self.row_for(game['id'])
        if row < 0:
            return False
        self.games[row] = game
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.UserRole])
        return True


def text_lines(text, metrics, limit, max_lines=3):
    """Wrap labels without creating QLabel widgets for every title."""
    result=[]
    current=''
    words=text.split()
    for i, word in enumerate(words):
        candidate=(current+' '+word).strip()
        if metrics.horizontalAdvance(candidate)<=limit:
            current=candidate
        else:
            if current:
                result.append(current)
                current=word
            else:
                result.append(metrics.elidedText(word, Qt.TextElideMode.ElideRight, limit))
                current=''
            if len(result) == max_lines-1:
                remaining=' '.join(([current] if current else []) + words[i+1:])
                result.append(metrics.elidedText(remaining, Qt.TextElideMode.ElideRight, limit))
                return result
    if current:
        result.append(metrics.elidedText(current, Qt.TextElideMode.ElideRight, limit))
    return result[:max_lines]


class CoverCache:
    """Bounded, scaled pixmap cache. Preserves EXIF orientation and file updates."""
    def __init__(self):
        QPixmapCache.setCacheLimit(max(QPixmapCache.cacheLimit(), 96 * 1024))
        self.failed = set()

    def get(self, path: str, width: int, height: int):
        """Return a poster-sized pixmap containing ALL image pixels, no bars.

        Decode at thumbnail resolution, then guarantee the output pixmap exactly
        matches the poster rectangle. A cover with a different aspect ratio is
        slightly rescaled rather than cropped or letterboxed. These trade-offs
        are intentional: the user prefers a full poster without losing artwork.
        """
        if not path or width <= 0 or height <= 0:
            return None
        try:
            stat=os.stat(path)
        except OSError:
            return None
        # Bump this revision whenever image rendering changes so Qt's global
        # pixmap cache cannot retain the old letterboxed v0.9.9 thumbnails.
        key=f'gameshelf::edge-to-edge-v0910::{path}::{stat.st_mtime_ns}:{stat.st_size}::{width}x{height}'
        pix=QPixmapCache.find(key)
        if pix is not None and not pix.isNull():
            return pix
        if key in self.failed:
            return None
        reader=QImageReader(path)
        reader.setAutoTransform(True)
        reader.setScaledSize(QSize(width,height))
        image=reader.read()
        if image.isNull():
            self.failed.add(key)
            return None
        pix=QPixmap.fromImage(image)
        # Some image plugins / rotated EXIF sources do not honour requested
        # scaling perfectly; explicitly enforce exact pixel dimensions.
        if pix.size()!=QSize(width,height):
            pix=pix.scaled(width,height,Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        QPixmapCache.insert(key,pix)
        return pix


class GameDelegate(QStyledItemDelegate):
    """Draws a card for a visible row without allocating QWidget children."""
    def __init__(self, large=False, parent=None):
        super().__init__(parent)
        self.large=large
        self.grid=BIG_GRID if large else DESKTOP_GRID
        self.covers=CoverCache()

    def sizeHint(self, option, index):
        return self.grid

    def paint(self, painter, option, index):
        game=index.data(Qt.ItemDataRole.UserRole)
        if not game:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        cell=option.rect
        r=cell.adjusted(5,5,-5,-5)
        selected=bool(option.state & QStyle.StateFlag.State_Selected)
        hovered=bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setPen(QPen(QColor('#ffe99e' if selected else '#5b8aac' if hovered else '#283a4e'), 3 if selected else 2))
        painter.setBrush(QColor('#243449' if hovered else '#1c2635'))
        painter.drawRoundedRect(QRectF(r),12,12)

        pw,ph=(205,277) if self.large else (173,235)
        poster=QRect(r.x()+(r.width()-pw)//2,r.y()+7,pw,ph)
        pix=self.covers.get(game.get('artwork',''), pw,ph)
        if pix:
            # Entire decoded image maps to the entire rectangle. Qt never
            # receives a cropped source rectangle or a smaller destination.
            painter.drawPixmap(poster,pix,pix.rect())
        else:
            gradient=QLinearGradient(poster.topLeft(),poster.bottomRight())
            palette=[('#12364a','#162137'),('#46304a','#1b243a'),('#31524b','#15283b'),('#3c374f','#17263a')]
            a,b=palette[sum(map(ord,game['title']))%len(palette)]
            gradient.setColorAt(0,QColor(a));gradient.setColorAt(1,QColor(b))
            painter.fillRect(poster,gradient)
            painter.setPen(QColor('#b6dfff'))
            f=QFont('Segoe UI',10,QFont.Weight.Bold);painter.setFont(f)
            painter.drawText(poster.adjusted(10,8,-8,-8),Qt.AlignmentFlag.AlignTop|Qt.TextFlag.TextWordWrap,PLATFORMS.get(game['platform'],'GAME').upper())
            painter.setPen(QColor('#f6fbff'))
            f=QFont('Segoe UI',14,QFont.Weight.Bold);painter.setFont(f)
            painter.drawText(poster.adjusted(12,50,-10,-14),Qt.AlignmentFlag.AlignBottom|Qt.TextFlag.TextWordWrap,game['title'])

        painter.setPen(QColor('#f4f6fa'))
        f=QFont('Segoe UI',14 if self.large else 12,QFont.Weight.Bold)
        painter.setFont(f)
        title_y=poster.bottom()+8
        for line in text_lines(game['title'],painter.fontMetrics(),pw-6,3):
            title_rect=QRect(poster.x()+1,title_y,pw-2,21 if self.large else 18)
            painter.drawText(title_rect,Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,line)
            title_y+=21 if self.large else 18
        f=QFont('Segoe UI',10);painter.setFont(f)
        painter.setPen(QColor('#98aec7'))
        plat=PLATFORMS.get(game['platform'],game['platform'])
        platform_text=painter.fontMetrics().elidedText(plat,Qt.TextElideMode.ElideRight,pw-2)
        painter.drawText(QRect(poster.x()+1,r.bottom()-31,pw-2,19),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,platform_text)
        painter.restore()


def make_game_view(large=False, parent=None):
    view=QListView(parent)
    view.setViewMode(QListView.ViewMode.IconMode)
    view.setFlow(QListView.Flow.LeftToRight)
    view.setWrapping(True)
    view.setResizeMode(QListView.ResizeMode.Adjust)
    view.setMovement(QListView.Movement.Static)
    view.setLayoutMode(QListView.LayoutMode.Batched)
    view.setBatchSize(80)
    view.setUniformItemSizes(True)
    view.setGridSize(BIG_GRID if large else DESKTOP_GRID)
    view.setSpacing(3)
    view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setSelectionMode(QListView.SelectionMode.SingleSelection)
    view.setMouseTracking(True)
    view.setStyleSheet('QListView { background: transparent; border: none; outline: 0; }')
    model=GameModel(view)
    view.setModel(model)
    view.setItemDelegate(GameDelegate(large,view))
    return view,model

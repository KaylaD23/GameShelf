"""GameShelf's gradient wordmark, from the approved application branding.

The image has true transparency, so it looks right in every UI theme.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel

from app_identity import resource_path


class GameShelfWordmark(QLabel):
    """Display the white/cyan/blue/purple GameShelf artwork at a UI size.

    An accessible label is kept for screen readers and as a fallback if an
    installation has lost its bundled branding asset.
    """

    def __init__(self, width: int, height: int, parent=None):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setAccessibleName("GameShelf")
        self.setToolTip("GameShelf")
        self.setObjectName("wordmark")
        artwork=QPixmap(str(resource_path("gameshelf_wordmark.png")))
        if artwork.isNull():
            self.setText("GameShelf")
        else:
            self.setPixmap(artwork.scaled(QSize(width, height),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

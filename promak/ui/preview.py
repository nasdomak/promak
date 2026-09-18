"""The before/after preview shared by the picture tools.

One square per side, a caption under each, and the two helpers that turn a
file on disk into something Qt can draw - including an SVG, which is drawn
by Qt's own vector renderer and is therefore honest proof that the result
really is made of shapes.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

log = logging.getLogger(__name__)

PREVIEW_SIDE = 250


class PreviewBox(QFrame):
    """One square of the before/after preview, with its caption."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PreviewBox")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(7)

        heading = QLabel(title)
        heading.setObjectName("PreviewTitle")
        heading.setAlignment(Qt.AlignCenter)
        layout.addWidget(heading)

        self.image = QLabel()
        self.image.setObjectName("PreviewImage")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setFixedHeight(PREVIEW_SIDE)
        self.image.setMinimumWidth(160)
        self.image.setText("nothing to show yet")
        layout.addWidget(self.image, 1)

        self.caption = QLabel("")
        self.caption.setObjectName("PreviewCaption")
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setWordWrap(True)
        self.caption.setMinimumHeight(30)
        layout.addWidget(self.caption)

    # ----------------------------------------------------------- filling
    def clear(self, message: str = "nothing to show yet") -> None:
        self.image.setPixmap(QPixmap())
        self.image.setText(message)
        self.caption.setText("")

    def set_pixmap(self, pixmap: QPixmap, caption: str = "") -> None:
        if pixmap.isNull():
            self.clear("this file cannot be shown")
            self.caption.setText(caption)
            return
        width = max(160, self.image.width() or PREVIEW_SIDE)
        self.image.setText("")
        self.image.setPixmap(
            pixmap.scaled(width, PREVIEW_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.caption.setText(caption)

    def set_file(self, path: Path, caption: str = "") -> None:
        """Show any picture file, choosing the right way to draw it."""
        path = Path(path)
        if path.suffix.lower() == ".svg":
            self.set_pixmap(render_svg(path), caption)
        else:
            self.set_pixmap(QPixmap(str(path)), caption)


class PreviewPair(QWidget):
    """The two squares side by side."""

    def __init__(self, before_title: str, after_title: str, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.before = PreviewBox(before_title)
        self.after = PreviewBox(after_title)
        layout.addWidget(self.before, 1)
        layout.addWidget(self.after, 1)

    def clear(self) -> None:
        self.before.clear()
        self.after.clear()


def render_svg(path: Path, side: int = PREVIEW_SIDE * 2) -> QPixmap:
    """Draw an SVG file into a pixmap, on a white sheet.

    Qt's SVG renderer draws shapes and nothing else, so a picture that
    appears here really is a vector file - there is no pixel image hiding
    inside it.
    """
    try:
        data = QByteArray(Path(path).read_bytes())
    except OSError as exc:
        log.debug("Preview could not read %s: %s", path, exc)
        return QPixmap()

    try:
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:  # pragma: no cover - PySide6 always ships QtSvg
        log.warning("QtSvg is not available, so SVG files cannot be previewed.")
        return QPixmap()

    renderer = QSvgRenderer(data)
    if not renderer.isValid():
        return QPixmap()

    box = renderer.defaultSize()
    width = box.width() or side
    height = box.height() or side
    ratio = min(side / float(width), side / float(height))
    target = QImage(
        max(1, int(width * ratio)),
        max(1, int(height * ratio)),
        QImage.Format_ARGB32_Premultiplied,
    )
    target.fill(QColor("white"))
    painter = QPainter(target)
    try:
        renderer.render(painter, QRectF(0, 0, target.width(), target.height()))
    finally:
        painter.end()
    return QPixmap.fromImage(target)

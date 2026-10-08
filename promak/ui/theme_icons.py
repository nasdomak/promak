"""The little sun and moon of the light/dark switch.

They are drawn here with a few lines of painting instead of being shipped
as image files: they stay sharp at any screen scale and take the colour of
the current theme.  The button shows where a click takes you - a moon in
the light theme (go dark), a sun in the dark theme (go light).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

#: drawn larger than shown, then scaled down by Qt for crisp edges
_CANVAS = 64


def _canvas() -> QPixmap:
    pixmap = QPixmap(_CANVAS, _CANVAS)
    pixmap.fill(Qt.transparent)
    return pixmap


def sun_icon(colour: str) -> QIcon:
    """A round sun with eight short rays."""
    pixmap = _canvas()
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    tint = QColor(colour)
    centre = QPointF(_CANVAS / 2, _CANVAS / 2)
    painter.setPen(Qt.NoPen)
    painter.setBrush(tint)
    painter.drawEllipse(centre, 12.5, 12.5)
    pen = QPen(tint, 5.5, Qt.SolidLine, Qt.RoundCap)
    painter.setPen(pen)
    for step in range(8):
        angle = math.radians(step * 45)
        inner, outer = 20.0, 27.0
        painter.drawLine(
            QPointF(centre.x() + inner * math.cos(angle), centre.y() + inner * math.sin(angle)),
            QPointF(centre.x() + outer * math.cos(angle), centre.y() + outer * math.sin(angle)),
        )
    painter.end()
    return QIcon(pixmap)


def moon_icon(colour: str) -> QIcon:
    """A crescent moon: a disc with a smaller disc taken out of it."""
    pixmap = _canvas()
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    disc = QPainterPath()
    disc.addEllipse(QRectF(10, 10, 44, 44))
    bite = QPainterPath()
    bite.addEllipse(QRectF(26, 2, 38, 38))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(colour))
    painter.drawPath(disc.subtracted(bite))
    painter.end()
    return QIcon(pixmap)


def switch_icon(current_theme: str, colour: str) -> QIcon:
    """The icon for the switch: where a click would take you."""
    return moon_icon(colour) if current_theme == "light" else sun_icon(colour)

import math
import os

from PySide6.QtCore import Qt, QPointF, QRectF, QSize
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from components.utils import resource_path


class PolarWidget(QWidget):
    """
    Polarization indicator (0–360° dial).

    - Minimal, safe: pure paintEvent + value setter.
    - Uses resource_path() so it's PyInstaller-friendly later.
    - Supports optional ruler overlay assets with subtle opacity in light mode.
    """

    _RULER_CANDIDATES = (
        "assets/polar_ruler.png",
        "assets/polar_ruler.webp",
        "assets/ruler_polar.png",
        "assets/ruler_polar.webp",
    )

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(QSize(150, 150))
        self._polar = 0.0

        self._ruler = QPixmap()
        for rel in self._RULER_CANDIDATES:
            abs_path = resource_path(rel)
            if os.path.exists(abs_path):
                pm = QPixmap(abs_path)
                if not pm.isNull():
                    self._ruler = pm
                    break

    def set_polar(self, polar: float):
        polar = float(polar) % 360.0
        if self._polar != polar:
            self._polar = polar
            self.update()

    def _is_light_mode(self) -> bool:
        bg = self.palette().color(self.backgroundRole())
        return bg.value() >= 160

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w = self.width()
        h = self.height()
        side = min(w, h)

        center = QPointF(w / 2, h / 2)
        radius = (side / 2) * 0.90

        is_light = self._is_light_mode()

        ring_pen = QPen(QColor(0, 0, 0, 35) if is_light else QColor(255, 255, 255, 45), 2)
        tick_pen = QPen(QColor(0, 0, 0, 70) if is_light else QColor(255, 255, 255, 80), 1)
        text_color = QColor(0, 0, 0, 180) if is_light else QColor(255, 255, 255, 210)

        # Optional ruler overlay
        if not self._ruler.isNull():
            target = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
            painter.save()
            painter.setOpacity(0.18 if is_light else 0.30)
            painter.drawPixmap(target, self._ruler, self._ruler.rect())
            painter.restore()

        # Outer ring
        painter.setPen(ring_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(center, radius, radius)

        # Ticks
        painter.setPen(tick_pen)
        tick_outer = radius * 0.98
        tick_inner = radius * 0.90

        for deg in range(0, 360, 15):
            rad = math.radians(deg - 90)
            x1 = center.x() + tick_inner * math.cos(rad)
            y1 = center.y() + tick_inner * math.sin(rad)
            x2 = center.x() + tick_outer * math.cos(rad)
            y2 = center.y() + tick_outer * math.sin(rad)

            if deg % 90 == 0:
                painter.setPen(QPen(tick_pen.color(), 2))
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
                painter.setPen(tick_pen)
            else:
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Needle
        needle_len = radius * 0.85
        rad = math.radians(self._polar - 90)
        end = QPointF(
            center.x() + needle_len * math.cos(rad),
            center.y() + needle_len * math.sin(rad),
        )

        painter.setPen(QPen(QColor(0, 120, 255, 200) if is_light else QColor(0, 255, 160, 220), 3))
        painter.drawLine(center, end)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 160) if is_light else QColor(255, 255, 255, 200))
        painter.drawEllipse(center, 4, 4)

        # Center label/value
        painter.setPen(text_color)
        painter.setFont(QFont(self.font().family(), 9))
        painter.drawText(0, int(h * 0.55), w, 18, Qt.AlignCenter, "Polar")

        painter.setFont(QFont(self.font().family(), 10, QFont.Bold))
        painter.drawText(0, int(h * 0.65), w, 22, Qt.AlignCenter, f"{self._polar:.2f}°")

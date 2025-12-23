import math
import os
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from components.utils import resource_path


class ElevationWidget(QWidget):
    """
    Elevation / pitch indicator.

    - Uses resource_path() for robust loading (CWD + PyInstaller).
    - Supports optional ruler overlay assets with subtle opacity in light mode.
    - Supports a small status overlay label (e.g. SEARCHING/LOCKED/OFFLINE).
    """

    _RULER_CANDIDATES = (
        # existing candidates
        "assets/elevation_ruler.png",
        "assets/elevation_ruler.webp",
        "assets/ruler_elevation.png",
        "assets/ruler_elevation.webp",
        # extra forgiving candidates
        "assets/elevation_scale.png",
        "assets/elevation_scale.webp",
        "assets/elevation_ticks.png",
        "assets/elevation_ticks.webp",
        "assets/ruler.png",
        "assets/ruler.webp",
    )

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(150, 100)
        self._elevation = 0.0
        self._status_text = ""

        self._ruler = QPixmap()
        for rel in self._RULER_CANDIDATES:
            abs_path = resource_path(rel)
            if os.path.exists(abs_path):
                pm = QPixmap(abs_path)
                if not pm.isNull():
                    self._ruler = pm
                    break

    def set_elevation(self, elevation: float):
        elevation = float(elevation)
        if self._elevation != elevation:
            self._elevation = elevation
            self.update()

    def set_status(self, satellite_status: str | None):
        s = (satellite_status or "").strip().lower()
        if not s:
            text = ""
        elif "search" in s:
            text = "SEARCHING"
        elif "lock" in s:
            text = "LOCKED"
        elif "offline" in s or "fail" in s or "error" in s:
            text = "OFFLINE"
        else:
            text = ""
        if text != self._status_text:
            self._status_text = text
            self.update()

    def _is_light_mode(self) -> bool:
        bg = self.palette().color(self.backgroundRole())
        return bg.value() >= 160

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        width = self.width()
        height = self.height()

        # Layout: a semi-circle gauge
        side = min(width, height * 1.8)
        gauge_size = side * 0.85

        top_left = QPointF((width - gauge_size) / 2, (height - gauge_size / 2) / 2)
        center = QPointF(width / 2, top_left.y() + gauge_size / 2)
        radius = gauge_size / 2

        is_light = self._is_light_mode()

        arc_pen = QPen(QColor(0, 0, 0, 35) if is_light else QColor(255, 255, 255, 45), 2)
        tick_pen = QPen(QColor(0, 0, 0, 70) if is_light else QColor(255, 255, 255, 80), 1)
        text_color = QColor(0, 0, 0, 180) if is_light else QColor(255, 255, 255, 200)

        # Optional ruler overlay image
        if not self._ruler.isNull():
            target = QRectF(top_left.x(), top_left.y(), gauge_size, gauge_size)
            painter.save()
            painter.setOpacity(0.20 if is_light else 0.35)
            painter.drawPixmap(target, self._ruler, self._ruler.rect())
            painter.restore()

        # Semi-circle arc
        painter.setPen(arc_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawChord(top_left.x(), top_left.y(), gauge_size, gauge_size, 0 * 16, 180 * 16)

        # Ticks + labels
        painter.setPen(tick_pen)
        font = QFont(self.font().family(), 8)
        painter.setFont(font)

        for angle in range(0, 91, 15):
            rad = math.radians(180 - angle)
            x1 = center.x() + radius * math.cos(rad)
            y1 = center.y() - radius * math.sin(rad)

            tick_len = 10 if angle % 45 == 0 else 6
            x2 = center.x() + (radius - tick_len) * math.cos(rad)
            y2 = center.y() - (radius - tick_len) * math.sin(rad)

            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

            if angle % 45 == 0:
                painter.setPen(text_color)
                lx = center.x() + (radius + 12) * math.cos(rad)
                ly = center.y() - (radius + 12) * math.sin(rad)
                painter.drawText(int(lx - 10), int(ly - 6), 20, 12, Qt.AlignmentFlag.AlignCenter, str(angle))
                painter.setPen(tick_pen)

        # Needle
        needle_len = radius * 0.90
        elevation_rad = math.radians(180 - self._elevation)
        end_x = center.x() + needle_len * math.cos(elevation_rad)
        end_y = center.y() - needle_len * math.sin(elevation_rad)

        painter.setPen(QPen(QColor("red"), 3, Qt.PenStyle.SolidLine))
        painter.drawLine(center, QPointF(end_x, end_y))

        painter.setBrush(QColor(0, 0, 0, 190) if is_light else QColor(255, 255, 255, 200))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, 4, 4)

        # Status overlay (subtle in light mode)
        if self._status_text:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

            font2 = QFont(self.font().family(), 9)
            font2.setBold(True)
            painter.setFont(font2)

            painter.setOpacity(0.22 if is_light else 0.55)
            painter.setPen(QColor(0, 0, 0, 220) if is_light else QColor(255, 255, 255, 230))

            box = QRectF(0, height * 0.62, width, 22)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self._status_text)
            painter.restore()

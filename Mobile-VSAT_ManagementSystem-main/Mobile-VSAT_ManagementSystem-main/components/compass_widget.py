import math
import os
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import (
    QPainter,
    QPen,
    QColor,
    QFont,
    QPixmap,
)
from PySide6.QtCore import Qt, QSize, QPointF, QRectF

from components.utils import resource_path


class CompassWidget(QWidget):
    """
    Compass / azimuth indicator.

    Notes:
    - Uses resource_path() so it works regardless of CWD and is PyInstaller-friendly.
    - If optional ruler assets exist, they are drawn with subtle opacity in light mode.
    - Supports a small status overlay label (e.g. SEARCHING/LOCKED/OFFLINE).
    """

    # Optional overlay assets (safe if missing)
    _RULER_CANDIDATES = (
        # existing candidates
        "assets/compass_ruler.png",
        "assets/compass_ruler.webp",
        "assets/ruler_compass.png",
        "assets/ruler_compass.webp",
        # extra forgiving candidates (won't break anything if missing)
        "assets/compass_scale.png",
        "assets/compass_scale.webp",
        "assets/compass_ticks.png",
        "assets/compass_ticks.webp",
        "assets/ruler.png",
        "assets/ruler.webp",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle = 0.0
        self._status_text = ""  # e.g. "SEARCHING"

        self.setMinimumSize(QSize(150, 150))

        # Load assets cached on the instance.
        self._bg = QPixmap(resource_path("assets/compass_background.webp"))
        if self._bg.isNull():
            # Fallback if webp isn't supported on the deployment machine.
            self._bg = QPixmap(resource_path("assets/compass_background.png"))

        self._pointer = QPixmap(resource_path("assets/compass_pointer.png"))

        self._ruler = QPixmap()
        for rel in self._RULER_CANDIDATES:
            abs_path = resource_path(rel)
            if os.path.exists(abs_path):
                pm = QPixmap(abs_path)
                if not pm.isNull():
                    self._ruler = pm
                    break

    def set_azimuth(self, angle: float):
        self.angle = float(angle)
        self.update()

    def set_status(self, satellite_status: str | None):
        """
        Accepts the raw satellite status string (from TCP show).
        We'll convert it into a short overlay label.
        """
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
            # Keep minimal: don't spam unknown states
            text = ""
        if text != self._status_text:
            self._status_text = text
            self.update()

    def _is_light_mode(self) -> bool:
        # Heuristic: if the widget background is bright, assume light theme.
        bg = self.palette().color(self.backgroundRole())
        return bg.value() >= 160

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        side = min(self.width(), self.height())
        center = QPointF(self.width() / 2, self.height() / 2)

        outer_radius = (side / 2) * 0.95
        text_radius = (side / 2) * 0.78
        tick_outer = (side / 2) * 0.90
        tick_inner = (side / 2) * 0.86

        is_light = self._is_light_mode()

        ring_pen = QPen(QColor(0, 0, 0, 30) if is_light else QColor(255, 255, 255, 40), 2)
        tick_pen = QPen(QColor(0, 0, 0, 50) if is_light else QColor(255, 255, 255, 60), 1)

        # Draw background image if present
        if not self._bg.isNull():
            target = QRectF(
                center.x() - outer_radius,
                center.y() - outer_radius,
                outer_radius * 2,
                outer_radius * 2,
            )
            painter.save()
            painter.setOpacity(0.18 if is_light else 0.28)
            painter.drawPixmap(target, self._bg, self._bg.rect())
            painter.restore()

        # Subtle ruler overlay (optional assets)
        if not self._ruler.isNull():
            target = QRectF(
                center.x() - outer_radius,
                center.y() - outer_radius,
                outer_radius * 2,
                outer_radius * 2,
            )
            painter.save()
            painter.setOpacity(0.20 if is_light else 0.35)
            painter.drawPixmap(target, self._ruler, self._ruler.rect())
            painter.restore()

        # Outer ring
        painter.setPen(ring_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, outer_radius, outer_radius)

        # Ticks + cardinal labels
        painter.setFont(QFont(self.font().family(), 9))
        for angle in range(0, 360, 15):
            rad = math.radians(angle - 90)
            x1 = center.x() + tick_inner * math.cos(rad)
            y1 = center.y() + tick_inner * math.sin(rad)
            x2 = center.x() + tick_outer * math.cos(rad)
            y2 = center.y() + tick_outer * math.sin(rad)

            if angle % 90 == 0:
                # Longer cardinal ticks
                painter.setPen(QPen(tick_pen.color(), 2))
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

                label = {0: "N", 90: "E", 180: "S", 270: "W"}[angle]
                tx = center.x() + text_radius * math.cos(rad)
                ty = center.y() + text_radius * math.sin(rad)
                painter.setPen(QColor(0, 0, 0, 180) if is_light else QColor(255, 255, 255, 200))
                painter.drawText(
                    int(tx - 15),
                    int(ty - 15),
                    30,
                    30,
                    Qt.AlignmentFlag.AlignCenter,
                    label,
                )
            else:
                painter.setPen(tick_pen)
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Pointer
        if not self._pointer.isNull():
            pm = self._pointer
            size = outer_radius * 1.55
            target = QRectF(center.x() - size / 2, center.y() - size / 2, size, size)

            painter.save()
            painter.translate(center)
            painter.rotate(self.angle)
            painter.translate(-center)

            painter.setOpacity(0.85 if is_light else 1.0)
            painter.drawPixmap(target, pm, pm.rect())
            painter.restore()

        # Status overlay (subtle in light mode)
        if self._status_text:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

            # place near center, like a HUD label
            font = QFont(self.font().family(), 10)
            font.setBold(True)
            painter.setFont(font)

            # subtle opacity in light mode (your request)
            painter.setOpacity(0.22 if is_light else 0.55)

            # Use a neutral dark text in light mode; light text in dark mode
            painter.setPen(QColor(0, 0, 0, 220) if is_light else QColor(255, 255, 255, 230))

            box = QRectF(
                center.x() - outer_radius * 0.60,
                center.y() - 12,
                outer_radius * 1.20,
                24,
            )
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self._status_text)
            painter.restore()

# components/signal_gauge.py
from __future__ import annotations
import math
from PySide6.QtCore import Qt, QRectF, QPointF, Property
from PySide6.QtGui import QPainter, QPen, QFont, QColor, QLinearGradient, QBrush, QPolygonF
from PySide6.QtWidgets import QWidget

class GaugeWidget(QWidget):
    """
    Semicircle gauge with progress arc, tick labels, center readout, and a small pointer wedge.
    """
    def __init__(self, min_value=0.0, max_value=100.0, value=0.0, unit="", tick_labels=None, parent=None):
        super().__init__(parent)
        self._min = float(min_value)
        self._max = float(max_value)
        self._value = float(value)
        self._unit = unit
        self._ticks = list(tick_labels) if tick_labels else []
        self.setMinimumSize(220, 160)

        # Colors
        self.bg_color = QColor("#f8f9fa")
        self.arc_bg = QColor("#252f4c")
        self.arc_fg_1 = QColor("#54b7f8")
        self.arc_fg_2 = QColor("#5e779c")
        self.text_color = QColor("#000000")
        self.subtle = QColor("#8a8a92")

    # Property so you can animate later if you want
    def getValue(self) -> float:
        return self._value

    def setValue(self, v: float):
        v = max(self._min, min(self._max, float(v)))
        if v != self._value:
            self._value = v
            self.update()

    value = Property(float, fget=getValue, fset=setValue)

    def sizeHint(self):
        return self.minimumSize()

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        side = min(w, h * 1.25)
        cx, cy = w / 2.0, h * 0.9

        radius = side * 0.42
        thickness = radius * 0.18

        start_deg = 225
        span_deg = -270

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), self.bg_color)

        rect = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)

        # Track
        p.setPen(QPen(self.arc_bg, thickness, Qt.SolidLine, Qt.FlatCap))
        p.drawArc(rect, start_deg * 16, span_deg * 16)

        # Progress
        ratio = 0.0 if self._max <= self._min else (self._value - self._min) / (self._max - self._min)
        ratio = max(0.0, min(1.0, ratio))
        sweep = int(span_deg * ratio)

        # << MODIFICATION 1: Use a solid color instead of a gradient >>
        # grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        # grad.setColorAt(0.0, self.arc_fg_1)
        # grad.setColorAt(1.0, self.arc_fg_2)
        # p.setPen(QPen(QBrush(grad), thickness, Qt.SolidLine, Qt.FlatCap))
        p.setPen(QPen(self.arc_fg_1, thickness, Qt.SolidLine, Qt.FlatCap)) # Use the primary foreground color
        p.drawArc(rect, start_deg * 16, sweep * 16)

        if self._ticks:
            p.setPen(self.subtle)
            font_small = QFont(self.font())
            font_small.setPointSizeF(max(8.0, radius * 0.11))
            p.setFont(font_small)
            for t in self._ticks:
                tr = 0.0 if self._max <= self._min else (t - self._min) / (self._max - self._min)
                tr = max(0.0, min(1.0, tr))
                a = math.radians(start_deg + span_deg * tr)
                r_label = radius + thickness * 0.35
                lx = cx + r_label * -math.sin(a)
                ly = cy - r_label * math.cos(a)
                text = f"{int(t) if float(t).is_integer() else t}"
                br = p.boundingRect(0, 0, 1000, 1000, Qt.AlignCenter, text)
                br.moveCenter(QPointF(lx, ly).toPoint())
                p.drawText(br, Qt.AlignCenter, text)

        p.setPen(self.text_color)
        value_font = QFont(self.font()); value_font.setBold(True)
        value_font.setPointSizeF(max(12.0, radius * 0.22))
        p.setFont(value_font)
        value_rect = QRectF(cx - radius * 0.8, cy - radius * 0.45, radius * 1.6, radius * 0.5)
        p.drawText(value_rect, Qt.AlignCenter, f"{self._value:.2f}")

        if self._unit:
            unit_font = QFont(self.font())
            unit_font.setPointSizeF(max(9.0, radius * 0.12))
            p.setFont(unit_font)
            unit_rect = QRectF(cx - radius * 0.8, cy - radius * 0.15, radius * 1.6, radius * 0.4)
            p.setPen(self.subtle)
            p.drawText(unit_rect, Qt.AlignCenter, self._unit)

        p.end()

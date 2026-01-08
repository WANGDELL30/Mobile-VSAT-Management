# views/dashboard.py
from __future__ import annotations

from typing import Dict, Any
from datetime import datetime
from collections import deque
import time
import os

from PySide6.QtCore import (
    QObject,
    QThread,
    Signal,
    Slot,
    Qt,
    QTimer,
    QSize,
    QPropertyAnimation,
    QEasingCurve,
)
from PySide6.QtGui import QColor, QPixmap, QImageReader
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QGroupBox,
    QPushButton,
    QMessageBox,
    QGridLayout,
    QSizePolicy,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QGraphicsOpacityEffect,
    QScrollArea,
)

# ✅ IMPORTANT: do NOT import ACUClient here (prevents circular import)
# from services.acu_client import ACUClient

from components.kpi_tile import KpiTile
from components.signal_gauge import GaugeWidget
from components.compass_widget import CompassWidget
from components.elevation_widget import ElevationWidget
from components.polar_widget import PolarWidget
from components.utils import resource_path
from components.MapView import MapWorker


class InteractiveMapLabel(QLabel):
    """
    QLabel that supports mouse-drag panning (emits pan deltas).
    Keeps UI stable; actual tile rendering is done via MapWorker.
    """
    panDelta = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dragging = False
        self._last_pos = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_pos = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._dragging or self._last_pos is None:
            super().mouseMoveEvent(event)
            return
        pos = event.position().toPoint()
        dx = pos.x() - self._last_pos.x()
        dy = pos.y() - self._last_pos.y()
        self._last_pos = pos
        if dx or dy:
            self.panDelta.emit(dx, dy)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._last_pos = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class TcpShowWorker(QObject):
    """
    TCP polling worker (lives in its own QThread).
    Emits parsed telemetry dict periodically.
    """
    data = Signal(dict)
    error = Signal(str)
    finished = Signal()

    def __init__(self, client):
        super().__init__()
        self.client = client
        self._running = True

    @Slot()
    def stop(self):
        self._running = False
        try:
            if hasattr(self.client, "disconnect"):
                self.client.disconnect()
        except Exception:
            pass

    @Slot()
    def run(self):
        try:
            while self._running:
                try:
                    d = self.client.get_data() if hasattr(self.client, "get_data") else {}
                    if isinstance(d, dict):
                        self.data.emit(d)
                except Exception as e:
                    self.error.emit(str(e))
                time.sleep(1.0)
        except Exception as e:
            try:
                if hasattr(self.client, "disconnect"):
                    self.client.disconnect()
            except Exception:
                pass
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class DashboardView(QWidget):
    # Defaults; will be replaced by actual zoom folders found in ss4
    AVAILABLE_ZOOM_LEVELS = list(range(6, 17))  # 6..16
    DEFAULT_ZOOM_INDEX = AVAILABLE_ZOOM_LEVELS.index(11) if 11 in AVAILABLE_ZOOM_LEVELS else 0

    MIN_CN_RATIO = 0.0
    MAX_CN_RATIO = 20.0

    # Tile size constant for pan calculations
    TILE_SIZE = 256

    # Map request -> worker
    map_request = Signal(float, float, int, dict)  # lat, lon, zoom, pan_offset

    def __init__(self, parent=None):
        super().__init__(parent)

        # ---- Logging ----
        self._log_queue = deque()
        self._log_paused = False
        self._max_log_items = 500

        # ---- Threads ----
        self.tcp_thread: QThread | None = None
        self.tcp_worker: TcpShowWorker | None = None
        self.map_thread: QThread | None = None
        self.map_worker: MapWorker | None = None

        # ---- Data ----
        self.data: Dict[str, Any] = self._get_default_data()

        # ✅ Detect available zooms from assets folder
        self.AVAILABLE_ZOOM_LEVELS = self._available_tile_zooms()
        preferred = 11 if 11 in self.AVAILABLE_ZOOM_LEVELS else self.AVAILABLE_ZOOM_LEVELS[len(self.AVAILABLE_ZOOM_LEVELS) // 2]
        self.DEFAULT_ZOOM_INDEX = self.AVAILABLE_ZOOM_LEVELS.index(preferred)

        self.current_zoom_index = self.DEFAULT_ZOOM_INDEX
        self.map_pan_offset = {"x": 0, "y": 0}
        self._pan_px_accum_x = 0
        self._pan_px_accum_y = 0

        # --- Smooth pan preview (fast) ---
        self._last_render_request = 0.0
        self._render_throttle_s = 0.08

        # ---- UI ----
        self._init_ui()

        # ---- Timers ----
        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.setInterval(180)
        self._log_flush_timer.timeout.connect(self._flush_log_queue)
        self._log_flush_timer.start()

        self.log_event("Dashboard loaded", level="info")

        # ---- Map worker ----
        self._init_map_worker()
        self._request_map_render()

    # ---------------- Banner ----------------

    def fade_out_banner(self):
        if not hasattr(self, "info_banner"):
            return

        self.opacity_effect = QGraphicsOpacityEffect(self.info_banner)
        self.info_banner.setGraphicsEffect(self.opacity_effect)

        self.banner_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.banner_anim.setDuration(1000)
        self.banner_anim.setStartValue(1.0)
        self.banner_anim.setEndValue(0.0)
        self.banner_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.banner_anim.finished.connect(self.info_banner.hide)
        self.banner_anim.start()

    # ---------------- Map tile helpers ----------------

    def _available_tile_zooms(self) -> list[int]:
        """Scan the tile directory and return available zoom levels."""
        base = os.path.dirname(resource_path("assets/osm_tiles/ss4/{z}/{x}/{y}.png"))
        zooms: list[int] = []
        try:
            if not os.path.isdir(base):
                self.log_event(f"Tile directory not found: {base}", level="error")
                return [11]  # fallback
            
            for name in os.listdir(base):
                if name.isdigit():
                    zoom_dir = os.path.join(base, name)
                    if os.path.isdir(zoom_dir):
                        zooms.append(int(name))
            
            if zooms:
                self.log_event(f"Found offline map tiles for zoom levels: {sorted(zooms)}", level="success")
            else:
                self.log_event("No offline tiles found, map may show gray placeholders", level="warning")
        except Exception as e:
            self.log_event(f"Error scanning tile directory: {e}", level="error")
            return [11]
        
        zooms.sort()
        return zooms or [11]

    # ---------------- Data helpers ----------------

    def _get_default_data(self) -> Dict[str, Any]:
        # ✅ IMPORTANT: default (0,0) often has NO tiles in offline set => gray map.
        # Use Jakarta so you see tiles immediately.
        return {
            "azimuth": "N/A",
            "elevation": "N/A",
            "cn_ratio": "N/A",
            "signal_strength": "N/A",
            "status": "Offline",
            "satellite": "N/A",
            "latitude": -6.1753924,   # Jakarta
            "longitude": 106.8271528, # Jakarta
        }

    def _scale_deg(self, v) -> str:
        if v in (None, "", "N/A"):
            return "N/A"
        try:
            f = float(str(v).replace("°", "").strip())
            return f"{f:.1f}°"
        except Exception:
            return "N/A"

    def _fmt_lat(self, lat: float) -> str:
        hemi = "N" if lat >= 0 else "S"
        return f"{abs(lat):.7f}° {hemi}"

    def _fmt_lon(self, lon: float) -> str:
        hemi = "E" if lon >= 0 else "W"
        return f"{abs(lon):.7f}° {hemi}"

    def _safe_float(self, v: object, default: float = 0.0) -> float:
        try:
            if v is None:
                return default
            s = str(v).strip()
            if s.upper() == "N/A" or s == "":
                return default
            return float(s)
        except Exception:
            return default

    # ---------------- UI ----------------

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)

        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- Banner ---
        self.info_banner = QLabel("Welcome to the Mobile VSAT Management Dashboard!")
        self.info_banner.setObjectName("InfoBanner")
        self.info_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_banner.setWordWrap(True)
        QTimer.singleShot(4000, self.fade_out_banner)
        main_layout.addWidget(self.info_banner)

        # ---------------- HERO ROW (OLD UI LAYOUT) ----------------
        # Left: Map (top) -> Terminal Activity (under map) -> Antenna Location (under terminal)
        # Right: KPI / Pointing / Signal / Status
        hero_row = QHBoxLayout()
        hero_row.setSpacing(12)

        # ---- LEFT COLUMN ----
        left_col = QWidget()
        left_col.setObjectName("HeroLeftColumn")
        left_v = QVBoxLayout(left_col)
        left_v.setContentsMargins(0, 0, 0, 0)
        left_v.setSpacing(12)

        # 1) Map
        self.hero_map_widget = self._create_hero_map()
        left_v.addWidget(self.hero_map_widget)

        # 2) Antenna Location (moved up for quicker GPS visibility)
        self.location_group = self._create_location_group()
        left_v.addWidget(self.location_group)

        # 3) Terminal Activity (moved down)
        self.activity_group = self._create_activity_group()
        left_v.addWidget(self.activity_group)
        left_v.setStretchFactor(self.activity_group, 1)

        # ---- RIGHT COLUMN ----
        right_col = QWidget()
        right_col.setObjectName("HeroKpiColumn")
        right_v = QVBoxLayout(right_col)
        right_v.setContentsMargins(0, 0, 0, 0)
        right_v.setSpacing(12)

        self.kpi_tiles = self._create_kpi_tiles()
        self.pointing_group = self._create_pointing_group()
        self.signal_group = self._create_signal_group()
        self.status_group = self._create_status_group()

        right_v.addWidget(self.kpi_tiles)
        right_v.addWidget(self.pointing_group)
        right_v.addWidget(self.signal_group)
        right_v.addWidget(self.status_group)
        right_v.addStretch(1)

        # Add columns (keep proportions close to original)
        hero_row.addWidget(left_col, 4)
        hero_row.addWidget(right_col, 3)

        hero_container = QWidget()
        hero_container.setObjectName("HeroSection")
        hero_container.setLayout(hero_row)
        main_layout.addWidget(hero_container)

    def _toggle_log_pause(self):
        self._log_paused = not self._log_paused
        self.pause_button.setText("Resume" if self._log_paused else "Pause")

    # ---------------- Terminal Activity ----------------

    def _create_activity_group(self) -> QGroupBox:
        gb = self._create_card_group_box("Terminal Activity")
        v = QVBoxLayout(gb)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        header = QHBoxLayout()
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self._toggle_log_pause)

        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self._clear_log)

        header.addWidget(self.pause_button)
        header.addWidget(clear_button)
        header.addStretch(1)
        v.addLayout(header)

        self.log_list = QListWidget()
        self.log_list.setObjectName("TerminalList")
        self.log_list.setStyleSheet("font-family: 'Consolas', 'Monaco', 'Courier New', monospace;")
        v.addWidget(self.log_list)
        return gb

    def _clear_log(self):
        try:
            self.log_list.clear()
        except Exception:
            pass

    def log_event(self, message: str, level: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_queue.append((ts, message, level))

    def _flush_log_queue(self):
        if self._log_paused:
            return

        # Trim UI list if needed
        try:
            while self.log_list.count() > self._max_log_items:
                self.log_list.takeItem(self.log_list.count() - 1)
        except Exception:
            pass

        # Trim queue
        if len(self._log_queue) > 2000:
            while len(self._log_queue) > 1200:
                self._log_queue.popleft()
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_queue.appendleft((ts, "Log queue trimmed to keep UI responsive", "warning"))

        max_per_tick = 12
        added = 0

        while self._log_queue and added < max_per_tick:
            ts, message, level = self._log_queue.popleft()
            item = QListWidgetItem(f"[{ts}] {message}")

            if level == "error":
                item.setForeground(QColor("#991B1B"))
            elif level == "warning":
                item.setForeground(QColor("#854D0E"))
            elif level == "success":
                item.setForeground(QColor("#166534"))
            else:
                item.setForeground(QColor("#0F172A"))

            self.log_list.insertItem(0, item)
            added += 1

    # ---------------- KPI / Status groups ----------------

    def _create_card_group_box(self, title: str) -> QGroupBox:
        gb = QGroupBox(title)
        gb.setObjectName("DashboardCard")
        return gb

    def _create_kpi_tiles(self) -> QWidget:
        wrap = QWidget()
        wrap.setObjectName("KpiTilesWrap")
        grid = QGridLayout(wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        self.kpi_satellite = KpiTile("Satellite", "N/A")
        self.kpi_status = KpiTile("Link Status", "Offline")
        self.kpi_cn = KpiTile("C/N", "N/A")
        self.kpi_signal = KpiTile("Signal", "N/A")

        grid.addWidget(self.kpi_satellite, 0, 0)
        grid.addWidget(self.kpi_status, 0, 1)
        grid.addWidget(self.kpi_cn, 1, 0)
        grid.addWidget(self.kpi_signal, 1, 1)

        return wrap

    def _create_pointing_group(self) -> QGroupBox:
        gb = self._create_card_group_box("Pointing")
        v = QVBoxLayout(gb)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)

        row = QHBoxLayout()
        self.compass = CompassWidget()
        self.elevation = ElevationWidget()

        row.addWidget(self.compass, 2)
        row.addWidget(self.elevation, 1)
        v.addLayout(row)

        self.polar = PolarWidget()
        v.addWidget(self.polar)

        return gb

    def _create_signal_group(self) -> QGroupBox:
        gb = self._create_card_group_box("Signal")
        v = QVBoxLayout(gb)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)

        row = QHBoxLayout()

        self.cn_label = QLabel("0.0 dB")
        self.cn_label.setObjectName("InlineValue")
        self.cn_label.setProperty("accent", "green")

        self.signal_gauge = GaugeWidget(
            min_value=self.MIN_CN_RATIO,
            max_value=self.MAX_CN_RATIO,
            value=0,
            unit="dB",
            tick_labels=[0, 5, 10, 15, 20],
        )
        self.signal_gauge.setObjectName("SignalGauge")

        row.addWidget(QLabel("C/N Ratio:"))
        row.addWidget(self.cn_label)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(self.signal_gauge)

        return gb

    def _create_status_group(self) -> QGroupBox:
        gb = self._create_card_group_box("Status")
        v = QVBoxLayout(gb)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)

        self.status_label = QLabel("Offline")
        self.status_label.setObjectName("StatusPill")
        self.status_label.setProperty("state", "bad")

        v.addWidget(self.status_label)
        return gb

    def _create_location_group(self) -> QGroupBox:
        gb = self._create_card_group_box("Antenna Location")
        v = QVBoxLayout(gb)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)

        self.lat_value = QLabel(self._fmt_lat(float(self.data.get("latitude", 0.0))))
        self.lon_value = QLabel(self._fmt_lon(float(self.data.get("longitude", 0.0))))
        self.lat_value.setObjectName("InlineValue")
        self.lon_value.setObjectName("InlineValue")

        v.addWidget(QLabel("Latitude:"))
        v.addWidget(self.lat_value)
        v.addWidget(QLabel("Longitude:"))
        v.addWidget(self.lon_value)

        return gb

    # ---------------- Hero map ----------------

    def _create_hero_badge(self) -> QWidget:
        badge = QWidget()
        badge.setObjectName("HeroBadge")
        badge.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        row = QHBoxLayout(badge)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)

        row.addStretch(1)
        return badge

    def _create_hero_controls(self) -> QWidget:
        controls = QWidget()
        controls.setObjectName("HeroMapControls")
        controls.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.zoom_level_label = QLabel("Zoom: N/A")
        self.zoom_level_label.setObjectName("HeroMapZoomLabel")

        self.map_reset_button = QPushButton("Reset")
        self.map_reset_button.setObjectName("MapControlButton")
        self.map_reset_button.clicked.connect(self._reset_map_view)

        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setObjectName("MapZoomButton")
        self.zoom_in_button.clicked.connect(self._zoom_in)

        self.zoom_out_button = QPushButton("-")
        self.zoom_out_button.setObjectName("MapZoomButton")
        self.zoom_out_button.clicked.connect(self._zoom_out)

        row = QHBoxLayout(controls)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)
        row.addWidget(self.zoom_level_label)
        row.addStretch(1)
        row.addWidget(self.zoom_out_button)
        row.addWidget(self.zoom_in_button)
        row.addWidget(self.map_reset_button)

        return controls

    def _create_hero_map(self) -> QWidget:
        wrap = QFrame()
        wrap.setObjectName("HeroMapWrap")
        wrap.setFrameShape(QFrame.NoFrame)

        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        badge = self._create_hero_badge()
        v.addWidget(badge)

        # Map label (interactive pan)
        self.map_label = InteractiveMapLabel()
        self.map_label.setObjectName("MapLabel")
        self.map_label.setMinimumHeight(420)
        self.map_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.map_label.setScaledContents(True)
        self.map_label.panDelta.connect(self._on_map_pan_delta)
        v.addWidget(self.map_label, 1)

        controls = self._create_hero_controls()
        v.addWidget(controls)

        return wrap

    # ---------------- Map worker ----------------

    def _init_map_worker(self):
        # ✅ Make missing tile directory obvious instead of silent gray
        base_dir = os.path.dirname(resource_path("assets/osm_tiles/ss4/{z}/{x}/{y}.png"))
        if not os.path.isdir(base_dir):
            self.log_event(f"Offline tile base folder not found: {base_dir}", level="warning")

        self.map_thread = QThread(self)
        self.map_worker = MapWorker(
            tile_path_template=resource_path("assets/osm_tiles/ss4/{z}/{x}/{y}.png"),
            allow_online=False  # Disable online fallback to use only offline tiles
        )
        self.map_worker.moveToThread(self.map_thread)

        # Connect signals
        self.map_worker.finished.connect(self._on_map_load_success)
        self.map_worker.error.connect(self._on_map_load_error)
        self.map_worker.log.connect(self.log_event)  # Connect MapWorker logs to Terminal Activity

        self.map_request.connect(self.map_worker.run, Qt.ConnectionType.QueuedConnection)
        self.map_thread.start()
        
        self.log_event("Map worker initialized (offline mode)", level="info")

    @Slot(bytes)
    def _on_map_load_success(self, image_data: bytes):
        pix = QPixmap()
        pix.loadFromData(image_data)
        self.map_label.setPixmap(pix)

    @Slot(str)
    def _on_map_load_error(self, msg: str):
        self.log_event(f"Map worker error: {msg}", level="error")

    def _request_map_render(self):
        z = self.AVAILABLE_ZOOM_LEVELS[self.current_zoom_index]
        lat = float(self.data.get("latitude", 0.0))
        lon = float(self.data.get("longitude", 0.0))

        self.zoom_level_label.setText(f"Zoom: {z}")
        # Emit correct parameters: lat, lon, zoom, pan_offset dict
        self.map_request.emit(lat, lon, z, self.map_pan_offset)

    def _zoom_in(self):
        if self.current_zoom_index < len(self.AVAILABLE_ZOOM_LEVELS) - 1:
            self.current_zoom_index += 1
            self._request_map_render()

    def _zoom_out(self):
        if self.current_zoom_index > 0:
            self.current_zoom_index -= 1
            self._request_map_render()

    def _reset_map_view(self):
        """Reset map to default view (center on antenna location, no pan offset)."""
        self.map_pan_offset = {"x": 0, "y": 0}
        self._pan_px_accum_x = 0
        self._pan_px_accum_y = 0
        self.current_zoom_index = self.DEFAULT_ZOOM_INDEX
        self._request_map_render()
        self.log_event("Map view reset to default", level="info")

    @Slot(int, int)
    def _on_map_pan_delta(self, dx: int, dy: int):
        """Handle map pan drag - convert pixel movement to tile offsets."""
        # Accumulate pixel movements
        self._pan_px_accum_x += dx
        self._pan_px_accum_y += dy

        # Convert accumulated pixels to tile offsets (256 pixels = 1 tile)
        tile_offset_x = -int(self._pan_px_accum_x / self.TILE_SIZE)
        tile_offset_y = -int(self._pan_px_accum_y / self.TILE_SIZE)
        
        # Update tile offsets
        self.map_pan_offset["x"] = tile_offset_x
        self.map_pan_offset["y"] = tile_offset_y

        # Keep remainder for smooth sub-tile panning
        # This will be used for pixel-perfect preview in future enhancement
        
        # Throttle render requests for performance
        now = time.time()
        if now - self._last_render_request < self._render_throttle_s:
            return
        self._last_render_request = now

        # Request new map render with updated offsets
        self._request_map_render()

    # ---------------- TCP thread control ----------------

    def start_tcp(self, client):
        self._stop_tcp()

        self.tcp_thread = QThread(self)
        self.tcp_worker = TcpShowWorker(client)
        self.tcp_worker.moveToThread(self.tcp_thread)

        self.tcp_thread.started.connect(self.tcp_worker.run)
        self.tcp_worker.data.connect(self._on_tcp_data, Qt.ConnectionType.QueuedConnection)
        self.tcp_worker.error.connect(self._on_tcp_error, Qt.ConnectionType.QueuedConnection)
        self.tcp_worker.finished.connect(self.tcp_thread.quit)

        self.tcp_thread.finished.connect(self.tcp_worker.deleteLater)
        self.tcp_thread.finished.connect(self.tcp_thread.deleteLater)

        self.tcp_thread.start()
        self.log_event("TCP worker started", level="success")

    def _stop_tcp(self):
        try:
            if self.tcp_worker:
                self.tcp_worker.stop()
        except Exception:
            pass
        try:
            if self.tcp_thread:
                self.tcp_thread.quit()
                self.tcp_thread.wait(3000)
        except Exception:
            pass
        self.tcp_thread = None
        self.tcp_worker = None

    @Slot(dict)
    def _on_tcp_data(self, d: dict):
        # 🔍 DEBUG: Log what we're receiving
        self.log_event(f"📨 Received data keys: {list(d.keys())}", level="info")
        if d:
            sample = {k: d[k] for k in list(d.keys())[:8]}
            self.log_event(f"📊 Data sample: {sample}", level="info")
        
        # Merge and update UI
        self.data.update(d)
        
        # ✅ FIX: Map ACU driver keys (current_*) to Dashboard expected keys
        if "current_azimuth" in self.data:
            self.data["azimuth"] = self.data["current_azimuth"]
        if "current_pitch" in self.data:
            self.data["elevation"] = self.data["current_pitch"]
        if "current_polarization" in self.data:
            self.data["polarization"] = self.data["current_polarization"]
        if "agc_level" in self.data:
            self.data["cn_ratio"] = self.data["agc_level"]
            self.data["signal_strength"] = self.data["agc_level"]

        az = self._scale_deg(self.data.get("azimuth", "N/A"))
        el = self._scale_deg(self.data.get("elevation", "N/A"))
        cn = self._safe_float(self.data.get("cn_ratio", "N/A"), 0.0)

        self.kpi_satellite.set_value(str(self.data.get("satellite", "N/A")))
        self.kpi_status.set_value(str(self.data.get("status", "Offline")))
        self.kpi_cn.set_value(f"{cn:.1f} dB")
        self.kpi_signal.set_value(str(self.data.get("signal_strength", "N/A")))

        # Pointing widgets (best-effort)
        try:
            # ✅ FIXED: Use set_azimuth() not setValue()
            self.compass.set_azimuth(self._safe_float(az.replace("°", ""), 0.0))
        except Exception:
            pass
        try:
            # ✅ FIXED: Use set_elevation() not setValue()
            self.elevation.set_elevation(self._safe_float(el.replace("°", ""), 0.0))
        except Exception:
            pass
        try:
            # ✅ FIXED: Use set_polar() not setValues()
            # Polar widget only takes one value (polarization angle)
            pol = self._safe_float(self.data.get("polarization", "0").replace("°", ""), 0.0)
            self.polar.set_polar(pol)
        except Exception:
            pass

        # Signal
        try:
            self.cn_label.setText(f"{cn:.1f} dB")
            self.signal_gauge.setValue(cn)
        except Exception:
            pass

        # Status pill
        status = str(self.data.get("status", "Offline"))
        self.status_label.setText(status)
        # Use QSS-compatible state names: ok/error instead of good/bad
        self.status_label.setProperty("state", "ok" if status.lower() in ("online", "tracking", "locked") else "error")
        self.status_label.style().polish(self.status_label)

        # Location labels
        try:
            lat = float(self.data.get("latitude", 0.0))
            lon = float(self.data.get("longitude", 0.0))
            self.lat_value.setText(self._fmt_lat(lat))
            self.lon_value.setText(self._fmt_lon(lon))
        except Exception:
            pass

        # Map update
        self._request_map_render()

        self.log_event(f"Telemetry updated | Az={az} El={el} C/N={cn:.1f}dB", level="info")

    @Slot(str)
    def _on_tcp_error(self, msg: str):
        self.log_event(f"TCP error: {msg}", level="error")

    # ---------------- Qt cleanup ----------------

    def closeEvent(self, event):
        try:
            self._stop_tcp()
        except Exception:
            pass

        try:
            if self.map_thread:
                self.map_thread.quit()
                self.map_thread.wait(3000)
        except Exception:
            pass

        super().closeEvent(event)

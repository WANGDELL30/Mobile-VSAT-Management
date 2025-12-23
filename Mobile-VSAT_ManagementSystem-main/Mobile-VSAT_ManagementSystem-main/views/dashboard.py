# views/dashboard.py
from __future__ import annotations
from typing import Dict, Any

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QTimer, QSettings
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QFormLayout,
    QPushButton, QMessageBox, QGridLayout, QSizePolicy, QFrame
)

from services.acu_client import ACUClient
from components.compass_widget import CompassWidget
from components.signal_gauge import GaugeWidget
from components.MapView import MapWorker
from components.elevation_widget import ElevationWidget
from components.utils import resource_path


# ---------------- TCP Worker ----------------

class TcpShowWorker(QObject):
    data_ready = Signal(dict)
    error = Signal(str)

    def __init__(self, host: str, port: int):
        super().__init__()
        self.host = host
        self.port = port
        self.client = ACUClient(host=host, port=port)
        self._connected = False

    @Slot()
    def run(self):
        try:
            if not self._connected:
                self.client.connect(timeout=2.0)
                self._connected = True

            data = self.client.show(retries=1, timeout=1.0)
            if isinstance(data, dict):
                self.data_ready.emit(data)

        except Exception as e:
            self._connected = False
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.error.emit(str(e))


class DashboardView(QWidget):
    UPDATE_INTERVAL_MS = 700

    # IMPORTANT: must match your available folders in assets/osm_tiles/ss4/
    AVAILABLE_ZOOM_LEVELS = [10, 11]
    DEFAULT_ZOOM_INDEX = 1  # start at 11

    MIN_CN_RATIO = 0.0
    MAX_CN_RATIO = 20.0

    map_request = Signal(float, float, int, dict)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DashboardView")

        self.data: Dict[str, Any] = self._get_default_data()
        self.current_zoom_index = self.DEFAULT_ZOOM_INDEX
        self.map_pan_offset = {"x": 0, "y": 0}
        self.error_dialog: QMessageBox | None = None
        self.is_connected = True

        self._tcp_host: str | None = None
        self._tcp_port: int | None = None

        self._thread: QThread | None = None
        self._worker: TcpShowWorker | None = None
        self._timer: QTimer | None = None

        self._init_ui()
        self._init_map_worker()
        self._start_tcp_from_settings()
        self._init_timer()

        self.update_ui_with_data()
        self._request_map_update()

    # ---------------- Data helpers ----------------

    def _get_default_data(self) -> Dict[str, Any]:
        return {
            "azimuth": "N/A",
            "elevation": "N/A",
            "polar": "N/A",
            "cn_ratio": "N/A",
            "latitude": "0.0° N",
            "longitude": "0.0° E",
            "connection_status": "Offline",
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

    def _normalize_tcp(self, raw: dict) -> Dict[str, Any]:
        def pick(*keys, default=None):
            for k in keys:
                if k in raw and raw.get(k) not in (None, ""):
                    return raw.get(k)
            return default

        az = self._scale_deg(pick("current_azimuth", "taz", "az"))
        el = self._scale_deg(pick("current_pitch", "current_elevation", "tel", "el"))  # IMPORTANT
        pol = self._scale_deg(pick("current_polar", "tpol", "pol", "polar"))
        cn = pick("cn_ratio", "cn", "snr", default="N/A")

        lat = pick("latitude", "lat")
        lon = pick("longitude", "lon")

        try:
            lat_f = float(lat)
            lat = self._fmt_lat(lat_f)
        except Exception:
            lat = lat if isinstance(lat, str) and lat else "0.0° N"

        try:
            lon_f = float(lon)
            lon = self._fmt_lon(lon_f)
        except Exception:
            lon = lon if isinstance(lon, str) and lon else "0.0° E"

        status = pick("connection_status", "status", default="Online" if self.is_connected else "Offline")

        return {
            "azimuth": az,
            "elevation": el,
            "polar": pol,
            "cn_ratio": cn,
            "latitude": lat,
            "longitude": lon,
            "connection_status": status,
        }

    # ---------------- UI ----------------

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Banner (styled via QSS)
        self.info_banner = QLabel("Welcome to the Mobile VSAT Management Dashboard!")
        self.info_banner.setObjectName("InfoBanner")
        self.info_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_banner.setWordWrap(True)
        QTimer.singleShot(4000, self.info_banner.hide)
        main_layout.addWidget(self.info_banner)

        # --- Hero section: Map illustration + KPI stack ---
        hero_row = QHBoxLayout()
        hero_row.setSpacing(12)

        self.hero_map_widget = self._create_hero_map()
        hero_row.addWidget(self.hero_map_widget, 0, Qt.AlignmentFlag.AlignTop)

        self.pointing_group = self._create_pointing_group()
        self.signal_group = self._create_signal_group()
        self.status_group = self._create_status_group()

        kpi_stack = QVBoxLayout()
        kpi_stack.setSpacing(12)
        kpi_stack.setContentsMargins(0, 0, 0, 0)
        kpi_stack.addWidget(self.pointing_group)
        kpi_stack.addWidget(self.signal_group)
        kpi_stack.addWidget(self.status_group)
        kpi_stack.addStretch(1)

        kpi_col = QWidget()
        kpi_col.setObjectName("HeroKpiColumn")
        kpi_col.setLayout(kpi_stack)

        hero_row.addWidget(kpi_col, 1)

        hero_container = QWidget()
        hero_container.setObjectName("HeroSection")
        hero_container.setLayout(hero_row)
        main_layout.addWidget(hero_container)

        # Bottom: location (coordinates only)
        self.location_group = self._create_location_group()
        main_layout.addWidget(self.location_group)

    def _create_pointing_group(self) -> QGroupBox:
        self.azimuth_label = QLabel("N/A")
        self.azimuth_label.setObjectName("PrimaryValue")
        self.azimuth_label.setProperty("accent", "blue")

        self.elevation_label = QLabel("N/A")
        self.elevation_label.setObjectName("PrimaryValue")
        self.elevation_label.setProperty("accent", "blue")

        self.polar_label = QLabel("N/A")
        self.polar_label.setObjectName("PrimaryValue")
        self.polar_label.setProperty("accent", "blue")

        self.compass_widget = CompassWidget()
        self.elevation_widget = ElevationWidget()

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form_layout.setHorizontalSpacing(10)
        form_layout.setVerticalSpacing(6)
        form_layout.addRow(self._make_form_label("Azimuth:"), self.azimuth_label)
        form_layout.addRow(self._make_form_label("Elevation:"), self.elevation_label)
        form_layout.addRow(self._make_form_label("Polar:"), self.polar_label)

        visuals_layout = QHBoxLayout()
        visuals_layout.setSpacing(12)
        visuals_layout.addWidget(self.compass_widget, 1)

        # Elevation HUD plate wrapper
        elev_plate = QWidget()
        elev_plate.setObjectName("HudPlate")
        elev_plate_layout = QVBoxLayout(elev_plate)
        elev_plate_layout.setContentsMargins(10, 10, 10, 10)
        elev_plate_layout.setSpacing(0)
        elev_plate_layout.addWidget(self.elevation_widget)
        visuals_layout.addWidget(elev_plate, 1)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addLayout(form_layout)
        layout.addLayout(visuals_layout)

        group_box = self._create_card_group_box("Pointing")
        group_box.setLayout(layout)
        return group_box

    def _create_signal_group(self) -> QGroupBox:
        # Inline value label under gauge
        self.cn_label = QLabel("N/A")
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

        # Gauge plate
        gauge_plate = QWidget()
        gauge_plate.setObjectName("HudPlate")
        gp = QVBoxLayout(gauge_plate)
        gp.setContentsMargins(10, 10, 10, 10)
        gp.setSpacing(6)

        # SAT OPS header row: left C/N RATIO, right dB
        header_row = QWidget()
        header_row.setObjectName("KpiHeaderRow")
        hr = QHBoxLayout(header_row)
        hr.setContentsMargins(2, 0, 2, 0)
        hr.setSpacing(6)

        left = QLabel("C/N RATIO")
        left.setObjectName("KpiHeaderLeft")
        right = QLabel("dB")
        right.setObjectName("KpiHeaderRight")

        hr.addWidget(left)
        hr.addStretch(1)
        hr.addWidget(right)

        gp.addWidget(header_row)
        gp.addWidget(self.signal_gauge)

        # Inline row: "C/N:  N/A"
        inline = QFrame()
        inline.setObjectName("InlineRow")
        inline_layout = QHBoxLayout(inline)
        inline_layout.setContentsMargins(10, 6, 10, 6)
        inline_layout.setSpacing(8)

        key = QLabel("C/N:")
        key.setObjectName("InlineKey")

        inline_layout.addWidget(key)
        inline_layout.addWidget(self.cn_label)
        inline_layout.addStretch(1)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(gauge_plate)
        layout.addWidget(inline)

        group_box = self._create_card_group_box("Signal Quality")
        group_box.setLayout(layout)
        return group_box

    def _create_status_group(self) -> QGroupBox:
        self.status_label = QLabel("Offline")
        self.status_label.setObjectName("StatusPill")
        self.status_label.setProperty("state", "offline")

        form = QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        form.addRow(self._make_form_label("Status:"), self.status_label)

        group_box = self._create_card_group_box("Satellite Status")
        group_box.setLayout(form)
        return group_box

    def _create_location_group(self) -> QGroupBox:
        self.latitude_label = QLabel("N/A")
        self.latitude_label.setObjectName("PrimaryValue")
        self.latitude_label.setProperty("accent", "blue")

        self.longitude_label = QLabel("N/A")
        self.longitude_label.setObjectName("PrimaryValue")
        self.longitude_label.setProperty("accent", "blue")

        labels_layout = QFormLayout()
        labels_layout.setHorizontalSpacing(10)
        labels_layout.setVerticalSpacing(6)
        labels_layout.addRow(self._make_form_label("Latitude:"), self.latitude_label)
        labels_layout.addRow(self._make_form_label("Longitude:"), self.longitude_label)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(labels_layout)

        group_box = self._create_card_group_box("Antenna Location")
        group_box.setLayout(layout)
        group_box.setProperty("variant", "compact")
        return group_box

    # ---------------- Hero map ----------------

    def _create_hero_map(self) -> QWidget:
        hero = QWidget()
        hero.setObjectName("HeroCard")
        hero.setFixedSize(760, 430)

        stack = QGridLayout(hero)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)

        # Base map label
        self.map_label = QLabel("Loading map…")
        self.map_label.setObjectName("HeroMapBase")
        self.map_label.setFixedSize(760, 430)
        self.map_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.map_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        stack.addWidget(self.map_label, 0, 0)

        # Optional overlays (safe if missing)
        for name, path in (
            ("HeroNoise", "assets/card_noise.png"),
            ("HeroWorldDots", "assets/world_dots.png"),
            ("HeroGridOverlay", "assets/hero_grid_overlay.png"),
            ("HeroSatelliteOutline", "assets/satellite_outline.png"),
        ):
            overlay = self._make_overlay_label(name, path)
            if overlay:
                stack.addWidget(overlay, 0, 0)

        badge = self._create_hero_badge()
        stack.addWidget(badge, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        controls = self._create_hero_controls()
        stack.addWidget(controls, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)

        self._update_map_controls_state()
        return hero

    def _make_overlay_label(self, object_name: str, rel_asset_path: str) -> QLabel | None:
        try:
            pix = QPixmap(resource_path(rel_asset_path))
        except Exception:
            return None
        if pix.isNull():
            return None

        lbl = QLabel()
        lbl.setObjectName(object_name)
        lbl.setFixedSize(760, 430)
        lbl.setScaledContents(True)
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lbl.setPixmap(
            pix.scaled(
                760, 430,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        return lbl

    def _create_hero_badge(self) -> QWidget:
        badge = QWidget()
        badge.setObjectName("HeroBadge")
        badge.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        row = QHBoxLayout(badge)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)

        sat_icon = self._make_icon_label("assets/icon_satellite.png", 18)
        if sat_icon:
            row.addWidget(sat_icon)

        title = QLabel("SAT OPS")
        title.setObjectName("HeroBadgeTitle")
        row.addWidget(title)

        dot = QLabel("•")
        dot.setObjectName("HeroBadgeDot")
        row.addWidget(dot)

        pol_icon = self._make_icon_label("assets/icon_polar.png", 18)
        if pol_icon:
            row.addWidget(pol_icon)

        sub = QLabel("TRACKING")
        sub.setObjectName("HeroBadgeSub")
        row.addWidget(sub)

        row.addStretch(1)
        return badge

    def _make_icon_label(self, rel_asset_path: str, size: int) -> QLabel | None:
        try:
            pix = QPixmap(resource_path(rel_asset_path))
        except Exception:
            return None
        if pix.isNull():
            return None

        lbl = QLabel()
        lbl.setObjectName("HeroBadgeIcon")
        lbl.setFixedSize(size, size)
        lbl.setPixmap(
            pix.scaled(
                size, size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        return lbl

    def _create_hero_controls(self) -> QWidget:
        controls = QWidget()
        controls.setObjectName("HeroMapControls")
        controls.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setObjectName("HeroMapBtn")
        self.zoom_in_button.setProperty("role", "primary")

        self.zoom_out_button = QPushButton("–")
        self.zoom_out_button.setObjectName("HeroMapBtn")

        self.pan_up_button = QPushButton("↑")
        self.pan_down_button = QPushButton("↓")
        self.pan_left_button = QPushButton("←")
        self.pan_right_button = QPushButton("→")
        self.map_reset_button = QPushButton("Reset")

        for b in (self.pan_up_button, self.pan_down_button, self.pan_left_button, self.pan_right_button, self.map_reset_button):
            b.setObjectName("HeroMapBtn")

        self.zoom_level_label = QLabel("Zoom: N/A")
        self.zoom_level_label.setObjectName("HeroMapZoomLabel")

        self.zoom_in_button.clicked.connect(lambda: self._change_zoom(1))
        self.zoom_out_button.clicked.connect(lambda: self._change_zoom(-1))
        self.pan_up_button.clicked.connect(lambda: self._pan_map(dy=-1))
        self.pan_down_button.clicked.connect(lambda: self._pan_map(dy=1))
        self.pan_left_button.clicked.connect(lambda: self._pan_map(dx=-1))
        self.pan_right_button.clicked.connect(lambda: self._pan_map(dx=1))
        self.map_reset_button.clicked.connect(self._reset_map)

        pan_layout = QGridLayout()
        pan_layout.setContentsMargins(0, 0, 0, 0)
        pan_layout.setHorizontalSpacing(6)
        pan_layout.setVerticalSpacing(6)
        pan_layout.addWidget(self.pan_up_button, 0, 1)
        pan_layout.addWidget(self.pan_left_button, 1, 0)
        pan_layout.addWidget(self.pan_down_button, 1, 1)
        pan_layout.addWidget(self.pan_right_button, 1, 2)

        zoom_row = QHBoxLayout()
        zoom_row.setContentsMargins(0, 0, 0, 0)
        zoom_row.setSpacing(6)
        zoom_row.addWidget(self.zoom_out_button)
        zoom_row.addWidget(self.zoom_in_button)

        layout = QVBoxLayout(controls)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(self.zoom_level_label)
        layout.addLayout(zoom_row)
        layout.addLayout(pan_layout)
        layout.addWidget(self.map_reset_button)

        return controls

    def _make_form_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("SecondaryLabel")
        return lbl

    def _create_card_group_box(self, title: str) -> QGroupBox:
        group_box = QGroupBox(title)
        group_box.setObjectName("DashboardCard")
        return group_box

    # ---------------- Map worker ----------------

    def _init_map_worker(self):
        tile_template = resource_path("assets/osm_tiles/ss4/{z}/{x}/{y}.png")

        self.map_thread = QThread(self)
        self.map_worker = MapWorker(tile_path_template=tile_template)
        self.map_worker.moveToThread(self.map_thread)

        self.map_worker.finished.connect(self._on_map_load_success)
        self.map_worker.error.connect(self._on_map_load_error)
        self.map_request.connect(self.map_worker.run)

        self.map_thread.start()

    @Slot(bytes)
    def _on_map_load_success(self, image_data: bytes):
        pixmap = QPixmap()
        pixmap.loadFromData(image_data)

        target = self.map_label.size()
        if not target.isEmpty():
            pixmap = pixmap.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.map_label.setPixmap(pixmap)

    @Slot(str)
    def _on_map_load_error(self, error_message: str):
        self.map_label.setText(f"Map Error:\n{error_message}")

    def _request_map_update(self):
        lat, lon = self._parse_coords()
        zoom = self.AVAILABLE_ZOOM_LEVELS[self.current_zoom_index]
        self.map_request.emit(lat, lon, zoom, self.map_pan_offset)

    def _parse_coords(self) -> tuple[float, float]:
        lat_str = self.data.get("latitude", "0.0° N")
        lon_str = self.data.get("longitude", "0.0° E")

        def parse(s: str, neg_hemi: str) -> float:
            s = s.strip()
            num_part = s.split("°")[0].strip()
            hemi = s.split()[-1].strip().upper() if len(s.split()) >= 2 else ""
            val = float(num_part)
            if hemi == neg_hemi:
                val *= -1
            return val

        return parse(lat_str, "S"), parse(lon_str, "W")

    def _change_zoom(self, delta: int):
        new_zoom = self.current_zoom_index + delta
        if 0 <= new_zoom < len(self.AVAILABLE_ZOOM_LEVELS):
            self.current_zoom_index = new_zoom
            self._update_map_controls_state()
            self._request_map_update()

    def _pan_map(self, dx: int = 0, dy: int = 0):
        self.map_pan_offset["x"] += dx
        self.map_pan_offset["y"] += dy
        self._request_map_update()

    def _reset_map(self):
        self.map_pan_offset = {"x": 0, "y": 0}
        self.current_zoom_index = self.DEFAULT_ZOOM_INDEX
        self._update_map_controls_state()
        self._request_map_update()

    def _update_map_controls_state(self):
        zoom_level = self.AVAILABLE_ZOOM_LEVELS[self.current_zoom_index]
        self.zoom_level_label.setText(f"Zoom: {zoom_level}")
        self.zoom_in_button.setEnabled(self.current_zoom_index < len(self.AVAILABLE_ZOOM_LEVELS) - 1)
        self.zoom_out_button.setEnabled(self.current_zoom_index > 0)

    # ---------------- TCP polling ----------------

    def _get_settings_endpoint(self) -> tuple[str, int]:
        s = QSettings("MVMS", "MVMS")
        host = s.value("acu/host", "192.168.0.1")
        port = int(s.value("acu/port", 2217))
        return str(host), int(port)

    def _start_tcp_from_settings(self):
        host, port = self._get_settings_endpoint()
        self._tcp_host, self._tcp_port = host, port

        self._thread = QThread(self)
        self._worker = TcpShowWorker(host=host, port=port)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.data_ready.connect(self._on_data_ready)
        self._worker.error.connect(self._on_error)

        self._thread.start()

    def _stop_tcp(self):
        if self._thread:
            try:
                self._thread.quit()
                self._thread.wait(1500)
            except Exception:
                pass
            self._thread = None
        self._worker = None

    def _init_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(self.UPDATE_INTERVAL_MS)
        self._timer.timeout.connect(self._poll_latest)
        self._timer.start()

    def _poll_latest(self):
        host, port = self._get_settings_endpoint()
        if (host, port) != (self._tcp_host, self._tcp_port):
            self._stop_tcp()
            self._start_tcp_from_settings()

        if self._worker:
            self._worker.run()

    @Slot(dict)
    def _on_data_ready(self, raw: dict):
        self.is_connected = True
        self.data.update(self._normalize_tcp(raw))
        self.update_ui_with_data()
        self._request_map_update()

    @Slot(str)
    def _on_error(self, err_msg: str):
        self.is_connected = False
        self.info_banner.setText(err_msg)
        self.info_banner.setProperty("state", "error")
        self.info_banner.style().unpolish(self.info_banner)
        self.info_banner.style().polish(self.info_banner)
        self.info_banner.show()

    # ---------------- UI update ----------------

    def update_ui_with_data(self):
        self.azimuth_label.setText(str(self.data.get("azimuth", "N/A")))
        self.elevation_label.setText(str(self.data.get("elevation", "N/A")))
        self.polar_label.setText(str(self.data.get("polar", "N/A")))

        try:
            az = float(str(self.data.get("azimuth", "0")).replace("°", "").strip())
        except Exception:
            az = 0.0

        try:
            el = float(str(self.data.get("elevation", "0")).replace("°", "").strip())
        except Exception:
            el = 0.0

        # CompassWidget
        if hasattr(self.compass_widget, "set_azimuth"):
            self.compass_widget.set_azimuth(az)
        elif hasattr(self.compass_widget, "set_angle"):
            self.compass_widget.set_angle(az)

        # ElevationWidget
        if hasattr(self.elevation_widget, "set_elevation"):
            self.elevation_widget.set_elevation(el)
        elif hasattr(self.elevation_widget, "set_angle"):
            self.elevation_widget.set_angle(el)

        cn_text = str(self.data.get("cn_ratio", "N/A"))
        self.cn_label.setText(cn_text)
        try:
            cn_val = float(str(cn_text).replace("dB", "").strip())
        except Exception:
            cn_val = 0.0

        # GaugeWidget
        if hasattr(self.signal_gauge, "setValue"):
            self.signal_gauge.setValue(cn_val)
        elif hasattr(self.signal_gauge, "set_value"):
            self.signal_gauge.set_value(cn_val)

        self.latitude_label.setText(str(self.data.get("latitude", "N/A")))
        self.longitude_label.setText(str(self.data.get("longitude", "N/A")))

        status = str(self.data.get("connection_status", "Offline"))
        self.status_label.setText(status)

        if not self.is_connected:
            self.status_label.setProperty("state", "offline")
        else:
            st = status.lower()
            if "ok" in st or "online" in st:
                self.status_label.setProperty("state", "ok")
            elif "warn" in st:
                self.status_label.setProperty("state", "warning")
            elif "err" in st or "fault" in st:
                self.status_label.setProperty("state", "error")
            else:
                self.status_label.setProperty("state", "info")

        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def closeEvent(self, event):
        try:
            if self._timer:
                self._timer.stop()
        except Exception:
            pass

        try:
            self._stop_tcp()
        except Exception:
            pass

        try:
            self.map_thread.quit()
            self.map_thread.wait(1500)
        except Exception:
            pass

        super().closeEvent(event)

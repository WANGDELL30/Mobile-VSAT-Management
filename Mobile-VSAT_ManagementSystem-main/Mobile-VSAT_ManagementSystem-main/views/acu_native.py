# views/acu_native.py
from __future__ import annotations

import os

from PySide6.QtGui import QTextCursor, QDesktopServices, QPixmap
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QSettings, QUrl, QTimer
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QFormLayout,
    QMessageBox, QFrame, QTextEdit, QCheckBox, QSpinBox, QDoubleSpinBox,
    QButtonGroup, QStackedWidget, QSizePolicy, QComboBox
)

from services.acu_client import ACUClient
from services.acu_driver import build_frame, parse_sat, parse_place
from components.utils import resource_path


# ---------------- Worker ----------------

class AcuWorker(QObject):
    connected = Signal(bool)
    status = Signal(dict)   # emits parsed dict from SHOW / SAT / PLACE / etc.
    error = Signal(str)
    tx = Signal(str)
    rx = Signal(str)

    # generic custom command send
    send_command = Signal(str, list, int, float)

    # Manual SHOW request
    request_show = Signal()

    # SAT/PLACE
    request_sat_read = Signal()
    request_place_read = Signal()
    request_sat_apply = Signal(str, str, str, str, str, str, str, int, float)
    request_place_apply = Signal(str, str, str, int, float)

    def __init__(self, host: str, port: int):
        super().__init__()
        self.host = host
        self.port = port
        self._running = False
        self._client = ACUClient(host=host, port=port)

        self.stream_enabled = True
        self.stream_interval_ms = 1000
        self.stream_sat_enabled = False  # New: for GET-SAT streaming

        self._pending_cmd: tuple[str, list[int], int, float] | None = None
        self._pending_show: bool = False

        self._pending_sat_read: bool = False
        self._pending_place_read: bool = False
        self._pending_sat_apply: tuple[str, str, str, str, str, str, str, int, float] | None = None
        self._pending_place_apply: tuple[str, str, str, int, float] | None = None

        self.send_command.connect(self._queue_command)
        self.request_show.connect(self._queue_show)

        self.request_sat_read.connect(self._queue_sat_read)
        self.request_place_read.connect(self._queue_place_read)
        self.request_sat_apply.connect(self._queue_sat_apply)
        self.request_place_apply.connect(self._queue_place_apply)
        
        # Timer placeholder (created in start() to ensure thread affinity)
        self.timer: QTimer | None = None

    @Slot()
    def start(self):
        self._running = True

        try:
            self._client.connect(timeout=2.0)
            self.connected.emit(True)
        except Exception as e:
            self.connected.emit(False)
            self.error.emit(f"Connect failed: {e}")
            return

        # Create timer IN THE WORKER THREAD
        self.timer = QTimer()
        self.timer.timeout.connect(self._on_tick)
        self.timer.start(self.stream_interval_ms)

    @Slot()
    def stop(self):
        self._running = False
        if self.timer:
            self.timer.stop()
            self.timer.deleteLater()
            self.timer = None
            
        try:
            self._client.disconnect()
        except Exception:
            pass
        self.connected.emit(False)

    @Slot()
    def _on_tick(self):
        if not self._running:
            return

        # 1) Custom command
        if self._pending_cmd is not None:
            frame_code, data_list, retries, timeout = self._pending_cmd
            self._pending_cmd = None
            try:
                parts = [p.strip() for p in frame_code.split(",") if p.strip()]
                if len(parts) >= 2:
                    frame_type = parts[0]
                    code = parts[1]
                    extra = parts[2:]
                    frame = build_frame(frame_type, code, *extra)
                else:
                    frame = build_frame("cmd", frame_code)

                self.tx.emit(frame.strip())
                resp = self._client.send_raw(frame, retries=retries, timeout=timeout)
                self.rx.emit(resp.strip()[:6000])

                low = resp.lower()
                if ",sat" in low:
                    parsed = parse_sat(resp)
                elif ",place" in low:
                    parsed = parse_place(resp)
                elif ",show" in low:
                    parsed = self._client.show(retries=1, timeout=timeout)
                else:
                    parsed = {"frame_code": "raw", "raw": resp}

                if isinstance(parsed, dict) and parsed:
                    self.status.emit(parsed)

            except Exception as e:
                self.error.emit(str(e))

        # 2) Manual SHOW
        if self._pending_show:
            self._pending_show = False
            try:
                data = self._client.show(retries=1, timeout=1.0)
                if isinstance(data, dict):
                    self.status.emit(data)
            except Exception as e:
                self.error.emit(str(e))

        # 3) SAT read
        if self._pending_sat_read:
            self._pending_sat_read = False
            try:
                frame = build_frame("cmd", "sat")
                self.tx.emit(frame.strip())
                frame = build_frame("cmd", "sat")
                self.tx.emit(frame.strip())
                resp = self._client.send_raw(frame, retries=2, timeout=5.0)
                self.rx.emit(resp.strip()[:6000])
                self.rx.emit(resp.strip()[:6000])
                parsed = parse_sat(resp)
                self.status.emit(parsed)
            except Exception as e:
                self.error.emit(str(e))

        # 4) PLACE read
        if self._pending_place_read:
            self._pending_place_read = False
            try:
                frame = build_frame("cmd", "place")
                self.tx.emit(frame.strip())
                frame = build_frame("cmd", "place")
                self.tx.emit(frame.strip())
                resp = self._client.send_raw(frame, retries=2, timeout=5.0)
                self.rx.emit(resp.strip()[:6000])
                self.rx.emit(resp.strip()[:6000])
                parsed = parse_place(resp)
                self.status.emit(parsed)
            except Exception as e:
                self.error.emit(str(e))

        # 5) SAT apply
        if self._pending_sat_apply is not None:
            args = self._pending_sat_apply
            self._pending_sat_apply = None
            try:
                (
                    name, center_freq, carrier_freq, carrier_rate,
                    sat_lon, pol_mode, lock_th, retries, timeout
                ) = args

                self.tx.emit(f"cmd,sat {name},{center_freq},{carrier_freq},{carrier_rate},{sat_lon},{pol_mode},{lock_th}")
                parsed = self._client.set_satellite(
                    name=name,
                    center_freq=center_freq,
                    carrier_freq=carrier_freq,
                    carrier_rate=carrier_rate,
                    sat_lon=sat_lon,
                    pol_mode=pol_mode,
                    lock_th=lock_th,
                    retries=retries,
                    timeout=timeout,
                )
                if isinstance(parsed, dict):
                    self.status.emit(parsed)
            except Exception as e:
                self.error.emit(str(e))

        # 6) PLACE apply
        if self._pending_place_apply is not None:
            args = self._pending_place_apply
            self._pending_place_apply = None
            try:
                lon, lat, heading, retries, timeout = args
                self.tx.emit(f"cmd,place {lon},{lat},{heading}")
                parsed = self._client.set_place(
                    lon=lon,
                    lat=lat,
                    heading=heading,
                    retries=retries,
                    timeout=timeout,
                )
                if isinstance(parsed, dict):
                    self.status.emit(parsed)
            except Exception as e:
                self.error.emit(str(e))

        # 7) Stream SHOW
        if self.stream_enabled:
            try:
                data = self._client.show(retries=1, timeout=1.0)
                if isinstance(data, dict):
                    self.status.emit(data)
            except Exception as e:
                self.error.emit(str(e))
                # Don't break loop (timer keeps running), just log error

        # 8) Stream GET-SAT
        if self.stream_sat_enabled:
            try:
                frame = build_frame("cmd", "sat")
                self.tx.emit(frame.strip())
                resp = self._client.send_raw(frame, retries=1, timeout=1.0)
                self.rx.emit(resp.strip()[:6000])
                parsed = parse_sat(resp)
                if isinstance(parsed, dict):
                    self.status.emit(parsed)
            except Exception as e:
                self.error.emit(f"GET-SAT: {str(e)}")

    @Slot(int)
    def set_stream_interval(self, ms: int):
        self.stream_interval_ms = ms
        if self._running and self.timer.isActive():
            self.timer.setInterval(self.stream_interval_ms)

    @Slot()
    def stop(self):
        self._running = False

    @Slot(bool)
    def set_stream(self, on: bool):
        self.stream_enabled = on

    @Slot(int)
    def set_stream_interval(self, ms: int):
        self.stream_interval_ms = max(100, int(ms))

    @Slot(bool)
    def set_stream_sat(self, on: bool):
        """Enable/disable automatic GET-SAT streaming."""
        self.stream_sat_enabled = on

    @Slot(str, list, int, float)
    def _queue_command(self, frame_code: str, data_list: list[int], retries: int, timeout: float):
        self._pending_cmd = (frame_code, list(data_list), int(retries), float(timeout))

    @Slot()
    def _queue_show(self):
        self._pending_show = True

    @Slot()
    def _queue_sat_read(self):
        self._pending_sat_read = True

    @Slot()
    def _queue_place_read(self):
        self._pending_place_read = True

    @Slot(str, str, str, str, str, str, str, int, float)
    def _queue_sat_apply(
        self,
        name: str,
        center_freq: str,
        carrier_freq: str,
        carrier_rate: str,
        sat_lon: str,
        pol_mode: str,
        lock_th: str,
        retries: int,
        timeout: float,
    ):
        self._pending_sat_apply = (name, center_freq, carrier_freq, carrier_rate, sat_lon, pol_mode, lock_th, int(retries), float(timeout))

    @Slot(str, str, str, int, float)
    def _queue_place_apply(self, lon: str, lat: str, heading: str, retries: int, timeout: float):
        self._pending_place_apply = (lon, lat, heading, int(retries), float(timeout))


# ---------------- UI helpers ----------------

class AcuNavButton(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("acuNavBtn")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(40)


def _make_card(title: str) -> QFrame:
    f = QFrame()
    f.setObjectName("acuCard")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(6)

    t = QLabel(title)
    t.setObjectName("acuCardTitle")
    v = QLabel("-")
    v.setObjectName("acuCardValue")

    lay.addWidget(t)
    lay.addStretch(1)
    lay.addWidget(v)

    f.value_label = v
    return f


def _panel() -> QFrame:
    p = QFrame()
    p.setObjectName("acuPanel")
    return p


# ---------------- Main View ----------------

class AcuNativeView(QWidget):

    # Signal to forward telemetry data to main Dashboard
    telemetry_data = Signal(dict)
    """
    ACU Settings screen with internal pages (like your website):
    - Dashboard (Telemetry + Commands)
    - Log Console
    - Satellite
    - Local Location
    - Manual
    - Manual Book
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AcuNativeView")

        self.host_in = QLineEdit("192.168.0.1")
        self.host_in.setObjectName("acuHostInput")

        self.port_in = QLineEdit("2217")
        self.port_in.setObjectName("acuPortInput")

        self.btn_connect = QPushButton("Connect TCP")
        self.btn_connect.setProperty("role", "primary")
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setEnabled(False)

        self.chk_stream = QCheckBox("Stream SHOW")
        self.chk_stream.setChecked(True)

        self.chk_stream_sat = QCheckBox("Stream SAT")
        self.chk_stream_sat.setChecked(False)  # Off by default

        self.stream_ms = QSpinBox()
        self.stream_ms.setRange(100, 5000)
        self.stream_ms.setValue(1000)  # ✅ 1 second (slower log updates)
        self.stream_ms.setSuffix(" ms")

        self.lbl_conn = QLabel("disconnected")
        self.lbl_conn.setAlignment(Qt.AlignCenter)
        self.lbl_conn.setObjectName("acuConnBadge")

        self.lbl_mode = QLabel("mode: -")
        self.lbl_mode.setAlignment(Qt.AlignCenter)
        self.lbl_mode.setObjectName("acuModeBadge")

        self.btn_stop_top = QPushButton("STOP")
        self.btn_stop_top.setObjectName("acuTopStop")
        self.btn_stop_top.setProperty("role", "danger")

        top_bar = QFrame()
        top_bar.setObjectName("acuTopBar")
        top = QHBoxLayout(top_bar)
        top.setContentsMargins(14, 10, 14, 10)
        top.setSpacing(10)

        top.addWidget(QLabel("TCP Target"))
        top.addWidget(self.host_in, 2)
        top.addWidget(QLabel(":"))
        top.addWidget(self.port_in, 1)
        top.addWidget(self.btn_connect)
        top.addWidget(self.btn_disconnect)
        top.addSpacing(8)
        top.addWidget(self.lbl_conn)
        top.addWidget(self.lbl_mode)
        top.addStretch(1)
        top.addWidget(self.btn_stop_top)
        top.addWidget(self.chk_stream)
        top.addWidget(self.chk_stream_sat)

        # ---------- Internal navigation + pages ----------
        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("acuPageStack")

        nav = self._build_acu_nav()
        pages = self._build_pages()

        main_row = QHBoxLayout()
        main_row.setSpacing(12)
        main_row.addWidget(nav, 1)
        main_row.addWidget(pages, 4)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)
        root.addWidget(top_bar)
        root.addLayout(main_row, 1)

        # ---------- Thread/worker ----------
        self._thread: QThread | None = None
        self._worker: AcuWorker | None = None

        self._set_conn_badge(False)
        self._set_mode_badge(None)

        # ---------- Signals ----------
        self.btn_connect.clicked.connect(self._on_connect)
        self.btn_disconnect.clicked.connect(self._on_disconnect)

        self.chk_stream.toggled.connect(self._on_stream_toggle)
        self.chk_stream_sat.toggled.connect(self._on_stream_sat_toggle)
        self.stream_ms.valueChanged.connect(self._on_stream_interval)

        # top STOP (hard stop)
        self.btn_stop_top.clicked.connect(lambda: self._send_custom_frame("cmd,stop"))

        # default page = Dashboard like website
        self.nav_group.button(0).setChecked(True)
        self.page_stack.setCurrentIndex(0)

    # ----------------- UI builders -----------------

    def _build_acu_nav(self) -> QWidget:
        nav = QFrame()
        nav.setObjectName("acuSideNav")
        lay = QVBoxLayout(nav)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        lay.addSpacing(6)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_group.idClicked.connect(self._switch_acu_page)

        btns = [
            "Dashboard",
            "Log Console",
            "Satellite",
            "Local Location",
            "Manual",
            "Manual Book",
        ]

        for idx, name in enumerate(btns):
            b = AcuNavButton(name)
            self.nav_group.addButton(b, idx)
            lay.addWidget(b)

        lay.addStretch(1)
        return nav

    def _build_pages(self) -> QWidget:
        # Page 0: Dashboard (Telemetry + Commands)
        self.page_dashboard = QWidget()
        dash_layout = QHBoxLayout(self.page_dashboard)
        dash_layout.setContentsMargins(0, 0, 0, 0)
        dash_layout.setSpacing(12)
        dash_layout.addWidget(self._build_telemetry_panel(), 3)
        dash_layout.addWidget(self._build_commands_panel(), 2)

        # Page 1: Log Console
        self.page_log = QWidget()
        v = QVBoxLayout(self.page_log)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        
        # Title row with buttons
        title_row = QHBoxLayout()
        title = QLabel("Log Console")
        title.setObjectName("acuSectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        
        # Pause button
        self.btn_pause_log = QPushButton("Pause")
        self.btn_pause_log.setCheckable(True)
        self.btn_pause_log.setObjectName("acuButton")
        self.btn_pause_log.clicked.connect(self._toggle_log_pause)
        title_row.addWidget(self.btn_pause_log)
        
        # Clear button
        self.btn_clear_log = QPushButton("Clear")
        self.btn_clear_log.setObjectName("acuButton")
        self.btn_clear_log.clicked.connect(self._clear_log)
        title_row.addWidget(self.btn_clear_log)
        
        v.addLayout(title_row)
        
        self.log_big = QTextEdit()
        self.log_big.setReadOnly(True)
        self._log_paused = False
        v.addWidget(self.log_big, 1)

        # Page 2: Satellite
        self.page_sat = self._build_satellite_page()

        # Page 3: Local Location
        self.page_loc = self._build_local_location_page()

        # Page 4: Manual
        self.page_manual = self._build_manual_page()

        # Page 5: Manual Book
        self.page_book = self._build_manual_book_page()

        self.page_stack.addWidget(self.page_dashboard)  # 0
        self.page_stack.addWidget(self.page_log)        # 1
        self.page_stack.addWidget(self.page_sat)        # 2
        self.page_stack.addWidget(self.page_loc)        # 3
        self.page_stack.addWidget(self.page_manual)     # 4
        self.page_stack.addWidget(self.page_book)       # 5

        return self.page_stack

    def _build_telemetry_panel(self) -> QWidget:
        wrap = _panel()
        root = QVBoxLayout(wrap)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        telemetry_title = QLabel("Realtime Telemetry (SHOW)")
        telemetry_title.setObjectName("acuSectionTitle")
        telemetry_sub = QLabel("Live data from ACU + command control")
        telemetry_sub.setObjectName("acuSectionSub")
        root.addWidget(telemetry_title)
        root.addWidget(telemetry_sub)

        self.cards: dict[str, QFrame] = {}

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        root.addLayout(grid)

        card_defs = [
            # Row 1: Targets
            ("Target Azimuth (deg)", "target_azimuth"),
            ("Target Elevation (deg)", "target_elevation"),
            ("Target Polarization (deg)", "target_polarization"),
            ("Satellite Name", "satellite_name"),

            # Row 2: Current
            ("Current Azimuth (deg)", "current_azimuth"),
            ("Current Elevation (deg)", "current_elevation"),
            ("Current Polarization (deg)", "current_polarization"),
            ("Satellite Longitude (deg)", "satellite_longitude"),

            # Row 3: Status
            ("Antenna Status (code)", "antenna_status"),
            ("AGC Level (V)", "agc"),
            ("Polarization Mode", "polarization_mode"),
        ]
        for i, (title, key) in enumerate(card_defs):
            c = _make_card(title)
            self.cards[key] = c
            grid.addWidget(c, i // 4, i % 4)

        loc_title = QLabel("Antenna Location")
        loc_title.setObjectName("acuSectionTitle")
        root.addWidget(loc_title)

        loc_grid = QGridLayout()
        loc_grid.setHorizontalSpacing(12)
        loc_grid.setVerticalSpacing(12)
        root.addLayout(loc_grid)

        self.cards["longitude"] = _make_card("Longitude (deg)")
        self.cards["latitude"] = _make_card("Latitude (deg)")
        self.cards["gps_status"] = _make_card("GPS Status")

        loc_grid.addWidget(self.cards["longitude"], 0, 0)
        loc_grid.addWidget(self.cards["latitude"], 0, 1)
        loc_grid.addWidget(self.cards["gps_status"], 0, 2, 1, 2)

        return wrap

    def _build_commands_panel(self) -> QWidget:
        wrap = _panel()
        root = QVBoxLayout(wrap)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        cmd_title = QLabel("Commands")
        cmd_title.setObjectName("acuSectionTitle")
        cmd_sub = QLabel("Quick commands + custom frames")
        cmd_sub.setObjectName("acuSectionSub")
        root.addWidget(cmd_title)
        root.addWidget(cmd_sub)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self.btn_reset = QPushButton("Reset")
        self.btn_search = QPushButton("Search (align star)")
        self.btn_stow = QPushButton("Stow (collection)")
        self.btn_stop = QPushButton("STOP")

        self.btn_stop.setObjectName("acuStopButton")
        self.btn_stop.setProperty("role", "danger")

        grid.addWidget(self.btn_reset, 0, 0)
        grid.addWidget(self.btn_search, 0, 1)
        grid.addWidget(self.btn_stow, 1, 0)
        grid.addWidget(self.btn_stop, 1, 1)
        root.addLayout(grid)

        # Custom Command
        cmd_title = QLabel("Custom Command")
        cmd_title.setObjectName("acuSectionTitle")
        root.addWidget(cmd_title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setSpacing(8)

        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("e.g., cmd,search")
        form.addRow("Frame code", self.cmd_input)

        self.btn_send = QPushButton("Send")
        self.btn_send.setObjectName("acuPrimaryButton")
        form.addRow("", self.btn_send)
        root.addLayout(form)

        root.addSpacing(10)
        log_row = QHBoxLayout()
        log_title = QLabel("Log Console")
        log_title.setObjectName("acuSubTitle")
        self.btn_clear_log = QPushButton("Clear")
        self.btn_clear_log.setFixedWidth(80)

        log_row.addWidget(log_title)
        log_row.addStretch(1)
        log_row.addWidget(self.btn_clear_log)
        root.addLayout(log_row)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(180)
        root.addWidget(self.log, 1)

        # Bind actions
        self.btn_reset.clicked.connect(lambda: self._send_custom_frame("cmd,reset"))
        self.btn_search.clicked.connect(lambda: self._send_custom_frame("cmd,search"))
        self.btn_stow.clicked.connect(lambda: self._send_custom_frame("cmd,stow"))
        self.btn_stop.clicked.connect(lambda: self._send_custom_frame("cmd,stop"))
        self.btn_send.clicked.connect(self._on_custom_send)
        self.btn_clear_log.clicked.connect(self._clear_log)

        return wrap

    # -------- Satellite --------

    def _build_satellite_page(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        title = QLabel("Satellite")
        title.setObjectName("acuSectionTitle")
        sub = QLabel("Live read + update satellite parameters")
        sub.setObjectName("acuSectionSub")
        root.addWidget(title)
        root.addWidget(sub)

        row = QHBoxLayout()
        row.setSpacing(12)
        root.addLayout(row, 1)

        left = _panel()
        l = QVBoxLayout(left)
        l.setContentsMargins(14, 14, 14, 14)
        l.setSpacing(10)

        t = QLabel("Live Satellite Read")
        t.setObjectName("acuSubTitle")
        t.setObjectName("acuSubTitle")
        l.addWidget(t)

        # Connection Status Indicator
        self.sat_conn_status = QLabel("Status: Disconnected")
        self.sat_conn_status.setStyleSheet("color: red; font-weight: bold;")
        l.addWidget(self.sat_conn_status)

        self.sat_readout = QTextEdit()
        self.sat_readout.setReadOnly(True)
        self.sat_readout.setMinimumHeight(220)
        self.sat_readout.setText("Waiting WS...")
        l.addWidget(self.sat_readout, 1)

        btn_row = QHBoxLayout()
        self.btn_sat_read = QPushButton("Read Satellite")
        self.btn_sat_read.setProperty("role", "ghost")
        btn_row.addWidget(self.btn_sat_read)
        btn_row.addStretch(1)
        l.addLayout(btn_row)

        right = _panel()
        r = QVBoxLayout(right)
        r.setContentsMargins(14, 14, 14, 14)
        r.setSpacing(10)

        rt = QLabel("Satellite Settings")
        rt.setObjectName("acuSubTitle")
        r.addWidget(rt)

        self.sat_preset = QComboBox()
        self.sat_preset.addItems(["Custom", "Nusantara 1 (PSN VI)"])
        self.sat_preset.currentIndexChanged.connect(self._on_sat_preset_changed)

        self.sat_name = QLineEdit("SAT-1")
        self.sat_center = QLineEdit("")
        self.sat_carrier_freq = QLineEdit("0")
        self.sat_carrier_rate = QLineEdit("0")
        self.sat_lon = QLineEdit("0")
        self.sat_pol_mode = QLineEdit("1")
        self.sat_lock_th = QLineEdit("5,0")

        form = QFormLayout()
        form.addRow("Preset", self.sat_preset)
        form.addRow("Name", self.sat_name)
        form.addRow("Center Freq (MHz)", self.sat_center)
        form.addRow("Carrier Freq (MHz)", self.sat_carrier_freq)
        form.addRow("Carrier Rate (ksps)", self.sat_carrier_rate)
        form.addRow("Satellite Longitude (deg)", self.sat_lon)
        form.addRow("Pol Mode (0=Horizontal,1=Vertical)", self.sat_pol_mode)
        form.addRow("Lock Threshold", self.sat_lock_th)
        r.addLayout(form)

        self.btn_sat_apply = QPushButton("Apply Satellite")
        self.btn_sat_apply.setProperty("role", "primary")
        r.addWidget(self.btn_sat_apply)

        row.addWidget(left, 3)
        row.addWidget(right, 2)

        self.btn_sat_read.clicked.connect(self._request_sat_read)
        self.btn_sat_apply.clicked.connect(self._apply_satellite)

        return w

    # -------- Local Location --------

    def _build_local_location_page(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        title = QLabel("Local Location")
        title.setObjectName("acuSectionTitle")
        sub = QLabel("Live read + update place / GPS settings")
        sub.setObjectName("acuSectionSub")
        root.addWidget(title)
        root.addWidget(sub)

        row = QHBoxLayout()
        row.setSpacing(12)
        root.addLayout(row, 1)

        left = _panel()
        l = QVBoxLayout(left)
        l.setContentsMargins(14, 14, 14, 14)
        l.setSpacing(10)

        t = QLabel("Live Place Read")
        t.setObjectName("acuSubTitle")
        l.addWidget(t)

        self.place_readout = QTextEdit()
        self.place_readout.setReadOnly(True)
        self.place_readout.setMinimumHeight(220)
        self.place_readout.setText("Waiting WS...")
        l.addWidget(self.place_readout, 1)

        btn_row = QHBoxLayout()
        self.btn_place_read = QPushButton("Read Place")
        self.btn_place_read.setProperty("role", "ghost")
        btn_row.addWidget(self.btn_place_read)
        btn_row.addStretch(1)
        l.addLayout(btn_row)

        right = _panel()
        r = QVBoxLayout(right)
        r.setContentsMargins(14, 14, 14, 14)
        r.setSpacing(10)

        rt = QLabel("Set Local Location")
        rt.setObjectName("acuSubTitle")
        r.addWidget(rt)

        self.place_lon = QLineEdit("")
        self.place_lat = QLineEdit("")
        self.place_heading = QLineEdit("blank")

        form = QFormLayout()
        form.addRow("Longitude", self.place_lon)
        form.addRow("Latitude", self.place_lat)
        form.addRow("Heading (optional)", self.place_heading)
        r.addLayout(form)

        self.btn_place_apply = QPushButton("Apply Location")
        self.btn_place_apply.setProperty("role", "primary")
        r.addWidget(self.btn_place_apply)

        row.addWidget(left, 3)
        row.addWidget(right, 2)

        self.btn_place_read.clicked.connect(self._request_place_read)
        self.btn_place_apply.clicked.connect(self._apply_place)

        return w

    # -------- Manual --------

    def _build_manual_page(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        title = QLabel("Manual Control")
        title.setObjectName("acuSectionTitle")
        sub = QLabel("Direct position control (cmd,dir) - Proven Working!")
        sub.setObjectName("acuSectionSub")
        root.addWidget(title)
        root.addWidget(sub)

        row = QHBoxLayout()
        row.setSpacing(12)
        root.addLayout(row, 1)

        # LEFT: Simple DIR command (matching working terminal code)
        left = _panel()
        l = QVBoxLayout(left)
        l.setContentsMargins(14, 14, 14, 14)
        l.setSpacing(12)

        # Simple DIR section (cmd,dir AZ EL POL)
        dir_title = QLabel("Simple Position Command (cmd,dir)")
        dir_title.setObjectName("acuSubTitle")
        dir_sub = QLabel("✅ This format is PROVEN to work!")
        dir_sub.setObjectName("acuSectionSub")
        l.addWidget(dir_title)
        l.addWidget(dir_sub)

        self.dir_az = QLineEdit("")
        self.dir_az.setPlaceholderText("e.g., 80.23")
        self.dir_el = QLineEdit("")
        self.dir_el.setPlaceholderText("e.g., 40.0")
        self.dir_pol = QLineEdit("")
        self.dir_pol.setPlaceholderText("e.g., 0")

        form_dir = QFormLayout()
        form_dir.addRow("Azimuth (deg)", self.dir_az)
        form_dir.addRow("Elevation (deg)", self.dir_el)
        form_dir.addRow("Polarization (deg)", self.dir_pol)
        l.addLayout(form_dir)

        self.btn_send_dir = QPushButton("Move Antenna (cmd,dir)")
        self.btn_send_dir.setProperty("role", "primary")
        l.addWidget(self.btn_send_dir)

        l.addSpacing(20)

        # Divider line
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)
        l.addWidget(divider)

        l.addSpacing(10)

        # Dirx section
        dirx_title = QLabel("Advanced Dirx Command")

        dirx_title.setObjectName("acuSubTitle")
        l.addWidget(dirx_title)

        self.dirx_sport = QComboBox()
        # Keep labels website-ish, but send short codes
        self.dirx_sport.addItem("a (azimuth)", "a")
        self.dirx_sport.addItem("e (elevation)", "e")
        self.dirx_sport.addItem("p (polarization)", "p")
        self.dirx_sport.addItem("ae (azimuth + elevation)", "ae")
        self.dirx_sport.addItem("ap (azimuth + polarization)", "ap")
        self.dirx_sport.addItem("ep (elevation + polarization)", "ep")
        self.dirx_sport.addItem("aep (azimuth + elevation + polarization)", "aep")

        self.dirx_az_target = QLineEdit("")
        self.dirx_az_target.setPlaceholderText("leave blank to omit")
        self.dirx_az_speed = QLineEdit("")
        self.dirx_az_speed.setPlaceholderText("leave blank to omit")

        self.dirx_el_target = QLineEdit("")
        self.dirx_el_target.setPlaceholderText("leave blank to omit")
        self.dirx_el_speed = QLineEdit("")
        self.dirx_el_speed.setPlaceholderText("leave blank to omit")

        self.dirx_pol_target = QLineEdit("")
        self.dirx_pol_target.setPlaceholderText("leave blank to omit")
        self.dirx_pol_speed = QLineEdit("")
        self.dirx_pol_speed.setPlaceholderText("leave blank to omit")

        form = QFormLayout()
        form.addRow("Sport Type", self.dirx_sport)
        form.addRow("Azimuth Target (deg)", self.dirx_az_target)
        form.addRow("Azimuth Speed (deg/s)", self.dirx_az_speed)
        form.addRow("Pitch Target (deg)", self.dirx_el_target)
        form.addRow("Pitch Speed (deg/s)", self.dirx_el_speed)
        form.addRow("Pol Target (deg)", self.dirx_pol_target)
        form.addRow("Pol Speed (deg/s)", self.dirx_pol_speed)
        l.addLayout(form)

        self.btn_send_dirx = QPushButton("Send Dirx")
        self.btn_send_dirx.setProperty("role", "primary")
        l.addWidget(self.btn_send_dirx)

        # Divider-ish spacing
        l.addSpacing(6)

        # Speed-only section
        speed_title = QLabel("Speed-only Manual Mode")
        speed_title.setObjectName("acuSubTitle")
        l.addWidget(speed_title)

        self.speed_dir = QComboBox()
        self.speed_dir.addItem("L (Azimuth Left)", "L")
        self.speed_dir.addItem("R (Azimuth Right)", "R")
        self.speed_dir.addItem("U (Pitch Up)", "U")
        self.speed_dir.addItem("D (Pitch Down)", "D")
        self.speed_dir.addItem("CW (Pol CW)", "CW")
        self.speed_dir.addItem("CCW (Pol CCW)", "CCW")
        self.speed_val = QLineEdit("")
        self.speed_val.setPlaceholderText("ex: 2.50")

        form2 = QFormLayout()
        form2.addRow("Direction Code", self.speed_dir)
        form2.addRow("Speed", self.speed_val)
        l.addLayout(form2)

        self.btn_send_speed = QPushButton("Send Speed-only")
        self.btn_send_speed.setProperty("role", "primary")
        l.addWidget(self.btn_send_speed)

        l.addStretch(1)

        # RIGHT: Tips card
        right = _panel()
        r = QVBoxLayout(right)
        r.setContentsMargins(14, 14, 14, 14)
        r.setSpacing(10)

        tips_title = QLabel("Tips")
        tips_title.setObjectName("acuSubTitle")
        r.addWidget(tips_title)

        tips = QLabel(
            "• Blank fields are omitted (fill-a-space behavior).\n"
            "• Sport type decides which axes are meaningful.\n"
            "• Use STOP for immediate halt."
        )
        tips.setWordWrap(True)
        tips.setObjectName("acuSectionSub")
        r.addWidget(tips)
        r.addStretch(1)

        row.addWidget(left, 3)
        row.addWidget(right, 2)

        # wiring
        self.btn_send_dir.clicked.connect(self._manual_send_dir)
        self.btn_send_dirx.clicked.connect(self._manual_send_dirx)
        self.btn_send_speed.clicked.connect(self._manual_send_speed_only)

        return w

    def _blank(self, s: str) -> str:
        s = (s or "").strip()
        return s if s else "blank"

    @Slot()
    def _manual_send_dir(self):
        """
        Send simple cmd,dir command (matching working terminal code)
        Format: $cmd,dir,AZ,EL,POL*checksum\r\n
        """
        if not self._require_worker():
            return

        az = self.dir_az.text().strip()
        el = self.dir_el.text().strip()
        pol = self.dir_pol.text().strip()

        if not az or not el or not pol:
            QMessageBox.warning(
                self,
                "Missing Values",
                "Please enter all three values: Azimuth, Elevation, and Polarization"
            )
            return

        # Build frame: cmd,dir,AZ,EL,POL (matching working code)
        frame = build_frame("cmd", "dir", az, el, pol)
        self._append_log(f"[DIR] Moving to Az={az}° El={el}° Pol={pol}°")
        self._send_raw_frame(frame)

    @Slot()
    def _manual_send_dirx(self):
        if not self._require_worker():
            return

        sport = self.dirx_sport.currentData() or "a"
        az_t = self._blank(self.dirx_az_target.text())
        az_s = self._blank(self.dirx_az_speed.text())
        el_t = self._blank(self.dirx_el_target.text())
        el_s = self._blank(self.dirx_el_speed.text())
        pol_t = self._blank(self.dirx_pol_target.text())
        pol_s = self._blank(self.dirx_pol_speed.text())

        # We send: cmd,dirx,<sport>,<azT>,<azS>,<elT>,<elS>,<polT>,<polS>
        # This matches the website concept + "blank" omission behavior.
        frame = build_frame("cmd", "dirx", str(sport), az_t, az_s, el_t, el_s, pol_t, pol_s)
        self._append_log(f"[MANUAL] dirx sport={sport}")
        self._send_raw_frame(frame)

    @Slot()
    def _manual_send_speed_only(self):
        if not self._require_worker():
            return

        d = self.speed_dir.currentData() or "L"
        spd = self._blank(self.speed_val.text())

        # We send: cmd,manual,<dir>,<speed>
        frame = build_frame("cmd", "manual", str(d), spd)
        self._append_log(f"[MANUAL] speed-only dir={d} speed={spd}")
        self._send_raw_frame(frame)

    # -------- Manual Book --------

    def _build_manual_book_page(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        title = QLabel("Manual Book")
        title.setObjectName("acuSectionTitle")
        sub = QLabel("Embedded PDF manual")
        sub.setObjectName("acuSectionSub")
        root.addWidget(title)
        root.addWidget(sub)

        panel = _panel()
        p = QVBoxLayout(panel)
        p.setContentsMargins(14, 14, 14, 14)
        p.setSpacing(10)

        # Top row with actions
        row = QHBoxLayout()
        row.setSpacing(10)

        self.manual_pdf_path = resource_path("assets/Manual.pdf")

        self.btn_open_external = QPushButton("Open externally")
        self.btn_open_external.setProperty("role", "primary")
        row.addWidget(self.btn_open_external)
        row.addStretch(1)

        p.addLayout(row)

        viewer_container = QFrame()
        viewer_container.setObjectName("acuPdfContainer")
        vc = QVBoxLayout(viewer_container)
        vc.setContentsMargins(0, 0, 0, 0)
        vc.setSpacing(0)

        self._pdf_view_kind = "none"
        self._pdf_doc = None
        self._pdf_view = None

        # Try QtPdfWidgets first (best)
        try:
            from PySide6.QtPdf import QPdfDocument
            from PySide6.QtPdfWidgets import QPdfView

            doc = QPdfDocument(self)
            view = QPdfView(self)
            view.setDocument(doc)

            if os.path.exists(self.manual_pdf_path):
                doc.load(self.manual_pdf_path)

            self._pdf_doc = doc
            self._pdf_view = view
            self._pdf_view_kind = "qtpdf"
            vc.addWidget(view, 1)

        except Exception:
            # Fallback: WebEngine if available
            try:
                from PySide6.QtWebEngineWidgets import QWebEngineView

                web = QWebEngineView(self)
                if os.path.exists(self.manual_pdf_path):
                    web.setUrl(QUrl.fromLocalFile(self.manual_pdf_path))

                self._pdf_view = web
                self._pdf_view_kind = "webengine"
                vc.addWidget(web, 1)

            except Exception:
                # Final fallback: show a message
                msg = QLabel("PDF viewer not available in this build.\nUse 'Open externally' to view Manual.pdf.")
                msg.setWordWrap(True)
                msg.setAlignment(Qt.AlignCenter)
                msg.setObjectName("acuSectionSub")
                vc.addWidget(msg, 1)

        p.addWidget(viewer_container, 1)
        root.addWidget(panel, 1)

        self.btn_open_external.clicked.connect(self._open_manual_external)

        return w

    @Slot()
    def _open_manual_external(self):
        path = self.manual_pdf_path
        if not os.path.exists(path):
            QMessageBox.warning(self, "Manual Book", f"Manual not found:\n{path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ----------------- navigation -----------------

    @Slot(int)
    def _switch_acu_page(self, idx: int):
        self.page_stack.setCurrentIndex(idx)

    # ----------------- helpers -----------------

    def _append_log(self, s: str):
        """Append to log consoles, respecting pause state."""
        if hasattr(self, "log") and self.log:
            self.log.append(s)
            self.log.moveCursor(QTextCursor.End)

        if hasattr(self, "log_big") and self.log_big and not self._log_paused:
            self.log_big.append(s)
            self.log_big.moveCursor(QTextCursor.End)

    @Slot()
    def _toggle_log_pause(self):
        """Toggle pause state for log console."""
        self._log_paused = self.btn_pause_log.isChecked()
        if self._log_paused:
            self.btn_pause_log.setText("Resume")
            self._append_log("[Log Paused]")
        else:
            self.btn_pause_log.setText("Pause")
            self.log_big.append("[Log Resumed]")
            self.log_big.moveCursor(QTextCursor.End)

    def _clear_log(self):
        if hasattr(self, "log") and self.log:
            self.log.clear()
        if hasattr(self, "log_big") and self.log_big:
            self.log_big.clear()

    def _set_conn_badge(self, ok: bool):
        self.lbl_conn.setText("connected" if ok else "disconnected")
        self.lbl_conn.setProperty("state", "ok" if ok else "error")
        self.lbl_conn.style().unpolish(self.lbl_conn)
        self.lbl_conn.style().polish(self.lbl_conn)
        self.lbl_conn.update()

    def _set_mode_badge(self, mode_text: str | None):
        txt = (mode_text or "-").strip() or "-"
        self.lbl_mode.setText(f"mode: {txt}")
        self.lbl_mode.setProperty("state", "info" if txt != "-" else "muted")
        self.lbl_mode.style().unpolish(self.lbl_mode)
        self.lbl_mode.style().polish(self.lbl_mode)
        self.lbl_mode.update()

    def _get_host_port(self) -> tuple[str, int]:
        host = self.host_in.text().strip()
        port_raw = self.port_in.text().strip()
        try:
            port = int(port_raw)
        except Exception:
            raise ValueError("Port must be a number (e.g. 2217)")
        return host, port

    def _require_worker(self) -> bool:
        if not self._worker:
            QMessageBox.warning(self, "ACU", "Not connected")
            return False
        return True

    def _send_raw_frame(self, frame: str):
        """
        Send a raw already-built frame safely through the same worker path.
        We reuse the 'send_command' signal by passing a synthetic code:
        the worker will rebuild if it detects commas. For raw frames, just
        send it via ACUClient directly using the worker is cleaner, but we
        keep minimal changes: send as cmd with parts.
        """
        # If already connected, simplest is to send via worker custom command path:
        # Convert "$cmd,dirx,..." frame into "cmd,dirx,..." for builder.
        cleaned = frame.strip()
        if cleaned.startswith("$"):
            cleaned = cleaned[1:]
        cleaned = cleaned.strip()
        self._worker.send_command.emit(cleaned, [], 2, 2.0)

    # ----------------- connect/disconnect -----------------

    @Slot()
    def _on_connect(self):
        if self._thread is not None:
            self._append_log("Already connecting/connected.")
            return

        try:
            host, port = self._get_host_port()
        except Exception as e:
            QMessageBox.warning(self, "ACU", str(e))
            return

        s = QSettings("MVMS", "MVMS")
        s.setValue("acu/host", host)
        s.setValue("acu/port", port)

        self._thread = QThread(self)
        self._worker = AcuWorker(host, port)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.start)

        self._worker.connected.connect(self._on_connected)
        self._worker.status.connect(self._on_status)
        self._worker.error.connect(self._on_error)
        self._worker.tx.connect(lambda msg: self._append_log(f"$ TX: {msg}"))
        self._worker.rx.connect(lambda msg: self._append_log(f"* RX: {msg}"))

        self.btn_connect.setEnabled(False)
        self.btn_disconnect.setEnabled(True)
        self._append_log(f"Connecting to {host}:{port} ...")

        self._thread.start()

        self._worker.set_stream(self.chk_stream.isChecked())
        self._worker.set_stream_interval(self.stream_ms.value())

    @Slot()
    def _on_disconnect(self):
        if self._worker:
            try:
                self._worker.stop()
            except Exception:
                pass

        if self._thread:
            try:
                self._thread.quit()
                self._thread.wait(1500)
            except Exception:
                pass

        self._thread = None
        self._worker = None

        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self._set_conn_badge(False)
        self._set_mode_badge(None)
        self._append_log("Disconnected")

    @Slot(bool)
    def _on_stream_toggle(self, on: bool):
        if self._worker:
            self._worker.set_stream(on)

    @Slot(bool)
    def _on_stream_sat_toggle(self, on: bool):
        """Handle Stream SAT checkbox toggle."""
        if self._worker:
            self._worker.set_stream_sat(on)

    @Slot(int)
    def _on_stream_interval(self, ms: int):
        if self._worker:
            self._worker.set_stream_interval(ms)

    # ----------------- Commands -----------------

    def _send_custom_frame(self, frame_code: str):
        if not self._require_worker():
            return
        # Build preview frame to show in log
        from services.acu_driver import build_frame
        parts = [p.strip() for p in frame_code.split(",") if p.strip()]
        if len(parts) >= 2:
            preview = build_frame(parts[0], parts[1], *parts[2:])
        else:
            preview = build_frame("cmd", frame_code)
        
        self._append_log(f"[CMD] Sending: {frame_code} → {preview.strip()}")
        self._worker.send_command.emit(frame_code, [], 2, 2.0)

    @Slot()
    def _request_show(self):
        if not self._require_worker():
            return
        self._append_log("[SHOW] request")
        self._worker.request_show.emit()

    @Slot()
    def _request_sat_read(self):
        if not self._require_worker():
            return
        self._append_log("[SAT] read request")
        self._worker.request_sat_read.emit()

    @Slot()
    def _request_place_read(self):
        if not self._require_worker():
            return
        self._append_log("[PLACE] read request")
        self._worker.request_place_read.emit()

    @Slot()
    def _apply_satellite(self):
        if not self._require_worker():
            return

        name = self.sat_name.text().strip()
        center = self.sat_center.text().strip()
        cf = self.sat_carrier_freq.text().strip()
        cr = self.sat_carrier_rate.text().strip()
        lon = self.sat_lon.text().strip()
        pol = self.sat_pol_mode.text().strip()
        lock = self.sat_lock_th.text().strip()

        if not name:
            QMessageBox.warning(self, "Satellite", "Name is required")
            return

        self._append_log(f"[SAT] apply name={name}")
        self._append_log(f"[SAT] apply name={name}")
        self._worker.request_sat_apply.emit(name, center, cf, cr, lon, pol, lock, 2, 5.0)

    @Slot(int)
    def _on_sat_preset_changed(self, index: int):
        txt = self.sat_preset.currentText()
        if "Nusantara 1" in txt:
            # PSN VI Parameters
            # Longitude: 146.0 E
            # Beacon: 4196 MHz (Vertical/Horizontal) -> Picking V=1
            self.sat_name.setText("Nusantara 1")
            self.sat_center.setText("4196")
            self.sat_carrier_freq.setText("4196")
            self.sat_carrier_rate.setText("0")
            self.sat_lon.setText("146.0")
            self.sat_pol_mode.setText("1") # Vertical
            self.sat_lock_th.setText("5.0")

    @Slot()
    def _apply_place(self):
        if not self._require_worker():
            return

        lon = self.place_lon.text().strip()
        lat = self.place_lat.text().strip()
        heading = self.place_heading.text().strip() or "blank"

        if not lon or not lat:
            QMessageBox.warning(self, "Local Location", "Longitude and Latitude are required")
            return

        self._append_log(f"[PLACE] apply lon={lon} lat={lat}")
        self._worker.request_place_apply.emit(lon, lat, heading, 2, 2.0)

    @Slot()
    def _on_custom_send(self):
        if not self._require_worker():
            return
        
        # ✅ Use cmd_input (the actual field that exists)
        cleaned = self.cmd_input.text().strip()
        if not cleaned:
            return
        
        # Remove leading $ if present
        if cleaned.startswith("$"):
            cleaned = cleaned[1:]
        cleaned = cleaned.strip()
        
        self._append_log(f"[Custom] Sending: {cleaned}")
        self._worker.send_command.emit(cleaned, [], 2, 2.0)

    @Slot(bool)
    def _on_connected(self, ok: bool):
        self._set_conn_badge(ok)
        if not ok:
            self._set_mode_badge(None)
        self.btn_connect.setEnabled(not ok)
        self.btn_disconnect.setEnabled(ok)
        self.btn_disconnect.setEnabled(ok)
        self._append_log("Connected" if ok else "Disconnected")

        if ok:
             # Auto-read satellite config on connect to populate dashboard
             # Delay to 2500ms to avoid fighting with initial SHOW stream
             QTimer.singleShot(2500, lambda: self._worker.request_sat_read.emit())

        # Update Satellite Page Status
        if hasattr(self, "sat_conn_status"):
            if ok:
                self.sat_conn_status.setText("Status: Connected to ACU")
                self.sat_conn_status.setStyleSheet("color: green; font-weight: bold;")
            else:
                self.sat_conn_status.setText("Status: Disconnected")
                self.sat_conn_status.setStyleSheet("color: red; font-weight: bold;")


    def _format_polarization(self, pol_value):
        """Format polarization: 0=Horizontal, 1=Vertical"""
        try:
            val = int(pol_value)
            if val == 0:
                return "Horizontal (0)"
            elif val == 1:
                return "Vertical (1)"
            return str(pol_value)
        except:
            return str(pol_value)

    @Slot(dict)
    def _on_status(self, data: dict):
        # 🔄 ROLLBACK: Simple forward dulu untuk debugging
        # Forward langsung tanpa mapping
        if data and isinstance(data, dict):
            self.telemetry_data.emit(data)
        
        # 📝 Log ACU responses
        import time
        timestamp = time.strftime('[%H:%M:%S]')
        if 'raw' in data:
            raw_data = data['raw']
            frame_code = data.get('frame_code', 'unknown')
            self._append_log(f"{timestamp} 📥 ACU [{frame_code}]: {raw_data[:150]}")
            self._append_log(f"{timestamp} 📥 ACU Response: {data['raw'][:120]}")
        
        frame_code = str(data.get("frame_code", "")).lower()

        # SAT updates
        if frame_code == "sat":
            raw = data.get("raw", "")
            if raw and hasattr(self, "sat_readout"):
                self.sat_readout.setPlainText(str(raw).strip())

            def set_if(widget: QLineEdit, key: str):
                v = data.get(key)
                if v is not None and str(v).strip() != "":
                    widget.setText(str(v))

            set_if(self.sat_name, "sat_name")
            set_if(self.sat_center, "center_freq")
            set_if(self.sat_carrier_freq, "carrier_freq")
            set_if(self.sat_carrier_rate, "carrier_rate")
            set_if(self.sat_lon, "sat_longitude")
            # Format polarization mode
            pol_val = data.get("pol_mode")
            if pol_val is not None and str(pol_val).strip() != "":
                formatted_pol = self._format_polarization(pol_val)
                self.sat_pol_mode.setText(formatted_pol)
            set_if(self.sat_lock_th, "lock_threshold")
            
            # ✅ Update Dashboard cards with satellite info
            if "sat_name" in data and "satellite_name" in self.cards:
                self.cards["satellite_name"].value_label.setText(str(data.get("sat_name", "-")))
            if "sat_longitude" in data and "satellite_longitude" in self.cards:
                self.cards["satellite_longitude"].value_label.setText(str(data.get("sat_longitude", "-")))
            if pol_val is not None and "polarization_mode" in self.cards:
                formatted_pol = self._format_polarization(pol_val)
                self.cards["polarization_mode"].value_label.setText(formatted_pol)
            
            return

        # PLACE updates
        if frame_code == "place":
            raw = data.get("raw", "")
            if raw and hasattr(self, "place_readout"):
                self.place_readout.setPlainText(str(raw).strip())

            def set_if(widget: QLineEdit, key: str):
                v = data.get(key)
                if v is not None and str(v).strip() != "":
                    widget.setText(str(v))

            set_if(self.place_lon, "longitude")
            set_if(self.place_lat, "latitude")
            set_if(self.place_heading, "heading")
            return

        # SHOW telemetry
        def pick(*keys, default=None):
            for k in keys:
                if k in data and data.get(k) not in (None, ""):
                    return data.get(k)
            return default

        def to_float(v):
            try:
                return float(v)
            except Exception:
                return None

        def scale_deg(v):
            f = to_float(v)
            if f is None:
                return None
            if abs(f) > 360 and abs(f) <= 36000:
                f = f / 100.0
            return f

        def scale_latlon(v):
            f = to_float(v)
            if f is None:
                return None
            if abs(f) > 180:
                f = f / 1_000_000.0
            return f

        mapping = {
            "target_azimuth":      scale_deg(pick("target_azimuth", "caz", "preset_azimuth")),
            "target_elevation":    scale_deg(pick("target_elevation", "cel", "preset_pitch")),
            "target_polarization": scale_deg(pick("target_polarization", "cpol", "preset_polarization")),
            "current_azimuth":     scale_deg(pick("current_azimuth", "taz", "az")),
            "current_elevation":   scale_deg(pick("current_pitch", "current_elevation", "tel", "el")),
            "current_polarization": scale_deg(pick("current_polarization", "tpol", "pol")),
            "antenna_status":      pick("antenna_status", "acustu", "status"),
            "agc":                 pick("agc", "agc_level", "agc_level_v"),
            "latitude":            scale_latlon(pick("latitude", "lat")),
            "longitude":           scale_latlon(pick("longitude", "lng", "lon")),
            "gps_status":          pick("gps_status", "gps"),
        }

        mode = pick("mode", "work_mode", "acu_mode", "acumode")
        if mode is not None:
            self._set_mode_badge(str(mode))

        for k, v in mapping.items():
            if not hasattr(self, "cards") or k not in self.cards or v is None:
                continue

            if k in (
                "target_azimuth", "target_elevation", "target_polarization",
                "current_azimuth", "current_elevation", "current_polarization"
            ):
                try:
                    self.cards[k].value_label.setText(f"{float(v):.2f}°")
                except Exception:
                    self.cards[k].value_label.setText(f"{v}°")
            elif k in ("latitude", "longitude"):
                try:
                    self.cards[k].value_label.setText(f"{float(v):.6f}°")
                except Exception:
                    self.cards[k].value_label.setText(f"{v}°")
            elif k == "agc":
                try:
                    self.cards[k].value_label.setText(f"{float(v):.0f} V")
                except Exception:
                    self.cards[k].value_label.setText(str(v))
            else:
                self.cards[k].value_label.setText(str(v))

    @Slot(str)
    def _on_error(self, msg: str):
        self._append_log(f"ERROR: {msg}")
        try:
            QMessageBox.warning(self, "ACU", msg)
        except Exception:
            pass
        self._on_disconnect()

    def closeEvent(self, event):
        try:
            self._on_disconnect()
        except Exception:
            pass
        super().closeEvent(event)

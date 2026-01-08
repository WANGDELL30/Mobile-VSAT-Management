import os
import sys
import re

from PySide6.QtCore import Slot, Qt, QSize
from PySide6.QtGui import QIcon, QColor, QPalette, QPixmap, QImageReader
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QVBoxLayout, QPushButton, QStackedWidget, QButtonGroup,
    QSizePolicy, QLabel
)

from views.dashboard import DashboardView
from views.acu_native import AcuNativeView
from views.modem_webview import ModemView
from views.voip_webview import VoipView
from views.helpPage import HelpPage

from components.utils import resource_path, resource_url


def _resolve_qss_urls(qss_text: str) -> str:
    """
    Qt resolves relative url(...) paths in stylesheets relative to the *process working directory*,
    not relative to the .qss file location. This rewrites url(relative.png) -> url(file:///ABS.png).
    """
    def repl(match: re.Match) -> str:
        raw = (match.group(1) or "").strip()

        # strip quotes if present
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1].strip()

        # Leave these untouched
        if raw.startswith(":") or raw.startswith("data:") or raw.startswith("http://") or raw.startswith("https://"):
            return f"url({match.group(1)})"

        # Already a file URL
        if raw.startswith("file:"):
            return f"url({raw})"

        # Everything else: treat as project-relative path
        return f"url({resource_url(raw)})"

    return re.sub(r"url\(([^)]+)\)", repl, qss_text)


def audit_assets() -> None:
    """
    Debug helper: must be called AFTER QApplication is created.
    """
# Commented out verbose asset audit
#     print("\n=== MVMS ASSET AUDIT ===")
#     fmts = [bytes(x).decode(errors="ignore") for x in QImageReader.supportedImageFormats()]
#     print("Supported image formats:", fmts)

    must_exist = [
        "assets/Dashboard.png",
        "assets/ACU.png",
        "assets/Modem.png",
        "assets/voip.png",
        "assets/help.png",
        "assets/back.png",
        "assets/forward.png",
        "assets/refresh.png",
        "assets/app_icon.ico",
        # only if you actually have this file:
        "assets/compass_background.webp",
    ]

    for rel in must_exist:
        abs_path = resource_path(rel)
        exists = os.path.exists(abs_path)

        # Only attempt to load if file exists (prevents noise)
        if exists:
            icon = QIcon(abs_path)
            pix = QPixmap(abs_path)
            ok_icon = not icon.isNull()
            ok_pix = not pix.isNull()
        else:
            ok_icon = False
            ok_pix = False

        print(f"{rel}")
        print(f"  path: {abs_path}")
        print(f"  exists: {exists}")
        print(f"  QIcon ok: {ok_icon} | QPixmap ok: {ok_pix}")


class NavButton(QPushButton):
    """A custom checkable button for the navigation pane."""
    def __init__(self, text: str, icon_path: str, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.setIcon(QIcon(resource_path(icon_path)))
        self.setIconSize(QSize(20, 20))

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(44)
        self.setStyleSheet("text-align: left; padding-left: 12px;")
        self.setIconSize(QSize(20, 20))
        
        self.setStyleSheet("text-align: left; padding-left: 12px;")
        self.setLayoutDirection(Qt.LeftToRight)


class MainWindow(QMainWindow):
    """The main application window."""

    # (Button Text, Icon Path, View Class)
    PAGES = [
        ("Dashboard",      "assets/Dashboard.png", DashboardView),
        ("ACU Settings",   "assets/ACU.png",       AcuNativeView),
        ("Modem Settings", "assets/Modem.png",     ModemView),
        ("VoIP Settings",  "assets/voip.png",      VoipView),
        ("Help",           "assets/help.png",      HelpPage),
    ]

    def __init__(self):
        super().__init__()
        self._setup_window()
        self._init_ui()
        self._connect_signals()

        self.nav_buttons[0].setChecked(True)
        self.switch_page(0)

    def _setup_window(self):
        self.setWindowTitle("Mobile VSAT Management System")
        self.setGeometry(100, 100, 1200, 800)

        # App icon
        self.setWindowIcon(QIcon(resource_path("assets/app_icon.ico")))

        # Load stylesheet and fix url(...) paths
        stylesheet_path = resource_path("styles/mainStyle.qss")
        try:
            with open(stylesheet_path, "r", encoding="utf-8") as f:
                qss = f.read()
            qss = _resolve_qss_urls(qss)
            self.setStyleSheet(qss)
        except FileNotFoundError:
            print("Warning: stylesheet 'styles/mainStyle.qss' not found.")

    def _init_ui(self):
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        nav_pane = self._create_nav_pane()
        self.stacked_widget = self._create_main_content()

        main_layout.addWidget(nav_pane)
        main_layout.addWidget(self.stacked_widget)
        self.setCentralWidget(central_widget)

    def _create_nav_pane(self) -> QWidget:
        nav_widget = QWidget()
        nav_widget.setObjectName("NavContainer")
        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        # Title with PSN logo
        title_container = QWidget()
        title_layout = QHBoxLayout(title_container)
        title_layout.setContentsMargins(8, 10, 8, 10)
        title_layout.setSpacing(8)
        
        # PSN Logo
        psn_logo = QLabel()
        psn_pixmap = QPixmap(resource_path("assets/cropped-psn-ico.png"))
        psn_logo.setPixmap(psn_pixmap.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        title_layout.addWidget(psn_logo)
        
        # MVMS Text
        title = QLabel("MVMS")
        title.setObjectName("MenuLabel")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        title_layout.addWidget(title)
        title_layout.addStretch(1)
        
        nav_layout.addWidget(title_container)

        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        self.nav_buttons = []

        for idx, (text, icon_path, _) in enumerate(self.PAGES):
            btn = NavButton(text, icon_path)
            btn.setObjectName("NavButton")
            self.button_group.addButton(btn, idx)
            nav_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        nav_layout.addStretch(1)
        
        # Global Emergency Stop button
        self.btn_emergency_stop = QPushButton("🛑 EMERGENCY STOP")
        self.btn_emergency_stop.setObjectName("EmergencyStopButton")
        self.btn_emergency_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_emergency_stop.setMinimumHeight(50)
        self.btn_emergency_stop.clicked.connect(self._on_emergency_stop)
        nav_layout.addWidget(self.btn_emergency_stop)
        
        return nav_widget

    def _create_main_content(self) -> QStackedWidget:
        stacked = QStackedWidget()
        
        # Create view instances and store references
        self.dashboard_view = None
        self.acu_view = None
        
        for idx, (_, _, view_class) in enumerate(self.PAGES):
            view = view_class()
            stacked.addWidget(view)
            
            # Store references to key views
            if idx == 0:  # Dashboard
                self.dashboard_view = view
            elif idx == 1:  # ACU Settings
                self.acu_view = view
        
        # ✅ Connect ACU telemetry to Dashboard
        if self.acu_view and self.dashboard_view:
            if hasattr(self.acu_view, 'telemetry_data') and hasattr(self.dashboard_view, '_on_tcp_data'):
                self.acu_view.telemetry_data.connect(self.dashboard_view._on_tcp_data)
        
        return stacked

    def _connect_signals(self):
        self.button_group.idClicked.connect(self.switch_page)

    def _call_lifecycle(self, widget, method_name: str):
        if hasattr(widget, method_name):
            try:
                getattr(widget, method_name)()
            except Exception:
                pass

    @Slot(int)
    def switch_page(self, idx: int):
        current = self.stacked_widget.currentWidget()
        if current:
            self._call_lifecycle(current, "on_leave")

        self.stacked_widget.setCurrentIndex(idx)

        new = self.stacked_widget.currentWidget()
        if new:
            self._call_lifecycle(new, "on_enter")


    def _on_emergency_stop(self):
        """Handle global emergency stop button - sends STOP to ACU."""
        from PySide6.QtWidgets import QMessageBox
        
        reply = QMessageBox.question(
            self, 
            "Emergency Stop",
            "Send EMERGENCY STOP to ACU?\n\nThis will immediately halt antenna movement.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Send stop via ACU view
            if hasattr(self, 'acu_view') and self.acu_view:
                self.acu_view._on_stop()
                self.statusBar().showMessage("⚠ EMERGENCY STOP SENT", 5000)


def setup_app_style() -> QPalette:
    QApplication.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(240, 240, 240))
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.black)
    palette.setColor(QPalette.ColorRole.Base, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(240, 240, 240))
    palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.black)
    palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.black)
    palette.setColor(QPalette.ColorRole.Button, QColor(240, 240, 240))
    palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.black)
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
    return palette


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setPalette(setup_app_style())

    # ✅ Safe: QPixmap/QIcon only after QApplication exists
    # audit_assets()  # Disabled - too verbose

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

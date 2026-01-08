# views/modem_webview.py
import os
from pathlib import Path

from dotenv import load_dotenv
from PySide6.QtCore import QUrl, QSettings, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QToolButton, QLineEdit, QPushButton, QLabel
from PySide6.QtWebEngineWidgets import QWebEngineView

from components.utils import resource_path

load_dotenv()


def _to_qurl(value: str) -> QUrl:
    """
    Supports:
      - https://... (internet)
      - http://...
      - file:///C:/... (local absolute)
      - assets/help.html (project-relative)
      - C:\\path\\file.html (absolute path)
    """
    value = (value or "").strip()
    if not value:
        return QUrl()

    if value.startswith(("http://", "https://", "file://")):
        return QUrl(value)

    p = Path(value)
    if not p.is_absolute():
        # relative -> make it relative to current working dir
        p = (Path.cwd() / p).resolve()

    return QUrl.fromLocalFile(str(p))


class ModemView(QWidget):
    def __init__(self):
        super().__init__()

        # Load URL from settings or .env
        settings = QSettings("MVMS", "MVMS")
        saved_url = settings.value("modem/url", "")
        
        # Prefer saved URL, fallback to .env
        if not saved_url:
            saved_url = os.getenv("MODEM_URL") or os.getenv("modem") or ""

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ===== URL Configuration Panel =====
        config_panel = QWidget()
        config_panel.setStyleSheet("background-color: #f5f5f5; padding: 8px;")
        config_layout = QHBoxLayout(config_panel)
        config_layout.setContentsMargins(10, 8, 10, 8)
        config_layout.setSpacing(8)

        url_label = QLabel("Modem URL:")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("e.g., http://192.168.1.1 or file:///path/to/modem.html")
        self.url_input.setText(saved_url)
        
        self.btn_load_url = QPushButton("Load URL")
        self.btn_load_url.setStyleSheet("padding: 6px 16px;")
        
        config_layout.addWidget(url_label)
        config_layout.addWidget(self.url_input, 1)
        config_layout.addWidget(self.btn_load_url)

        # ===== Navigation Bar =====
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 6, 6, 6)
        bar.setSpacing(8)

        back_btn = QToolButton()
        back_btn.setIcon(QIcon(resource_path("assets/back.png")))
        fwd_btn = QToolButton()
        fwd_btn.setIcon(QIcon(resource_path("assets/forward.png")))
        ref_btn = QToolButton()
        ref_btn.setIcon(QIcon(resource_path("assets/refresh.png")))

        bar.addWidget(back_btn)
        bar.addWidget(fwd_btn)
        bar.addWidget(ref_btn)
        bar.addStretch()

        # ===== WebView =====
        self.webview = QWebEngineView()

        url = _to_qurl(saved_url)
        if not url.isValid():
            # Offline-friendly fallback HTML
            self.webview.setHtml(
                "<h2>Modem page not configured</h2>"
                "<p>Enter modem URL above and click <b>Load URL</b>.</p>"
                "<p>You can use:</p>"
                "<ul>"
                "<li>HTTP/HTTPS URL: <code>http://192.168.1.1</code></li>"
                "<li>Local file: <code>file:///C:/path/to/modem.html</code></li>"
                "<li>Or set <b>MODEM_URL</b> in <code>.env</code></li>"
                "</ul>"
            )
        else:
            self.webview.setUrl(url)

        # ===== Connections =====
        back_btn.clicked.connect(self.webview.back)
        fwd_btn.clicked.connect(self.webview.forward)
        ref_btn.clicked.connect(self.webview.reload)
        self.btn_load_url.clicked.connect(self._on_load_url)

        def update_nav():
            h = self.webview.history()
            back_btn.setEnabled(h.canGoBack())
            fwd_btn.setEnabled(h.canGoForward())

        update_nav()
        self.webview.loadFinished.connect(lambda _ok: update_nav())
        self.webview.urlChanged.connect(lambda _u: update_nav())
        self.webview.loadStarted.connect(update_nav)
        self.webview.loadProgress.connect(lambda _p: update_nav())

        # ===== Layout Assembly =====
        root.addWidget(config_panel)
        root.addLayout(bar)
        root.addWidget(self.webview, 1)
        self.setLayout(root)

    @Slot()
    def _on_load_url(self):
        """Load the URL from the input field."""
        url_text = self.url_input.text().strip()
        if not url_text:
            self.webview.setHtml("<h2>No URL provided</h2><p>Please enter a URL in the field above.</p>")
            return

        url = _to_qurl(url_text)
        if url.isValid():
            self.webview.setUrl(url)
            # Save to settings for persistence
            settings = QSettings("MVMS", "MVMS")
            settings.setValue("modem/url", url_text)
        else:
            self.webview.setHtml(
                f"<h2>Invalid URL</h2>"
                f"<p>Could not load: <code>{url_text}</code></p>"
                f"<p>Please check the URL format.</p>"
            )


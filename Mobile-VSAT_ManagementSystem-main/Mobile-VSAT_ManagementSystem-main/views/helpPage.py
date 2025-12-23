# views/helpPage.py
import os
from pathlib import Path

from dotenv import load_dotenv
from PySide6.QtCore import QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QToolButton
from PySide6.QtWebEngineWidgets import QWebEngineView

from components.utils import resource_path

load_dotenv()


def _to_qurl(value: str) -> QUrl:
    value = (value or "").strip()
    if not value:
        return QUrl()
    if value.startswith(("http://", "https://", "file://")):
        return QUrl(value)
    p = Path(value)
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    return QUrl.fromLocalFile(str(p))


class HelpPage(QWidget):
    def __init__(self):
        super().__init__()

        help_url = os.getenv("HELP_URL") or os.getenv("help") or ""

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

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

        self.webview = QWebEngineView()
        url = _to_qurl(help_url)

        if not url.isValid():
            self.webview.setHtml(
                "<h2>Help page not configured</h2>"
                "<p>Set <b>HELP_URL</b> in <code>.env</code>.</p>"
                "<p>You can use a local file, e.g. <code>assets/help.html</code></p>"
            )
        else:
            self.webview.setUrl(url)

        back_btn.clicked.connect(self.webview.back)
        fwd_btn.clicked.connect(self.webview.forward)
        ref_btn.clicked.connect(self.webview.reload)

        def update_nav():
            h = self.webview.history()
            back_btn.setEnabled(h.canGoBack())
            fwd_btn.setEnabled(h.canGoForward())

        update_nav()
        self.webview.loadFinished.connect(lambda _ok: update_nav())
        self.webview.urlChanged.connect(lambda _u: update_nav())
        self.webview.loadStarted.connect(update_nav)
        self.webview.loadProgress.connect(lambda _p: update_nav())

        root.addLayout(bar)
        root.addWidget(self.webview)
        self.setLayout(root)

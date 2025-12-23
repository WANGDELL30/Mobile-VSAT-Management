# views/acu_webview.py
from PySide6.QtCore import QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QToolButton
from PySide6.QtWebEngineWidgets import QWebEngineView
from components.utils import resource_path
from dotenv import load_dotenv
from views.acu_native import AcuNativeView
import os

class AcuView(QWidget):
    def __init__(self):
        super().__init__()

        acu_url = os.getenv("ACU_IP")

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 6, 6, 6)
        bar.setSpacing(8)

        back_btn = QToolButton(); back_btn.setIcon(QIcon(resource_path("assets/back.png"))); back_btn.setToolTip("Back")
        fwd_btn  = QToolButton(); fwd_btn.setIcon(QIcon(resource_path("assets/forward.png"))); fwd_btn.setToolTip("Forward")
        ref_btn  = QToolButton(); ref_btn.setIcon(QIcon(resource_path("assets/refresh.png"))); ref_btn.setToolTip("Refresh")

        bar.addWidget(back_btn); bar.addWidget(fwd_btn); bar.addWidget(ref_btn); bar.addStretch()

        self.webview = QWebEngineView()
        self.webview.setUrl(QUrl(acu_url))  # your ACU URL

        back_btn.clicked.connect(self.webview.back)
        fwd_btn.clicked.connect(self.webview.forward)
        ref_btn.clicked.connect(self.webview.reload)

        def update_nav():
            hist = self.webview.history()
            back_btn.setEnabled(hist.canGoBack())
            fwd_btn.setEnabled(hist.canGoForward())

        update_nav()
        self.webview.loadFinished.connect(lambda ok: update_nav())
        self.webview.urlChanged.connect(lambda _: update_nav())
        self.webview.loadStarted.connect(update_nav)
        self.webview.loadProgress.connect(lambda _p: update_nav())

        root.addLayout(bar)
        root.addWidget(self.webview)
        self.setLayout(root)

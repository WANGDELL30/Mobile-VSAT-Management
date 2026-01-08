from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QHBoxLayout, QWidget
from PySide6.QtCore import Qt


class KpiTile(QFrame):
    """
    Reusable KPI tile:
    - title (label)
    - value (big)
    - subtext (small)
    - optional badge/pill on the right
    """

    def __init__(self, title: str, value: str = "--", sub: str = "", badge: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("KpiTile")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(6)

        # Row 1: title + optional badge
        top = QHBoxLayout()
        top.setSpacing(8)

        self.label = QLabel(title)
        self.label.setObjectName("KpiLabel")
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.badge = QLabel(badge)
        self.badge.setObjectName("KpiBadge")
        self.badge.setVisible(bool(badge))
        self.badge.setAlignment(Qt.AlignCenter)

        top.addWidget(self.label, 1)
        top.addWidget(self.badge, 0, Qt.AlignRight)

        # Row 2: value
        self.value = QLabel(value)
        self.value.setObjectName("KpiValue")
        self.value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Row 3: subtext
        self.sub = QLabel(sub)
        self.sub.setObjectName("KpiSub")
        self.sub.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.sub.setVisible(bool(sub))

        root.addLayout(top)
        root.addWidget(self.value)
        root.addWidget(self.sub)

    def set_value(self, text: str, accent: str | None = None):
        self.value.setText(text)
        if accent:
            self.value.setProperty("accent", accent)
            self.value.style().unpolish(self.value)
            self.value.style().polish(self.value)

    def set_sub(self, text: str):
        self.sub.setText(text)
        self.sub.setVisible(bool(text))

    def set_badge(self, text: str):
        self.badge.setText(text)
        self.badge.setVisible(bool(text))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
from app.config import (
    COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_GREEN, COLOR_PANEL_BG,
    COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_TEXT_MUTED
)

class MetricCard(QFrame):
    """Futuristic telemetry card displaying metric value, subtitle, and progress bar."""

    def __init__(self, title: str, unit: str = "%", accent: str = COLOR_CYAN, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.title_text = title
        self.unit = unit
        self.accent = accent
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # Header row: Title and optional status
        h_layout = QHBoxLayout()
        self.title_lbl = QLabel(self.title_text.upper())
        self.title_lbl.setStyleSheet(f"""
            color: {COLOR_TEXT_SECONDARY};
            font-size: 10px;
            font-weight: bold;
            letter-spacing: 1.5px;
        """)
        h_layout.addWidget(self.title_lbl)
        h_layout.addStretch()

        self.tag_lbl = QLabel("REALTIME")
        self.tag_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 9px; letter-spacing: 1px;")
        h_layout.addWidget(self.tag_lbl)
        layout.addLayout(h_layout)

        # Large Value
        self.val_lbl = QLabel(f"0{self.unit}")
        self.val_lbl.setStyleSheet(f"""
            color: {self.accent};
            font-size: 24px;
            font-weight: 800;
            letter-spacing: 1px;
        """)
        layout.addWidget(self.val_lbl)

        # Subtitle / Details
        self.sub_lbl = QLabel("INITIALIZING...")
        self.sub_lbl.setStyleSheet(f"""
            color: {COLOR_TEXT_SECONDARY};
            font-size: 11px;
        """)
        layout.addWidget(self.sub_lbl)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        if self.accent == COLOR_GREEN:
            self.progress.setProperty("class", "green-bar")
        layout.addWidget(self.progress)

    def set_value(self, val: float, subtitle: str = "", progress_pct: float = None):
        if self.unit == "%":
            self.val_lbl.setText(f"{val:3.1f}%")
        else:
            self.val_lbl.setText(f"{val} {self.unit}".strip())

        if subtitle:
            self.sub_lbl.setText(subtitle)

        if progress_pct is not None:
            self.progress.setValue(int(min(max(progress_pct, 0), 100)))
        elif self.unit == "%":
            self.progress.setValue(int(min(max(val, 0), 100)))

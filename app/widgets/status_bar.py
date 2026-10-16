import time
from datetime import datetime
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget
from app.config import (
    COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_GREEN, COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY, COLOR_PANEL_ALT, FONT_FAMILY_DISPLAY
)
from app.services.system_service import SystemService
from app.icons import get_pixmap, get_icon

class TopStatusBar(QFrame):
    """Liquid glass top header bar with crisp vector icons, zero emojis, and real session telemetry."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("header-bar")
        self.setFixedHeight(48)
        self._start_time = time.time()
        self._os_info = SystemService.get_os_info()
        self._setup_ui()

        # Update clock & session every 1 second
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_time)
        self._timer.start(1000)

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(14)

        # 1. CypherX Logo Pill with Vector Icon (Zero emojis)
        logo_box = QHBoxLayout()
        logo_box.setSpacing(8)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(get_pixmap("widgets", "#38bdf8", 18))
        logo_box.addWidget(icon_lbl)

        self.logo_label = QLabel("CYPHER-X")
        self.logo_label.setStyleSheet("""
            color: #ffffff;
            font-size: 13px;
            font-weight: 800;
            letter-spacing: 2px;
        """)
        logo_box.addWidget(self.logo_label)

        sub_lbl = QLabel("COMMAND CENTER")
        sub_lbl.setStyleSheet("""
            color: #64748b;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1.5px;
        """)
        logo_box.addWidget(sub_lbl)

        logo_widget = QWidget()
        logo_widget.setLayout(logo_box)
        layout.addWidget(logo_widget)

        layout.addWidget(self._create_separator())

        # 2. System Status Indicator
        status_box = QHBoxLayout()
        status_box.setSpacing(6)

        shield_icon = QLabel()
        shield_icon.setPixmap(get_pixmap("shield", "#34d399", 14))
        status_box.addWidget(shield_icon)

        self.status_lbl = QLabel("SYSTEM ACTIVE")
        self.status_lbl.setStyleSheet("color: #34d399; font-weight: 700; font-size: 11px; letter-spacing: 1px;")
        status_box.addWidget(self.status_lbl)

        status_widget = QWidget()
        status_widget.setLayout(status_box)
        layout.addWidget(status_widget)

        layout.addWidget(self._create_separator())

        # 3. Hostname & Platform
        host_str = f"{self._os_info['hostname'].upper()} • {self._os_info['os'].upper()}"
        self.host_lbl = QLabel(host_str)
        self.host_lbl.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 500;")
        layout.addWidget(self.host_lbl)

        layout.addStretch()

        # 4. Session Duration
        self.session_lbl = QLabel("Session: 00:00:00")
        self.session_lbl.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 500;")
        layout.addWidget(self.session_lbl)

        layout.addWidget(self._create_separator())

        # 5. Live Digital Clock Pill with vector icon
        clock_box = QHBoxLayout()
        clock_box.setSpacing(6)

        c_icon = QLabel()
        c_icon.setPixmap(get_pixmap("clock", "#38bdf8", 14))
        clock_box.addWidget(c_icon)

        self.clock_lbl = QLabel()
        self.clock_lbl.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 600;")
        clock_box.addWidget(self.clock_lbl)

        clock_pill = QFrame()
        clock_pill.setStyleSheet("""
            background-color: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 12px;
            padding: 2px 10px;
        """)
        clock_pill.setLayout(clock_box)
        layout.addWidget(clock_pill)

        self._update_time()

    def _create_separator(self) -> QLabel:
        sep = QLabel("•")
        sep.setStyleSheet("color: rgba(255, 255, 255, 0.15); font-size: 12px;")
        return sep

    def _update_time(self):
        now = datetime.now()
        self.clock_lbl.setText(now.strftime("%a %b %d  %H:%M:%S"))

        elapsed = int(time.time() - self._start_time)
        hrs = elapsed // 3600
        mins = (elapsed % 3600) // 60
        secs = elapsed % 60
        self.session_lbl.setText(f"Session: {hrs:02d}:{mins:02d}:{secs:02d}")

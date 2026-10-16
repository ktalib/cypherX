from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QWidget
)
from app.config import (
    COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_RED, COLOR_YELLOW,
    COLOR_PANEL_BG, COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY
)
from app.icons import get_pixmap

class CyberConfirmationDialog(QDialog):
    """Futuristic Sci-Fi Confirmation and Safety Dialog."""

    def __init__(self, title: str, message: str, warning_level: str = "warning",
                 confirm_text: str = "CONFIRM EXECUTION", cancel_text: str = "ABORT",
                 details: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"CYBEROPS // {title.upper()}")
        self.setFixedWidth(460)
        self.setModal(True)
        self.warning_level = warning_level  # "info", "warning", "danger"
        self._setup_ui(title, message, confirm_text, cancel_text, details)

    def _setup_ui(self, title: str, message: str, confirm_text: str, cancel_text: str, details: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        # Header with vector icon
        header = QHBoxLayout()
        icon_name = "shield" if self.warning_level == "warning" else ("x" if self.warning_level == "danger" else "widgets")
        accent_color = "#ef4444" if self.warning_level == "danger" else ("#fbbf24" if self.warning_level == "warning" else "#38bdf8")

        icon_lbl = QLabel()
        icon_lbl.setPixmap(get_pixmap(icon_name, accent_color, 22))
        header.addWidget(icon_lbl)

        title_lbl = QLabel(title.upper())
        title_lbl.setStyleSheet(f"color: {accent_color}; font-size: 13px; font-weight: bold; letter-spacing: 1.5px;")
        header.addWidget(title_lbl)
        header.addStretch()
        layout.addLayout(header)

        # Message
        msg_lbl = QLabel(message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 11px; line-height: 1.4;")
        layout.addWidget(msg_lbl)

        # Details if any
        if details:
            detail_frame = QFrame()
            detail_frame.setObjectName("panel")
            df_layout = QVBoxLayout(detail_frame)
            df_layout.setContentsMargins(8, 8, 8, 8)
            d_lbl = QLabel(details)
            d_lbl.setWordWrap(True)
            d_lbl.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px;")
            df_layout.addWidget(d_lbl)
            layout.addWidget(detail_frame)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        abort_btn = QPushButton(cancel_text)
        abort_btn.clicked.connect(self.reject)
        btn_row.addWidget(abort_btn)

        confirm_btn = QPushButton(confirm_text)
        if self.warning_level == "danger":
            confirm_btn.setObjectName("danger-btn")
        else:
            confirm_btn.setObjectName("action-btn-primary")
        confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(confirm_btn)

        layout.addLayout(btn_row)

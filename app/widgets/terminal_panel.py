from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QApplication
)
from app.config import (
    COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_GREEN, COLOR_YELLOW,
    COLOR_RED, COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_PANEL_ALT, FONT_FAMILY_MONO
)

class TerminalPanel(QFrame):
    """Futuristic terminal log console displaying real-time operations, alerts, and system telemetry."""

    _instance = None

    @classmethod
    def get_instance(cls):
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        TerminalPanel._instance = self
        self.setObjectName("panel")
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Header bar
        header = QHBoxLayout()
        title = QLabel("TERMINAL FEED // SYSTEM EVENT LOG")
        title.setObjectName("section-header")
        header.addWidget(title)

        header.addStretch()

        self.clear_btn = QPushButton("CLEAR")
        self.clear_btn.setFixedHeight(22)
        self.clear_btn.clicked.connect(self.clear_terminal)
        header.addWidget(self.clear_btn)

        self.copy_btn = QPushButton("COPY")
        self.copy_btn.setFixedHeight(22)
        self.copy_btn.clicked.connect(self.copy_terminal)
        header.addWidget(self.copy_btn)

        layout.addLayout(header)

        # Log Output Box
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: #040809;
                border: 1px solid {COLOR_BORDER_MUTED};
                color: {COLOR_TEXT_PRIMARY};
                font-family: {FONT_FAMILY_MONO};
                font-size: 11px;
                line-height: 1.3;
            }}
        """)
        layout.addWidget(self.log_text)

        # Initial Welcome Messages
        self.log_info("CYBEROPS system initialization complete. Local services online.")
        self.log_info("Kernel monitors attached. Hardware telemetry streaming active.")

    def log(self, prefix: str, color: str, msg: str):
        now_str = datetime.now().strftime("%H:%M:%S")
        html = f"""<div style="margin: 2px 0;">
            <span style="color: #44635b;">[{now_str}]</span> 
            <span style="color: {color}; font-weight: bold;">{prefix}</span> 
            <span style="color: #cbe0dc;">{msg}</span>
        </div>"""
        self.log_text.append(html)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def log_info(self, msg: str):
        self.log("[INFO]", COLOR_CYAN, msg)

    def log_success(self, msg: str):
        self.log("[DONE]", COLOR_GREEN, msg)

    def log_warning(self, msg: str):
        self.log("[WARN]", COLOR_YELLOW, msg)

    def log_error(self, msg: str):
        self.log("[FAIL]", COLOR_RED, msg)

    def clear_terminal(self):
        self.log_text.clear()
        self.log_info("Terminal buffer cleared.")

    def copy_terminal(self):
        QApplication.clipboard().setText(self.log_text.toPlainText())
        self.log_info("Terminal content copied to clipboard.")

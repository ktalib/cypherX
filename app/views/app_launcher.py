import os
import shutil
import subprocess
from PySide6.QtCore import Qt, QFileInfo
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QLineEdit, QFileDialog, QFrame, QScrollArea,
    QMessageBox, QFileIconProvider
)
from app.config import (
    COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_GREEN, COLOR_PANEL_BG,
    COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_PANEL_ALT
)
from app.database import Database
from app.widgets.terminal_panel import TerminalPanel
from app.icons import get_pixmap, get_icon

_ICON_PROVIDER = None  # created lazily (needs a QApplication)
_ICON_CACHE = {}       # shortcut path -> QIcon

# Default curated safe Windows utility shortcuts
DEFAULT_LAUNCHER_APPS = [
    {"name": "Task Manager", "path": "taskmgr.exe", "desc": "Windows Task Manager"},
    {"name": "Command Prompt", "path": "cmd.exe", "desc": "Command Line Shell"},
    {"name": "PowerShell", "path": "powershell.exe", "desc": "PowerShell Console"},
    {"name": "Registry Editor", "path": "regedit.exe", "desc": "Windows Registry"},
    {"name": "Resource Monitor", "path": "resmon.exe", "desc": "Detailed System Resources"},
    {"name": "Disk Management", "path": "diskmgmt.msc", "desc": "Partition & Disk Config"},
    {"name": "Device Manager", "path": "devmgmt.msc", "desc": "Hardware & Drivers"},
    {"name": "Notepad", "path": "notepad.exe", "desc": "Text Editor"},
    {"name": "Calculator", "path": "calc.exe", "desc": "Windows Calculator"},
]

class ApplicationLauncherView(QWidget):
    """Fast searchable launcher for approved executables and favorite applications."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.shortcuts = []
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        # Header Title
        title_box = QFrame()
        title_box.setObjectName("panel")
        tb_l = QHBoxLayout(title_box)
        tb_l.setContentsMargins(14, 10, 14, 10)
        title = QLabel("APPLICATION LAUNCHER // APPROVED EXECUTABLES & SHORTCUT MATRIX")
        title.setObjectName("section-header")
        tb_l.addWidget(title)
        main_layout.addWidget(title_box)

        # Controls & Add Shortcut Frame
        ctrl_frame = QFrame()
        ctrl_frame.setObjectName("panel")
        ctrl_layout = QHBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(12, 10, 12, 10)
        ctrl_layout.setSpacing(10)

        ctrl_layout.addWidget(QLabel("FILTER LAUNCHER:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search shortcuts...")
        self.search_input.textChanged.connect(self._apply_filter)
        ctrl_layout.addWidget(self.search_input)

        add_btn = QPushButton("+ ADD CUSTOM APP / FOLDER")
        add_btn.setObjectName("action-btn-primary")
        add_btn.clicked.connect(self._add_custom_app)
        ctrl_layout.addWidget(add_btn)

        main_layout.addWidget(ctrl_frame)

        # Grid of Shortcut Cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        self.cards_container = QWidget()
        self.grid_layout = QGridLayout(self.cards_container)
        self.grid_layout.setSpacing(10)

        scroll.setWidget(self.cards_container)
        main_layout.addWidget(scroll)

        self._load_shortcuts()

    def _load_shortcuts(self):
        saved = Database.get_instance().get_setting("custom_launcher_shortcuts", [])
        self.shortcuts = DEFAULT_LAUNCHER_APPS + saved
        self._render_cards(self.shortcuts)
        self._apply_filter()

    @staticmethod
    def _app_icon(path: str) -> QIcon:
        """Real Windows icon for the target (exe / msc / folder), or a vector fallback.
        Remembered per path: asking Windows for an icon is slow."""
        if path not in _ICON_CACHE:
            _ICON_CACHE[path] = ApplicationLauncherView._lookup_icon(path)
        return _ICON_CACHE[path]

    @staticmethod
    def _lookup_icon(path: str) -> QIcon:
        resolved = path
        if not os.path.isabs(path):
            resolved = shutil.which(path) or os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", path)
        global _ICON_PROVIDER
        if _ICON_PROVIDER is None:
            _ICON_PROVIDER = QFileIconProvider()
        if os.path.exists(resolved):
            icon = _ICON_PROVIDER.icon(QFileInfo(resolved))
            if not icon.isNull():
                return icon
        return get_icon("launcher", "#38bdf8", 32)

    def _render_cards(self, items):
        """Build one tile per shortcut. Filtering only re-arranges these (see _place_cards)."""
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._cards = []

        custom = {a["path"] for a in Database.get_instance().get_setting("custom_launcher_shortcuts", [])}
        for app in items:
            card = QPushButton()
            card.setObjectName("launch-tile")
            card.setCursor(Qt.PointingHandCursor)
            card.setToolTip(f"{app['path']}\nClick to launch" +("  ·  right-click to remove" if app["path"] in custom else ""))
            card.setFixedHeight(84)
            card.setStyleSheet("""
                QPushButton#launch-tile { background: rgba(18,26,34,0.72); border: 1px solid rgba(255,255,255,0.10);
                                          border-radius: 14px; text-align: left; padding: 0; }
                QPushButton#launch-tile:hover { background: rgba(30,42,54,0.85); border: 1px solid rgba(56,189,248,0.45); }
                QPushButton#launch-tile:pressed { background: rgba(56,189,248,0.20); }
            """)
            h = QHBoxLayout(card)
            h.setContentsMargins(14, 10, 12, 10)
            h.setSpacing(12)
            icon_lbl = QLabel()
            icon_lbl.setPixmap(self._app_icon(app["path"]).pixmap(32, 32))
            icon_lbl.setFixedSize(36, 36)
            icon_lbl.setAlignment(Qt.AlignCenter)
            icon_lbl.setStyleSheet("background: rgba(255,255,255,0.06); border-radius: 10px;")
            h.addWidget(icon_lbl)
            v = QVBoxLayout()
            v.setSpacing(2)
            name_lbl = QLabel(app["name"])
            name_lbl.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: 700; background: transparent;")
            desc_lbl = QLabel(app.get("desc") or app["path"])
            desc_lbl.setStyleSheet("color: #94a3b8; font-size: 11px; background: transparent;")
            v.addWidget(name_lbl)
            v.addWidget(desc_lbl)
            h.addLayout(v, 1)
            for lbl in (icon_lbl, name_lbl, desc_lbl):
                lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            card.clicked.connect(lambda ch=False, p=app["path"], n=app["name"]: self._launch(p, n))
            if app["path"] in custom:
                card.setContextMenuPolicy(Qt.CustomContextMenu)
                card.customContextMenuRequested.connect(lambda _pos, p=app["path"], n=app["name"]: self._remove_custom(p, n))
            self._cards.append((app, card))

    def _place_cards(self, visible):
        cols = 4
        while self.grid_layout.count():
            self.grid_layout.takeAt(0)
        for r in range(self.grid_layout.rowCount()):
            self.grid_layout.setRowStretch(r, 0)
        shown = 0
        for app, card in self._cards:
            if visible(app):
                self.grid_layout.addWidget(card, shown // cols, shown % cols)
                card.show()
                shown += 1
            else:
                card.hide()
        for c in range(cols):
            self.grid_layout.setColumnStretch(c, 1)
        self.grid_layout.setRowStretch(shown // cols + 1, 1)

    def _remove_custom(self, path, name):
        if QMessageBox.question(self, "Remove Shortcut", f"Remove '{name}' from the launcher?") != QMessageBox.Yes:
            return
        saved = [a for a in Database.get_instance().get_setting("custom_launcher_shortcuts", []) if a["path"] != path]
        Database.get_instance().set_setting("custom_launcher_shortcuts", saved)
        self._load_shortcuts()

    def _apply_filter(self):
        q = self.search_input.text().strip().lower()
        self._place_cards(lambda a: not q or q in a["name"].lower() or q in a.get("desc", "").lower())

    def _add_custom_app(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select App, Shortcut or File to Add", "C:\\",
                                                   "Programs (*.exe *.lnk *.bat *.cmd *.msc);;All Files (*.*)")
        if file_path:
            name = os.path.splitext(os.path.basename(file_path))[0]
            new_item = {"name": name, "path": file_path, "desc": file_path}
            saved = Database.get_instance().get_setting("custom_launcher_shortcuts", [])
            saved.append(new_item)
            Database.get_instance().set_setting("custom_launcher_shortcuts", saved)
            self._load_shortcuts()

    def _launch(self, path, name):
        try:
            os.startfile(path)
            term = TerminalPanel.get_instance()
            if term:
                term.log_success(f"Application launched: {name}")
            Database.get_instance().log_operation(
                operation_type="App Launcher",
                action=f"Launched {name}",
                result="Success",
                target_path=path
            )
        except Exception as e:
            QMessageBox.critical(self, "Launch Error", f"Failed to launch '{name}':\n{str(e)}")

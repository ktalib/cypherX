"""
Navigation Sidebar for CypherX with Lucide/Apple-style vector icons (zero emojis)
and liquid glass styling.
"""
from typing import List, Tuple
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QWidget
)
from app.icons import get_icon, get_pixmap

# Tuple format: (module_id, display_label, icon_name, description)
MODULE_DEFINITIONS: List[Tuple[str, str, str, str]] = [
    ("widget_screen", "Widget Screen", "widgets", "Live liquid glass desktop & lock widgets"),
    ("smart_home", "Smart Home", "home", "3D home & power system"),
    ("dashboard", "Command Center", "dashboard", "Main operations telemetry hub"),
    ("my_computer", "My Computer", "computer", "System overview & hardware"),
    ("disk_analyzer", "Disk Analyzer", "pie_chart", "Storage breakdown & charts"),
    ("disk_cleaner", "Disk Cleaner", "cleaner", "Safe temp & cache cleaner"),
    ("folder_organizer", "Folder Organizer", "folder_organizer", "Rule-based file organizer"),
    ("file_explorer", "File Explorer", "file_explorer", "Directory browsing & launch"),
    ("duplicate_finder", "Duplicate Finder", "duplicate_finder", "Content-hash duplicate tool"),
    ("large_file_finder", "Large File Finder", "large_files", "Isolate heavy storage files"),
    ("process_manager", "Process Manager", "process_manager", "Task & PID controller"),
    ("startup_manager", "Startup Manager", "startup_manager", "Boot app registry manager"),
    ("system_monitor", "System Monitor", "system_monitor", "Live CPU, RAM & Disk charts"),
    ("network_monitor", "Network Monitor", "network_monitor", "Interface & bandwidth stats"),
    ("clock_calendar", "Clock & Calendar", "clock", "World clocks, timer, alarms"),
    ("notes_tasks", "Notes & Tasks", "notes", "Local SQLite productivity"),
    ("app_launcher", "App Launcher", "launcher", "Fast executable shortcuts"),
    ("automation_center", "Automation Center", "automation", "Scheduled task triggers"),
    ("operation_history", "Operation History", "history", "Action audit log & undo"),
    ("settings", "Settings", "settings", "Preferences & themes"),
]


class NavigationSidebar(QFrame):
    """Liquid glass sidebar with crisp vector icons, smooth collapsible rail, and zero emojis."""

    module_selected = Signal(int, str)  # (index, module_id)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(230)
        self.is_collapsed = False
        self.buttons: List[QPushButton] = []
        self._current_idx = 0
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 14, 8, 14)
        main_layout.setSpacing(8)

        # Header with collapse toggle
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(6, 0, 4, 4)

        self.brand_icon = QLabel()
        self.brand_icon.setPixmap(get_pixmap("widgets", "#38bdf8", 18))
        top_bar.addWidget(self.brand_icon)

        self.nav_title = QLabel("CYPHER-X")
        self.nav_title.setStyleSheet("""
            color: #ffffff;
            font-size: 12px;
            font-weight: 800;
            letter-spacing: 2px;
        """)
        top_bar.addWidget(self.nav_title)
        top_bar.addStretch()

        self.collapse_btn = QPushButton()
        self.collapse_btn.setFixedSize(28, 28)
        self.collapse_btn.setIcon(get_icon("chevron_left", "#94a3b8", 16))
        self.collapse_btn.setToolTip("Collapse Navigation")
        self.collapse_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.16);
            }
        """)
        self.collapse_btn.clicked.connect(self.toggle_collapse)
        top_bar.addWidget(self.collapse_btn)

        main_layout.addLayout(top_bar)

        # Scroll Area for navigation items
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self.items_layout = QVBoxLayout(container)
        self.items_layout.setContentsMargins(0, 4, 0, 4)
        self.items_layout.setSpacing(4)

        for idx, (mod_id, label, icon_name, desc) in enumerate(MODULE_DEFINITIONS):
            btn = QPushButton(f"  {label}".replace("&", "&&"))
            btn.setObjectName("nav-btn")
            btn.setToolTip(desc)
            btn.setIcon(get_icon(icon_name, "#cbd5e1", 18))
            btn.setIconSize(QSize(18, 18))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton#nav-btn {
                    text-align: left;
                    padding: 8px 12px;
                    border-radius: 10px;
                    border: 1px solid transparent;
                    color: #cbd5e1;
                    font-size: 12px;
                    font-weight: 500;
                    background: transparent;
                }
                QPushButton#nav-btn:hover {
                    background: rgba(255, 255, 255, 0.10);
                    color: #ffffff;
                }
                QPushButton#nav-btn[active="true"] {
                    background: rgba(56, 189, 248, 0.20);
                    border: 1px solid rgba(56, 189, 248, 0.35);
                    color: #ffffff;
                    font-weight: 600;
                }
            """)
            btn.clicked.connect(lambda checked=False, i=idx, m=mod_id: self._on_module_clicked(i, m))
            self.buttons.append(btn)
            self.items_layout.addWidget(btn)

        self.items_layout.addStretch()
        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        # Select first module (Widget Screen) by default
        self._set_active_button(0)

    def _on_module_clicked(self, index: int, module_id: str):
        self._current_idx = index
        self._set_active_button(index)
        self.module_selected.emit(index, module_id)

    def _set_active_button(self, index: int):
        for i, btn in enumerate(self.buttons):
            is_active = (i == index)
            btn.setProperty("active", "true" if is_active else "false")
            icon_name = MODULE_DEFINITIONS[i][2]
            icon_color = "#38bdf8" if is_active else "#94a3b8"
            btn.setIcon(get_icon(icon_name, icon_color, 18))
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        if self.is_collapsed:
            self.setFixedWidth(64)
            self.nav_title.setVisible(False)
            self.brand_icon.setVisible(False)
            self.collapse_btn.setIcon(get_icon("chevron_right", "#94a3b8", 16))
            for i, btn in enumerate(self.buttons):
                btn.setText("")
                btn.setFixedWidth(46)
        else:
            self.setFixedWidth(230)
            self.nav_title.setVisible(True)
            self.brand_icon.setVisible(True)
            self.collapse_btn.setIcon(get_icon("chevron_left", "#94a3b8", 16))
            for i, btn in enumerate(self.buttons):
                btn.setText(f"  {MODULE_DEFINITIONS[i][1]}".replace("&", "&&"))
                btn.setMinimumWidth(0)
                btn.setMaximumWidth(16777215)

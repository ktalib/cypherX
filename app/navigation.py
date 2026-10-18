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
from app.database import Database

# Every page: module_id -> (display_label, icon_name, description)
MODULES = {
    "smart_dashboard": ("Home Dashboard", "activity", "Smart home at a glance"),
    "smart_home": ("Smart Home", "home", "3D home & power system"),
    "cctv": ("CCTV", "video", "Security cameras & motion alerts"),
    "widget_screen": ("Widget Screen", "widgets", "Live liquid glass desktop & lock widgets"),
    "notes_tasks": ("Notes & Tasks", "notes", "Notes and to-dos"),
    "bills": ("Bills", "file_text", "Household bills, due dates & split"),
    "groceries": ("Groceries", "check_square", "Shopping lists with prices & budget"),
    "clock_calendar": ("Clock & Calendar", "clock", "World clocks, timer, alarms"),
    "app_launcher": ("App Launcher", "launcher", "Fast executable shortcuts"),
    "dashboard": ("Command Center", "dashboard", "Main operations telemetry hub"),
    "my_computer": ("My Computer", "computer", "System overview & hardware"),
    "system_monitor": ("System Monitor", "system_monitor", "Live CPU, RAM & Disk charts"),
    "network_monitor": ("Network Monitor", "network_monitor", "Interface & bandwidth stats"),
    "process_manager": ("Process Manager", "process_manager", "Task & PID controller"),
    "startup_manager": ("Startup Manager", "startup_manager", "Boot app registry manager"),
    "disk_analyzer": ("Disk Analyzer", "pie_chart", "Storage breakdown & charts"),
    "disk_cleaner": ("Disk Cleaner", "cleaner", "Safe temp & cache cleaner"),
    "file_explorer": ("File Explorer", "file_explorer", "Directory browsing & launch"),
    "folder_organizer": ("Folder Organizer", "folder_organizer", "Rule-based file organizer"),
    "duplicate_finder": ("Duplicate Finder", "duplicate_finder", "Content-hash duplicate tool"),
    "large_file_finder": ("Large File Finder", "large_files", "Isolate heavy storage files"),
    "automation_center": ("Automation Center", "automation", "Scheduled task triggers"),
    "operation_history": ("Operation History", "history", "Action audit log & undo"),
    "settings": ("Settings", "settings", "Preferences, accounts & themes"),
}

# Sidebar groups: (group_id, title, icon, root_only, collapsed_by_default, module_ids).
# "Server" is the PC the smart home runs on: its OS tools are for root only.
NAV_GROUPS = [
    ("smart_home", "Smart Home", "home", False, False,
     ["smart_dashboard", "smart_home", "cctv", "widget_screen"]),
    ("apps", "Apps", "widgets", False, False,
     ["notes_tasks", "bills", "groceries", "clock_calendar", "app_launcher"]),
    ("server", "Server", "hard_drive", True, True,
     ["dashboard", "my_computer", "system_monitor", "network_monitor", "process_manager",
      "startup_manager", "disk_analyzer", "disk_cleaner", "file_explorer", "folder_organizer",
      "duplicate_finder", "large_file_finder", "automation_center", "operation_history"]),
]
PINNED = ["settings"]          # always shown under the groups

# Tuple format: (module_id, display_label, icon_name, description), in sidebar order.
# The main window adds its pages to the stack in this order.
MODULE_DEFINITIONS: List[Tuple[str, str, str, str]] = [
    (mid, *MODULES[mid]) for group in NAV_GROUPS for mid in group[5]
] + [(mid, *MODULES[mid]) for mid in PINNED]

ROOT_ONLY_MODULES = {mid for g in NAV_GROUPS if g[3] for mid in g[5]}


def module_allowed(module_id, role):
    return role == "root" or module_id not in ROOT_ONLY_MODULES


_NAV_BTN_QSS = """
    QPushButton#nav-btn {
        text-align: left;
        padding: 7px 12px;
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
"""

_GROUP_QSS = """
    QPushButton#nav-group {
        text-align: left;
        padding: 6px 8px 4px 8px;
        border: none;
        border-radius: 8px;
        color: #64748b;
        font-size: 10px;
        font-weight: 800;
        letter-spacing: 1.4px;
        background: transparent;
    }
    QPushButton#nav-group:hover { color: #cbd5e1; background: rgba(255,255,255,0.05); }
"""


class NavigationSidebar(QFrame):
    """Liquid glass sidebar: collapsible Smart Home / Apps / Server groups,
    Settings pinned below, the signed-in user and a lock button at the bottom."""

    module_selected = Signal(int, str)  # (index, module_id)
    lock_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(230)
        self.is_collapsed = False
        self.buttons: List[QPushButton] = []
        self.group_headers = {}
        self.group_of = {}
        self.role = "root"
        self._current_idx = 0
        db = Database.get_instance()
        stored = db.get_setting("nav_collapsed_groups", None)
        self.collapsed_groups = set(stored if isinstance(stored, list) else
                                    [g[0] for g in NAV_GROUPS if g[4]])
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 14, 8, 12)
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
        self.items_layout.setContentsMargins(0, 0, 0, 4)
        self.items_layout.setSpacing(3)

        index = {mid: i for i, (mid, *_rest) in enumerate(MODULE_DEFINITIONS)}
        self.buttons = [None] * len(MODULE_DEFINITIONS)
        for gid, title, icon, _root, _collapsed, mods in NAV_GROUPS:
            header = QPushButton()
            header.setObjectName("nav-group")
            header.setCursor(Qt.PointingHandCursor)
            header.setStyleSheet(_GROUP_QSS)
            header.setIconSize(QSize(12, 12))
            header.clicked.connect(lambda _=False, g=gid: self.toggle_group(g))
            self.group_headers[gid] = header
            self.items_layout.addSpacing(6)
            self.items_layout.addWidget(header)
            for mid in mods:
                self.group_of[mid] = gid
                self.items_layout.addWidget(self._make_button(index[mid], mid))
        self.items_layout.addSpacing(8)
        for mid in PINNED:
            self.items_layout.addWidget(self._make_button(index[mid], mid))

        self.items_layout.addStretch()
        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        # Signed-in user + lock
        self.user_box = QFrame()
        self.user_box.setObjectName("nav-user")
        self.user_box.setStyleSheet("QFrame#nav-user{background:rgba(255,255,255,0.05);border:1px solid "
                                    "rgba(255,255,255,0.10);border-radius:12px;}")
        ul = QHBoxLayout(self.user_box)
        ul.setContentsMargins(8, 6, 6, 6)
        ul.setSpacing(8)
        self.avatar = QLabel()
        self.avatar.setFixedSize(28, 28)
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setStyleSheet("background:#38bdf8;color:#04131d;border-radius:14px;"
                                  "font-weight:800;font-size:12px;")
        self.user_lbl = QLabel()
        self.user_lbl.setStyleSheet("color:#f8fafc;font-size:12px;font-weight:600;background:transparent;")
        self.lock_btn = QPushButton()
        self.lock_btn.setFixedSize(28, 28)
        self.lock_btn.setIcon(get_icon("lock", "#cbd5e1", 14))
        self.lock_btn.setToolTip("Lock (Ctrl+L)")
        self.lock_btn.setCursor(Qt.PointingHandCursor)
        self.lock_btn.setStyleSheet("QPushButton{background:transparent;border:none;border-radius:8px;}"
                                    "QPushButton:hover{background:rgba(255,255,255,0.12);}")
        self.lock_btn.clicked.connect(self.lock_requested.emit)
        ul.addWidget(self.avatar)
        ul.addWidget(self.user_lbl, 1)
        ul.addWidget(self.lock_btn)
        main_layout.addWidget(self.user_box)

        self._apply_groups()
        self._set_active_button(0)

    def _make_button(self, idx, mod_id):
        _, label, icon_name, desc = MODULE_DEFINITIONS[idx]
        btn = QPushButton(f"  {label}".replace("&", "&&"))
        btn.setObjectName("nav-btn")
        btn.setToolTip(desc)
        btn.setIcon(get_icon(icon_name, "#cbd5e1", 18))
        btn.setIconSize(QSize(18, 18))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(_NAV_BTN_QSS)
        btn.clicked.connect(lambda checked=False, i=idx, m=mod_id: self._on_module_clicked(i, m))
        self.buttons[idx] = btn
        return btn

    # ------------------------------------------------------------- groups --

    def toggle_group(self, gid):
        if gid in self.collapsed_groups:
            self.collapsed_groups.discard(gid)
        else:
            self.collapsed_groups.add(gid)
        try:
            Database.get_instance().set_setting("nav_collapsed_groups", sorted(self.collapsed_groups))
        except Exception:
            pass
        self._apply_groups()

    def expand_group_of(self, module_id):
        gid = self.group_of.get(module_id)
        if gid in self.collapsed_groups:
            self.toggle_group(gid)

    def _apply_groups(self):
        for gid, title, icon, root_only, _c, mods in NAV_GROUPS:
            allowed = self.role == "root" or not root_only
            collapsed = gid in self.collapsed_groups
            header = self.group_headers[gid]
            header.setVisible(allowed)
            if self.is_collapsed:
                header.setText("")
                header.setIcon(get_icon(icon, "#64748b", 12))
                header.setToolTip(f"{title} ({'show' if collapsed else 'hide'})")
            else:
                header.setText(f"  {title.upper()}" + (f"   · {len(mods)}" if collapsed else ""))
                header.setIcon(get_icon("chevron_right" if collapsed else "chevron_down", "#64748b", 12))
                header.setToolTip(f"{'Show' if collapsed else 'Hide'} {title}")
            for mid in mods:
                idx = next(i for i, m in enumerate(MODULE_DEFINITIONS) if m[0] == mid)
                self.buttons[idx].setVisible(allowed and not collapsed)

    # --------------------------------------------------------------- user --

    def set_user(self, user):
        self.role = user.get("role", "user")
        name = user.get("username", "")
        self.avatar.setText(name[:1].upper())
        self.user_lbl.setText(f"{name}<br><span style='color:#64748b;font-size:10px;font-weight:600'>"
                              f"{'root access' if self.role == 'root' else 'user'}</span>")
        self.user_lbl.setVisible(not self.is_collapsed)
        self._apply_groups()

    # ------------------------------------------------------------ buttons --

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
        self.user_lbl.setVisible(not self.is_collapsed)
        self.avatar.setVisible(not self.is_collapsed)      # the narrow rail keeps just the lock
        self._apply_groups()

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
    "fridge": ("Fridge", "fridge", "What's in the fridge, counted from photos"),
    "widget_screen": ("Widget Screen", "widgets", "Live liquid glass desktop & lock widgets"),
    "smart_devices": ("Smart Devices", "plug", "Smart plugs, sockets, bulbs & switches found on the Wi-Fi"),
    "notes_tasks": ("Notes & Tasks", "notes", "Notes and to-dos"),
    "bills": ("Bills", "file_text", "Household bills, due dates & split"),
    "groceries": ("Groceries", "check_square", "Shopping lists with prices & budget"),
    "clock_calendar": ("Clock & Calendar", "clock", "World clocks, timer, alarms"),
    "app_launcher": ("App Launcher", "launcher", "Fast executable shortcuts"),
    "dashboard": ("Command Center", "dashboard", "Main operations telemetry hub"),
    "services": ("Services", "layers", "Background services, watchdog & logs"),
    "my_computer": ("My Computer", "computer", "System overview & hardware"),
    "lan_devices": ("Wi-Fi Devices", "wifi", "Every device on the home network"),
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

# Home network sidebar: collapsible groups (group_id, title, icon, collapsed_by_default, module_ids)
NAV_GROUPS = [
    ("smart_home", "Smart Home", "home", False,
     ["smart_dashboard", "smart_home", "smart_devices", "cctv", "fridge", "widget_screen"]),
    ("apps", "Apps", "widgets", False,
     ["notes_tasks", "bills", "groceries", "clock_calendar", "app_launcher"]),
]

# Server console sidebar (the PC the smart home runs on): sections (title, module_ids). Root only.
SERVER_SECTIONS = [
    ("Overview", ["dashboard", "services", "my_computer", "system_monitor", "network_monitor", "lan_devices"]),
    ("Processes & automation", ["process_manager", "startup_manager", "automation_center"]),
    ("Storage & files", ["disk_analyzer", "disk_cleaner", "file_explorer", "folder_organizer",
                         "duplicate_finder", "large_file_finder"]),
    ("Logs", ["operation_history"]),
]
PINNED = ["settings"]          # shown in both modes, under everything else

# Tuple format: (module_id, display_label, icon_name, description), in sidebar order.
# The main window adds its pages to the stack in this order.
MODULE_DEFINITIONS: List[Tuple[str, str, str, str]] = (
    [(mid, *MODULES[mid]) for g in NAV_GROUPS for mid in g[4]]
    + [(mid, *MODULES[mid]) for _t, mods in SERVER_SECTIONS for mid in mods]
    + [(mid, *MODULES[mid]) for mid in PINNED]
)

SERVER_MODULES = {mid for _t, mods in SERVER_SECTIONS for mid in mods}
ROOT_ONLY_MODULES = SERVER_MODULES
HOME_MODE, SERVER_MODE = "home", "server"


def module_allowed(module_id, role):
    return role == "root" or module_id not in ROOT_ONLY_MODULES


def module_mode(module_id):
    """Which sidebar a page belongs to (None for pages shown in both)."""
    if module_id in SERVER_MODULES:
        return SERVER_MODE
    if module_id in PINNED:
        return None
    return HOME_MODE


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
        background: rgba(%s, 0.20);
        border: 1px solid rgba(%s, 0.35);
        color: #ffffff;
        font-weight: 600;
    }
"""
_HOME_RGB, _SERVER_RGB = "56, 189, 248", "34, 197, 94"

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

_SECTION_QSS = "color:#4b6b5a;font-size:10px;font-weight:800;letter-spacing:1.4px;padding:8px 8px 2px 8px;" \
               "background:transparent;"


class NavigationSidebar(QFrame):
    """Liquid glass sidebar with two modes.

    home    Smart Home and Apps groups (collapsible) plus a "Server" button that
            opens the server console (root only)
    server  the server tools in sections, a "Return to Home" button, green accent
    Settings is pinned in both; the signed-in user and a lock button sit at the bottom.
    """

    module_selected = Signal(int, str)  # (index, module_id)
    lock_requested = Signal()
    server_requested = Signal()
    home_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(230)
        self.is_collapsed = False
        self.mode = HOME_MODE
        self.buttons: List[QPushButton] = []
        self.group_headers = {}
        self.section_labels = []
        self.group_of = {}
        self.role = "root"
        self._current_idx = 0
        stored = Database.get_instance().get_setting("nav_collapsed_groups", None)
        self.collapsed_groups = set(stored if isinstance(stored, list) else
                                    [g[0] for g in NAV_GROUPS if g[3]]) - {"server"}
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 14, 8, 12)
        main_layout.setSpacing(8)

        # Header with collapse toggle
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(6, 0, 4, 4)

        self.brand_icon = QLabel()
        top_bar.addWidget(self.brand_icon)
        self.nav_title = QLabel()
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

        index = {m[0]: i for i, m in enumerate(MODULE_DEFINITIONS)}
        self.buttons = [None] * len(MODULE_DEFINITIONS)

        # -- home groups
        for gid, title, icon, _collapsed, mods in NAV_GROUPS:
            header = QPushButton()
            header.setObjectName("nav-group")
            header.setCursor(Qt.PointingHandCursor)
            header.setStyleSheet(_GROUP_QSS)
            header.setIconSize(QSize(12, 12))
            header.clicked.connect(lambda _=False, g=gid: self.toggle_group(g))
            self.group_headers[gid] = header
            self.items_layout.addWidget(header)
            for mid in mods:
                self.group_of[mid] = gid
                self.items_layout.addWidget(self._make_button(index[mid], mid))

        # -- the way into the server console (home mode, root only)
        self.server_btn = QPushButton("  Server")
        self.server_btn.setObjectName("nav-server")
        self.server_btn.setIcon(get_icon("hard_drive", "#22c55e", 18))
        self.server_btn.setIconSize(QSize(18, 18))
        self.server_btn.setCursor(Qt.PointingHandCursor)
        self.server_btn.setToolTip("Open the server console: the PC this smart home runs on")
        self.server_btn.setStyleSheet("""
            QPushButton#nav-server {
                text-align: left; padding: 9px 12px; margin-top: 10px; border-radius: 10px;
                border: 1px solid rgba(34, 197, 94, 0.35); background: rgba(34, 197, 94, 0.10);
                color: #dcfce7; font-size: 12px; font-weight: 700;
            }
            QPushButton#nav-server:hover { background: rgba(34, 197, 94, 0.20); }
        """)
        self.server_btn.clicked.connect(lambda: self.server_requested.emit())
        self.items_layout.addWidget(self.server_btn)

        # -- server sections (server mode)
        for title, mods in SERVER_SECTIONS:
            lbl = QLabel(title.upper())
            lbl.setStyleSheet(_SECTION_QSS)
            self.section_labels.append(lbl)
            self.items_layout.addWidget(lbl)
            for mid in mods:
                self.items_layout.addWidget(self._make_button(index[mid], mid))

        self.items_layout.addSpacing(8)
        for mid in PINNED:
            self.items_layout.addWidget(self._make_button(index[mid], mid))
        self.items_layout.addStretch()
        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        # -- back to the home network (server mode)
        self.home_btn = QPushButton("  Return to Home")
        self.home_btn.setObjectName("nav-home")
        self.home_btn.setIcon(get_icon("home", "#04131d", 16))
        self.home_btn.setCursor(Qt.PointingHandCursor)
        self.home_btn.setToolTip("Leave the server console and go back to the Smart Home screens")
        self.home_btn.setStyleSheet("""
            QPushButton#nav-home {
                text-align: left; padding: 9px 12px; border-radius: 10px; border: none;
                background: #38bdf8; color: #04131d; font-size: 12px; font-weight: 800;
            }
            QPushButton#nav-home:hover { background: #7dd3fc; }
        """)
        self.home_btn.clicked.connect(lambda: self.home_requested.emit())
        main_layout.addWidget(self.home_btn)

        # -- signed-in user + lock
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
        self.user_lbl = QLabel()
        self.user_lbl.setStyleSheet("color:#f8fafc;font-size:12px;font-weight:600;background:transparent;")
        self.lock_btn = QPushButton()
        self.lock_btn.setFixedSize(28, 28)
        self.lock_btn.setIcon(get_icon("lock", "#cbd5e1", 14))
        self.lock_btn.setToolTip("Lock (Ctrl+L)")
        self.lock_btn.setCursor(Qt.PointingHandCursor)
        self.lock_btn.setStyleSheet("QPushButton{background:transparent;border:none;border-radius:8px;}"
                                    "QPushButton:hover{background:rgba(255,255,255,0.12);}")
        self.lock_btn.clicked.connect(lambda: self.lock_requested.emit())
        ul.addWidget(self.avatar)
        ul.addWidget(self.user_lbl, 1)
        ul.addWidget(self.lock_btn)
        main_layout.addWidget(self.user_box)

        self.set_mode(HOME_MODE)
        self._set_active_button(0)

    def _make_button(self, idx, mod_id):
        _, label, icon_name, desc = MODULE_DEFINITIONS[idx]
        btn = QPushButton(f"  {label}".replace("&", "&&"))
        btn.setObjectName("nav-btn")
        btn.setToolTip(desc)
        btn.setIconSize(QSize(18, 18))
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda checked=False, i=idx, m=mod_id: self._on_module_clicked(i, m))
        self.buttons[idx] = btn
        return btn

    # --------------------------------------------------------------- modes --

    def set_mode(self, mode):
        self.mode = mode
        server = mode == SERVER_MODE
        accent = "#22c55e" if server else "#38bdf8"
        rgb = _SERVER_RGB if server else _HOME_RGB
        self.brand_icon.setPixmap(get_pixmap("hard_drive" if server else "widgets", accent, 18))
        self.nav_title.setText("SERVER" if server else "CYPHER-X")
        self.nav_title.setStyleSheet(f"color:{'#dcfce7' if server else '#ffffff'};font-size:12px;"
                                     "font-weight:800;letter-spacing:2px;")
        self.avatar.setStyleSheet(f"background:{accent};color:#04131d;border-radius:14px;"
                                  "font-weight:800;font-size:12px;")
        qss = _NAV_BTN_QSS % (rgb, rgb)
        for b in self.buttons:
            b.setStyleSheet(qss)
        self.setProperty("mode", mode)
        self._apply_groups()
        self._set_active_button(self._current_idx)

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
        home = self.mode == HOME_MODE
        index = {m[0]: i for i, m in enumerate(MODULE_DEFINITIONS)}
        for gid, title, icon, _c, mods in NAV_GROUPS:
            collapsed = gid in self.collapsed_groups
            header = self.group_headers[gid]
            header.setVisible(home)
            if self.is_collapsed:
                header.setText("")
                header.setIcon(get_icon(icon, "#64748b", 12))
                header.setToolTip(f"{title} ({'show' if collapsed else 'hide'})")
            else:
                header.setText(f"  {title.upper()}" + (f"   · {len(mods)}" if collapsed else ""))
                header.setIcon(get_icon("chevron_right" if collapsed else "chevron_down", "#64748b", 12))
                header.setToolTip(f"{'Show' if collapsed else 'Hide'} {title}")
            for mid in mods:
                self.buttons[index[mid]].setVisible(home and not collapsed)
        self.server_btn.setVisible(home and self.role == "root")
        self.server_btn.setText("" if self.is_collapsed else "  Server")
        for lbl in self.section_labels:
            lbl.setVisible(not home and not self.is_collapsed)
        for mid in SERVER_MODULES:
            self.buttons[index[mid]].setVisible(not home)
        self.home_btn.setVisible(not home)
        self.home_btn.setText("" if self.is_collapsed else "  Return to Home")

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
        accent = "#22c55e" if self.mode == SERVER_MODE else "#38bdf8"
        for i, btn in enumerate(self.buttons):
            is_active = (i == index)
            btn.setProperty("active", "true" if is_active else "false")
            btn.setIcon(get_icon(MODULE_DEFINITIONS[i][2], accent if is_active else "#94a3b8", 18))
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        if self.is_collapsed:
            self.setFixedWidth(64)
            self.nav_title.setVisible(False)
            self.brand_icon.setVisible(False)
            self.collapse_btn.setIcon(get_icon("chevron_right", "#94a3b8", 16))
            for btn in self.buttons:
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

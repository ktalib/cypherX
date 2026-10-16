"""
Settings — every option here takes effect immediately and is saved automatically.
"""
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QComboBox,
    QCheckBox, QFrame, QScrollArea, QMessageBox, QSlider
)

from app.config import DB_PATH, USER_DATA_DIR
from app.database import Database

try:
    import winreg
except ImportError:  # non-Windows
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "CYPHER-X"

DEFAULTS = {
    "pref_rate": 1500,
    "pref_backdrop_dim": 66,
    "pref_right_panel": True,
    "pref_sidebar_collapsed": False,
    "pref_home_fullscreen": False,
    "pref_recycle": True,
    "pref_confirm": True,
    "pref_close_to_tray": False,
}


def get_pref(key):
    return Database.get_instance().get_setting(key, DEFAULTS[key])


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    main = Path(__file__).resolve().parent.parent.parent / "main.py"
    return f'"{pyw if pyw.exists() else exe}" "{main}"'


def autostart_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(on: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass


class SettingsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = True
        self._build()
        self._loading = False

    # ------------------------------------------------------------------ UI --

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        head = QFrame()
        head.setObjectName("panel")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(14, 10, 14, 10)
        t = QLabel("SETTINGS // PREFERENCES")
        t.setObjectName("section-header")
        hl.addWidget(t)
        hl.addStretch()
        self.saved_lbl = QLabel("Changes apply instantly and are saved automatically")
        self.saved_lbl.setStyleSheet("color:#64748b;font-size:11px;background:transparent;")
        hl.addWidget(self.saved_lbl)
        root.addWidget(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        cols = QHBoxLayout(body)
        cols.setContentsMargins(0, 0, 4, 0)
        cols.setSpacing(12)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.setSpacing(12)
        right.setSpacing(12)
        cols.addLayout(left, 1)
        cols.addLayout(right, 1)

        left.addWidget(self._appearance_card())
        left.addWidget(self._home_card())
        left.addStretch()
        right.addWidget(self._system_card())
        right.addWidget(self._safety_card())
        right.addWidget(self._data_card())
        right.addStretch()

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

    def _card(self, title, subtitle=""):
        card = QFrame()
        card.setObjectName("panel")
        lo = QVBoxLayout(card)
        lo.setContentsMargins(16, 14, 16, 14)
        lo.setSpacing(10)
        h = QLabel(title.upper())
        h.setStyleSheet("color:#38bdf8;font-size:11px;font-weight:800;letter-spacing:1.2px;background:transparent;")
        lo.addWidget(h)
        if subtitle:
            s = QLabel(subtitle)
            s.setWordWrap(True)
            s.setStyleSheet("color:#64748b;font-size:11px;background:transparent;")
            lo.addWidget(s)
        return card, lo

    @staticmethod
    def _hint(text):
        l = QLabel(text)
        l.setWordWrap(True)
        l.setStyleSheet("color:#64748b;font-size:11px;margin-left:24px;background:transparent;")
        return l

    def _appearance_card(self):
        card, lo = self._card("Appearance", "Tool pages sit on a blurred copy of your Home wallpaper.")
        row = QHBoxLayout()
        row.addWidget(QLabel("Background darkness"))
        self.dim = QSlider(Qt.Horizontal)
        self.dim.setRange(30, 95)
        self.dim.setValue(int(get_pref("pref_backdrop_dim")))
        self.dim_val = QLabel(f"{self.dim.value()}%")
        self.dim_val.setFixedWidth(40)
        self.dim.valueChanged.connect(self._on_dim)
        row.addWidget(self.dim, 1)
        row.addWidget(self.dim_val)
        lo.addLayout(row)

        self.cb_panel = QCheckBox("Show the System Specification panel on tool pages")
        self.cb_panel.setChecked(bool(get_pref("pref_right_panel")))
        self.cb_panel.toggled.connect(self._on_panel)
        lo.addWidget(self.cb_panel)

        self.cb_sidebar = QCheckBox("Start with the navigation sidebar collapsed")
        self.cb_sidebar.setChecked(bool(get_pref("pref_sidebar_collapsed")))
        self.cb_sidebar.toggled.connect(lambda on: self._save("pref_sidebar_collapsed", on))
        lo.addWidget(self.cb_sidebar)
        return card

    def _home_card(self):
        card, lo = self._card("Home screen")
        self.cb_fs = QCheckBox("Open the Home screen in full screen when CYPHER-X starts")
        self.cb_fs.setChecked(bool(get_pref("pref_home_fullscreen")))
        self.cb_fs.toggled.connect(lambda on: self._save("pref_home_fullscreen", on))
        lo.addWidget(self.cb_fs)

        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.addWidget(QLabel("Change wallpaper every"), 0, 0)
        self.wp_interval = QComboBox()
        for secs, text in [(10, "10 seconds"), (30, "30 seconds"), (60, "1 minute"),
                           (300, "5 minutes"), (900, "15 minutes"), (3600, "1 hour")]:
            self.wp_interval.addItem(text, secs)
        g.addWidget(self.wp_interval, 0, 1)
        lo.addLayout(g)

        self.cb_online = QCheckBox("Auto-load new wallpapers from the internet")
        lo.addWidget(self.cb_online)
        self.cb_shuffle = QCheckBox("Shuffle wallpapers")
        lo.addWidget(self.cb_shuffle)

        manage = QPushButton("Manage Wallpapers…")
        manage.clicked.connect(self._open_wallpapers)
        lo.addWidget(manage, 0, Qt.AlignLeft)

        QTimer.singleShot(0, self._bind_wallpapers)
        return card

    def _system_card(self):
        card, lo = self._card("System")
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.addWidget(QLabel("Live telemetry refresh"), 0, 0)
        self.rate = QComboBox()
        for ms, text in [(1000, "Fast — every 1 s"), (1500, "Balanced — every 1.5 s"), (3000, "Power saver — every 3 s")]:
            self.rate.addItem(text, ms)
        self.rate.setCurrentIndex(max(0, self.rate.findData(int(get_pref("pref_rate")))))
        self.rate.currentIndexChanged.connect(self._on_rate)
        g.addWidget(self.rate, 0, 1)
        lo.addLayout(g)

        self.cb_autostart = QCheckBox("Launch CYPHER-X when I sign in to Windows")
        self.cb_autostart.setEnabled(winreg is not None)
        self.cb_autostart.setChecked(autostart_enabled())
        self.cb_autostart.toggled.connect(self._on_autostart)
        lo.addWidget(self.cb_autostart)
        lo.addWidget(self._hint("Adds an entry under your user's Startup apps (no admin rights needed)."))

        self.cb_tray = QCheckBox("Keep running in the system tray when the window is closed")
        self.cb_tray.setChecked(bool(get_pref("pref_close_to_tray")))
        self.cb_tray.toggled.connect(lambda on: self._save("pref_close_to_tray", on))
        lo.addWidget(self.cb_tray)
        lo.addWidget(self._hint("Music, alarms and automations keep working. Quit from the tray icon menu."))
        return card

    def _safety_card(self):
        card, lo = self._card("Safety")
        self.cb_recycle = QCheckBox("Prefer the Recycle Bin over permanent deletion")
        self.cb_recycle.setChecked(bool(get_pref("pref_recycle")))
        self.cb_recycle.toggled.connect(lambda on: self._save("pref_recycle", on))
        lo.addWidget(self.cb_recycle)
        self.cb_confirm = QCheckBox("Ask for confirmation before destructive operations")
        self.cb_confirm.setChecked(bool(get_pref("pref_confirm")))
        self.cb_confirm.toggled.connect(lambda on: self._save("pref_confirm", on))
        lo.addWidget(self.cb_confirm)
        locked = QCheckBox("Protect Windows system folders and critical processes")
        locked.setChecked(True)
        locked.setEnabled(False)
        lo.addWidget(locked)
        lo.addWidget(self._hint("Always on — cannot be disabled."))
        return card

    def _data_card(self):
        card, lo = self._card("Data")
        path = QLabel(str(DB_PATH))
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path.setWordWrap(True)
        path.setStyleSheet("color:#cbd5e1;font-size:11px;font-family:'Cascadia Mono','Consolas',monospace;background:transparent;")
        lo.addWidget(path)
        row = QHBoxLayout()
        open_btn = QPushButton("Open Data Folder")
        open_btn.clicked.connect(lambda: os.startfile(str(USER_DATA_DIR)))
        clear_btn = QPushButton("Clear Operation History")
        clear_btn.setObjectName("danger-btn")
        clear_btn.clicked.connect(self._clear_history)
        row.addWidget(open_btn)
        row.addWidget(clear_btn)
        row.addStretch()
        lo.addLayout(row)
        return card

    # ------------------------------------------------------------- actions --

    def _save(self, key, value):
        Database.get_instance().set_setting(key, value)
        if not self._loading:
            self.saved_lbl.setText("Saved ✓")
            self.saved_lbl.setStyleSheet("color:#34d399;font-size:11px;font-weight:700;background:transparent;")
            QTimer.singleShot(1600, lambda: (
                self.saved_lbl.setText("Changes apply instantly and are saved automatically"),
                self.saved_lbl.setStyleSheet("color:#64748b;font-size:11px;background:transparent;")))

    def _on_dim(self, v):
        self.dim_val.setText(f"{v}%")
        win = self.window()
        if hasattr(win, "backdrop"):
            win.backdrop.set_dim(v)
        self._save("pref_backdrop_dim", v)

    def _on_panel(self, on):
        self._save("pref_right_panel", on)
        win = self.window()
        if hasattr(win, "right_panel"):
            win.right_panel.setVisible(on)

    def _on_rate(self):
        ms = self.rate.currentData()
        self._save("pref_rate", ms)
        win = self.window()
        if hasattr(win, "metrics_timer"):
            win.metrics_timer.setInterval(ms)

    def _on_autostart(self, on):
        try:
            set_autostart(on)
            self._save("pref_autostart", on)
        except OSError as e:
            QMessageBox.warning(self, "Startup", f"Couldn't change the startup entry:\n{e}")
            self.cb_autostart.blockSignals(True)
            self.cb_autostart.setChecked(autostart_enabled())
            self.cb_autostart.blockSignals(False)

    def _clear_history(self):
        if QMessageBox.question(self, "Clear History",
                                "Delete the entire operation history? This cannot be undone.") == QMessageBox.Yes:
            Database.get_instance().clear_operation_history()
            self._save("history_cleared", True)

    # ---- wallpaper settings are shared with the Home screen ----

    def _wallpapers(self):
        win = self.window()
        view = getattr(win, "view_widget_screen", None)
        return getattr(view, "wallpapers", None)

    def _bind_wallpapers(self):
        wp = self._wallpapers()
        if wp is None:
            return
        idx = self.wp_interval.findData(wp.interval)
        if idx < 0:
            self.wp_interval.addItem(f"{wp.interval} seconds", wp.interval)
            idx = self.wp_interval.count() - 1
        self.wp_interval.setCurrentIndex(idx)
        self.cb_online.setChecked(wp.online)
        self.cb_shuffle.setChecked(wp.shuffle)
        self.wp_interval.currentIndexChanged.connect(lambda: wp.set_interval(self.wp_interval.currentData()))
        self.cb_online.toggled.connect(lambda on: wp.set_online(on))
        self.cb_shuffle.toggled.connect(wp.set_shuffle)
        wp.state_changed.connect(self._sync_wallpapers)

    def _sync_wallpapers(self):
        wp = self._wallpapers()
        for w, val in ((self.cb_online, wp.online), (self.cb_shuffle, wp.shuffle)):
            w.blockSignals(True)
            w.setChecked(val)
            w.blockSignals(False)

    def _open_wallpapers(self):
        view = getattr(self.window(), "view_widget_screen", None)
        if view:
            view.open_wallpaper_dialog()

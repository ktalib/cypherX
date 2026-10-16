"""
Automation Center — scheduled watchdogs that really run while CYPHER-X is open.

Every rule is read-only / non-destructive: it measures something and notifies you
(Windows notification + terminal + Operation History). Nothing is moved or deleted.
"""
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import psutil
from PySide6.QtCore import Qt, QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame
)

from app.database import Database
from app.widgets.terminal_panel import TerminalPanel

STARTUP = 0
# id, name, schedule label, interval seconds, description, default enabled
RULES = [
    ("disk_alert", "Low disk space alert", "Every 15 minutes", 900,
     "Notify when the system drive has less than 10 GB free", True),
    ("ram_alert", "High memory alert", "Every 5 minutes", 300,
     "Notify when RAM usage stays above 90%", True),
    ("battery_alert", "Low battery alert", "Every 5 minutes", 300,
     "Notify when running on battery below 20%", True),
    ("auto_downloads", "Downloads tidiness check", "When CYPHER-X starts", STARTUP,
     "Count loose files in Downloads and suggest the Folder Organizer (nothing is moved)", False),
    ("temp_cleanup", "Temp space report", "Daily", 86400,
     "Measure how much space old temp files use", False),
    ("sys_report", "Hardware snapshot", "Weekly", 604800,
     "Record CPU / RAM / disk usage to Operation History", False),
]


def _fmt_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"


class AutomationEngine(QObject):
    """Runs due rules once a minute; slow checks run on a worker thread."""

    notify = Signal(str, str)        # title, message
    ran = Signal(str)                # rule id

    def __init__(self, parent=None):
        super().__init__(parent)
        db = Database.get_instance()
        saved = db.get_setting("automation_rules", [])
        enabled = {r.get("id"): r.get("enabled") for r in saved if isinstance(r, dict)}
        self.enabled = {rid: enabled.get(rid, default) for rid, *_, default in RULES}
        self.last_run = db.get_setting("automation_last_run", {})
        self._busy = set()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check_due)
        self._timer.start(60_000)
        QTimer.singleShot(8000, self._run_startup)

    def save(self):
        db = Database.get_instance()
        db.set_setting("automation_rules", [{"id": r, "enabled": e} for r, e in self.enabled.items()])
        db.set_setting("automation_last_run", self.last_run)

    def _run_startup(self):
        for rid, _, _, interval, _, _ in RULES:
            if interval == STARTUP and self.enabled.get(rid):
                self.run(rid)
        self.check_due()

    def check_due(self):
        now = time.time()
        for rid, _, _, interval, _, _ in RULES:
            if interval == STARTUP or not self.enabled.get(rid):
                continue
            last = self.last_run.get(rid, {}).get("ts", 0)
            if now - last >= interval:
                self.run(rid)

    def run(self, rid):
        if rid in self._busy:
            return
        self._busy.add(rid)
        threading.Thread(target=self._worker, args=(rid,), daemon=True).start()

    def _worker(self, rid):
        try:
            result, alert = getattr(self, f"_rule_{rid}")()
        except Exception as e:  # never let a watchdog crash the app
            result, alert = f"Error: {e}", None
        self.last_run[rid] = {"ts": time.time(), "result": result}
        self._busy.discard(rid)
        if alert:
            self.notify.emit(*alert)
        self.ran.emit(rid)

    # ---- rules (run on worker thread; must not touch widgets) ----

    @staticmethod
    def _rule_disk_alert():
        drive = os.environ.get("SystemDrive", "C:") + "\\"
        free = psutil.disk_usage(drive).free
        msg = f"{_fmt_size(free)} free on {drive}"
        if free < 10 * 1024 ** 3:
            return msg, ("Low disk space", f"Only {msg}. Try Disk Cleaner or Large File Finder.")
        return msg, None

    @staticmethod
    def _rule_ram_alert():
        first = psutil.virtual_memory().percent
        time.sleep(5)
        second = psutil.virtual_memory().percent
        msg = f"RAM at {second:.0f}%"
        if first > 90 and second > 90:
            return msg, ("High memory usage", f"{msg}. Process Manager shows what is using it.")
        return msg, None

    @staticmethod
    def _rule_battery_alert():
        bat = psutil.sensors_battery()
        if bat is None:
            return "No battery (desktop / AC power)", None
        msg = f"Battery {bat.percent:.0f}%{' (charging)' if bat.power_plugged else ''}"
        if not bat.power_plugged and bat.percent < 20:
            return msg, ("Battery low", f"{msg} — plug in your charger.")
        return msg, None

    @staticmethod
    def _rule_auto_downloads():
        dl = Path.home() / "Downloads"
        if not dl.is_dir():
            return "No Downloads folder", None
        files = [p for p in dl.iterdir() if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        msg = f"{len(files)} loose files ({_fmt_size(size)}) in Downloads"
        if len(files) >= 25:
            return msg, ("Downloads is getting messy", f"{msg}. Open Folder Organizer to sort them.")
        return msg, None

    @staticmethod
    def _rule_temp_cleanup():
        temp = Path(os.environ.get("TEMP", Path.home() / "AppData" / "Local" / "Temp"))
        cutoff = time.time() - 86400
        total = count = 0
        for root, _dirs, files in os.walk(temp):
            for f in files:
                try:
                    st = os.stat(os.path.join(root, f))
                except OSError:
                    continue
                if st.st_mtime < cutoff:
                    total += st.st_size
                    count += 1
        msg = f"{_fmt_size(total)} in {count} temp files older than 24 h"
        if total > 1024 ** 3:
            return msg, ("Temp files piling up", f"{msg}. Disk Cleaner can recycle them safely.")
        return msg, None

    @staticmethod
    def _rule_sys_report():
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\").percent
        msg = f"CPU {cpu:.0f}% · RAM {ram:.0f}% · Disk {disk:.0f}%"
        Database.get_instance().log_operation(
            operation_type="Automation", action="Hardware snapshot", result=msg, target_path="")
        return msg, None


class AutomationCenterView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = AutomationEngine(self)
        self.engine.notify.connect(self._on_notify)
        self.engine.ran.connect(self._on_ran)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        title_box = QFrame()
        title_box.setObjectName("panel")
        tb_l = QHBoxLayout(title_box)
        tb_l.setContentsMargins(14, 10, 14, 10)
        title = QLabel("AUTOMATION CENTER // WATCHDOGS & SCHEDULED CHECKS")
        title.setObjectName("section-header")
        tb_l.addWidget(title)
        main_layout.addWidget(title_box)

        desc_card = QFrame()
        desc_card.setObjectName("panel")
        dcl = QHBoxLayout(desc_card)
        dcl.setContentsMargins(14, 8, 14, 8)
        desc_lbl = QLabel("Enabled rules run automatically while CYPHER-X is open — turn on \"Keep running in "
                          "the system tray\" in Settings to keep them working after you close the window. Rules "
                          "only measure and notify; they never move or delete files.")
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        dcl.addWidget(desc_lbl)
        main_layout.addWidget(desc_card)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Rule", "Schedule", "What it does", "Last result", "", ""])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.Fixed)
        hh.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 86)
        self.table.setColumnWidth(5, 86)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        main_layout.addWidget(self.table, 1)
        QTimer.singleShot(0, lambda: self.table.setTextElideMode(Qt.ElideRight))
        self._render_table()

    def _render_table(self):
        self.table.setRowCount(len(RULES))
        for row, (rid, name, sched, _iv, desc, _d) in enumerate(RULES):
            on = self.engine.enabled.get(rid, False)
            name_item = QTableWidgetItem(name)
            name_item.setForeground(Qt.white if on else Qt.gray)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(sched))
            d = QTableWidgetItem(desc)
            d.setToolTip(desc)
            self.table.setItem(row, 2, d)
            last = self.engine.last_run.get(rid)
            if last:
                when = datetime.fromtimestamp(last["ts"]).strftime("%d %b %H:%M")
                res = QTableWidgetItem(f"{when} — {last['result']}")
                res.setToolTip(res.text())
            else:
                res = QTableWidgetItem("Not run yet")
                res.setForeground(Qt.gray)
            self.table.setItem(row, 3, res)

            toggle = QPushButton("On" if on else "Off")
            toggle.setObjectName("action-btn-primary" if on else "")
            toggle.setFixedHeight(24)
            toggle.setToolTip("Disable rule" if on else "Enable rule")
            toggle.clicked.connect(lambda _=False, r=rid: self._toggle_rule(r))
            run = QPushButton("Run now")
            run.setFixedHeight(24)
            run.clicked.connect(lambda _=False, r=rid: self._run_now(r))
            for col, b in ((4, toggle), (5, run)):
                holder = QWidget()
                hl = QHBoxLayout(holder)
                hl.setContentsMargins(4, 0, 4, 0)
                hl.addWidget(b)
                self.table.setCellWidget(row, col, holder)

    def _toggle_rule(self, rid):
        self.engine.enabled[rid] = not self.engine.enabled.get(rid, False)
        self.engine.save()
        self._render_table()
        term = TerminalPanel.get_instance()
        if term:
            term.log_info(f"Automation '{rid}' {'enabled' if self.engine.enabled[rid] else 'disabled'}.")
        if self.engine.enabled[rid]:
            self.engine.check_due()

    def _run_now(self, rid):
        row = [r[0] for r in RULES].index(rid)
        item = QTableWidgetItem("Running…")
        self.table.setItem(row, 3, item)
        self.engine.run(rid)

    def _on_ran(self, rid):
        self.engine.save()
        self._render_table()
        term = TerminalPanel.get_instance()
        last = self.engine.last_run.get(rid, {})
        if term and last:
            term.log_info(f"Automation {rid}: {last.get('result')}")

    def _on_notify(self, title, message):
        win = self.window()
        if hasattr(win, "notify"):
            win.notify(title, message)
        term = TerminalPanel.get_instance()
        if term:
            term.log_warning(f"{title}: {message}")
        Database.get_instance().log_operation(
            operation_type="Automation", action=title, result=message, target_path="")

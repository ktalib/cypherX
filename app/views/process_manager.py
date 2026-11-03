"""
Process Manager — live, Task-Manager-style process list.

Sampling runs on a background thread every 2 s (CPU % needs two samples, so the
sampler keeps psutil's process cache warm). The table can be grouped by app,
sorted by any column, and every row has a context menu.

The table is model-based: a refresh swaps the row list and Qt asks only for the
rows on screen, instead of building a cell object for every process every tick.
"""
import os
import subprocess
import threading
import time
import webbrowser
from urllib.parse import quote_plus

import psutil
from PySide6.QtCore import Qt, QObject, QTimer, Signal, QFileInfo, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor, QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTableView,
    QHeaderView, QFrame, QCheckBox, QMessageBox, QFileIconProvider, QAbstractItemView
)

from app.icons import get_icon
from app.services.process_service import ProcessService
from app.widgets.confirmation_dialog import CyberConfirmationDialog
from app.widgets.terminal_panel import TerminalPanel
from app.widgets.home.common import make_menu, hicon
from app.database import Database

PRIORITIES = [
    ("Low", getattr(psutil, "IDLE_PRIORITY_CLASS", 19)),
    ("Below normal", getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", 10)),
    ("Normal", getattr(psutil, "NORMAL_PRIORITY_CLASS", 0)),
    ("Above normal", getattr(psutil, "ABOVE_NORMAL_PRIORITY_CLASS", -5)),
    ("High", getattr(psutil, "HIGH_PRIORITY_CLASS", -10)),
]
COLUMNS = ["Name", "PID", "CPU", "Memory", "Threads", "Status", "Location"]
SORT_KEYS = {0: "name", 1: "pid", 2: "cpu", 3: "mem", 4: "threads", 5: "status", 6: "exe"}


class ProcessSampler(QObject):
    sampled = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ncpu = psutil.cpu_count() or 1
        self._busy = False

    def sample(self):
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        rows = []
        try:
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "exe",
                                          "status", "num_threads"]):
                try:
                    i = p.info
                    pid = i["pid"]
                    name = i.get("name") or f"PID {pid}"
                    rows.append({
                        "pid": pid,
                        "name": name,
                        "cpu": 0.0 if pid == 0 else (i.get("cpu_percent") or 0.0) / self._ncpu,
                        "mem": i["memory_info"].rss if i.get("memory_info") else 0,
                        "exe": i.get("exe") or "",
                        "status": (i.get("status") or "running").capitalize(),
                        "threads": i.get("num_threads") or 0,
                        "protected": ProcessService.is_protected_process(name, pid),
                        "count": 1,
                    })
                except (psutil.Error, KeyError):
                    continue
        finally:
            self._busy = False
        self.sampled.emit(rows)


def _fmt_mem(b):
    mb = b / 1048576
    return f"{mb / 1024:.2f} GB" if mb >= 1024 else f"{mb:.1f} MB"


RED, BLUE, PURPLE = QColor("#f87171"), QColor("#38bdf8"), QColor(167, 139, 250, 40)
RED_BG, BLUE_BG = QColor(248, 113, 113, 40), QColor(56, 189, 248, 28)
YELLOW, DIMMED = QColor("#facc15"), QColor("#64748b")
RIGHT = int(Qt.AlignRight | Qt.AlignVCenter)
_DISPLAY, _FG, _BG, _ALIGN, _ICON, _USER, _TIP = (
    Qt.DisplayRole.value, Qt.ForegroundRole.value, Qt.BackgroundRole.value, Qt.TextAlignmentRole.value,
    Qt.DecorationRole.value, Qt.UserRole.value, Qt.ToolTipRole.value)
_ROLES = frozenset((_DISPLAY, _FG, _BG, _ALIGN, _ICON, _USER, _TIP))


class ProcessModel(QAbstractTableModel):
    """The visible rows (already filtered, grouped and sorted). Cells are computed on demand."""

    def __init__(self, icon_for, parent=None):
        super().__init__(parent)
        self.rows = []
        self.grouped = False
        self.icon_for = icon_for
        self._cells = {}

    def set_rows(self, rows, grouped):
        self.beginResetModel()
        self.rows = rows
        self.grouped = grouped
        self._cells = {}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def _row(self, i):
        """Every role of one row, worked out once per refresh (Qt asks for each cell many times)."""
        cells = self._cells.get(i)
        if cells is None:
            r = self.rows[i]
            hot, warm = r["cpu"] >= 25, r["cpu"] >= 5
            cells = self._cells[i] = (
                (r["name"], f"{r['count']} procs" if self.grouped and r["count"] > 1 else str(r["pid"]),
                 f"{r['cpu']:.1f}%", _fmt_mem(r["mem"]), str(r["threads"]), r["status"], r["exe"] or "—"),
                (YELLOW if r["protected"] else None, None, RED if hot else BLUE if warm else None,
                 None, None, None, DIMMED),
                (None, None, RED_BG if hot else BLUE_BG if warm else None,
                 PURPLE if r["mem"] >= 1 << 30 else None, None, None, None),
            )
        return cells

    def data(self, index, role=Qt.DisplayRole):
        # Qt calls this for every visible cell and role on each paint: plain-int roles,
        # because comparing PySide's enum objects costs more than the lookup itself
        role = int(role) if not isinstance(role, int) else role
        if role not in _ROLES:
            return None
        i, c = index.row(), index.column()
        if role == _DISPLAY:
            return self._row(i)[0][c]
        if role == _FG:
            return self._row(i)[1][c]
        if role == _BG:
            return self._row(i)[2][c]
        if role == _ALIGN:
            return RIGHT if 1 <= c <= 4 else None
        if role == _ICON:
            return self.icon_for(self.rows[i]["exe"]) if c == 0 else None
        if role == _USER:
            return self.rows[i]
        if role == _TIP and c == 6:
            return self.rows[i]["exe"] or None
        return None


class StatChip(QFrame):
    def __init__(self, title, color):
        super().__init__()
        self.setObjectName("panel")
        lo = QVBoxLayout(self)
        lo.setContentsMargins(14, 8, 14, 8)
        lo.setSpacing(0)
        t = QLabel(title)
        t.setStyleSheet("color:#94a3b8;font-size:10px;font-weight:800;letter-spacing:1px;background:transparent;")
        self.value = QLabel("—")
        self.value.setStyleSheet(f"color:{color};font-size:20px;font-weight:300;background:transparent;")
        lo.addWidget(t)
        lo.addWidget(self.value)


class ProcessManagerView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self._icons = {}
        self._icon_provider = None
        self._sort_col = 2
        self._sort_desc = True
        self._first = True

        self.sampler = ProcessSampler(self)
        self.sampler.sampled.connect(self._on_sample)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(2000)

        self._setup_ui()
        self.sampler.sample()
        QTimer.singleShot(900, self.sampler.sample)   # second sample → real CPU %

    # ------------------------------------------------------------------ UI --

    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(12)

        title_box = QFrame()
        title_box.setObjectName("panel")
        tb = QHBoxLayout(title_box)
        tb.setContentsMargins(14, 10, 14, 10)
        title = QLabel("PROCESS MANAGER // LIVE TASKS & RESOURCE USAGE")
        title.setObjectName("section-header")
        tb.addWidget(title)
        tb.addStretch()
        self.live_lbl = QLabel("● LIVE")
        self.live_lbl.setStyleSheet("color:#34d399;font-size:10px;font-weight:800;background:transparent;")
        tb.addWidget(self.live_lbl)
        main.addWidget(title_box)

        chips = QHBoxLayout()
        chips.setSpacing(10)
        self.chip_cpu = StatChip("CPU", "#38bdf8")
        self.chip_mem = StatChip("MEMORY", "#a78bfa")
        self.chip_procs = StatChip("PROCESSES", "#f8fafc")
        self.chip_threads = StatChip("THREADS", "#f5be4b")
        for c in (self.chip_cpu, self.chip_mem, self.chip_procs, self.chip_threads):
            chips.addWidget(c, 1)
        main.addLayout(chips)

        bar = QFrame()
        bar.setObjectName("panel")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name, PID or path…")
        self.search.setClearButtonEnabled(True)
        self._search_wait = QTimer(self)               # don't redraw the list on every keystroke
        self._search_wait.setSingleShot(True)
        self._search_wait.setInterval(180)
        self._search_wait.timeout.connect(self._render)
        self.search.textChanged.connect(self._search_wait.start)
        bl.addWidget(self.search, 1)
        self.cb_group = QCheckBox("Group by app")
        self.cb_group.toggled.connect(self._render)
        bl.addWidget(self.cb_group)
        self.cb_live = QCheckBox("Live updates")
        self.cb_live.setChecked(True)
        self.cb_live.toggled.connect(lambda on: self.live_lbl.setText("● LIVE" if on else "❚❚ PAUSED"))
        bl.addWidget(self.cb_live)
        self.loc_btn = QPushButton(" Open Location")
        self.loc_btn.setIcon(get_icon("folder", "#e2e8f0", 14))
        self.loc_btn.clicked.connect(lambda: self._reveal(self._selected()))
        bl.addWidget(self.loc_btn)
        self.kill_btn = QPushButton(" End Task")
        self.kill_btn.setObjectName("danger-btn")
        self.kill_btn.setIcon(get_icon("x", "#fca5a5", 14))
        self.kill_btn.clicked.connect(lambda: self._end_task(self._selected()))
        bl.addWidget(self.kill_btn)
        main.addWidget(bar)

        self.model = ProcessModel(self._icon, self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setProperty("elide_middle", True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.selectionModel().selectionChanged.connect(self._sync_buttons)
        self.table.doubleClicked.connect(lambda _: self._reveal(self._selected()))
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 80), (2, 80), (3, 100), (4, 80), (5, 90), (6, 220)):
            hh.setSectionResizeMode(c, QHeaderView.Interactive)
            self.table.setColumnWidth(c, w)
        hh.setSortIndicatorShown(True)
        hh.setSectionsClickable(True)
        hh.sectionClicked.connect(self._on_header)
        hh.setSortIndicator(self._sort_col, Qt.DescendingOrder)
        main.addWidget(self.table, 1)

        hint = QLabel("Right-click a process for more actions · yellow names are protected Windows components")
        hint.setStyleSheet("color:#64748b;font-size:10px;background:transparent;")
        main.addWidget(hint)
        self._sync_buttons()

    # ------------------------------------------------------------- data --

    def _tick(self):
        if self.isVisible() and self.cb_live.isChecked():
            self.sampler.sample()

    def showEvent(self, e):
        super().showEvent(e)
        self.sampler.sample()

    def refresh_processes(self):
        self.sampler.sample()

    def _on_sample(self, rows):
        self.rows = rows
        vm = psutil.virtual_memory()
        self.chip_cpu.value.setText(f"{psutil.cpu_percent(interval=None):.0f}%")
        self.chip_mem.value.setText(f"{vm.used / 1073741824:.1f} / {vm.total / 1073741824:.1f} GB")
        self.chip_procs.value.setText(f"{len(rows):,}")
        self.chip_threads.value.setText(f"{sum(r['threads'] for r in rows):,}")
        self._render()

    def _visible_rows(self):
        q = self.search.text().strip().lower()
        rows = self.rows
        if self.cb_group.isChecked():
            groups = {}
            for r in rows:
                g = groups.get(r["name"].lower())
                if g is None:
                    groups[r["name"].lower()] = dict(r, pids=[r["pid"]])
                else:
                    g["cpu"] += r["cpu"]
                    g["mem"] += r["mem"]
                    g["threads"] += r["threads"]
                    g["count"] += 1
                    g["pids"].append(r["pid"])
                    g["exe"] = g["exe"] or r["exe"]
            rows = list(groups.values())
        if q:
            rows = [r for r in rows if q in r["name"].lower() or q in str(r["pid"]) or q in r["exe"].lower()]
        key = SORT_KEYS[self._sort_col]
        if key in ("name", "status", "exe"):
            rows = sorted(rows, key=lambda r: str(r[key]).lower(), reverse=self._sort_desc)
        else:
            rows = sorted(rows, key=lambda r: r[key], reverse=self._sort_desc)
        return rows

    def _icon(self, exe):
        if exe not in self._icons:
            icon = None
            if exe and os.path.exists(exe):
                if self._icon_provider is None:
                    self._icon_provider = QFileIconProvider()
                icon = self._icon_provider.icon(QFileInfo(exe))
            self._icons[exe] = icon if icon and not icon.isNull() else get_icon("process_manager", "#64748b", 16)
        return self._icons[exe]

    def _render(self):
        sel = self._selected()
        grouped = self.cb_group.isChecked()
        sel_key = None
        if sel:
            sel_key = sel["name"].lower() if grouped else (sel["name"], sel["pid"])
        scroll = self.table.verticalScrollBar().value()
        rows = self._visible_rows()

        self.model.set_rows(rows, grouped)
        if sel_key is not None:
            for i, r in enumerate(rows):
                if sel_key == (r["name"].lower() if grouped else (r["name"], r["pid"])):
                    self.table.selectRow(i)
                    break
        self.table.verticalScrollBar().setValue(scroll)
        self._sync_buttons()

    def _on_header(self, col):
        if col == self._sort_col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col = col
            self._sort_desc = col not in (0, 5, 6)
        self.table.horizontalHeader().setSortIndicator(
            col, Qt.DescendingOrder if self._sort_desc else Qt.AscendingOrder)
        self._render()

    # ---------------------------------------------------------- actions --

    def _selected(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        return self.model.data(rows[0], Qt.UserRole)

    def _sync_buttons(self):
        r = self._selected()
        self.kill_btn.setEnabled(bool(r) and not r["protected"])
        self.loc_btn.setEnabled(bool(r) and bool(r["exe"]))

    def _context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        self.table.selectRow(index.row())
        r = self._selected()
        if not r:
            return
        m = make_menu(self)
        grouped = len(r.get("pids", [r["pid"]])) > 1
        end = m.addAction(hicon("x", "#f87171", 14),
                          f"End all {len(r['pids'])} '{r['name']}' processes" if grouped else "End task",
                          lambda: self._end_task(r))
        end.setEnabled(not r["protected"])
        if not grouped:
            tree = m.addAction("End process tree", lambda: self._end_task(r, tree=True))
            tree.setEnabled(not r["protected"])
            pr = make_menu(m)
            pr.setTitle("Set priority")
            try:
                current = psutil.Process(r["pid"]).nice()
            except psutil.Error:
                current = None
            for label, value in PRIORITIES:
                a = pr.addAction(label, lambda v=value, n=label: self._set_priority(r, v, n))
                a.setCheckable(True)
                a.setChecked(value == current)
            pr.setEnabled(not r["protected"])
            m.addMenu(pr)
        m.addSeparator()
        loc = m.addAction(hicon("folder", "#e2e8f0", 14), "Open file location", lambda: self._reveal(r))
        loc.setEnabled(bool(r["exe"]))
        m.addAction(hicon("duplicate_finder", "#e2e8f0", 14), "Copy path",
                    lambda: QGuiApplication.clipboard().setText(r["exe"] or r["name"]))
        m.addAction(hicon("search", "#e2e8f0", 14), "Search online",
                    lambda: webbrowser.open("https://www.google.com/search?q=" + quote_plus(f"{r['name']} process")))
        m.exec(QCursor.pos())

    def _reveal(self, r):
        if r and r["exe"] and os.path.exists(r["exe"]):
            subprocess.Popen(f'explorer /select,"{os.path.normpath(r["exe"])}"')

    def _set_priority(self, r, value, label):
        try:
            psutil.Process(r["pid"]).nice(value)
            TerminalPanel.get_instance() and TerminalPanel.get_instance().log_info(
                f"Priority of {r['name']} (PID {r['pid']}) set to {label}.")
        except psutil.AccessDenied:
            QMessageBox.warning(self, "Access Denied",
                                "Windows refused the change. Run CYPHER-X as administrator to change this process.")
        except psutil.Error as e:
            QMessageBox.warning(self, "Priority", str(e))

    def _end_task(self, r, tree=False):
        if not r:
            return
        if r["protected"]:
            QMessageBox.critical(self, "Protected Process",
                                 f"'{r['name']}' is an essential Windows component and cannot be terminated.")
            return
        pids = list(r.get("pids", [r["pid"]]))
        if tree:
            try:
                pids += [c.pid for c in psutil.Process(r["pid"]).children(recursive=True)]
            except psutil.Error:
                pass
        what = (f"all {len(pids)} '{r['name']}' processes" if len(pids) > 1
                else f"'{r['name']}' (PID {r['pid']})")
        dialog = CyberConfirmationDialog(
            title="END TASK",
            message=f"End {what}?\n\nUnsaved work in this app will be lost.",
            warning_level="danger", confirm_text="END TASK", cancel_text="CANCEL", parent=self)
        if dialog.exec() != CyberConfirmationDialog.Accepted:
            return
        failures = []
        for pid in pids:
            res = ProcessService.terminate_process(pid)
            if not res["success"]:
                failures.append(res.get("error", f"PID {pid}"))
        term = TerminalPanel.get_instance()
        if term:
            term.log_warning(f"Ended {what}.")
        Database.get_instance().log_operation(
            operation_type="Process Manager", action=f"Ended {what}",
            result="Success" if not failures else f"{len(failures)} failed")
        if failures:
            QMessageBox.warning(self, "Some processes could not be ended", "\n".join(failures[:6]))
        time.sleep(0.2)
        self.sampler.sample()

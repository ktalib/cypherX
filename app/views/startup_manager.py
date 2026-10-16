"""
Startup Manager — enable / disable apps that launch when you sign in, using the
same reversible switch as Windows Task Manager. Flags broken entries whose
program has been uninstalled and lets you remove them (with an undo backup).
"""
import os

from PySide6.QtCore import Qt, QFileInfo
from PySide6.QtGui import QColor, QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QMessageBox, QFileIconProvider, QAbstractItemView, QLineEdit
)

from app.icons import get_icon
from app.services.startup_service import StartupService
from app.widgets.confirmation_dialog import CyberConfirmationDialog
from app.widgets.terminal_panel import TerminalPanel
from app.widgets.home.common import make_menu, hicon
from app.ui_polish import reveal_path
from app.database import Database


class StartupManagerView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []
        self._icons = QFileIconProvider()
        self._setup_ui()
        self.refresh_entries()

    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(12)

        title_box = QFrame()
        title_box.setObjectName("panel")
        tb = QHBoxLayout(title_box)
        tb.setContentsMargins(14, 8, 10, 8)
        title = QLabel("STARTUP MANAGER // APPS THAT LAUNCH WHEN YOU SIGN IN")
        title.setObjectName("section-header")
        tb.addWidget(title)
        tb.addStretch()
        refresh = QPushButton(" Rescan")
        refresh.setIcon(get_icon("refresh", "#e2e8f0", 13))
        refresh.clicked.connect(self.refresh_entries)
        tb.addWidget(refresh)
        main.addWidget(title_box)

        bar = QFrame()
        bar.setObjectName("panel")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 8, 14, 8)
        self.summary_lbl = QLabel("")
        self.summary_lbl.setStyleSheet("color:#e2e8f0;font-size:12px;font-weight:600;background:transparent;")
        bl.addWidget(self.summary_lbl)
        bl.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter…")
        self.search.setFixedWidth(220)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._render)
        bl.addWidget(self.search)
        main.addWidget(bar)

        self.table = QTableWidget(0, 5)
        self.table.setProperty("elide_middle", True)
        self.table.setHorizontalHeaderLabels(["App", "Status", "Where it's registered", "Command", ""])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 250)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 170)
        self.table.setColumnWidth(4, 96)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        main.addWidget(self.table, 1)

        hint = QLabel("Disabling works like Task Manager's Startup tab — the entry stays and can be re-enabled any "
                      "time. Machine-wide entries may need CYPHER-X to run as administrator. Right-click for more.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b;font-size:11px;background:transparent;")
        main.addWidget(hint)

    # ------------------------------------------------------------- data --

    def refresh_entries(self):
        self.entries = StartupService.get_startup_entries()
        for e in self.entries:
            e["program"], e["exists"] = StartupService.program_path(e["command"])
            if e.get("type") == "shortcut":
                e["program"], e["exists"] = e["path"], os.path.exists(e["path"])
        self._render()

    def _render(self):
        q = self.search.text().strip().lower()
        rows = [e for e in self.entries if not q or q in e["name"].lower() or q in e["command"].lower()]
        on = sum(1 for e in self.entries if e["enabled"])
        broken = sum(1 for e in self.entries if not e["exists"])
        self.summary_lbl.setText(f"{len(self.entries)} startup apps  ·  {on} enabled  ·  "
                                 f"{len(self.entries) - on} disabled" + (f"  ·  {broken} broken" if broken else ""))
        self.table.setRowCount(len(rows))
        for r, e in enumerate(rows):
            icon = (self._icons.icon(QFileInfo(e["program"])) if e["exists"]
                    else get_icon("x", "#f87171", 16))
            name = QTableWidgetItem(icon, e["name"])
            name.setData(Qt.UserRole, e)
            name.setToolTip(e["name"])
            if not e["enabled"]:
                name.setForeground(QColor("#64748b"))
            self.table.setItem(r, 0, name)

            if not e["exists"]:
                st = QTableWidgetItem("Program missing")
                st.setForeground(QColor("#f87171"))
                st.setToolTip("The program this entry launches no longer exists — it's safe to remove.")
            else:
                st = QTableWidgetItem("Enabled" if e["enabled"] else "Disabled")
                st.setForeground(QColor("#34d399") if e["enabled"] else QColor("#94a3b8"))
            self.table.setItem(r, 1, st)
            self.table.setItem(r, 2, QTableWidgetItem(e["source"].replace("Registry: ", "")))
            cmd = QTableWidgetItem(e["command"])
            cmd.setForeground(QColor("#94a3b8"))
            cmd.setToolTip(e["command"])
            self.table.setItem(r, 3, cmd)

            if e["exists"]:
                btn = QPushButton("Disable" if e["enabled"] else "Enable")
                btn.setObjectName("danger-btn" if e["enabled"] else "action-btn-primary")
                btn.clicked.connect(lambda _=False, x=e: self._toggle(x))
            else:
                btn = QPushButton("Remove")
                btn.setObjectName("danger-btn")
                btn.clicked.connect(lambda _=False, x=e: self._remove(x))
            btn.setFixedHeight(24)
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(4, 0, 4, 0)
            hl.addWidget(btn)
            self.table.setCellWidget(r, 4, holder)

    # ---------------------------------------------------------- actions --

    def _toggle(self, e):
        res = StartupService.set_enabled(e, not e["enabled"])
        if not res["success"]:
            QMessageBox.warning(self, "Startup Manager", res["error"])
            return
        state = "Enabled" if not e["enabled"] else "Disabled"
        term = TerminalPanel.get_instance()
        if term:
            term.log_info(f"Startup app {state.lower()}: {e['name']}")
        Database.get_instance().log_operation(
            operation_type="Startup Manager", action=f"{state} {e['name']}", result="Success",
            target_path=e.get("program") or "")
        self.refresh_entries()

    def _remove(self, e):
        dialog = CyberConfirmationDialog(
            title="REMOVE STARTUP ENTRY",
            message=f"Remove '{e['name']}' from startup entirely?\n\nCommand: {e['command']}\n\n"
                    "A backup is saved to Operation History so it can be restored.",
            warning_level="warning", confirm_text="REMOVE", cancel_text="CANCEL", parent=self)
        if dialog.exec() != CyberConfirmationDialog.Accepted:
            return
        res = StartupService.remove_startup_entry(e)
        if not res["success"]:
            QMessageBox.warning(self, "Startup Manager", res.get("error", "Failed"))
            return
        backup = {k: v for k, v in res["backup"].items() if k not in ("program", "exists")}
        Database.get_instance().log_operation(
            operation_type="Startup Manager", action=f"Removed startup entry {e['name']}",
            result="Removed with backup", can_undo=True, undo_data={"backup": backup})
        self.refresh_entries()

    def _menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return
        e = self.table.item(item.row(), 0).data(Qt.UserRole)
        m = make_menu(self)
        if e["exists"]:
            m.addAction("Disable" if e["enabled"] else "Enable", lambda: self._toggle(e))
            m.addAction(hicon("folder", "#e2e8f0", 14), "Open file location", lambda: reveal_path(e["program"]))
        m.addAction(hicon("trash", "#f87171", 14), "Remove entry…", lambda: self._remove(e))
        m.addSeparator()
        m.addAction(hicon("duplicate_finder", "#e2e8f0", 14), "Copy command",
                    lambda: QGuiApplication.clipboard().setText(e["command"]))
        m.exec(QCursor.pos())

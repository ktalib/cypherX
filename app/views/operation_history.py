import os
import csv
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QComboBox, QFileDialog, QMessageBox
)
from app.config import (
    COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_GREEN, COLOR_YELLOW,
    COLOR_PANEL_BG, COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_PANEL_ALT
)
from app.database import Database
from app.widgets.terminal_panel import TerminalPanel

class OperationHistoryView(QWidget):
    """Audit logging and operational history view with filtering, export, and undo tracking."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.operations = []
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
        title = QLabel("OPERATION HISTORY // MISSION LOG AUDIT & UNDO REGISTRY")
        title.setObjectName("section-header")
        tb_l.addWidget(title)
        main_layout.addWidget(title_box)

        # Controls & Filter Bar
        ctrl_frame = QFrame()
        ctrl_frame.setObjectName("panel")
        ctrl_layout = QHBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(12, 10, 12, 10)
        ctrl_layout.setSpacing(10)

        ctrl_layout.addWidget(QLabel("FILTER OPERATION:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("All Modules", "")
        self.filter_combo.addItem("Disk Cleaner", "Disk Cleaner")
        self.filter_combo.addItem("Folder Organizer", "Folder Organizer")
        self.filter_combo.addItem("Disk Analyzer", "Disk Analyzer")
        self.filter_combo.addItem("Large File Finder", "Large File Finder")
        self.filter_combo.addItem("Process Manager", "Process Manager")
        self.filter_combo.addItem("Startup Manager", "Startup Manager")
        self.filter_combo.addItem("App Launcher", "App Launcher")
        self.filter_combo.addItem("Automation", "Automation")
        self.filter_combo.currentIndexChanged.connect(self.refresh_history)
        ctrl_layout.addWidget(self.filter_combo)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search actions, paths, results…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh_history)
        ctrl_layout.addWidget(self.search, 1)

        refresh_btn = QPushButton("REFRESH AUDIT")
        refresh_btn.setObjectName("action-btn-primary")
        refresh_btn.clicked.connect(self.refresh_history)
        ctrl_layout.addWidget(refresh_btn)

        export_btn = QPushButton("EXPORT CSV")
        export_btn.clicked.connect(self.export_csv)
        ctrl_layout.addWidget(export_btn)

        clear_btn = QPushButton("CLEAR HISTORY")
        clear_btn.setObjectName("danger-btn")
        clear_btn.clicked.connect(self._clear_history)
        ctrl_layout.addWidget(clear_btn)

        main_layout.addWidget(ctrl_frame)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Timestamp", "Module", "Action", "Target Path", "Result", "Can Undo"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        main_layout.addWidget(self.table)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)

        self.refresh_history()

    def _menu(self, pos):
        from PySide6.QtGui import QCursor, QGuiApplication
        from app.widgets.home.common import make_menu, hicon
        from app.ui_polish import open_path, reveal_path
        item = self.table.itemAt(pos)
        if not item or item.row() >= len(self.operations):
            return
        op = self.operations[item.row()]
        m = make_menu(self)
        undo = m.addAction(hicon("rotate_ccw", "#e2e8f0", 14), "Undo this operation", lambda: self._undo(op))
        undo.setEnabled(bool(op.get("can_undo")) and bool(op.get("undo_data")))
        path = op.get("target_path")
        if path and os.path.exists(path):
            m.addSeparator()
            m.addAction(hicon("eye", "#e2e8f0", 14), "Open", lambda: open_path(path))
            m.addAction(hicon("folder", "#e2e8f0", 14), "Show in Explorer", lambda: reveal_path(path))
        m.addAction(hicon("duplicate_finder", "#e2e8f0", 14), "Copy row",
                    lambda: QGuiApplication.clipboard().setText(
                        " | ".join(str(op.get(k) or "") for k in ("timestamp", "operation_type", "action",
                                                                   "target_path", "result"))))
        m.exec(QCursor.pos())

    def _undo(self, op):
        import json
        try:
            data = json.loads(op.get("undo_data") or "{}")
        except ValueError:
            data = {}
        kind = op.get("operation_type")
        if QMessageBox.question(self, "Undo", f"Undo '{op['action']}'?") != QMessageBox.Yes:
            return
        if kind == "Folder Organizer" and data.get("moves"):
            from app.services.file_organizer_service import FileOrganizerService
            res = FileOrganizerService.undo_moves(data["moves"])
            ok = res.get("restored_count", 0) > 0
            msg = f"Restored {res.get('restored_count', 0)} files."
            if res.get("failed"):
                msg += f"\n{len(res['failed'])} could not be restored:\n" + "\n".join(res["failed"][:5])
        elif kind == "Startup Manager" and data.get("backup"):
            from app.services.startup_service import StartupService
            res = StartupService.restore_startup_entry(data["backup"])
            ok = res.get("success", False)
            msg = "Startup entry restored." if ok else res.get("error", "Restore failed.")
        else:
            QMessageBox.information(self, "Undo", "This operation can't be undone automatically.")
            return
        if ok:
            Database.get_instance().mark_operation_undone(op["id"])
        QMessageBox.information(self, "Undo", msg)
        self.refresh_history()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_history()

    def refresh_history(self):
        mod_filter = self.filter_combo.currentData()
        self.operations = Database.get_instance().get_operations(limit=1000, filter_type=mod_filter if mod_filter else None)
        q = self.search.text().strip().lower() if hasattr(self, "search") else ""
        if q:
            self.operations = [op for op in self.operations
                               if q in " ".join(str(op.get(k) or "") for k in
                                                ("timestamp", "operation_type", "action", "target_path", "result")).lower()]

        self.table.setRowCount(len(self.operations))
        for row, op in enumerate(self.operations):
            self.table.setItem(row, 0, QTableWidgetItem(op["timestamp"]))
            self.table.setItem(row, 1, QTableWidgetItem(op["operation_type"]))
            self.table.setItem(row, 2, QTableWidgetItem(op["action"]))
            self.table.setItem(row, 3, QTableWidgetItem(op.get("target_path") or "--"))
            self.table.setItem(row, 4, QTableWidgetItem(op["result"]))

            undo_str = "YES" if op["can_undo"] else "NO"
            undo_item = QTableWidgetItem(undo_str)
            undo_item.setForeground(Qt.green if op["can_undo"] else Qt.gray)
            self.table.setItem(row, 5, undo_item)

    def _clear_history(self):
        reply = QMessageBox.question(
            self, "Clear History", "Permanently clear the recorded operation history log?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            Database.get_instance().clear_operation_history()
            self.refresh_history()
            term = TerminalPanel.get_instance()
            if term:
                term.log_info("Operation history database cleared.")

    def export_csv(self):
        if not self.operations:
            QMessageBox.information(self, "No Records", "No operations recorded to export.")
            return

        save_path, _ = QFileDialog.getSaveFileName(self, "Export Audit Log to CSV", "operation_history.csv", "CSV Files (*.csv)")
        if not save_path:
            return

        try:
            with open(save_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["ID", "Timestamp", "Operation Type", "Action", "Target Path", "Result", "Can Undo"])
                for op in self.operations:
                    writer.writerow([op["id"], op["timestamp"], op["operation_type"], op["action"], op["target_path"], op["result"], op["can_undo"]])
            QMessageBox.information(self, "Export Finished", f"Saved history to:\n{save_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

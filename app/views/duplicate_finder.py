import os
import subprocess
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QFrame, QCheckBox, QMessageBox
)
from app.config import (
    COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_GREEN, COLOR_YELLOW, COLOR_RED,
    COLOR_PANEL_BG, COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_PANEL_ALT
)
from app.services.system_service import SystemService
from app.workers.duplicate_worker import DuplicateFinderWorker
from app.workers.cleanup_worker import CleanupExecuteWorker
from app.widgets.confirmation_dialog import CyberConfirmationDialog
from app.widgets.terminal_panel import TerminalPanel
from app.database import Database
from app.ui_polish import attach_file_menu

class DuplicateFinderView(QWidget):
    """Cryptographic SHA-256 duplicate file detection and safe pruning utility."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: DuplicateFinderWorker = None
        self.results_data = None
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
        title = QLabel("DUPLICATE FINDER // SHA-256 CRYPTOGRAPHIC CONTENT DETECTOR")
        title.setObjectName("section-header")
        tb_l.addWidget(title)
        main_layout.addWidget(title_box)

        # Controls Bar
        ctrl_frame = QFrame()
        ctrl_frame.setObjectName("panel")
        ctrl_layout = QHBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(12, 10, 12, 10)
        ctrl_layout.setSpacing(10)

        self.path_input = QLineEdit(str(Path.home() / "Documents"))
        ctrl_layout.addWidget(self.path_input)

        browse_btn = QPushButton("BROWSE...")
        browse_btn.clicked.connect(self._browse)
        ctrl_layout.addWidget(browse_btn)

        self.scan_btn = QPushButton("SCAN DUPLICATES")
        self.scan_btn.setObjectName("action-btn-primary")
        self.scan_btn.clicked.connect(self.start_scan)
        ctrl_layout.addWidget(self.scan_btn)

        self.cancel_btn = QPushButton("ABORT")
        self.cancel_btn.setObjectName("danger-btn")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_scan)
        ctrl_layout.addWidget(self.cancel_btn)

        self.delete_btn = QPushButton("PRUNE SELECTED")
        self.delete_btn.setObjectName("danger-btn")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self.prompt_delete_duplicates)
        ctrl_layout.addWidget(self.delete_btn)

        main_layout.addWidget(ctrl_frame)

        # Progress bar
        self.progress_frame = QFrame()
        self.progress_frame.setVisible(False)
        pf_layout = QVBoxLayout(self.progress_frame)
        pf_layout.setContentsMargins(0, 0, 0, 0)
        self.status_lbl = QLabel("Ready for scan.")
        self.status_lbl.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px;")
        pf_layout.addWidget(self.status_lbl)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(5)
        pf_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.progress_frame)

        # Summary strip
        self.summary_frame = QFrame()
        self.summary_frame.setObjectName("panel")
        sf_layout = QHBoxLayout(self.summary_frame)
        sf_layout.setContentsMargins(14, 8, 14, 8)

        self.summary_lbl = QLabel("NO DUPLICATES FOUND YET")
        self.summary_lbl.setStyleSheet(f"color: {COLOR_CYAN}; font-size: 11px; font-weight: bold;")
        sf_layout.addWidget(self.summary_lbl)
        sf_layout.addStretch()

        self.recycle_cb = QCheckBox("USE RECYCLE BIN (SAFE)")
        self.recycle_cb.setChecked(True)
        sf_layout.addWidget(self.recycle_cb)

        main_layout.addWidget(self.summary_frame)

        # Results Table
        self.table = QTableWidget()
        self.table.setProperty("elide_middle", True)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Select Duplicate", "Filename", "Size", "Duplicate Group", "Location"])
        attach_file_menu(self.table, lambda r: self.table.item(r, 4).text() if self.table.item(r, 4) else None)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        main_layout.addWidget(self.table)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Directory to Scan", self.path_input.text())
        if folder:
            self.path_input.setText(folder)

    def start_scan(self):
        target = self.path_input.text().strip()
        if not os.path.exists(target):
            QMessageBox.warning(self, "Invalid Path", "Directory does not exist.")
            return

        self.scan_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.delete_btn.setEnabled(False)
        self.progress_frame.setVisible(True)
        self.status_lbl.setText(f"Starting duplicate scan in {target}...")

        term = TerminalPanel.get_instance()
        if term:
            term.log_info(f"Duplicate Finder initiated on target: {target}")

        self.worker = DuplicateFinderWorker(target)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def cancel_scan(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.scan_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.progress_frame.setVisible(False)
            self.status_lbl.setText("Scan cancelled.")

    def _on_progress(self, count, text):
        self.status_lbl.setText(f"[{count:,} files] {text}")

    def _on_finished(self, results):
        self.results_data = results
        self.scan_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_frame.setVisible(False)

        groups = results["duplicate_groups"]
        wasted_str = SystemService.format_bytes(results["wasted_bytes"])
        self.summary_lbl.setText(
            f"IDENTIFIED {results['total_groups']} DUPLICATE GROUPS ({results['total_duplicates']} REDUNDANT COPIES, {wasted_str} RECLAIMABLE)"
        )

        # Populate Table: First copy is reference (unchecked), subsequent copies checked
        row_idx = 0
        total_rows = sum(len(g) for g in groups)
        self.table.setRowCount(total_rows)

        for g_idx, group in enumerate(groups):
            for copy_idx, file_item in enumerate(group):
                is_reference = (copy_idx == 0)

                cb_item = QTableWidgetItem("REFERENCE COPY" if is_reference else "REDUNDANT DUPLICATE")
                cb_item.setCheckState(Qt.Unchecked if is_reference else Qt.Checked)
                if is_reference:
                    cb_item.setForeground(Qt.cyan)
                else:
                    cb_item.setForeground(Qt.yellow)

                self.table.setItem(row_idx, 0, cb_item)
                self.table.setItem(row_idx, 1, QTableWidgetItem(file_item["name"]))
                self.table.setItem(row_idx, 2, QTableWidgetItem(SystemService.format_bytes(file_item["size"])))
                self.table.setItem(row_idx, 3, QTableWidgetItem(f"Group #{g_idx + 1} (SHA-256 match)"))
                self.table.setItem(row_idx, 4, QTableWidgetItem(file_item["path"]))
                row_idx += 1

        self.delete_btn.setEnabled(results["total_duplicates"] > 0)

        term = TerminalPanel.get_instance()
        if term:
            term.log_success(f"Duplicate scan complete: {results['total_groups']} groups found, {wasted_str} redundant space.")

    def _on_error(self, err):
        self.scan_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_frame.setVisible(False)
        QMessageBox.critical(self, "Scan Failed", str(err))

    def prompt_delete_duplicates(self):
        to_delete = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                path_item = self.table.item(row, 4)
                if path_item:
                    to_delete.append(path_item.text())

        if not to_delete:
            QMessageBox.information(self, "No Selection", "No duplicate copies selected for removal.")
            return

        use_trash = self.recycle_cb.isChecked()
        dest_msg = "moved to the Windows Recycle Bin" if use_trash else "permanently deleted"

        dialog = CyberConfirmationDialog(
            title="CONFIRM DUPLICATE REMOVAL",
            message=f"You are about to remove {len(to_delete):,} redundant duplicate copies.\n\n"
                    f"Files will be {dest_msg}.\n"
                    "Original reference copies will be safely preserved.",
            warning_level="warning" if use_trash else "danger",
            confirm_text="REMOVE DUPLICATES",
            cancel_text="ABORT",
            parent=self
        )

        if dialog.exec() != CyberConfirmationDialog.Accepted:
            return

        exec_worker = CleanupExecuteWorker(to_delete, use_recycle_bin=use_trash)
        exec_worker.finished.connect(self._on_delete_finished)
        exec_worker.start()

    def _on_delete_finished(self, summary):
        QMessageBox.information(
            self, "Duplicates Removed",
            f"Successfully removed {summary['removed']} duplicates ({SystemService.format_bytes(summary['bytes_freed'])} freed)!"
        )
        term = TerminalPanel.get_instance()
        if term:
            term.log_success(f"Duplicate cleaner removed {summary['removed']} copies.")

        # Re-scan or clear
        self.table.setRowCount(0)
        self.delete_btn.setEnabled(False)
        self.summary_lbl.setText("CLEANUP COMPLETED - REDUNDANT COPIES REMOVED")

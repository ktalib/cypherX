import os
import csv
import subprocess
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QFrame, QComboBox, QMessageBox
)
from app.config import (
    COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_GREEN, COLOR_PANEL_BG,
    COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_PANEL_ALT, LARGE_FILE_PRESETS
)
from app.services.system_service import SystemService
from app.services.disk_service import DiskService
from app.workers.scan_worker import LargeFileWorker
from app.widgets.terminal_panel import TerminalPanel
from app.database import Database
from app.ui_polish import attach_file_menu

class LargeFileFinderView(QWidget):
    """Finds heavy storage-consuming files with configurable size presets and filters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: LargeFileWorker = None
        self.files_found = []
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
        title = QLabel("LARGE FILE FINDER // HEAVY STORAGE ISOLATOR")
        title.setObjectName("section-header")
        tb_l.addWidget(title)
        main_layout.addWidget(title_box)

        # Control Panel
        ctrl_frame = QFrame()
        ctrl_frame.setObjectName("panel")
        ctrl_layout = QHBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(12, 10, 12, 10)
        ctrl_layout.setSpacing(10)

        # Preset threshold combo
        ctrl_layout.addWidget(QLabel("MIN SIZE:"))
        self.preset_combo = QComboBox()
        self.preset_combo.setFixedWidth(100)
        for label, byte_val in LARGE_FILE_PRESETS:
            self.preset_combo.addItem(label, byte_val)
        self.preset_combo.setCurrentIndex(1)  # Default 100 MB
        ctrl_layout.addWidget(self.preset_combo)

        # Path input
        self.path_input = QLineEdit(str(Path.home()))
        ctrl_layout.addWidget(self.path_input)

        browse_btn = QPushButton("BROWSE...")
        browse_btn.clicked.connect(self._browse)
        ctrl_layout.addWidget(browse_btn)

        self.scan_btn = QPushButton("FIND LARGE FILES")
        self.scan_btn.setObjectName("action-btn-primary")
        self.scan_btn.clicked.connect(self.start_scan)
        ctrl_layout.addWidget(self.scan_btn)

        self.cancel_btn = QPushButton("ABORT")
        self.cancel_btn.setObjectName("danger-btn")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_scan)
        ctrl_layout.addWidget(self.cancel_btn)

        self.export_btn = QPushButton("EXPORT CSV")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export_csv)
        ctrl_layout.addWidget(self.export_btn)

        main_layout.addWidget(ctrl_frame)

        # Progress indicator
        self.progress_frame = QFrame()
        self.progress_frame.setVisible(False)
        pf_layout = QVBoxLayout(self.progress_frame)
        pf_layout.setContentsMargins(0, 0, 0, 0)
        self.status_lbl = QLabel("Ready.")
        self.status_lbl.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px;")
        pf_layout.addWidget(self.status_lbl)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(5)
        pf_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.progress_frame)

        # Summary strip
        self.summary_lbl = QLabel("SELECT DIRECTORY AND THRESHOLD TO SCAN")
        self.summary_lbl.setStyleSheet(f"color: {COLOR_CYAN}; font-size: 11px; font-weight: bold;")
        main_layout.addWidget(self.summary_lbl)

        # Results Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Filename", "Size", "Extension", "Last Modified", "Actions"])
        self.files_found = []
        attach_file_menu(self.table, lambda r: self.files_found[r]["path"] if r < len(self.files_found) else None)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        main_layout.addWidget(self.table)

    def _browse(self):
        f = QFileDialog.getExistingDirectory(self, "Select Search Root", self.path_input.text())
        if f:
            self.path_input.setText(f)

    def start_scan(self):
        target = self.path_input.text().strip()
        if not os.path.exists(target):
            QMessageBox.warning(self, "Path Not Found", "Target folder does not exist.")
            return

        min_bytes = self.preset_combo.currentData()
        self.scan_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.export_btn.setEnabled(False)
        self.progress_frame.setVisible(True)
        self.status_lbl.setText(f"Scanning for files >= {self.preset_combo.currentText()} in {target}...")

        term = TerminalPanel.get_instance()
        if term:
            term.log_info(f"Large File Finder searching {target} (Threshold: {self.preset_combo.currentText()})")

        self.worker = LargeFileWorker(target, min_bytes)
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

    def _on_progress(self, count, name):
        self.status_lbl.setText(f"Scanned {count:,} files... inspecting {name[:30]}")

    def _on_finished(self, results):
        self.files_found = results
        self.scan_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.export_btn.setEnabled(True)
        self.progress_frame.setVisible(False)

        total_size = sum(f["size"] for f in results)
        self.summary_lbl.setText(
            f"FOUND {len(results):,} LARGE FILES CONSUMING {SystemService.format_bytes(total_size)} TOTAL SPACE"
        )

        self.table.setRowCount(len(results))
        for row, f in enumerate(results):
            self.table.setItem(row, 0, QTableWidgetItem(f["name"]))
            self.table.setItem(row, 1, QTableWidgetItem(SystemService.format_bytes(f["size"])))
            self.table.setItem(row, 2, QTableWidgetItem(f["extension"].upper()))
            dt_str = datetime.fromtimestamp(f["modified"]).strftime("%Y-%m-%d %H:%M")
            self.table.setItem(row, 3, QTableWidgetItem(dt_str))

            action_widget = QWidget()
            aw_layout = QHBoxLayout(action_widget)
            aw_layout.setContentsMargins(0, 0, 0, 0)
            aw_layout.setSpacing(4)

            open_btn = QPushButton("OPEN")
            open_btn.setFixedHeight(20)
            open_btn.clicked.connect(lambda ch=False, p=f["path"]: self._open_file(p))
            aw_layout.addWidget(open_btn)

            reveal_btn = QPushButton("REVEAL")
            reveal_btn.setFixedHeight(20)
            reveal_btn.clicked.connect(lambda ch=False, p=f["path"]: self._reveal_file(p))
            aw_layout.addWidget(reveal_btn)

            self.table.setCellWidget(row, 4, action_widget)

        term = TerminalPanel.get_instance()
        if term:
            term.log_success(f"Large File Finder completed: {len(results)} files found ({SystemService.format_bytes(total_size)}).")

        Database.get_instance().log_operation(
            operation_type="Large File Finder",
            action=f"Filtered >= {self.preset_combo.currentText()}",
            result=f"{len(results)} files found ({SystemService.format_bytes(total_size)})",
            target_path=self.path_input.text()
        )

    def _on_error(self, err):
        self.scan_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_frame.setVisible(False)
        QMessageBox.critical(self, "Error", f"Failed large file search:\n{err}")

    def _open_file(self, path):
        if os.path.exists(path):
            os.startfile(path)

    def _reveal_file(self, path):
        if os.path.exists(path):
            subprocess.run(f'explorer /select,"{os.path.normpath(path)}"', shell=True)

    def export_csv(self):
        if not self.files_found:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Export Report to CSV", "large_files_report.csv", "CSV Files (*.csv)")
        if not save_path:
            return
        try:
            with open(save_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Filename", "Path", "Size (Bytes)", "Formatted Size", "Extension", "Last Modified"])
                for item in self.files_found:
                    dt_str = datetime.fromtimestamp(item["modified"]).strftime("%Y-%m-%d %H:%M:%S")
                    writer.writerow([item["name"], item["path"], item["size"], SystemService.format_bytes(item["size"]), item["extension"], dt_str])
            QMessageBox.information(self, "Export Done", f"Saved to:\n{save_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

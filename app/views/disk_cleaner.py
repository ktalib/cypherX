import os
from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QFrame, QComboBox, QCheckBox, QMessageBox
)
from app.config import (
    COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_GREEN, COLOR_RED, COLOR_PANEL_BG,
    COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_PANEL_ALT
)
from app.services.system_service import SystemService
from app.services.cleanup_service import CleanupService
from app.workers.cleanup_worker import CleanupAnalyzeWorker, CleanupExecuteWorker
from app.widgets.confirmation_dialog import CyberConfirmationDialog
from app.widgets.terminal_panel import TerminalPanel
from app.database import Database
from app.ui_polish import attach_file_menu

class DiskCleanerView(QWidget):
    """Safe disk-cleaning utility with dry-run preview, selective pruning, and Recycle Bin protection."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.analyze_worker: CleanupAnalyzeWorker = None
        self.exec_worker: CleanupExecuteWorker = None
        self.candidates = []
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
        title = QLabel("DISK CLEANER // RECYCLE-BIN PROTECTED SCRUBBER")
        title.setObjectName("section-header")
        tb_l.addWidget(title)
        main_layout.addWidget(title_box)

        # Target Selection & Controls
        ctrl_frame = QFrame()
        ctrl_frame.setObjectName("panel")
        ctrl_layout = QHBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(12, 10, 12, 10)
        ctrl_layout.setSpacing(10)

        ctrl_layout.addWidget(QLabel("CLEANUP TARGET:"))
        self.target_combo = QComboBox()
        self.target_combo.setFixedWidth(240)
        for t in CleanupService.get_cleanup_targets():
            self.target_combo.addItem(f"{t['name']}", t["path"])
        ctrl_layout.addWidget(self.target_combo)

        ctrl_layout.addWidget(QLabel("MIN AGE:"))
        self.age_combo = QComboBox()
        self.age_combo.addItem("Older than 24 hours", 24.0)
        self.age_combo.addItem("Older than 3 days", 72.0)
        self.age_combo.addItem("Older than 7 days", 168.0)
        self.age_combo.addItem("All safe temp files", 0.0)
        ctrl_layout.addWidget(self.age_combo)

        self.analyze_btn = QPushButton("ANALYZE TARGET")
        self.analyze_btn.setObjectName("action-btn-primary")
        self.analyze_btn.clicked.connect(self.start_analysis)
        ctrl_layout.addWidget(self.analyze_btn)

        self.clean_btn = QPushButton("EXECUTE CLEANUP")
        self.clean_btn.setObjectName("danger-btn")
        self.clean_btn.setEnabled(False)
        self.clean_btn.clicked.connect(self.prompt_and_execute_cleanup)
        ctrl_layout.addWidget(self.clean_btn)

        main_layout.addWidget(ctrl_frame)

        # Progress bar
        self.progress_frame = QFrame()
        self.progress_frame.setVisible(False)
        pf_layout = QVBoxLayout(self.progress_frame)
        pf_layout.setContentsMargins(0, 0, 0, 0)
        self.status_lbl = QLabel("Ready for analysis.")
        self.status_lbl.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px;")
        pf_layout.addWidget(self.status_lbl)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(5)
        pf_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.progress_frame)

        # Summary strip with Select All toggle
        self.summary_frame = QFrame()
        self.summary_frame.setObjectName("panel")
        sf_layout = QHBoxLayout(self.summary_frame)
        sf_layout.setContentsMargins(14, 8, 14, 8)

        self.select_all_cb = QCheckBox("SELECT ALL ITEMS")
        self.select_all_cb.setChecked(True)
        self.select_all_cb.stateChanged.connect(self._toggle_select_all)
        sf_layout.addWidget(self.select_all_cb)

        sf_layout.addStretch()

        self.recycle_cb = QCheckBox("MOVE TO RECYCLE BIN (SAFE)")
        self.recycle_cb.setChecked(True)
        self.recycle_cb.setToolTip("Recommended: Allows files to be restored if needed")
        sf_layout.addWidget(self.recycle_cb)

        sf_layout.addStretch()

        self.recovery_lbl = QLabel("POTENTIAL RECOVERY: 0.0 MB")
        self.recovery_lbl.setStyleSheet(f"color: {COLOR_GREEN}; font-weight: bold; font-size: 11px;")
        sf_layout.addWidget(self.recovery_lbl)

        main_layout.addWidget(self.summary_frame)

        # Candidates Table
        self.table = QTableWidget()
        self.table.setProperty("elide_middle", True)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Filename", "Size", "Age (Hours)", "Location"])
        attach_file_menu(self.table, lambda r: self.table.item(r, 3).text() if self.table.item(r, 3) else None, open_on_double_click=False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        main_layout.addWidget(self.table)

    def start_analysis(self):
        target_path = self.target_combo.currentData()
        if not target_path or not os.path.exists(target_path):
            QMessageBox.warning(self, "Invalid Path", "Selected target directory does not exist.")
            return

        min_age = self.age_combo.currentData()
        self.analyze_btn.setEnabled(False)
        self.clean_btn.setEnabled(False)
        self.progress_frame.setVisible(True)
        self.status_lbl.setText(f"Analyzing {target_path} (Read-only scan)...")

        term = TerminalPanel.get_instance()
        if term:
            term.log_info(f"Disk Cleaner analyzing: {target_path} (Safe analysis mode)")

        self.analyze_worker = CleanupAnalyzeWorker(target_path, min_age_hours=min_age)
        self.analyze_worker.progress.connect(self._on_analyze_progress)
        self.analyze_worker.finished.connect(self._on_analyze_finished)
        self.analyze_worker.error.connect(self._on_analyze_error)
        self.analyze_worker.start()

    def _on_analyze_progress(self, count, name):
        self.status_lbl.setText(f"Inspected {count:,} items... ({name[:30]})")

    def _on_analyze_finished(self, results):
        self.analyze_btn.setEnabled(True)
        self.progress_frame.setVisible(False)

        self.candidates = results["candidates"]
        total_bytes = results["total_bytes"]
        self.recovery_lbl.setText(f"POTENTIAL RECOVERY: {SystemService.format_bytes(total_bytes)} ({len(self.candidates):,} ITEMS)")

        self.table.setRowCount(len(self.candidates))
        for row, item in enumerate(self.candidates):
            # Checkbox item
            f_item = QTableWidgetItem(item["name"])
            f_item.setCheckState(Qt.Checked)
            self.table.setItem(row, 0, f_item)
            self.table.setItem(row, 1, QTableWidgetItem(SystemService.format_bytes(item["size"])))
            self.table.setItem(row, 2, QTableWidgetItem(f"{item['age_hours']:.1f}h"))
            self.table.setItem(row, 3, QTableWidgetItem(item["path"]))

        self.clean_btn.setEnabled(len(self.candidates) > 0)

        term = TerminalPanel.get_instance()
        if term:
            term.log_success(f"Analysis complete: {len(self.candidates)} items eligible for safe recovery ({SystemService.format_bytes(total_bytes)}).")

    def _on_analyze_error(self, err):
        self.analyze_btn.setEnabled(True)
        self.progress_frame.setVisible(False)
        QMessageBox.critical(self, "Analysis Failed", str(err))

    def _toggle_select_all(self, state):
        check_val = Qt.Checked if state == Qt.Checked.value else Qt.Unchecked
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(check_val)
        self._recalc_selected()

    def _recalc_selected(self):
        selected_bytes = 0
        selected_count = 0
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                selected_count += 1
                if row < len(self.candidates):
                    selected_bytes += self.candidates[row]["size"]
        self.recovery_lbl.setText(f"SELECTED RECOVERY: {SystemService.format_bytes(selected_bytes)} ({selected_count:,} ITEMS)")
        self.clean_btn.setEnabled(selected_count > 0)

    def prompt_and_execute_cleanup(self):
        selected_paths = []
        selected_bytes = 0
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                if row < len(self.candidates):
                    selected_paths.append(self.candidates[row]["path"])
                    selected_bytes += self.candidates[row]["size"]

        if not selected_paths:
            QMessageBox.information(self, "No Items", "No items selected for removal.")
            return

        use_trash = self.recycle_cb.isChecked()
        dest_msg = "moved to the Windows Recycle Bin" if use_trash else "permanently deleted"

        dialog = CyberConfirmationDialog(
            title="CONFIRM DISK CLEANUP",
            message=f"You are about to remove {len(selected_paths):,} temporary files ({SystemService.format_bytes(selected_bytes)}).\n\n"
                    f"Selected files will be {dest_msg}.\n"
                    "Locked and active application files will automatically be skipped.",
            warning_level="warning" if use_trash else "danger",
            confirm_text="EXECUTE CLEANUP",
            cancel_text="ABORT",
            parent=self
        )

        if dialog.exec() != CyberConfirmationDialog.Accepted:
            term = TerminalPanel.get_instance()
            if term:
                term.log_info("Disk Cleanup aborted by user.")
            return

        self.analyze_btn.setEnabled(False)
        self.clean_btn.setEnabled(False)
        self.progress_frame.setVisible(True)
        self.progress_bar.setRange(0, len(selected_paths))
        self.progress_bar.setValue(0)
        self.status_lbl.setText(f"Executing cleanup ({len(selected_paths)} files)...")

        self.exec_worker = CleanupExecuteWorker(selected_paths, use_recycle_bin=use_trash)
        self.exec_worker.progress.connect(self._on_clean_progress)
        self.exec_worker.finished.connect(self._on_clean_finished)
        self.exec_worker.start()

    def _on_clean_progress(self, count, name):
        self.progress_bar.setValue(count)
        self.status_lbl.setText(f"Processed {count}/{len(self.candidates)}: {name[:30]}")

    def _on_clean_finished(self, summary):
        self.analyze_btn.setEnabled(True)
        self.progress_frame.setVisible(False)
        self.clean_btn.setEnabled(False)

        freed_str = SystemService.format_bytes(summary["bytes_freed"])
        msg = f"Cleanup completed successfully!\n\n" \
              f"Files Removed: {summary['removed']:,}\n" \
              f"Space Reclaimed: {freed_str}\n" \
              f"Files Skipped / Locked: {summary['skipped']:,}"
        QMessageBox.information(self, "Cleanup Complete", msg)

        term = TerminalPanel.get_instance()
        if term:
            term.log_success(f"Disk Cleanup finished: Reclaimed {freed_str} ({summary['removed']} removed, {summary['skipped']} skipped).")

        Database.get_instance().log_operation(
            operation_type="Disk Cleaner",
            action=f"Scrubbed {self.target_combo.currentText()}",
            result=f"{summary['removed']} files removed, {freed_str} reclaimed",
            target_path=self.target_combo.currentData()
        )

        # Clear table
        self.table.setRowCount(0)
        self.candidates = []
        self.recovery_lbl.setText("RECOVERY: 0.0 MB")

import os
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QFrame, QComboBox, QMessageBox
)
from app.config import (
    COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_GREEN, COLOR_YELLOW, COLOR_RED,
    COLOR_PANEL_BG, COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_PANEL_ALT
)
from app.services.system_service import SystemService
from app.services.file_organizer_service import FileOrganizerService
from app.workers.organize_worker import OrganizeWorker
from app.widgets.confirmation_dialog import CyberConfirmationDialog
from app.widgets.terminal_panel import TerminalPanel
from app.database import Database

class FolderOrganizerView(QWidget):
    """Rule-based intelligent file organizer with dry-run preview, conflict handling, and undo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.planned_plan = None
        self.last_executed = None
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
        title = QLabel("FOLDER ORGANIZER // HEURISTIC FILE CLASSIFIER & UNDO ENGINE")
        title.setObjectName("section-header")
        tb_l.addWidget(title)
        main_layout.addWidget(title_box)

        # Controls Bar
        ctrl_frame = QFrame()
        ctrl_frame.setObjectName("panel")
        ctrl_outer = QVBoxLayout(ctrl_frame)
        ctrl_outer.setContentsMargins(12, 10, 12, 10)
        ctrl_outer.setSpacing(8)
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(10)
        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        button_row.addStretch()
        ctrl_outer.addLayout(ctrl_layout)
        ctrl_outer.addLayout(action_row)
        ctrl_outer.addLayout(button_row)

        # Folder path
        downloads_path = str(Path.home() / "Downloads")
        self.path_input = QLineEdit(downloads_path if os.path.exists(downloads_path) else str(Path.home()))
        ctrl_layout.addWidget(QLabel("FOLDER:"))
        ctrl_layout.addWidget(self.path_input, 1)

        browse_btn = QPushButton("BROWSE...")
        browse_btn.clicked.connect(self._browse_folder)
        ctrl_layout.addWidget(browse_btn)

        # Strategy
        action_row.addWidget(QLabel("STRATEGY:"))
        self.strat_combo = QComboBox()
        self.strat_combo.addItem("By File Category (Docs, Media, Code...)", "category")
        self.strat_combo.addItem("By File Extension (.PDF, .PNG...)", "extension")
        self.strat_combo.addItem("By Creation Date (YYYY-MM)", "date_ym")
        self.strat_combo.addItem("By Creation Year (YYYY)", "date_y")
        action_row.addWidget(self.strat_combo, 1)

        # Conflict resolution
        action_row.addWidget(QLabel("CONFLICTS:"))
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItem("Rename with suffix (_1)", "rename")
        self.conflict_combo.addItem("Skip existing destination", "skip")
        action_row.addWidget(self.conflict_combo, 1)

        self.preview_btn = QPushButton("SIMULATE (DRY RUN)")
        self.preview_btn.setObjectName("action-btn-primary")
        self.preview_btn.clicked.connect(self.simulate_organization)
        button_row.addWidget(self.preview_btn)

        self.execute_btn = QPushButton("EXECUTE MOVES")
        self.execute_btn.setEnabled(False)
        self.execute_btn.clicked.connect(self.execute_moves)
        button_row.addWidget(self.execute_btn)

        self.undo_btn = QPushButton("UNDO LAST MOVE")
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self.undo_moves)
        button_row.addWidget(self.undo_btn)

        main_layout.addWidget(ctrl_frame)

        # Summary strip
        self.summary_frame = QFrame()
        self.summary_frame.setObjectName("panel")
        sf_layout = QHBoxLayout(self.summary_frame)
        sf_layout.setContentsMargins(14, 8, 14, 8)

        self.stat_files = QLabel("PENDING MOVES: 0")
        self.stat_files.setStyleSheet(f"color: {COLOR_CYAN}; font-weight: bold; font-size: 11px;")
        self.stat_conflicts = QLabel("CONFLICTS DETECTED: 0")
        self.stat_conflicts.setStyleSheet(f"color: {COLOR_YELLOW}; font-weight: bold; font-size: 11px;")

        sf_layout.addWidget(self.stat_files)
        sf_layout.addStretch()
        sf_layout.addWidget(self.stat_conflicts)
        main_layout.addWidget(self.summary_frame)

        # Preview Moves Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Filename", "Size", "Target Category / Subfolder", "Destination Path", "Conflict Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        main_layout.addWidget(self.table)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Organize", self.path_input.text())
        if folder:
            self.path_input.setText(folder)

    def simulate_organization(self):
        target = self.path_input.text().strip()
        if not os.path.exists(target):
            QMessageBox.warning(self, "Invalid Directory", "Target directory does not exist.")
            return

        strategy = self.strat_combo.currentData()
        try:
            self.planned_plan = FileOrganizerService.preview_organization(target, strategy=strategy)
            moves = self.planned_plan["planned_moves"]

            self.stat_files.setText(f"PENDING MOVES: {len(moves):,} FILES ({SystemService.format_bytes(self.planned_plan['total_bytes'])})")
            self.stat_conflicts.setText(f"CONFLICTS DETECTED: {self.planned_plan['conflicts']}")

            self.table.setRowCount(len(moves))
            for row, item in enumerate(moves):
                self.table.setItem(row, 0, QTableWidgetItem(item["filename"]))
                self.table.setItem(row, 1, QTableWidgetItem(SystemService.format_bytes(item["size"])))
                self.table.setItem(row, 2, QTableWidgetItem(item["subfolder"]))
                self.table.setItem(row, 3, QTableWidgetItem(item["dest_path"]))

                c_item = QTableWidgetItem("CONFLICT DETECTED" if item["has_conflict"] else "OK - UNIQUE")
                c_item.setForeground(Qt.yellow if item["has_conflict"] else Qt.cyan)
                self.table.setItem(row, 4, c_item)

            self.execute_btn.setEnabled(len(moves) > 0)

            term = TerminalPanel.get_instance()
            if term:
                term.log_info(f"Folder Organizer generated dry-run preview: {len(moves)} items classified under strategy '{strategy}'.")

        except Exception as e:
            QMessageBox.critical(self, "Simulation Failed", str(e))

    def execute_moves(self):
        if not self.planned_plan or not self.planned_plan["planned_moves"]:
            return

        moves = self.planned_plan["planned_moves"]
        conflict_mode = self.conflict_combo.currentData()

        dialog = CyberConfirmationDialog(
            title="CONFIRM FILE REORGANIZATION",
            message=f"You are about to organize {len(moves):,} files in '{self.path_input.text()}'.\n\n"
                    f"Selected strategy: {self.strat_combo.currentText()}\n"
                    f"Conflict mode: {self.conflict_combo.currentText()}\n\n"
                    "All operations are recorded to history and can be safely undone.",
            warning_level="info",
            confirm_text="EXECUTE MOVES",
            cancel_text="ABORT",
            parent=self
        )

        if dialog.exec() != CyberConfirmationDialog.Accepted:
            return

        self.execute_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)

        worker = OrganizeWorker(moves, conflict_mode=conflict_mode)
        worker.finished.connect(self._on_execute_finished)
        worker.start()

    def _on_execute_finished(self, summary):
        self.execute_btn.setEnabled(False)
        self.preview_btn.setEnabled(True)
        self.last_executed = summary["executed_moves"]
        self.undo_btn.setEnabled(len(self.last_executed) > 0)

        QMessageBox.information(
            self, "Organization Finished",
            f"Successfully reorganized {summary['executed_count']} files!\n"
            f"Skipped items: {summary['skipped_count']}"
        )

        term = TerminalPanel.get_instance()
        if term:
            term.log_success(f"Folder Organizer executed {summary['executed_count']} moves ({summary['skipped_count']} skipped).")

        # Record to Database with undo log
        Database.get_instance().log_operation(
            operation_type="Folder Organizer",
            action=f"Organized into {self.strat_combo.currentText()}",
            result=f"{summary['executed_count']} files moved",
            target_path=self.path_input.text(),
            can_undo=True,
            undo_data={"moves": summary["executed_moves"]}
        )

        # Clear preview table
        self.table.setRowCount(0)
        self.stat_files.setText("PENDING MOVES: 0")

    def undo_moves(self):
        if not self.last_executed:
            return

        reply = QMessageBox.question(
            self, "Undo Reorganization",
            f"Revert {len(self.last_executed)} moved files back to their original root location?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        undo_res = FileOrganizerService.undo_moves(self.last_executed)
        QMessageBox.information(self, "Undo Complete", f"Restored {undo_res['restored_count']} files to original paths.")

        term = TerminalPanel.get_instance()
        if term:
            term.log_success(f"Folder Organizer restored {undo_res['restored_count']} files back to initial state.")

        self.undo_btn.setEnabled(False)
        self.last_executed = None

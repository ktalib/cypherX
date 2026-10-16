from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QComboBox, QMessageBox, QSplitter
)
from app.config import (
    COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_GREEN, COLOR_YELLOW, COLOR_RED,
    COLOR_PANEL_BG, COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_PANEL_ALT
)
from app.database import Database
from app.widgets.terminal_panel import TerminalPanel

class NotesTasksView(QWidget):
    """Local SQLite productivity suite for operational tasks, mission directives, and notes."""

    def __init__(self, parent=None):
        super().__init__(parent)
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
        title = QLabel("NOTES & TASKS // LOCAL DIRECTIVE REPOSITORY")
        title.setObjectName("section-header")
        tb_l.addWidget(title)
        main_layout.addWidget(title_box)

        splitter = QSplitter(Qt.Horizontal)

        # LEFT PANE: Task Manager
        task_widget = QWidget()
        tl = QVBoxLayout(task_widget)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)

        # Add Task Row
        add_frame = QFrame()
        add_frame.setObjectName("panel")
        afl = QHBoxLayout(add_frame)
        afl.setContentsMargins(10, 8, 10, 8)
        afl.setSpacing(8)

        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("Enter new task directive...")
        self.task_input.returnPressed.connect(self._add_task)
        afl.addWidget(self.task_input)

        self.prio_combo = QComboBox()
        self.prio_combo.addItems(["High", "Medium", "Low"])
        self.prio_combo.setCurrentIndex(1)
        afl.addWidget(self.prio_combo)

        add_btn = QPushButton("ADD TASK")
        add_btn.setObjectName("action-btn-primary")
        add_btn.clicked.connect(self._add_task)
        afl.addWidget(add_btn)

        tl.addWidget(add_frame)

        # Task Table
        self.task_table = QTableWidget()
        self.task_table.setColumnCount(4)
        self.task_table.setHorizontalHeaderLabels(["Status", "Directive", "Priority", "Actions"])
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        tl.addWidget(self.task_table)

        splitter.addWidget(task_widget)

        # RIGHT PANE: Quick Cyber Scratchpad & Notes
        notes_widget = QWidget()
        nl = QVBoxLayout(notes_widget)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(8)

        notes_header = QFrame()
        notes_header.setObjectName("panel")
        nh_l = QHBoxLayout(notes_header)
        nh_l.setContentsMargins(10, 8, 10, 8)
        n_lbl = QLabel("CYBER LOG SCRATCHPAD")
        n_lbl.setStyleSheet(f"color: {COLOR_CYAN}; font-size: 11px; font-weight: bold; letter-spacing: 1px;")
        nh_l.addWidget(n_lbl)
        nh_l.addStretch()

        save_note_btn = QPushButton("SAVE SCRATCHPAD")
        save_note_btn.setObjectName("action-btn-primary")
        save_note_btn.clicked.connect(self._save_notes)
        nh_l.addWidget(save_note_btn)
        nl.addWidget(notes_header)

        self.notes_editor = QTextEdit()
        self.notes_editor.setPlaceholderText("Record operational notes, system thoughts, or logs here...")
        nl.addWidget(self.notes_editor)

        splitter.addWidget(notes_widget)
        splitter.setSizes([550, 350])
        main_layout.addWidget(splitter, 1)

        # Scratchpad auto-saves shortly after you stop typing
        self._notes_timer = QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.timeout.connect(lambda: self._save_notes(silent=True))
        self.notes_editor.textChanged.connect(lambda: self._notes_timer.start(800))

        self.refresh_tasks()
        self._load_notes()

    def _add_task(self):
        title = self.task_input.text().strip()
        if not title:
            return
        prio = self.prio_combo.currentText()
        Database.get_instance().add_task(title=title, priority=prio)
        self.task_input.clear()
        self.refresh_tasks()

        term = TerminalPanel.get_instance()
        if term:
            term.log_info(f"Task created: '{title}' [{prio}]")

    def refresh_tasks(self):
        tasks = Database.get_instance().get_tasks()
        self.task_table.setRowCount(len(tasks))
        for row, t in enumerate(tasks):
            # Status check
            status_item = QTableWidgetItem("COMPLETED" if t["completed"] else "PENDING")
            status_item.setForeground(Qt.green if t["completed"] else Qt.yellow)
            self.task_table.setItem(row, 0, status_item)

            title_item = QTableWidgetItem(t["title"])
            if t["completed"]:
                title_item.setForeground(Qt.gray)
            self.task_table.setItem(row, 1, title_item)

            prio_item = QTableWidgetItem(t["priority"].upper())
            prio_color = Qt.red if t["priority"] == "High" else (Qt.cyan if t["priority"] == "Medium" else Qt.gray)
            prio_item.setForeground(prio_color)
            self.task_table.setItem(row, 2, prio_item)

            # Actions
            act_w = QWidget()
            al = QHBoxLayout(act_w)
            al.setContentsMargins(0, 0, 0, 0)
            al.setSpacing(4)

            toggle_btn = QPushButton("DONE" if not t["completed"] else "REOPEN")
            toggle_btn.setFixedHeight(20)
            toggle_btn.clicked.connect(lambda ch=False, tid=t["id"], comp=t["completed"]: self._toggle_task(tid, not comp))
            al.addWidget(toggle_btn)

            del_btn = QPushButton("DEL")
            del_btn.setObjectName("danger-btn")
            del_btn.setFixedHeight(20)
            del_btn.clicked.connect(lambda ch=False, tid=t["id"]: self._delete_task(tid))
            al.addWidget(del_btn)

            self.task_table.setCellWidget(row, 3, act_w)

    def _toggle_task(self, task_id, new_completed):
        Database.get_instance().update_task_status(task_id, new_completed)
        self.refresh_tasks()

    def _delete_task(self, task_id):
        Database.get_instance().delete_task(task_id)
        self.refresh_tasks()

    def _load_notes(self):
        saved = Database.get_instance().get_setting("user_scratchpad", "")
        self.notes_editor.blockSignals(True)
        self.notes_editor.setPlainText(saved)
        self.notes_editor.blockSignals(False)

    def _save_notes(self, silent=False):
        content = self.notes_editor.toPlainText()
        Database.get_instance().set_setting("user_scratchpad", content)
        if not silent:
            QMessageBox.information(self, "Saved", "Scratchpad persisted to local database.")

    def showEvent(self, event):
        # Tasks can be added/completed from the Home screen too
        super().showEvent(event)
        self.refresh_tasks()

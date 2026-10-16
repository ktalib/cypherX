import os
import subprocess
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, QFileInfo
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QComboBox, QApplication, QMessageBox, QFileIconProvider
)
from app.ui_polish import attach_file_menu
from app.config import (
    COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_GREEN, COLOR_PANEL_BG,
    COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_PANEL_ALT
)
from app.services.system_service import SystemService
from app.services.disk_service import DiskService
from app.icons import get_icon

class FileExplorerView(QWidget):
    """Futuristic cyberpunk file navigator with breadcrumb navigation and Windows Explorer integration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history = []
        self.future = []
        self.current_path = Path.home()
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
        title = QLabel("FILE EXPLORER // DIRECTORY NAVIGATOR & FS LAUNCHER")
        title.setObjectName("section-header")
        tb_l.addWidget(title)
        main_layout.addWidget(title_box)

        # Navigation Bar (Back, Forward, Up, Breadcrumb, Drives)
        nav_frame = QFrame()
        nav_frame.setObjectName("panel")
        nl = QHBoxLayout(nav_frame)
        nl.setContentsMargins(10, 8, 10, 8)
        nl.setSpacing(8)

        self.back_btn = QPushButton()
        self.back_btn.setIcon(get_icon("chevron_left", "#e2e8f0", 16))
        self.back_btn.setToolTip("Back")
        self.back_btn.setFixedSize(34, 32)
        self.back_btn.setStyleSheet("padding: 0px;")
        self.back_btn.clicked.connect(self._go_back)
        nl.addWidget(self.back_btn)

        self.forward_btn = QPushButton()
        self.forward_btn.setIcon(get_icon("chevron_right", "#e2e8f0", 16))
        self.forward_btn.setToolTip("Forward")
        self.forward_btn.setFixedSize(34, 32)
        self.forward_btn.setStyleSheet("padding: 0px;")
        self.forward_btn.clicked.connect(self._go_forward)
        nl.addWidget(self.forward_btn)

        self.up_btn = QPushButton()
        self.up_btn.setIcon(get_icon("chevron_up", "#e2e8f0", 16))
        self.up_btn.setToolTip("Up one level")
        self.up_btn.setFixedSize(34, 32)
        self.up_btn.setStyleSheet("padding: 0px;")
        self.up_btn.clicked.connect(self._go_up)
        nl.addWidget(self.up_btn)

        # Drive selector
        self.drive_combo = QComboBox()
        self.drive_combo.setFixedWidth(80)
        for d in DiskService.get_drives():
            self.drive_combo.addItem(d["mountpoint"])
        self.drive_combo.currentIndexChanged.connect(self._on_drive_changed)
        nl.addWidget(self.drive_combo)

        # Breadcrumb / path input
        self.path_input = QLineEdit(str(self.current_path))
        self.path_input.returnPressed.connect(self._on_path_entered)
        nl.addWidget(self.path_input)

        open_native_btn = QPushButton("OPEN IN EXPLORER")
        open_native_btn.clicked.connect(self._open_native_explorer)
        nl.addWidget(open_native_btn)

        copy_path_btn = QPushButton("COPY PATH")
        copy_path_btn.clicked.connect(self._copy_path)
        nl.addWidget(copy_path_btn)

        main_layout.addWidget(nav_frame)

        # Search filter bar
        filter_frame = QFrame()
        filter_frame.setObjectName("panel")
        fl = QHBoxLayout(filter_frame)
        fl.setContentsMargins(10, 6, 10, 6)
        fl.addWidget(QLabel("FILTER CURRENT FOLDER:"))
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter files by name...")
        self.filter_input.textChanged.connect(self._apply_filter)
        fl.addWidget(self.filter_input, 1)
        # Quick access to the usual user folders
        for label, icon, sub_dir in [("Home", "home", ""), ("Desktop", "computer", "Desktop"),
                                     ("Documents", "file_text", "Documents"), ("Downloads", "arrow_down", "Downloads"),
                                     ("Pictures", "image", "Pictures"), ("Music", "music", "Music"),
                                     ("Videos", "eye", "Videos")]:
            target = Path.home() / sub_dir if sub_dir else Path.home()
            if not target.exists():
                continue
            qb = QPushButton()
            qb.setIcon(get_icon(icon, "#cbd5e1", 15))
            qb.setToolTip(label)
            qb.setFixedSize(32, 30)
            qb.setStyleSheet("padding:0px;")
            qb.clicked.connect(lambda _=False, t=target: self._jump(t))
            fl.addWidget(qb)
        main_layout.addWidget(filter_frame)

        # File List Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Name", "Type / Ext", "Size", "Date Modified"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        attach_file_menu(self.table, self._row_path, open_on_double_click=False)
        main_layout.addWidget(self.table)
        self.count_lbl = QLabel("")
        self.count_lbl.setStyleSheet("color:#64748b;font-size:11px;background:transparent;")
        main_layout.addWidget(self.count_lbl)

        self.all_entries = []
        self._load_directory(self.current_path)

    def _load_directory(self, path: Path):
        try:
            if not path.exists() or not path.is_dir():
                return
            self.current_path = path
            self.path_input.setText(str(path))

            entries = []
            for entry in os.scandir(str(path)):
                try:
                    stat = entry.stat()
                    is_dir = entry.is_dir(follow_symlinks=False)
                    entries.append({
                        "name": entry.name,
                        "path": entry.path,
                        "is_dir": is_dir,
                        "size": 0 if is_dir else stat.st_size,
                        "mtime": stat.st_mtime,
                        "ext": "[DIR]" if is_dir else (os.path.splitext(entry.name)[1].lower() or "FILE")
                    })
                except (PermissionError, OSError):
                    continue

            # Sort directories first, then alphabetically
            entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
            self.all_entries = entries
            self._render_table(entries)

            self.back_btn.setEnabled(len(self.history) > 0)
            self.forward_btn.setEnabled(len(self.future) > 0)
        except Exception as e:
            QMessageBox.critical(self, "Directory Error", str(e))

    def _row_path(self, row):
        it = self.table.item(row, 0)
        return str(self.current_path / (it.data(Qt.UserRole) or it.text())) if it else None

    def _jump(self, target):
        self.history.append(self.current_path)
        self.future.clear()
        self._load_directory(Path(target))

    def _file_icon(self, item):
        """Real Windows shell icon, cached per extension (per file for .exe/.lnk/.ico)."""
        if not hasattr(self, "_icon_cache"):
            self._icon_cache = {}
            self._icon_provider = QFileIconProvider()
        if item["is_dir"]:
            key = "<dir>"
        elif item["ext"] in (".exe", ".lnk", ".ico", ".url"):
            key = item["path"]
        else:
            key = item["ext"]
        if key not in self._icon_cache:
            self._icon_cache[key] = (self._icon_provider.icon(QFileIconProvider.Folder) if item["is_dir"]
                                     else self._icon_provider.icon(QFileInfo(item["path"])))
        return self._icon_cache[key]

    def _render_table(self, entries):
        self.table.setRowCount(len(entries))
        files = sum(1 for e in entries if not e["is_dir"])
        total = sum(e["size"] for e in entries)
        if hasattr(self, "count_lbl"):
            self.count_lbl.setText(f"{len(entries) - files} folders · {files} files · "
                                   f"{SystemService.format_bytes(total)}  —  right-click for more options")
        for row, item in enumerate(entries):
            name_item = QTableWidgetItem(item['name'])
            name_item.setIcon(self._file_icon(item))
            name_item.setData(Qt.UserRole, item['name'])
            if item["is_dir"]:
                name_item.setForeground(Qt.white)
            self.table.setItem(row, 0, name_item)

            self.table.setItem(row, 1, QTableWidgetItem(item["ext"].upper()))
            size_str = "--" if item["is_dir"] else SystemService.format_bytes(item["size"])
            self.table.setItem(row, 2, QTableWidgetItem(size_str))

            dt_str = datetime.fromtimestamp(item["mtime"]).strftime("%Y-%m-%d %H:%M")
            self.table.setItem(row, 3, QTableWidgetItem(dt_str))

    def _apply_filter(self):
        query = self.filter_input.text().strip().lower()
        if not query:
            self._render_table(self.all_entries)
        else:
            filtered = [e for e in self.all_entries if query in e["name"].lower()]
            self._render_table(filtered)

    def _on_item_double_clicked(self, item):
        row = item.row()
        item_0 = self.table.item(row, 0)
        clean_name = item_0.data(Qt.UserRole) or item_0.text()
        target = self.current_path / clean_name

        if target.is_dir():
            self.history.append(self.current_path)
            self.future.clear()
            self._load_directory(target)
        elif target.is_file():
            os.startfile(str(target))

    def _go_back(self):
        if self.history:
            self.future.append(self.current_path)
            prev = self.history.pop()
            self._load_directory(prev)

    def _go_forward(self):
        if self.future:
            self.history.append(self.current_path)
            nxt = self.future.pop()
            self._load_directory(nxt)

    def _go_up(self):
        parent = self.current_path.parent
        if parent != self.current_path:
            self.history.append(self.current_path)
            self.future.clear()
            self._load_directory(parent)

    def _on_path_entered(self):
        p = Path(self.path_input.text().strip())
        if p.exists() and p.is_dir():
            self.history.append(self.current_path)
            self.future.clear()
            self._load_directory(p)

    def _on_drive_changed(self, idx):
        drive = self.drive_combo.currentText()
        if drive:
            p = Path(drive)
            if p.exists():
                self.history.append(self.current_path)
                self.future.clear()
                self._load_directory(p)

    def _open_native_explorer(self):
        subprocess.run(f'explorer "{os.path.normpath(str(self.current_path))}"', shell=True)

    def _copy_path(self):
        QApplication.clipboard().setText(str(self.current_path))

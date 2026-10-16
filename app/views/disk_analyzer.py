"""
Disk Analyzer — full-tree scan with a space ring chart, category breakdown,
drill-down into subfolders, file types and the 50 largest files anywhere.
"""
import os
import csv
import subprocess
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QLineEdit,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QFrame,
    QSplitter, QComboBox, QMessageBox, QTabWidget, QAbstractItemView, QSizePolicy
)

from app.icons import get_icon
from app.services.system_service import SystemService
from app.services.disk_service import DiskService
from app.workers.scan_worker import FolderScanWorker
from app.widgets.terminal_panel import TerminalPanel
from app.widgets.home.common import make_menu, hicon
from app.database import Database

PALETTE = ["#38bdf8", "#a78bfa", "#f5be4b", "#34d399", "#f87171", "#fb923c",
           "#22d3ee", "#e879f9", "#94a3b8"]
CAT_COLORS = {"Videos": "#f87171", "Images": "#34d399", "Audio": "#e879f9", "Documents": "#38bdf8",
              "Archives": "#f5be4b", "Installers": "#fb923c", "Code": "#a78bfa",
              "Spreadsheets": "#22d3ee", "Presentations": "#facc15", "Other": "#64748b"}
fmt = SystemService.format_bytes


class SizeItem(QTableWidgetItem):
    def __init__(self, size):
        super().__init__(fmt(size))
        self.size = size
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        return self.size < getattr(other, "size", 0)


class RingChart(QWidget):
    """Donut chart of the biggest subfolders, total in the centre."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments = []     # (label, value, color)
        self.total = 0
        self.setMinimumSize(170, 170)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setFixedWidth(180)

    def set_data(self, segments, total):
        self.segments, self.total = segments, total
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 12
        r = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        p.setPen(QPen(QColor(255, 255, 255, 22), 18))
        p.drawArc(r, 0, 360 * 16)
        if self.total > 0:
            start = 90 * 16
            for _label, value, color in self.segments:
                span = -int(360 * 16 * value / self.total)
                if span == 0:
                    continue
                p.setPen(QPen(QColor(color), 18, Qt.SolidLine, Qt.FlatCap))
                p.drawArc(r, start, span + (8 if span < -16 else 0))
                start += span
        f = QFont(self.font())
        f.setPixelSize(18)
        f.setWeight(QFont.Light)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(r.adjusted(0, -10, 0, -10), Qt.AlignCenter, fmt(self.total) if self.total else "—")
        f.setPixelSize(10)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        p.setPen(QColor("#94a3b8"))
        p.drawText(r.adjusted(0, 22, 0, 22), Qt.AlignCenter, "TOTAL")


class DiskAnalyzerView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: FolderScanWorker = None
        self.last_results = None
        self.history = []
        self._setup_ui()

    # ------------------------------------------------------------------ UI --

    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(12)

        title_box = QFrame()
        title_box.setObjectName("panel")
        tb = QHBoxLayout(title_box)
        tb.setContentsMargins(14, 10, 14, 10)
        title = QLabel("DISK ANALYZER // WHERE IS MY SPACE GOING?")
        title.setObjectName("section-header")
        tb.addWidget(title)
        main.addWidget(title_box)

        ctrl = QFrame()
        ctrl.setObjectName("panel")
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(12, 8, 12, 8)
        cl.setSpacing(8)
        self.back_btn = QPushButton()
        self.back_btn.setIcon(get_icon("chevron_left", "#e2e8f0", 16))
        self.back_btn.setToolTip("Back to previous folder")
        self.back_btn.setFixedSize(34, 32)
        self.back_btn.setEnabled(False)
        self.back_btn.clicked.connect(self._go_back)
        cl.addWidget(self.back_btn)
        self.up_btn = QPushButton()
        self.up_btn.setIcon(get_icon("chevron_up", "#e2e8f0", 16))
        self.up_btn.setToolTip("Analyze parent folder")
        self.up_btn.setFixedSize(34, 32)
        self.up_btn.clicked.connect(self._go_up)
        cl.addWidget(self.up_btn)
        self.drive_combo = QComboBox()
        self.drive_combo.setFixedWidth(84)
        for d in DiskService.get_drives():
            self.drive_combo.addItem(d["mountpoint"], d["mountpoint"])
        self.drive_combo.activated.connect(lambda _: self._analyze(self.drive_combo.currentData()))
        cl.addWidget(self.drive_combo)
        self.path_input = QLineEdit(str(Path.home()))
        self.path_input.returnPressed.connect(self.start_scan)
        cl.addWidget(self.path_input, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_folder)
        cl.addWidget(browse)
        self.scan_btn = QPushButton("Analyze")
        self.scan_btn.setObjectName("action-btn-primary")
        self.scan_btn.clicked.connect(self.start_scan)
        cl.addWidget(self.scan_btn)
        self.cancel_btn = QPushButton("Stop")
        self.cancel_btn.setObjectName("danger-btn")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_scan)
        cl.addWidget(self.cancel_btn)
        self.export_btn = QPushButton("Export CSV")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export_csv)
        cl.addWidget(self.export_btn)
        main.addWidget(ctrl)

        self.progress_frame = QFrame()
        self.progress_frame.setVisible(False)
        pf = QVBoxLayout(self.progress_frame)
        pf.setContentsMargins(0, 0, 0, 0)
        pf.setSpacing(4)
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color:#94a3b8;font-size:11px;background:transparent;")
        pf.addWidget(self.status_lbl)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(6)
        pf.addWidget(self.progress_bar)
        main.addWidget(self.progress_frame)

        # Overview: ring + legend | category bars
        over = QHBoxLayout()
        over.setSpacing(12)
        ring_card = QFrame()
        ring_card.setObjectName("panel")
        rl = QHBoxLayout(ring_card)
        rl.setContentsMargins(12, 10, 14, 10)
        rl.setSpacing(12)
        self.ring = RingChart()
        rl.addWidget(self.ring)
        lv = QVBoxLayout()
        lv.setSpacing(3)
        self.summary_lbl = QLabel("Pick a folder or drive and press Analyze.")
        self.summary_lbl.setWordWrap(True)
        self.summary_lbl.setStyleSheet("color:#e2e8f0;font-size:12px;font-weight:600;background:transparent;")
        lv.addWidget(self.summary_lbl)
        self.legend = QGridLayout()
        self.legend.setHorizontalSpacing(8)
        self.legend.setVerticalSpacing(2)
        lv.addLayout(self.legend)
        lv.addStretch()
        rl.addLayout(lv, 1)
        over.addWidget(ring_card, 3)

        cat_card = QFrame()
        cat_card.setObjectName("panel")
        cv = QVBoxLayout(cat_card)
        cv.setContentsMargins(14, 10, 14, 10)
        cv.setSpacing(5)
        h = QLabel("BY FILE CATEGORY")
        h.setStyleSheet("color:#94a3b8;font-size:10px;font-weight:800;letter-spacing:1px;background:transparent;")
        cv.addWidget(h)
        self.cat_layout = QVBoxLayout()
        self.cat_layout.setSpacing(4)
        cv.addLayout(self.cat_layout)
        cv.addStretch()
        over.addWidget(cat_card, 2)
        main.addLayout(over)

        # Details
        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)
        lh = QLabel("FOLDERS  ·  double-click to drill in")
        lh.setStyleSheet("color:#38bdf8;font-size:10px;font-weight:800;letter-spacing:1px;background:transparent;")
        ll.addWidget(lh)
        self.folder_table = self._table(["Folder", "Size", "Files", "Share"])
        self.folder_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        fh = self.folder_table.horizontalHeader()
        fh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        fh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        fh.setSectionResizeMode(3, QHeaderView.Fixed)
        self.folder_table.setColumnWidth(3, 96)
        self.folder_table.itemDoubleClicked.connect(self._drill)
        ll.addWidget(self.folder_table)
        splitter.addWidget(left)

        self.tabs = QTabWidget()
        self.large_table = self._table(["File", "Size", "Modified", "Location"])
        self.large_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.large_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.large_table.customContextMenuRequested.connect(self._file_menu)
        self.large_table.itemDoubleClicked.connect(lambda it: self._open(self.large_table.item(it.row(), 0).data(Qt.UserRole)))
        self.ext_table = self._table(["Type", "Files", "Total size", "Share"])
        self.ext_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabs.addTab(self.large_table, "Largest files")
        self.tabs.addTab(self.ext_table, "File types")
        splitter.addWidget(self.tabs)
        splitter.setSizes([480, 480])
        main.addWidget(splitter, 1)

    @staticmethod
    def _table(headers):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSortingEnabled(True)
        return t

    # ------------------------------------------------------------ actions --

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Analyze", self.path_input.text())
        if folder:
            self._analyze(folder)

    def _analyze(self, path, remember=True):
        if not path:
            return
        cur = self.last_results["root"] if self.last_results else None
        if remember and cur and os.path.normcase(cur) != os.path.normcase(path):
            self.history.append(cur)
        self.path_input.setText(os.path.normpath(path))
        self.start_scan()

    def _go_back(self):
        if self.history:
            self._analyze(self.history.pop(), remember=False)

    def _go_up(self):
        parent = str(Path(self.path_input.text()).parent)
        if parent and parent != self.path_input.text():
            self._analyze(parent)

    def _drill(self, item):
        name_item = self.folder_table.item(item.row(), 0)
        path = name_item.data(Qt.UserRole) if name_item else None
        if path and os.path.isdir(path):
            self._analyze(path)

    def start_scan(self):
        target = self.path_input.text().strip()
        if not os.path.isdir(target):
            QMessageBox.warning(self, "Invalid Path", "The specified folder does not exist.")
            return
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        if DiskService.is_protected_path(target):
            if QMessageBox.question(self, "System Folder",
                                    f"'{target}' is a Windows system folder. Some parts may be unreadable "
                                    "without administrator rights. Continue?") != QMessageBox.Yes:
                return
        self.scan_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.export_btn.setEnabled(False)
        self.progress_frame.setVisible(True)
        self.status_lbl.setText(f"Scanning {target}…")
        term = TerminalPanel.get_instance()
        if term:
            term.log_info(f"Disk Analyzer scanning {target}")
        self.worker = FolderScanWorker(target)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_scan_finished)
        self.worker.error.connect(self._on_scan_error)
        self.worker.start()

    def cancel_scan(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
        self.scan_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_frame.setVisible(False)

    def _on_progress(self, count, name):
        self.status_lbl.setText(f"Scanning… {count:,} files  ·  {name[:60]}")

    def _on_scan_error(self, err):
        self.cancel_scan()
        QMessageBox.critical(self, "Scan Error", f"Failed to complete scan:\n{err}")

    # ------------------------------------------------------------ render --

    def _on_scan_finished(self, res):
        self.last_results = res
        self.scan_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.export_btn.setEnabled(True)
        self.progress_frame.setVisible(False)
        self.back_btn.setEnabled(bool(self.history))
        total = res["total_size"]
        root = res["root"]

        skipped = f" · {res['skipped']} unreadable" if res.get("skipped") else ""
        self.summary_lbl.setText(f"{os.path.basename(root.rstrip(os.sep)) or root}\n"
                                 f"{res['file_count']:,} files in {res['folder_count']:,} folders{skipped}")

        # Ring + legend
        folders = sorted(res["subfolders"].items(), key=lambda x: x[1], reverse=True)
        segs = []
        for i, (name, size) in enumerate(folders[:7]):
            segs.append((name, size, PALETTE[i]))
        rest = sum(s for _, s in folders[7:]) + res.get("loose_size", 0)
        if rest:
            segs.append(("Other / loose files", rest, PALETTE[-1]))
        self.ring.set_data(segs, total)
        while self.legend.count():
            w = self.legend.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i, (name, size, color) in enumerate(segs):
            dot = QLabel()
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(f"background:{color};border-radius:4px;")
            n = QLabel(name if len(name) < 30 else name[:28] + "…")
            n.setStyleSheet("color:#cbd5e1;font-size:11px;background:transparent;")
            v = QLabel(f"{fmt(size)}  ·  {size * 100 / total:.0f}%" if total else fmt(size))
            v.setStyleSheet("color:#94a3b8;font-size:11px;background:transparent;")
            self.legend.addWidget(dot, i, 0)
            self.legend.addWidget(n, i, 1)
            self.legend.addWidget(v, i, 2, Qt.AlignRight)
        self.legend.setColumnStretch(1, 1)

        # Categories
        while self.cat_layout.count():
            it = self.cat_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        cats = sorted(res.get("categories", {}).items(), key=lambda x: x[1], reverse=True)
        top = cats[0][1] if cats else 1
        for name, size in cats[:7]:
            row = QWidget()
            row.setStyleSheet("background:transparent;")
            g = QGridLayout(row)
            g.setContentsMargins(0, 0, 0, 0)
            g.setVerticalSpacing(1)
            n = QLabel(name)
            n.setStyleSheet("color:#e2e8f0;font-size:11px;font-weight:600;")
            v = QLabel(fmt(size))
            v.setStyleSheet("color:#94a3b8;font-size:11px;")
            pb = QProgressBar()
            pb.setRange(0, 1000)
            pb.setValue(int(size * 1000 / top) if top else 0)
            pb.setTextVisible(False)
            pb.setFixedHeight(5)
            pb.setStyleSheet(f"QProgressBar{{background:rgba(255,255,255,0.07);border:none;border-radius:2px;}}"
                             f"QProgressBar::chunk{{background:{CAT_COLORS.get(name, '#64748b')};border-radius:2px;}}")
            g.addWidget(n, 0, 0)
            g.addWidget(v, 0, 1, Qt.AlignRight)
            g.addWidget(pb, 1, 0, 1, 2)
            self.cat_layout.addWidget(row)

        # Folders table
        t = self.folder_table
        t.setSortingEnabled(False)
        t.setRowCount(len(folders))
        files = res.get("subfolder_files", {})
        for r, (name, size) in enumerate(folders):
            it = QTableWidgetItem(get_icon("folder", "#fbbf24", 16), name)
            it.setData(Qt.UserRole, os.path.join(root, name))
            t.setItem(r, 0, it)
            t.setItem(r, 1, SizeItem(size))
            fi = QTableWidgetItem(f"{files.get(name, 0):,}")
            fi.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t.setItem(r, 2, fi)
            pct = size * 100 / total if total else 0
            pb = QProgressBar()
            pb.setRange(0, 100)
            pb.setValue(int(round(pct)))
            pb.setFormat(f"{pct:.1f}%")
            pb.setFixedHeight(16)
            pb.setStyleSheet("QProgressBar{background:rgba(255,255,255,0.06);border:none;border-radius:4px;"
                             "font-size:10px;color:#e2e8f0;}"
                             "QProgressBar::chunk{background:rgba(56,189,248,0.55);border-radius:4px;}")
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(6, 0, 6, 0)
            hl.addWidget(pb)
            t.setCellWidget(r, 3, holder)
        t.setSortingEnabled(True)
        t.sortItems(1, Qt.DescendingOrder)

        # Largest files
        t = self.large_table
        t.setSortingEnabled(False)
        t.setRowCount(len(res["largest_files"]))
        for r, f in enumerate(res["largest_files"]):
            it = QTableWidgetItem(f["name"])
            it.setData(Qt.UserRole, f["path"])
            it.setToolTip(f["path"])
            t.setItem(r, 0, it)
            t.setItem(r, 1, SizeItem(f["size"]))
            t.setItem(r, 2, QTableWidgetItem(datetime.fromtimestamp(f["modified"]).strftime("%Y-%m-%d")))
            loc = QTableWidgetItem(os.path.relpath(os.path.dirname(f["path"]), root))
            loc.setForeground(QColor("#64748b"))
            t.setItem(r, 3, loc)
        t.setSortingEnabled(True)

        # File types
        t = self.ext_table
        t.setSortingEnabled(False)
        exts = sorted(res["extensions"].items(), key=lambda x: x[1]["size"], reverse=True)
        t.setRowCount(len(exts))
        for r, (ext, d) in enumerate(exts):
            t.setItem(r, 0, QTableWidgetItem(ext))
            c = QTableWidgetItem(f"{d['count']:,}")
            c.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t.setItem(r, 1, c)
            t.setItem(r, 2, SizeItem(d["size"]))
            s = QTableWidgetItem(f"{d['size'] * 100 / total:.1f}%" if total else "—")
            s.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t.setItem(r, 3, s)
        t.setSortingEnabled(True)

        term = TerminalPanel.get_instance()
        if term:
            term.log_success(f"Disk analysis finished: {fmt(total)} across {res['file_count']:,} files.")
        Database.get_instance().log_operation(
            operation_type="Disk Analyzer", action=f"Scanned {root}",
            result=f"{res['file_count']} files, {fmt(total)}", target_path=root)

    # ------------------------------------------------------------ files --

    def _file_menu(self, pos):
        item = self.large_table.itemAt(pos)
        if not item:
            return
        path = self.large_table.item(item.row(), 0).data(Qt.UserRole)
        m = make_menu(self)
        m.addAction(hicon("eye", "#e2e8f0", 14), "Open", lambda: self._open(path))
        m.addAction(hicon("folder", "#e2e8f0", 14), "Show in Explorer", lambda: self._reveal(path))
        m.addAction(hicon("pie_chart", "#e2e8f0", 14), "Analyze containing folder",
                    lambda: self._analyze(os.path.dirname(path)))
        m.addAction(hicon("duplicate_finder", "#e2e8f0", 14), "Copy path",
                    lambda: QGuiApplication.clipboard().setText(path))
        m.exec(QCursor.pos())

    @staticmethod
    def _open(path):
        if path and os.path.exists(path):
            os.startfile(path)

    @staticmethod
    def _reveal(path):
        if path and os.path.exists(path):
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')

    def export_csv(self):
        if not self.last_results:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Export Scan Results", "disk_analysis_report.csv",
                                                   "CSV Files (*.csv)")
        if not save_path:
            return
        res = self.last_results
        try:
            with open(save_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Type", "Name", "Size (bytes)", "Size", "Detail"])
                w.writerow(["SUMMARY", res["root"], res["total_size"], fmt(res["total_size"]), f"{res['file_count']} files"])
                for name, size in sorted(res["subfolders"].items(), key=lambda x: x[1], reverse=True):
                    w.writerow(["FOLDER", name, size, fmt(size), res.get("subfolder_files", {}).get(name, "")])
                for name, size in res.get("categories", {}).items():
                    w.writerow(["CATEGORY", name, size, fmt(size), ""])
                for it in res["largest_files"]:
                    w.writerow(["LARGE_FILE", it["path"], it["size"], fmt(it["size"]), ""])
                for ext, d in res["extensions"].items():
                    w.writerow(["EXTENSION", ext, d["size"], fmt(d["size"]), d["count"]])
            QMessageBox.information(self, "Export Complete", f"Saved to:\n{save_path}")
        except OSError as e:
            QMessageBox.critical(self, "Export Error", str(e))

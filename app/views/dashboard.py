from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QProgressBar, QStackedWidget
)
from app.config import (
    COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_GREEN, COLOR_PANEL_BG,
    COLOR_RED, COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_PANEL_ALT,
    COLOR_YELLOW
)
from app.widgets.metric_card import MetricCard
from app.widgets.chart_widget import CyberLineChart
from app.widgets.terminal_panel import TerminalPanel
from app.services.system_service import SystemService
from app.services.network_service import NetworkService
from app.database import Database
from app.icons import get_icon

class DashboardView(QWidget):
    """Main Command Center Dashboard providing system overview and telemetry."""

    navigate_to_module = Signal(str)  # Emitted when quick actions trigger navigation

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(12)

        # 1. Quick Actions Command Bar
        c_layout.addWidget(self._build_quick_actions())

        # 2. Rotating health and alert widgets
        c_layout.addWidget(self._build_insight_carousel())

        # 3. Key Metrics Row (4 Cyber Metric Cards)
        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(10)

        self.card_cpu = MetricCard("CPU UTILIZATION", unit="%", accent=COLOR_CYAN)
        self.card_ram = MetricCard("RAM CONSUMPTION", unit="%", accent=COLOR_GREEN)
        self.card_disk = MetricCard("DISK CAPACITY (C:)", unit="%", accent=COLOR_CYAN)
        self.card_net = MetricCard("COMM BANDWIDTH", unit="KB/s", accent=COLOR_GREEN)

        metrics_layout.addWidget(self.card_cpu)
        metrics_layout.addWidget(self.card_ram)
        metrics_layout.addWidget(self.card_disk)
        metrics_layout.addWidget(self.card_net)
        c_layout.addLayout(metrics_layout)

        # 4. Oscilloscope Telemetry Graphs Row
        graphs_layout = QHBoxLayout()
        graphs_layout.setSpacing(10)

        self.chart_cpu = CyberLineChart(title="CPU REALTIME LOAD TRACKER", accent_color=COLOR_CYAN, unit="%")
        self.chart_ram = CyberLineChart(title="RAM REALTIME USAGE HISTORY", accent_color=COLOR_GREEN, unit="%")
        self.chart_net = CyberLineChart(title="BANDWIDTH TRAFFIC (KB/s)", accent_color=COLOR_CYAN, unit="KB/s")

        graphs_layout.addWidget(self.chart_cpu)
        graphs_layout.addWidget(self.chart_ram)
        graphs_layout.addWidget(self.chart_net)
        c_layout.addLayout(graphs_layout)

        # 5. Storage Overview & Tasks Row
        mid_row = QHBoxLayout()
        mid_row.setSpacing(10)

        # Disk drives panel
        self.drives_panel = self._build_drives_overview()
        mid_row.addWidget(self.drives_panel, stretch=2)

        # Active Tasks panel
        self.tasks_panel = self._build_tasks_preview()
        mid_row.addWidget(self.tasks_panel, stretch=1)

        c_layout.addLayout(mid_row)

        # 6. Live Operations Terminal Panel
        self.terminal = TerminalPanel()
        self.terminal.setMinimumHeight(180)
        c_layout.addWidget(self.terminal)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def _build_insight_carousel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("SYSTEM INSIGHTS")
        title.setObjectName("section-header")
        header.addWidget(title)
        header.addStretch()

        self.carousel_previous = QPushButton("<")
        self.carousel_previous.setToolTip("Previous dashboard widget")
        self.carousel_previous.clicked.connect(
            lambda: self._show_carousel_slide(self.insight_slides.currentIndex() - 1)
        )
        self.carousel_counter = QLabel("01 / 03")
        self.carousel_counter.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px; font-weight: bold;"
        )
        self.carousel_next = QPushButton(">")
        self.carousel_next.setToolTip("Next dashboard widget")
        self.carousel_next.clicked.connect(
            lambda: self._show_carousel_slide(self.insight_slides.currentIndex() + 1)
        )
        for button in (self.carousel_previous, self.carousel_next):
            button.setFixedSize(26, 24)
            button.setObjectName("action-btn")
        header.addWidget(self.carousel_previous)
        header.addWidget(self.carousel_counter)
        header.addWidget(self.carousel_next)
        layout.addLayout(header)

        self.insight_slides = QStackedWidget()
        self.insight_slides.setMinimumHeight(76)
        self.health_title, self.health_detail, self.health_action = self._make_insight_slide(
            "SYSTEM HEALTH", "Waiting for telemetry...", "OPEN SYSTEM MONITOR", "system_monitor"
        )
        self.alert_title, self.alert_detail, self.alert_action = self._make_insight_slide(
            "SMART ALERTS", "Waiting for telemetry...", "VIEW DETAILS", None
        )
        self._alert_module_id = None
        self.alert_action.clicked.connect(self._open_alert_target)
        self.capacity_title, self.capacity_detail, self.capacity_action = self._make_insight_slide(
            "STORAGE OUTLOOK", "Waiting for drive data...", "ANALYZE DISK", "disk_analyzer"
        )
        self._show_carousel_slide(0)
        layout.addWidget(self.insight_slides)

        self.carousel_timer = QTimer(self)
        self.carousel_timer.setInterval(7000)
        self.carousel_timer.timeout.connect(
            lambda: self._show_carousel_slide(self.insight_slides.currentIndex() + 1)
        )
        return frame

    def _make_insight_slide(self, title: str, detail: str, action_text: str,
                            module_id: str | None) -> tuple:
        slide = QWidget()
        row = QHBoxLayout(slide)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        text_column = QVBoxLayout()
        text_column.setSpacing(3)
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: {COLOR_CYAN}; font-size: 10px; font-weight: bold; letter-spacing: 1px;"
        )
        detail_label = QLabel(detail)
        detail_label.setWordWrap(True)
        detail_label.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY}; font-size: 12px;"
        )
        text_column.addWidget(title_label)
        text_column.addWidget(detail_label)
        row.addLayout(text_column, 1)

        action = QPushButton(action_text)
        action.setObjectName("action-btn-primary")
        if module_id:
            action.clicked.connect(lambda: self.navigate_to_module.emit(module_id))
        row.addWidget(action)

        self.insight_slides.addWidget(slide)
        return title_label, detail_label, action

    def _show_carousel_slide(self, index: int):
        if not hasattr(self, "insight_slides"):
            return
        count = self.insight_slides.count()
        if count == 0:
            return
        index %= count
        self.insight_slides.setCurrentIndex(index)
        self.carousel_counter.setText(f"{index + 1:02d} / {count:02d}")

    def _open_alert_target(self):
        if self._alert_module_id:
            self.navigate_to_module.emit(self._alert_module_id)

    def _build_quick_actions(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        lbl = QLabel("COMMAND ACTIONS:")
        lbl.setStyleSheet(f"color: {COLOR_CYAN}; font-size: 10px; font-weight: bold; letter-spacing: 1.5px;")
        layout.addWidget(lbl)

        btn_clean = QPushButton(" Clean Temp Files")
        btn_clean.setIcon(get_icon("cleaner", "#ffffff", 14))
        btn_clean.setObjectName("action-btn-primary")
        btn_clean.clicked.connect(lambda: self.navigate_to_module.emit("disk_cleaner"))
        layout.addWidget(btn_clean)

        btn_organize = QPushButton(" Organize Folder")
        btn_organize.setIcon(get_icon("folder_organizer", "#ffffff", 14))
        btn_organize.clicked.connect(lambda: self.navigate_to_module.emit("folder_organizer"))
        layout.addWidget(btn_organize)

        btn_analyze = QPushButton(" Analyze Disk")
        btn_analyze.setIcon(get_icon("pie_chart", "#ffffff", 14))
        btn_analyze.clicked.connect(lambda: self.navigate_to_module.emit("disk_analyzer"))
        layout.addWidget(btn_analyze)

        btn_dups = QPushButton(" Find Duplicates")
        btn_dups.setIcon(get_icon("duplicate_finder", "#ffffff", 14))
        btn_dups.clicked.connect(lambda: self.navigate_to_module.emit("duplicate_finder"))
        layout.addWidget(btn_dups)

        layout.addStretch()
        return frame

    def _build_drives_overview(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        self.drives_layout = QVBoxLayout(frame)
        self.drives_layout.setContentsMargins(14, 12, 14, 12)
        self.drives_layout.setSpacing(8)

        title = QLabel("STORAGE VOLUMES OVERVIEW")
        title.setObjectName("section-header")
        self.drives_layout.addWidget(title)

        self.drives_container = QVBoxLayout()
        self.drives_layout.addLayout(self.drives_container)
        return frame

    def _build_tasks_preview(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        h = QHBoxLayout()
        title = QLabel("ACTIVE MISSIONS & TASKS")
        title.setObjectName("section-header")
        h.addWidget(title)
        h.addStretch()

        btn = QPushButton("VIEW ALL")
        btn.setFixedHeight(20)
        btn.clicked.connect(lambda: self.navigate_to_module.emit("notes_tasks"))
        h.addWidget(btn)
        layout.addLayout(h)

        self.tasks_list_layout = QVBoxLayout()
        layout.addLayout(self.tasks_list_layout)
        self.refresh_tasks()
        return frame

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_tasks()
        self.carousel_timer.start()

    def hideEvent(self, event):
        self.carousel_timer.stop()
        super().hideEvent(event)

    def refresh_tasks(self):
        # Clear previous items
        while self.tasks_list_layout.count():
            item = self.tasks_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        tasks = Database.get_instance().get_tasks(include_completed=False)[:4]
        if not tasks:
            lbl = QLabel("No active pending tasks. All operations nominal.")
            lbl.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px;")
            self.tasks_list_layout.addWidget(lbl)
        else:
            for t in tasks:
                t_box = QWidget()
                tl = QHBoxLayout(t_box)
                tl.setContentsMargins(0, 2, 0, 2)
                dot = QLabel("◈")
                dot.setStyleSheet(f"color: {COLOR_GREEN}; font-size: 10px;")
                t_lbl = QLabel(t["title"])
                t_lbl.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 11px;")
                tl.addWidget(dot)
                tl.addWidget(t_lbl)
                tl.addStretch()
                self.tasks_list_layout.addWidget(t_box)

    def update_metrics(self, cpu_metrics: dict, mem_metrics: dict, disks: list, net_rates: dict):
        alerts = []
        health_level = "NOMINAL"
        health_color = COLOR_GREEN

        cpu_pct = cpu_metrics.get("percent") if cpu_metrics else None
        if cpu_pct is not None:
            if cpu_pct >= 90:
                alerts.append((f"Critical CPU load: {cpu_pct:.0f}%", "process_manager"))
                health_level, health_color = "CRITICAL", COLOR_RED
            elif cpu_pct >= 80:
                alerts.append((f"High CPU load: {cpu_pct:.0f}%", "process_manager"))
                if health_level == "NOMINAL":
                    health_level, health_color = "ATTENTION", COLOR_YELLOW

        ram_pct = mem_metrics.get("percent") if mem_metrics else None
        if ram_pct is not None:
            if ram_pct >= 90:
                alerts.append((f"Critical memory use: {ram_pct:.0f}%", "system_monitor"))
                health_level, health_color = "CRITICAL", COLOR_RED
            elif ram_pct >= 80:
                alerts.append((f"High memory use: {ram_pct:.0f}%", "system_monitor"))
                if health_level == "NOMINAL":
                    health_level, health_color = "ATTENTION", COLOR_YELLOW

        primary_disk = None
        for disk in disks or []:
            if disk["mountpoint"].upper().startswith("C"):
                primary_disk = disk
                break
        if primary_disk is None and disks:
            primary_disk = disks[0]
        if primary_disk is not None:
            disk_pct = primary_disk["percent"]
            if disk_pct >= 95:
                alerts.append((f"Critical storage: {primary_disk['mountpoint']} is {disk_pct:.0f}% full",
                               "disk_analyzer"))
                health_level, health_color = "CRITICAL", COLOR_RED
            elif disk_pct >= 85:
                alerts.append((f"Low disk space: {primary_disk['mountpoint']} is {disk_pct:.0f}% full",
                               "disk_analyzer"))
                if health_level == "NOMINAL":
                    health_level, health_color = "ATTENTION", COLOR_YELLOW

        self.health_title.setText(f"SYSTEM HEALTH  ·  {health_level}")
        self.health_title.setStyleSheet(
            f"color: {health_color}; font-size: 10px; font-weight: bold; letter-spacing: 1px;"
        )
        self.health_detail.setText(
            "All monitored resources are within normal ranges."
            if not alerts else f"{len(alerts)} resource alert{'s' if len(alerts) != 1 else ''} need attention."
        )
        self.alert_title.setText(f"SMART ALERTS  ·  {len(alerts)}")
        if alerts:
            self.alert_detail.setText("  •  ".join(message for message, _ in alerts))
            self.alert_action.setText("VIEW DETAILS")
            self._alert_module_id = alerts[0][1]
            self.alert_action.setEnabled(True)
        else:
            self.alert_detail.setText("No active resource alerts.")
            self.alert_action.setText("ALL CLEAR")
            self._alert_module_id = None
            self.alert_action.setEnabled(False)

        if primary_disk is not None:
            free_gb = primary_disk["free"] / (1024 ** 3)
            total_gb = primary_disk["total"] / (1024 ** 3)
            self.capacity_title.setText(f"STORAGE OUTLOOK  ·  {primary_disk['mountpoint']}")
            self.capacity_detail.setText(
                f"{free_gb:.1f} GB free of {total_gb:.1f} GB "
                f"({primary_disk['percent']:.0f}% used)."
            )

        # Update CPU
        if cpu_metrics:
            cpu_pct = cpu_metrics.get("percent", 0.0)
            freq = cpu_metrics.get("freq_mhz", 0)
            self.card_cpu.set_value(cpu_pct, subtitle=f"{freq} MHz | {cpu_metrics.get('count_logical', 1)} Threads")
            self.chart_cpu.add_point(cpu_pct)

        # Update RAM
        if mem_metrics:
            ram_pct = mem_metrics.get("percent", 0.0)
            used_gb = mem_metrics.get("used", 0) / (1024**3)
            tot_gb = mem_metrics.get("total", 0) / (1024**3)
            self.card_ram.set_value(ram_pct, subtitle=f"{used_gb:.1f} / {tot_gb:.1f} GB")
            self.chart_ram.add_point(ram_pct)

        # Update Network
        if net_rates:
            down_kb = net_rates.get("down_bps", 0.0) / 1024.0
            up_kb = net_rates.get("up_bps", 0.0) / 1024.0
            tot_kb = down_kb + up_kb
            self.card_net.set_value(round(tot_kb, 1), subtitle=f"↓ {down_kb:.1f} KB/s | ↑ {up_kb:.1f} KB/s", progress_pct=min(tot_kb / 50.0, 100))
            self.chart_net.add_point(tot_kb)

        # Update Disks
        if disks:
            # Primary drive for card
            primary = disks[0]
            for d in disks:
                if d["mountpoint"].upper().startswith("C"):
                    primary = d
                    break
            tot_gb = primary["total"] / (1024**3)
            free_gb = primary["free"] / (1024**3)
            self.card_disk.set_value(primary["percent"], subtitle=f"{free_gb:.1f} GB Free of {tot_gb:.0f} GB")

            # Render drives overview items if container empty
            if self.drives_container.count() == 0:
                for d in disks:
                    d_widget = QWidget()
                    dl = QVBoxLayout(d_widget)
                    dl.setContentsMargins(0, 4, 0, 4)
                    dl.setSpacing(3)

                    header_l = QHBoxLayout()
                    d_lbl = QLabel(f"{d['mountpoint']} [{d['fstype'].upper()}] - {SystemService.format_bytes(d['free'])} free of {SystemService.format_bytes(d['total'])}")
                    d_lbl.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 11px;")
                    d_pct = QLabel(f"{d['percent']}%")
                    d_pct.setStyleSheet(f"color: {COLOR_CYAN}; font-size: 11px; font-weight: bold;")
                    header_l.addWidget(d_lbl)
                    header_l.addStretch()
                    header_l.addWidget(d_pct)
                    dl.addLayout(header_l)

                    bar = QProgressBar()
                    bar.setRange(0, 100)
                    bar.setValue(int(d['percent']))
                    bar.setTextVisible(False)
                    bar.setFixedHeight(5)
                    dl.addWidget(bar)

                    self.drives_container.addWidget(d_widget)

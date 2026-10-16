from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QFrame, QScrollArea, QComboBox, QProgressBar
)
from app.config import (
    COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_GREEN, COLOR_PANEL_BG,
    COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_PANEL_ALT
)
from app.widgets.chart_widget import CyberLineChart
from app.services.system_service import SystemService
from app.services.network_service import NetworkService

class SystemMonitorView(QWidget):
    """Deep real-time Windows system telemetry dashboard with per-core analysis and historical charts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.per_core_bars = []
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        # Header Title with refresh rate picker
        title_box = QFrame()
        title_box.setObjectName("panel")
        tb_l = QHBoxLayout(title_box)
        tb_l.setContentsMargins(14, 10, 14, 10)
        title = QLabel("SYSTEM MONITOR // HARDWARE TELEMETRY & MULTI-CORE OSCILLOSCOPE")
        title.setObjectName("section-header")
        tb_l.addWidget(title)
        tb_l.addStretch()

        tb_l.addWidget(QLabel("SAMPLING INTERVAL:"))
        self.interval_combo = QComboBox()
        self.interval_combo.addItem("Fast (1.0s)", 1000)
        self.interval_combo.addItem("Normal (1.5s)", 1500)
        self.interval_combo.addItem("Eco (3.0s)", 3000)
        self.interval_combo.setCurrentIndex(1)
        tb_l.addWidget(self.interval_combo)

        main_layout.addWidget(title_box)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(12)

        # 1. Historical Telemetry Graphs Row
        graphs_layout = QHBoxLayout()
        graphs_layout.setSpacing(10)

        self.chart_cpu = CyberLineChart(title="PROCESSOR OVERALL LOAD", accent_color=COLOR_CYAN, unit="%", max_points=50)
        self.chart_ram = CyberLineChart(title="VIRTUAL RAM UTILIZATION", accent_color=COLOR_GREEN, unit="%", max_points=50)
        self.chart_net = CyberLineChart(title="LOCAL COMM THROUGHPUT", accent_color=COLOR_CYAN, unit="KB/s", max_points=50)

        graphs_layout.addWidget(self.chart_cpu)
        graphs_layout.addWidget(self.chart_ram)
        graphs_layout.addWidget(self.chart_net)
        c_layout.addLayout(graphs_layout)

        # 2. Per-Core CPU Breakdown Frame
        core_frame = QFrame()
        core_frame.setObjectName("panel")
        cf_layout = QVBoxLayout(core_frame)
        cf_layout.setContentsMargins(14, 12, 14, 12)
        cf_layout.setSpacing(8)

        cf_header = QLabel("LOGICAL CORES UTILIZATION MATRIX")
        cf_header.setStyleSheet(f"color: {COLOR_CYAN}; font-size: 11px; font-weight: bold; letter-spacing: 1px;")
        cf_layout.addWidget(cf_header)

        self.cores_grid = QGridLayout()
        self.cores_grid.setSpacing(8)
        self._init_cores_grid()
        cf_layout.addLayout(self.cores_grid)
        c_layout.addWidget(core_frame)

        # 3. Detailed Memory & Disk Activity Frame
        detail_frame = QFrame()
        detail_frame.setObjectName("panel")
        df_layout = QHBoxLayout(detail_frame)
        df_layout.setContentsMargins(14, 12, 14, 12)
        df_layout.setSpacing(14)

        # Physical RAM Details
        ram_box = QVBoxLayout()
        r_title = QLabel("MEMORY ALLOCATION")
        r_title.setStyleSheet(f"color: {COLOR_GREEN}; font-size: 11px; font-weight: bold;")
        ram_box.addWidget(r_title)

        self.lbl_ram_used = QLabel("Used: Calculating...")
        self.lbl_ram_avail = QLabel("Available: Calculating...")
        self.lbl_swap = QLabel("Swap / Paging: Calculating...")
        for lbl in (self.lbl_ram_used, self.lbl_ram_avail, self.lbl_swap):
            lbl.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 11px;")
            ram_box.addWidget(lbl)
        ram_box.addStretch()
        df_layout.addLayout(ram_box)

        # System Metrics & Tasks
        sys_box = QVBoxLayout()
        s_title = QLabel("SYSTEM KERNEL STATE")
        s_title.setStyleSheet(f"color: {COLOR_CYAN}; font-size: 11px; font-weight: bold;")
        sys_box.addWidget(s_title)

        self.lbl_uptime = QLabel("System Uptime: Calculating...")
        self.lbl_procs = QLabel("Active Processes: Calculating...")
        self.lbl_boot = QLabel("Kernel Boot: Active")
        for lbl in (self.lbl_uptime, self.lbl_procs, self.lbl_boot):
            lbl.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 11px;")
            sys_box.addWidget(lbl)
        sys_box.addStretch()
        df_layout.addLayout(sys_box)

        # Top processes by CPU
        top_box = QVBoxLayout()
        t_title = QLabel("TOP PROCESSES (CPU)")
        t_title.setStyleSheet(f"color: {COLOR_CYAN}; font-size: 11px; font-weight: bold;")
        top_box.addWidget(t_title)
        self.top_rows = []
        for _ in range(8):
            row = QHBoxLayout()
            name = QLabel("")
            name.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 11px;")
            cpu = QLabel("")
            cpu.setStyleSheet(f"color: {COLOR_CYAN}; font-size: 11px; font-weight: bold;")
            mem = QLabel("")
            mem.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px;")
            mem.setFixedWidth(70)
            mem.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(name, 1)
            row.addWidget(cpu)
            row.addWidget(mem)
            top_box.addLayout(row)
            self.top_rows.append((name, cpu, mem))
        top_box.addStretch()
        df_layout.addLayout(top_box, 1)
        self._top_tick = 0

        c_layout.addWidget(detail_frame)
        c_layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def _init_cores_grid(self):
        cpu_metrics = SystemService.get_cpu_metrics()
        per_cpu = cpu_metrics.get("per_cpu", [0.0])
        num_cores = len(per_cpu)
        cols = 4 if num_cores >= 8 else 2

        for i in range(num_cores):
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(2)

            hl = QHBoxLayout()
            lbl = QLabel(f"CORE #{i:02d}")
            lbl.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px; font-weight: bold;")
            val_lbl = QLabel("0.0%")
            val_lbl.setStyleSheet(f"color: {COLOR_CYAN}; font-size: 10px;")
            hl.addWidget(lbl)
            hl.addStretch()
            hl.addWidget(val_lbl)
            bl.addLayout(hl)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(False)
            bar.setFixedHeight(5)
            bl.addWidget(bar)

            row = i // cols
            col = i % cols
            self.cores_grid.addWidget(box, row, col)
            self.per_core_bars.append((bar, val_lbl))

    def update_telemetry(self, cpu_metrics: dict, mem_metrics: dict, disks: list, net_rates: dict, uptime_sec: float):
        # Update charts
        if cpu_metrics:
            cpu_pct = cpu_metrics.get("percent", 0.0)
            self.chart_cpu.add_point(cpu_pct)

            per_cpu = cpu_metrics.get("per_cpu", [])
            for i, (bar, val_lbl) in enumerate(self.per_core_bars):
                if i < len(per_cpu):
                    pct = per_cpu[i]
                    bar.setValue(int(pct))
                    val_lbl.setText(f"{pct:3.1f}%")

        if mem_metrics:
            ram_pct = mem_metrics.get("percent", 0.0)
            self.chart_ram.add_point(ram_pct)
            tot_gb = mem_metrics.get("total", 0) / (1024**3)
            used_gb = mem_metrics.get("used", 0) / (1024**3)
            avail_gb = mem_metrics.get("available", 0) / (1024**3)
            swap_pct = mem_metrics.get("swap_percent", 0.0)

            self.lbl_ram_used.setText(f"RAM Used: {used_gb:.2f} GB ({ram_pct:.1f}%)")
            self.lbl_ram_avail.setText(f"RAM Free: {avail_gb:.2f} GB")
            self.lbl_swap.setText(f"Paging/Swap Used: {swap_pct:.1f}%")

        if net_rates:
            tot_kb = (net_rates.get("down_bps", 0.0) + net_rates.get("up_bps", 0.0)) / 1024.0
            self.chart_net.add_point(tot_kb)

        # Uptime and process counts
        self.lbl_uptime.setText(f"System Uptime: {SystemService.format_uptime(uptime_sec)}")
        self.lbl_procs.setText(f"Active Processes: {SystemService.get_process_count()} PIDs running")
        if self.isVisible():
            self._top_tick += 1
            if self._top_tick % 2 == 1:
                self._refresh_top_processes()

    def _refresh_top_processes(self):
        import psutil
        ncpu = psutil.cpu_count() or 1
        procs = []
        for p in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
            try:
                if p.pid == 0:
                    continue
                cpu = (p.info["cpu_percent"] or 0.0) / ncpu
                mem = p.info["memory_info"].rss if p.info["memory_info"] else 0
                procs.append((cpu, mem, p.info["name"] or "?"))
            except (psutil.Error, AttributeError):
                continue
        procs.sort(reverse=True)
        for (name_l, cpu_l, mem_l), item in zip(self.top_rows, procs + [None] * len(self.top_rows)):
            if item is None:
                name_l.setText(""); cpu_l.setText(""); mem_l.setText("")
                continue
            cpu, mem, name = item
            name_l.setText(name[:28])
            cpu_l.setText(f"{cpu:4.1f}%")
            mem_l.setText(f"{mem / 1048576:,.0f} MB")

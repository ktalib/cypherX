import time
from datetime import datetime
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QWidget, QApplication
)
from app.config import (
    COLOR_BORDER_MUTED, COLOR_CYAN, COLOR_GREEN, COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY, COLOR_PANEL_ALT, FONT_FAMILY_MONO
)
from app.services.system_service import SystemService
from app.services.network_service import NetworkService

class RightInfoPanel(QFrame):
    """Persistent Right Telemetry Panel displaying live hardware and system specs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("right-rail")
        self.setFixedWidth(260)
        self._os_info = SystemService.get_os_info()
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 14, 12, 14)
        main_layout.setSpacing(10)

        # Header
        header = QLabel("SYSTEM SPECIFICATION")
        header.setObjectName("section-header")
        main_layout.addWidget(header)

        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        self.c_layout = QVBoxLayout(content)
        self.c_layout.setContentsMargins(0, 0, 0, 0)
        self.c_layout.setSpacing(12)

        # Section 1: Host & Platform
        self.c_layout.addWidget(self._make_section_title("HOST PLATFORM"))
        self.lbl_os = self._add_spec_row("OS:", self._os_info.get("os", "Windows"))
        self.lbl_host = self._add_spec_row("HOSTNAME:", self._os_info.get("hostname", "N/A"))
        self.lbl_arch = self._add_spec_row("ARCH:", self._os_info.get("arch", "x86_64"))
        self.lbl_screen = self._add_spec_row("SCREEN:", self._get_screen_resolution())
        self.lbl_uptime = self._add_spec_row("UPTIME:", "00h 00m 00s")

        # Section 2: Processor & Memory
        self.c_layout.addWidget(self._make_section_title("COMPUTE ENGINE"))
        self.lbl_cpu_name = self._add_spec_row("CPU MODEL:", self._os_info.get("processor", "N/A")[:18])
        self.lbl_cores = self._add_spec_row("CORES:", "Detecting...")
        self.lbl_ram_total = self._add_spec_row("RAM TOTAL:", "Detecting...")
        self.lbl_ram_free = self._add_spec_row("RAM AVAIL:", "Detecting...")

        # Section 3: Primary Storage
        self.c_layout.addWidget(self._make_section_title("LOCAL STORAGE"))
        self.lbl_disk_c = self._add_spec_row("DRIVE C:", "Detecting...")
        self.lbl_disk_free = self._add_spec_row("C: FREE:", "Detecting...")

        # Section 4: Network Link
        self.c_layout.addWidget(self._make_section_title("COMM LINK"))
        self.lbl_net_ip = self._add_spec_row("LOCAL IP:", "Detecting...")
        self.lbl_net_down = self._add_spec_row("DOWNLOAD:", "0.0 KB/s")
        self.lbl_net_up = self._add_spec_row("UPLOAD:", "0.0 KB/s")

        self.c_layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)
        QTimer.singleShot(500, self._detect_ip)

    def _detect_ip(self):
        import socket
        ip = "Offline"
        try:
            # UDP "connect" only selects the outbound interface — no packets are sent
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
        except OSError:
            try:
                ip = socket.gethostbyname(socket.gethostname())
            except OSError:
                pass
        self.set_local_ip(ip)
        QTimer.singleShot(60_000, self._detect_ip)

    def _make_section_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"""
            color: {COLOR_CYAN};
            font-size: 10px;
            font-weight: bold;
            letter-spacing: 1.5px;
            margin-top: 6px;
        """)
        return lbl

    def _add_spec_row(self, label: str, default_val: str) -> QLabel:
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title = QLabel(label)
        title.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px;")
        layout.addWidget(title)

        layout.addStretch()

        val = QLabel(default_val)
        val.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 10px; font-weight: bold;")
        layout.addWidget(val)

        self.c_layout.addWidget(box)
        return val

    def _get_screen_resolution(self) -> str:
        screen = QApplication.primaryScreen()
        if screen:
            size = screen.size()
            return f"{size.width()}x{size.height()}"
        return "N/A"

    def update_telemetry(self, cpu_metrics: dict, mem_metrics: dict,
                         disks: list, net_rates: dict, uptime_sec: float):
        # Update Uptime
        self.lbl_uptime.setText(SystemService.format_uptime(uptime_sec))

        # Update CPU & Memory
        if cpu_metrics:
            logical = cpu_metrics.get("count_logical", 1)
            physical = cpu_metrics.get("count_physical", 1)
            self.lbl_cores.setText(f"{logical} Thds ({physical} Cores)")

        if mem_metrics:
            total_gb = mem_metrics.get("total", 0) / (1024**3)
            avail_gb = mem_metrics.get("available", 0) / (1024**3)
            self.lbl_ram_total.setText(f"{total_gb:.1f} GB")
            self.lbl_ram_free.setText(f"{avail_gb:.1f} GB")

        # Update Primary Disk (C:)
        if disks:
            for d in disks:
                if d["mountpoint"].upper().startswith("C"):
                    tot_gb = d["total"] / (1024**3)
                    free_gb = d["free"] / (1024**3)
                    self.lbl_disk_c.setText(f"{tot_gb:.0f} GB ({d['fstype']})")
                    self.lbl_disk_free.setText(f"{free_gb:.1f} GB Free")
                    break

        # Update Network Speed
        if net_rates:
            self.lbl_net_down.setText(NetworkService.format_speed(net_rates.get("down_bps", 0.0)))
            self.lbl_net_up.setText(NetworkService.format_speed(net_rates.get("up_bps", 0.0)))

    def set_local_ip(self, ip_str: str):
        self.lbl_net_ip.setText(ip_str)

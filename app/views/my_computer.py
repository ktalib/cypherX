"""
My Computer — full hardware profile: device, OS, CPU, memory modules, graphics,
display, physical disks + volumes, motherboard/BIOS and battery.

Detailed inventory comes from Windows CIM/WMI via one PowerShell call that runs
on a background thread; the result is cached so the page opens instantly.
"""
import json
import os
import platform
import subprocess
import threading
import time

import psutil
from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame, QScrollArea,
    QPushButton, QProgressBar
)

from app.database import Database
from app.icons import get_pixmap, get_icon
from app.services.system_service import SystemService

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PS_SCRIPT = r"""
$ErrorActionPreference='SilentlyContinue'
$o=[ordered]@{}
$o.cs = Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,SystemType
$os = Get-CimInstance Win32_OperatingSystem
$o.os = [ordered]@{Caption=$os.Caption;Version=$os.Version;Build=$os.BuildNumber;Arch=$os.OSArchitecture;Install=$os.InstallDate.ToString('yyyy-MM-dd')}
$o.display = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').DisplayVersion
$o.cpu = @(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,L2CacheSize,L3CacheSize,SocketDesignation)
$o.gpu = @(Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion,CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate)
$o.board = Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer,Product
$b = Get-CimInstance Win32_BIOS
$o.bios = [ordered]@{Manufacturer=$b.Manufacturer;Version=$b.SMBIOSBIOSVersion;Date=$b.ReleaseDate.ToString('yyyy-MM-dd');Serial=$b.SerialNumber}
$o.ram = @(Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,Manufacturer,PartNumber,DeviceLocator)
$o.slots = (Get-CimInstance Win32_PhysicalMemoryArray).MemoryDevices
$o.disk = @(Get-PhysicalDisk | Select-Object FriendlyName,Size,MediaType,BusType,HealthStatus)
$o.bat = Get-CimInstance Win32_Battery | Select-Object Name,EstimatedChargeRemaining
$o.batfull = (Get-CimInstance -Namespace root\wmi -ClassName BatteryFullChargedCapacity).FullChargedCapacity
$o.batdesign = (Get-CimInstance -Namespace root\wmi -ClassName BatteryStaticData).DesignedCapacity
$o | ConvertTo-Json -Depth 4 -Compress
"""


def _gb(b, digits=1):
    return f"{(b or 0) / 1073741824:.{digits}f} GB"


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


class InventoryLoader(QObject):
    loaded = Signal(dict)

    def load(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        data = {}
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", PS_SCRIPT],
                                 capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW).stdout
            data = json.loads(out.strip() or "{}")
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        data["_at"] = time.strftime("%Y-%m-%d %H:%M")
        self.loaded.emit(data)


class SpecCard(QFrame):
    def __init__(self, title, icon):
        super().__init__()
        self.setObjectName("panel")
        self.lo = QVBoxLayout(self)
        self.lo.setContentsMargins(16, 12, 16, 14)
        self.lo.setSpacing(6)
        h = QHBoxLayout()
        h.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(get_pixmap(icon, "#38bdf8", 16))
        ic.setStyleSheet("background:transparent;")
        t = QLabel(title.upper())
        t.setStyleSheet("color:#38bdf8;font-size:11px;font-weight:800;letter-spacing:1.2px;background:transparent;")
        h.addWidget(ic)
        h.addWidget(t)
        h.addStretch()
        self.lo.addLayout(h)
        self.body = QVBoxLayout()
        self.body.setSpacing(5)
        self.lo.addLayout(self.body)
        self.lo.addStretch()

    def clear(self):
        def wipe(layout):
            while layout.count():
                it = layout.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
                elif it.layout():
                    wipe(it.layout())
        wipe(self.body)

    def row(self, label, value):
        r = QHBoxLayout()
        l = QLabel(label)
        l.setStyleSheet("color:#94a3b8;font-size:12px;background:transparent;")
        v = QLabel(str(value))
        v.setStyleSheet("color:#f8fafc;font-size:12px;font-weight:600;background:transparent;")
        v.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        v.setWordWrap(True)
        r.addWidget(l)
        r.addWidget(v, 1)
        self.body.addLayout(r)

    def bar(self, label, pct, right_text, color="#38bdf8"):
        top = QHBoxLayout()
        l = QLabel(label)
        l.setStyleSheet("color:#e2e8f0;font-size:12px;font-weight:600;background:transparent;")
        r = QLabel(right_text)
        r.setStyleSheet("color:#94a3b8;font-size:11px;background:transparent;")
        top.addWidget(l)
        top.addStretch()
        top.addWidget(r)
        self.body.addLayout(top)
        pb = QProgressBar()
        pb.setRange(0, 100)
        pb.setValue(int(pct))
        pb.setTextVisible(False)
        pb.setFixedHeight(8)
        if pct >= 90:
            color = "#f87171"
        pb.setStyleSheet(f"QProgressBar{{background:rgba(255,255,255,0.08);border:none;border-radius:4px;}}"
                         f"QProgressBar::chunk{{background:{color};border-radius:4px;}}")
        self.body.addWidget(pb)

    def note(self, text):
        n = QLabel(text)
        n.setWordWrap(True)
        n.setStyleSheet("color:#64748b;font-size:11px;background:transparent;")
        self.body.addWidget(n)


class MyComputerView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.inv = Database.get_instance().get_setting("hw_inventory", {}) or {}
        self.loader = InventoryLoader(self)
        self.loader.loaded.connect(self._on_inventory)
        self._setup_ui()
        self._render()
        QTimer.singleShot(1500, self.loader.load)
        self._live = QTimer(self)
        self._live.timeout.connect(self._render_live)
        self._live.start(5000)

    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(12)

        # Hero
        hero = QFrame()
        hero.setObjectName("panel")
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(18, 14, 18, 14)
        hl.setSpacing(16)
        ic = QLabel()
        ic.setPixmap(get_pixmap("computer", "#38bdf8", 44))
        ic.setStyleSheet("background:rgba(56,189,248,0.10);border-radius:14px;padding:10px;")
        hl.addWidget(ic)
        tv = QVBoxLayout()
        tv.setSpacing(2)
        self.h_model = QLabel(platform.node())
        self.h_model.setStyleSheet("color:#ffffff;font-size:22px;font-weight:300;background:transparent;")
        self.h_sub = QLabel("")
        self.h_sub.setStyleSheet("color:#cbd5e1;font-size:12px;background:transparent;")
        self.h_meta = QLabel("")
        self.h_meta.setStyleSheet("color:#64748b;font-size:11px;background:transparent;")
        tv.addWidget(self.h_model)
        tv.addWidget(self.h_sub)
        tv.addWidget(self.h_meta)
        hl.addLayout(tv, 1)
        bv = QVBoxLayout()
        bv.setSpacing(6)
        for text, icon, slot in [("Copy Specs", "duplicate_finder", self._copy_specs),
                                 ("Refresh", "refresh", self._refresh),
                                 ("System Information", "computer", lambda: self._launch("msinfo32.exe")),
                                 ("Device Manager", "settings", lambda: self._launch("devmgmt.msc"))]:
            b = QPushButton(" " + text)
            b.setIcon(get_icon(icon, "#e2e8f0", 13))
            b.clicked.connect(slot)
            bv.addWidget(b)
        grid_btns = QGridLayout()
        grid_btns.setSpacing(6)
        for i in range(bv.count()):
            w = bv.itemAt(i).widget()
            grid_btns.addWidget(w, i // 2, i % 2)
        hl.addLayout(grid_btns)
        main.addWidget(hero)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        g = QGridLayout(body)
        g.setContentsMargins(0, 0, 4, 0)
        g.setSpacing(12)
        self.c_cpu = SpecCard("Processor", "process_manager")
        self.c_mem = SpecCard("Memory", "layers")
        self.c_gpu = SpecCard("Graphics & Display", "eye")
        self.c_storage = SpecCard("Storage", "large_files")
        self.c_board = SpecCard("Motherboard & Firmware", "code")
        self.c_power = SpecCard("Battery & Power", "battery")
        for i, c in enumerate((self.c_cpu, self.c_mem, self.c_gpu, self.c_storage, self.c_board, self.c_power)):
            g.addWidget(c, i // 2, i % 2)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        g.setRowStretch(3, 1)
        scroll.setWidget(body)
        main.addWidget(scroll, 1)

    # ------------------------------------------------------------- data --

    def _refresh(self):
        self.h_meta.setText("Refreshing hardware inventory…")
        self.loader.load()

    def _on_inventory(self, data):
        if len(data) > 1:
            self.inv = data
            Database.get_instance().set_setting("hw_inventory", data)
        self._render()

    def _launch(self, target):
        try:
            os.startfile(target)
        except OSError:
            pass

    def showEvent(self, e):
        super().showEvent(e)
        self._render_live()

    def _render(self):
        inv = self.inv
        cs, osi = inv.get("cs") or {}, inv.get("os") or {}
        model = " ".join(x for x in (cs.get("Manufacturer"), cs.get("Model")) if x) or platform.node()
        self.h_model.setText(model)
        caption = osi.get("Caption") or f"Windows {platform.release()}"
        ver = inv.get("display")
        self.h_sub.setText(f"{platform.node()}  ·  {caption}{' ' + ver if ver else ''}  "
                           f"(build {osi.get('Build') or platform.version()})  ·  {osi.get('Arch') or platform.machine()}")
        meta = []
        if osi.get("Install"):
            meta.append(f"Installed {osi['Install']}")
        meta.append(f"Up {SystemService.format_uptime(SystemService.get_uptime_seconds())}")
        meta.append(f"Inventory {inv.get('_at', 'loading…')}")
        self.h_meta.setText("   ·   ".join(meta))

        # CPU
        c = self.c_cpu
        c.clear()
        cpu = (_as_list(inv.get("cpu")) or [{}])[0]
        c.row("Model", cpu.get("Name") or platform.processor())
        c.row("Cores / threads", f"{cpu.get('NumberOfCores') or psutil.cpu_count(False)} cores · "
                                 f"{cpu.get('NumberOfLogicalProcessors') or psutil.cpu_count()} threads")
        freq = psutil.cpu_freq()
        c.row("Base clock", f"{(cpu.get('MaxClockSpeed') or (freq.max if freq else 0)) / 1000:.2f} GHz")
        if cpu.get("L3CacheSize"):
            c.row("Cache", f"L2 {cpu.get('L2CacheSize', 0)} KB · L3 {cpu['L3CacheSize'] / 1024:.0f} MB")
        if cpu.get("SocketDesignation"):
            c.row("Socket", cpu["SocketDesignation"])

        # Memory
        m = self.c_mem
        m.clear()
        vm = psutil.virtual_memory()
        m.bar("In use", vm.percent, f"{_gb(vm.used)} of {_gb(vm.total)}", "#a78bfa")
        mods = _as_list(inv.get("ram"))
        if mods:
            speed = max((x.get("Speed") or 0) for x in mods)
            m.row("Installed", f"{_gb(sum(x.get('Capacity') or 0 for x in mods), 0)}"
                               f"{f' · {speed} MT/s' if speed else ''}")
            m.row("Slots used", f"{len(mods)} of {inv.get('slots') or len(mods)}")
            for x in mods:
                m.row(x.get("DeviceLocator") or "Module",
                      f"{_gb(x.get('Capacity'), 0)} · {(x.get('Manufacturer') or '').strip()} "
                      f"{(x.get('PartNumber') or '').strip()}")
        sw = psutil.swap_memory()
        m.row("Page file", f"{_gb(sw.used)} used of {_gb(sw.total)}")

        # GPU & display
        gp = self.c_gpu
        gp.clear()
        gpus = _as_list(inv.get("gpu"))
        for x in gpus:
            gp.row("Adapter", x.get("Name"))
            if x.get("AdapterRAM"):
                gp.row("Video memory", _gb(x["AdapterRAM"]))
            if x.get("DriverVersion"):
                gp.row("Driver", x["DriverVersion"])
        for s in QGuiApplication.screens():
            geo = s.geometry()
            dpr = s.devicePixelRatio()
            gp.row(s.name() or "Display",
                   f"{int(geo.width() * dpr)}×{int(geo.height() * dpr)} · {s.refreshRate():.0f} Hz"
                   f"{f' · {dpr * 100:.0f}% scale' if dpr != 1 else ''}")
        if not gpus:
            gp.note("Loading graphics details…" if not inv else "No graphics details available.")

        # Storage
        st = self.c_storage
        st.clear()
        for d in _as_list(inv.get("disk")):
            st.row(d.get("FriendlyName") or "Disk",
                   f"{_gb(d.get('Size'), 0)} · {d.get('MediaType') or ''} {d.get('BusType') or ''} · "
                   f"{d.get('HealthStatus') or ''}")
        for part in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            st.bar(f"{part.mountpoint}  {part.fstype}", u.percent,
                   f"{_gb(u.free)} free of {_gb(u.total)}", "#f5be4b")

        # Board & BIOS
        b = self.c_board
        b.clear()
        board, bios = inv.get("board") or {}, inv.get("bios") or {}
        if board:
            b.row("Motherboard", f"{board.get('Manufacturer', '')} {board.get('Product', '')}".strip())
        if bios:
            b.row("BIOS", f"{bios.get('Manufacturer', '')} {bios.get('Version', '')}".strip())
            b.row("BIOS date", bios.get("Date", "—"))
            if bios.get("Serial"):
                b.row("Serial number", bios["Serial"])
        b.row("System type", cs.get("SystemType") or platform.machine())
        b.row("Python runtime", platform.python_version())
        if not board:
            b.note("Loading firmware details…")

        self._render_power()

    def _render_power(self):
        p = self.c_power
        p.clear()
        bat = psutil.sensors_battery()
        if bat is None:
            p.row("Power source", "AC power (no battery)")
            return
        state = "Charging" if bat.power_plugged and bat.percent < 100 else (
            "Plugged in" if bat.power_plugged else "On battery")
        p.bar("Charge", bat.percent, f"{bat.percent:.0f}% · {state}", "#34d399")
        if not bat.power_plugged and bat.secsleft not in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED):
            h, rem = divmod(int(bat.secsleft), 3600)
            p.row("Time remaining", f"{h} h {rem // 60} min")
        full, design = self.inv.get("batfull"), self.inv.get("batdesign")
        if isinstance(full, list):
            full = full[0]
        if isinstance(design, list):
            design = design[0]
        if full and design:
            health = min(100, full * 100 / design)
            p.bar("Battery health", health, f"{full:,} of {design:,} mWh", "#38bdf8")
        elif full:
            p.row("Full charge capacity", f"{full:,} mWh")
        p.note("Tip: run 'powercfg /batteryreport' for a detailed battery history.")

    def _render_live(self):
        if not self.isVisible():
            return
        self._render_power()

    def _copy_specs(self):
        inv = self.inv
        cs = inv.get("cs") or {}
        lines = [f"{cs.get('Manufacturer', '')} {cs.get('Model', '')}".strip() or platform.node(),
                 f"OS: {(inv.get('os') or {}).get('Caption', platform.platform())} {inv.get('display') or ''}"]
        for x in _as_list(inv.get("cpu")):
            lines.append(f"CPU: {x.get('Name')} ({x.get('NumberOfCores')}C/{x.get('NumberOfLogicalProcessors')}T)")
        lines.append(f"RAM: {_gb(psutil.virtual_memory().total)}")
        for x in _as_list(inv.get("gpu")):
            lines.append(f"GPU: {x.get('Name')}")
        for d in _as_list(inv.get("disk")):
            lines.append(f"Disk: {d.get('FriendlyName')} {_gb(d.get('Size'), 0)} {d.get('MediaType') or ''}")
        QGuiApplication.clipboard().setText("\n".join(lines))
        self.h_meta.setText("Specs copied to clipboard ✓")

"""
Network Monitor — live throughput, connection status (Wi-Fi SSID / signal),
public IP & provider, latency test, adapters and per-app active connections.
"""
import json
import socket
import subprocess
import threading
import time

import psutil
from PySide6.QtCore import Qt, QObject, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QPushButton, QTabWidget, QLineEdit, QCheckBox, QAbstractItemView
)

from app.config import COLOR_CYAN, COLOR_GREEN
from app.icons import get_pixmap
from app.widgets.chart_widget import CyberLineChart
from app.widgets.home.common import http_get
from app.services.network_service import NetworkService
from app.services.system_service import SystemService

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def wifi_info():
    """Parse `netsh wlan show interfaces` → dict (empty when not on Wi-Fi)."""
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True,
                             text=True, timeout=4, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    info = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k == "ssid":
            info["ssid"] = v
        elif k == "signal":
            info["signal"] = v
        elif k.startswith("receive rate"):
            info["rx"] = v
        elif k == "state":
            info["state"] = v
        elif k == "radio type":
            info["radio"] = v
    return info if info.get("state", "").lower().startswith("connected") else {}


def tcp_latency(host, port=443, tries=3):
    times = []
    for _ in range(tries):
        t = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=2):
                times.append((time.perf_counter() - t) * 1000)
        except OSError:
            pass
    return (min(times), sum(times) / len(times)) if times else None


class NetWorker(QObject):
    """Runs blocking network probes off the GUI thread."""
    wifi = Signal(dict)
    latency = Signal(dict)
    connections = Signal(list)

    def run(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def probe_wifi(self):
        self.run(lambda: self.wifi.emit(wifi_info()))

    def probe_latency(self):
        def go():
            res = {}
            for name, host in (("Cloudflare", "1.1.1.1"), ("Google", "8.8.8.8"), ("Microsoft", "www.microsoft.com")):
                res[name] = tcp_latency(host)
            self.latency.emit(res)
        self.run(go)

    def probe_connections(self):
        def go():
            names = {}
            rows = []
            try:
                conns = psutil.net_connections(kind="inet")
            except (psutil.Error, OSError):
                conns = []
            for c in conns:
                if not c.raddr:
                    continue
                pid = c.pid or 0
                if pid not in names:
                    try:
                        names[pid] = psutil.Process(pid).name() if pid else "System"
                    except psutil.Error:
                        names[pid] = f"PID {pid}"
                rows.append({
                    "app": names[pid], "pid": pid,
                    "local": f"{c.laddr.ip}:{c.laddr.port}",
                    "remote": f"{c.raddr.ip}:{c.raddr.port}",
                    "state": c.status.replace("_", " ").title() if c.status != "NONE" else "UDP",
                    "proto": "TCP" if c.type == socket.SOCK_STREAM else "UDP",
                })
            rows.sort(key=lambda r: (r["app"].lower(), r["remote"]))
            self.connections.emit(rows)
        self.run(go)


class InfoCard(QFrame):
    def __init__(self, title, icon):
        super().__init__()
        self.setObjectName("panel")
        lo = QVBoxLayout(self)
        lo.setContentsMargins(14, 10, 14, 10)
        lo.setSpacing(2)
        h = QHBoxLayout()
        h.setSpacing(6)
        ic = QLabel()
        ic.setPixmap(get_pixmap(icon, "#94a3b8", 13))
        ic.setStyleSheet("background:transparent;")
        t = QLabel(title.upper())
        t.setStyleSheet("color:#94a3b8;font-size:10px;font-weight:800;letter-spacing:1px;background:transparent;")
        h.addWidget(ic)
        h.addWidget(t)
        h.addStretch()
        self.head = h
        lo.addLayout(h)
        self.value = QLabel("—")
        self.value.setStyleSheet("color:#f8fafc;font-size:17px;font-weight:400;background:transparent;")
        self.value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sub = QLabel("")
        self.sub.setStyleSheet("color:#64748b;font-size:11px;background:transparent;")
        self.sub.setWordWrap(True)
        lo.addWidget(self.value)
        lo.addWidget(self.sub)
        lo.addStretch()


class NetworkMonitorView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = NetWorker(self)
        self.worker.wifi.connect(self._on_wifi)
        self.worker.latency.connect(self._on_latency)
        self.worker.connections.connect(self._on_connections)
        self._conn_rows = []
        self._peak_down = self._peak_up = 0.0
        self._setup_ui()

        self._slow = QTimer(self)
        self._slow.timeout.connect(self._slow_refresh)
        self._slow.start(5000)
        QTimer.singleShot(300, self._slow_refresh)
        QTimer.singleShot(600, self.refresh_public_ip)

    # ------------------------------------------------------------------ UI --

    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(12)

        title_box = QFrame()
        title_box.setObjectName("panel")
        tb = QHBoxLayout(title_box)
        tb.setContentsMargins(14, 10, 14, 10)
        title = QLabel("NETWORK MONITOR // TRAFFIC, CONNECTIONS & LATENCY")
        title.setObjectName("section-header")
        tb.addWidget(title)
        main.addWidget(title_box)

        cards = QGridLayout()
        cards.setSpacing(10)
        self.card_conn = InfoCard("Connection", "wifi")
        self.card_local = InfoCard("Local address", "computer")
        self.card_public = InfoCard("Public IP", "network_monitor")
        self.card_ping = InfoCard("Latency", "zap")
        self.ping_btn = QPushButton("Test")
        self.ping_btn.setFixedHeight(22)
        self.ping_btn.clicked.connect(self._test_latency)
        self.card_ping.head.addWidget(self.ping_btn)
        ip_btn = QPushButton("Refresh")
        ip_btn.setFixedHeight(22)
        ip_btn.clicked.connect(self.refresh_public_ip)
        self.card_public.head.addWidget(ip_btn)
        for i, c in enumerate((self.card_conn, self.card_local, self.card_public, self.card_ping)):
            cards.addWidget(c, 0, i)
            cards.setColumnStretch(i, 1)
        main.addLayout(cards)

        graphs = QHBoxLayout()
        graphs.setSpacing(10)
        self.chart_down = CyberLineChart(title="DOWNLOAD (KB/s)", accent_color=COLOR_CYAN, unit="KB/s", max_points=60)
        self.chart_up = CyberLineChart(title="UPLOAD (KB/s)", accent_color=COLOR_GREEN, unit="KB/s", max_points=60)
        graphs.addWidget(self.chart_down)
        graphs.addWidget(self.chart_up)
        main.addLayout(graphs)

        strip = QFrame()
        strip.setObjectName("panel")
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(14, 8, 14, 8)
        self.lbl_recv = QLabel()
        self.lbl_recv.setStyleSheet(f"color:{COLOR_CYAN};font-size:11px;font-weight:bold;background:transparent;")
        self.lbl_peak = QLabel()
        self.lbl_peak.setStyleSheet("color:#94a3b8;font-size:11px;font-weight:bold;background:transparent;")
        self.lbl_sent = QLabel()
        self.lbl_sent.setStyleSheet(f"color:{COLOR_GREEN};font-size:11px;font-weight:bold;background:transparent;")
        sl.addWidget(self.lbl_recv)
        sl.addStretch()
        sl.addWidget(self.lbl_peak)
        sl.addStretch()
        sl.addWidget(self.lbl_sent)
        main.addWidget(strip)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_connections_tab(), "Active Connections")
        self.tabs.addTab(self._build_adapters_tab(), "Network Adapters")
        self.tabs.currentChanged.connect(lambda _: self._slow_refresh())
        main.addWidget(self.tabs, 1)

    def _make_table(self, headers):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        return t

    def _build_connections_tab(self):
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(0, 8, 0, 0)
        lo.setSpacing(8)
        row = QHBoxLayout()
        self.conn_filter = QLineEdit()
        self.conn_filter.setPlaceholderText("Filter by app, address or port…")
        self.conn_filter.setClearButtonEnabled(True)
        self.conn_filter.textChanged.connect(self._render_connections)
        self.conn_summary = QLabel("")
        self.conn_summary.setStyleSheet("color:#94a3b8;font-size:11px;background:transparent;")
        row.addWidget(self.conn_filter, 1)
        row.addWidget(self.conn_summary)
        lo.addLayout(row)
        self.conn_table = self._make_table(["App", "PID", "Protocol", "Local", "Remote", "State"])
        hh = self.conn_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        lo.addWidget(self.conn_table, 1)
        return w

    def _build_adapters_tab(self):
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(0, 8, 0, 0)
        lo.setSpacing(8)
        self.cb_up = QCheckBox("Only show connected adapters")
        self.cb_up.setChecked(True)
        self.cb_up.toggled.connect(self.refresh_adapters)
        lo.addWidget(self.cb_up)
        self.table = self._make_table(["Adapter", "Status", "Speed", "IPv4 Address", "Subnet Mask", "MAC Address"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        lo.addWidget(self.table, 1)
        self.refresh_adapters()
        return w

    # ------------------------------------------------------------- data --

    def _slow_refresh(self):
        if not self.isVisible():
            return
        self.worker.probe_wifi()
        if self.tabs.currentIndex() == 0:
            self.worker.probe_connections()
        else:
            self.refresh_adapters()
        self._update_local()

    def _update_local(self):
        ip = "Offline"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
        except OSError:
            pass
        self.card_local.value.setText(ip)
        self.card_local.sub.setText(socket.gethostname())

    def refresh_public_ip(self):
        self.card_public.value.setText("Looking up…")

        def done(data, err):
            try:
                j = json.loads(data)
                self.card_public.value.setText(j["query"])
                self.card_public.sub.setText(f"{j.get('isp', '')}\n{j.get('city', '')}, {j.get('country', '')}")
            except (TypeError, ValueError, KeyError):
                self.card_public.value.setText("Unavailable")
                self.card_public.sub.setText(err or "No internet connection")

        http_get("http://ip-api.com/json/?fields=query,isp,city,country", done)

    def _test_latency(self):
        self.ping_btn.setEnabled(False)
        self.card_ping.value.setText("Testing…")
        self.card_ping.sub.setText("")
        self.worker.probe_latency()

    def _on_latency(self, res):
        self.ping_btn.setEnabled(True)
        ok = {k: v for k, v in res.items() if v}
        if not ok:
            self.card_ping.value.setText("No response")
            self.card_ping.value.setStyleSheet("color:#f87171;font-size:17px;background:transparent;")
            return
        best = min(v[0] for v in ok.values())
        color = "#34d399" if best < 60 else "#f5be4b" if best < 150 else "#f87171"
        self.card_ping.value.setText(f"{best:.0f} ms")
        self.card_ping.value.setStyleSheet(f"color:{color};font-size:17px;background:transparent;")
        self.card_ping.sub.setText("  ·  ".join(f"{k} {v[1]:.0f}" if v else f"{k} —" for k, v in res.items()))

    def _on_wifi(self, info):
        if info:
            self.card_conn.value.setText(info.get("ssid", "Wi-Fi"))
            self.card_conn.sub.setText(f"Wi-Fi · signal {info.get('signal', '?')} · {info.get('rx', '?')} Mbps"
                                       + (f"\n{info['radio']}" if info.get("radio") else ""))
        else:
            up = [n for n in NetworkService.get_interfaces()
                  if n["is_up"] and n["ipv4"] not in ("N/A", "127.0.0.1") and not n["ipv4"].startswith("169.254")]
            if up:
                self.card_conn.value.setText(up[0]["name"])
                speed = up[0].get("speed_mbps") or 0
                self.card_conn.sub.setText(f"Wired / other · {speed} Mbps" if speed else "Connected")
            else:
                self.card_conn.value.setText("Disconnected")
                self.card_conn.sub.setText("No active network")

    def _on_connections(self, rows):
        self._conn_rows = rows
        self._render_connections()

    def _render_connections(self):
        q = self.conn_filter.text().strip().lower()
        rows = [r for r in self._conn_rows
                if not q or q in r["app"].lower() or q in r["remote"] or q in r["local"]]
        apps = len({r["app"] for r in rows})
        self.conn_summary.setText(f"{len(rows)} connections · {apps} apps")
        scroll = self.conn_table.verticalScrollBar().value()
        self.conn_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.conn_table.setItem(i, 0, QTableWidgetItem(r["app"]))
            self.conn_table.setItem(i, 1, QTableWidgetItem(str(r["pid"])))
            self.conn_table.setItem(i, 2, QTableWidgetItem(r["proto"]))
            self.conn_table.setItem(i, 3, QTableWidgetItem(r["local"]))
            self.conn_table.setItem(i, 4, QTableWidgetItem(r["remote"]))
            st = QTableWidgetItem(r["state"])
            st.setForeground(QColor("#34d399") if r["state"] == "Established" else QColor("#94a3b8"))
            self.conn_table.setItem(i, 5, st)
        self.conn_table.verticalScrollBar().setValue(scroll)

    def refresh_adapters(self):
        adapters = NetworkService.get_interfaces()
        if self.cb_up.isChecked():
            adapters = [a for a in adapters if a["is_up"]]
        self.table.setRowCount(len(adapters))
        for row, nic in enumerate(adapters):
            self.table.setItem(row, 0, QTableWidgetItem(nic["name"]))
            st = QTableWidgetItem("Connected" if nic["is_up"] else "Disconnected")
            st.setForeground(QColor("#34d399") if nic["is_up"] else QColor("#64748b"))
            self.table.setItem(row, 1, st)
            sp = nic.get("speed_mbps") or 0
            self.table.setItem(row, 2, QTableWidgetItem(f"{sp:,} Mbps" if sp else "—"))
            self.table.setItem(row, 3, QTableWidgetItem(nic["ipv4"]))
            self.table.setItem(row, 4, QTableWidgetItem(nic["netmask"]))
            self.table.setItem(row, 5, QTableWidgetItem(nic["mac"]))

    def update_telemetry(self, net_rates: dict):
        if net_rates:
            down_kb = net_rates.get("down_bps", 0.0) / 1024.0
            up_kb = net_rates.get("up_bps", 0.0) / 1024.0
            self.chart_down.add_point(down_kb)
            self.chart_up.add_point(up_kb)
            self._peak_down = max(self._peak_down, down_kb)
            self._peak_up = max(self._peak_up, up_kb)
            self.lbl_peak.setText(f"PEAK  ↓ {NetworkService.format_speed(self._peak_down * 1024).strip()}"
                                  f"   ↑ {NetworkService.format_speed(self._peak_up * 1024).strip()}")
        if not self.isVisible():
            return                      # chart history above is kept; the totals only matter on screen
        totals = NetworkService.get_totals()
        self.lbl_sent.setText(f"SENT SINCE BOOT: {SystemService.format_bytes(totals['bytes_sent'])}")
        self.lbl_recv.setText(f"RECEIVED SINCE BOOT: {SystemService.format_bytes(totals['bytes_recv'])}")

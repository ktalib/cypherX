"""
Wi-Fi Devices — everything Network watch has seen on the home network.
Double-click a name to rename a device; trust the ones you know.
"""
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox
)

from app.icons import get_icon

GREEN, AMBER, DIM, MUTED, TEXT = "#22c55e", "#f59e0b", "#64748b", "#94a3b8", "#f8fafc"
COLS = ["", "Name", "IP", "MAC address", "Maker", "Last seen", "Trusted"]


def _ago(ts):
    if not ts:
        return "—"
    s = time.time() - ts
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 86400:
        return f"{int(s // 3600)} h ago"
    return time.strftime("%d %b %H:%M", time.localtime(ts))


class LanDevicesView(QWidget):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.svc = manager.get("netwatch")
        self._filling = False
        self._sig = None
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(3000)

    def _build(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(12)
        bar = QFrame()
        bar.setObjectName("panel")
        tb = QHBoxLayout(bar)
        tb.setContentsMargins(14, 8, 10, 8)
        t = QLabel("WI-FI DEVICES // NETWORK WATCH")
        t.setObjectName("section-header")
        tb.addWidget(t)
        tb.addSpacing(12)
        self.summary = QLabel()
        self.summary.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:600;background:transparent;")
        tb.addWidget(self.summary, 1)
        for text, icon, slot in (("Scan now", "refresh", self._scan), ("Trust selected", "shield", self._trust),
                                 ("Forget selected", "trash", self._forget)):
            b = QPushButton(f" {text}")
            b.setIcon(get_icon(icon, "#e2e8f0", 13))
            b.clicked.connect(slot)
            tb.addWidget(b)
        main.addWidget(bar)

        card = QFrame()
        card.setObjectName("panel")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setProperty("compact_columns", True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setMinimumSectionSize(28)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.table.itemChanged.connect(self._renamed)
        cl.addWidget(self.table)
        self.hint = QLabel("Double-click a name to rename a device. New devices that aren't trusted show in amber.")
        self.hint.setStyleSheet(f"color:{DIM};font-size:11px;background:transparent;")
        cl.addWidget(self.hint)
        main.addWidget(card, 1)

    def showEvent(self, e):
        super().showEvent(e)
        self._sig = None
        self.refresh()

    def refresh(self):
        if not self.isVisible() or self.svc is None:
            return
        book = self.svc.book
        devices = dict(book.devices)
        running = self.svc.status == "running"
        info = self.svc.info()
        self.summary.setText((info[0] if info else "") + ("" if running else "  ·  Network watch is stopped — "
                                                                          "start it in Services"))
        rows = sorted(devices.items(), key=lambda kv: (not book.online(kv[0]), kv[1].get("ip", "")))
        sig = tuple((m, d.get("name"), d.get("ip"), d.get("trusted"), d.get("last_seen"), book.online(m))
                    for m, d in rows)
        if sig == self._sig or self.table.state() == QAbstractItemView.EditingState:
            return
        self._sig = sig
        self._filling = True
        self.table.setRowCount(len(rows))
        for r, (mac, d) in enumerate(rows):
            online = book.online(mac)
            dot = QTableWidgetItem("●")
            dot.setForeground(QColor(GREEN if online else DIM))
            dot.setToolTip("Online" if online else "Not seen in the last scan")
            name = QTableWidgetItem(d.get("name") or d.get("hostname") or "")
            name.setData(Qt.UserRole, mac)
            if not d.get("name") and not d.get("hostname"):
                name.setText("(unnamed)")
                name.setForeground(QColor(DIM))
            if not d.get("trusted"):
                name.setForeground(QColor(AMBER))
                name.setToolTip("Not trusted yet — is this one of yours?")
            cells = [dot, name, QTableWidgetItem(d.get("ip", "")), QTableWidgetItem(mac),
                     QTableWidgetItem(d.get("smart") or d.get("vendor", "")), QTableWidgetItem(_ago(d.get("last_seen"))),
                     QTableWidgetItem("Yes" if d.get("trusted") else "No")]
            for c, item in enumerate(cells):
                if c != 1:
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.table.setItem(r, c, item)
        self._filling = False
        if not rows:
            self.hint.setText("No devices yet. Start Network watch in Services, or press Scan now.")

    def _selected_macs(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        return [self.table.item(r, 1).data(Qt.UserRole) for r in rows]

    def _scan(self):
        if self.svc.status != "running":
            self.manager.start("netwatch")
        else:
            self.svc.scan_now()
        self.summary.setText("Scanning the network… (about 10–30 s)")

    def _trust(self):
        for mac in self._selected_macs():
            self.svc.book.trust(mac, True)
        self._sig = None
        self.refresh()

    def _forget(self):
        macs = self._selected_macs()
        if macs and QMessageBox.question(self, "Forget devices", f"Forget {len(macs)} device(s)? They'll show "
                                                                  "as new if they come back.") == QMessageBox.Yes:
            for mac in macs:
                self.svc.book.forget(mac)
            self._sig = None
            self.refresh()

    def _renamed(self, item):
        if self._filling or item.column() != 1:
            return
        mac = item.data(Qt.UserRole)
        if mac:
            self.svc.book.rename(mac, "" if item.text() == "(unnamed)" else item.text())
            self.svc.book.trust(mac, True)        # naming a device means you know it
            self._sig = None

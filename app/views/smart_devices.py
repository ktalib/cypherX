"""
Smart Devices — the smart plugs, sockets, bulbs and switches discovery found on
the Wi-Fi. Name them and link each one to the appliance plugged into it.
"""
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame, QScrollArea, QComboBox,
    QInputDialog, QMessageBox
)

from app.icons import get_pixmap
from app.widgets.home.common import make_menu, hicon
from app.views.smart_dashboard import _card, _action, _lbl, _chip_style
from app.views.smart_dashboard import ACCENT, GOOD, WARN, TEXT, SOFT, MUTED, DIM

KIND_ICON = {"plug": "plug", "bulb": "lightbulb", "light": "lightbulb", "switch": "power", "relay switch": "power",
             "TV / speaker": "tv", "hub": "layers"}

HOW_TO = ("How to add a smart plug or bulb:\n"
          "1. Pair it in its own app first (for the Tuya plugs: the Smart Life or Tuya Smart app).\n"
          "2. Use the same Wi-Fi as this PC — the 2.4 GHz network, not a guest network.\n"
          "3. Press Start discovery. Tuya devices show up within about 10 seconds.\n"
          "Windows Firewall may ask once: allow CYPHER-X on Private networks.")


def _ago(ts):
    s = time.time() - (ts or 0)
    return "just now" if s < 90 else f"{int(s // 60)} min ago" if s < 3600 else \
        f"{int(s // 3600)} h ago" if s < 86400 else time.strftime("%d %b", time.localtime(ts))


class DeviceCard(QFrame):
    def __init__(self, view, dev_id, parent=None):
        super().__init__(parent)
        self.view = view
        self.dev_id = dev_id
        self.setObjectName(f"sd_{abs(hash(dev_id))}")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(14, 12, 14, 12)
        lo.setSpacing(6)
        top = QHBoxLayout()
        self.icon = QLabel()
        self.icon.setFixedSize(34, 34)
        self.icon.setAlignment(Qt.AlignCenter)
        top.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.name = _lbl("", TEXT, 13, 700)
        self.sub = _lbl("", MUTED, 10, 500)
        col.addWidget(self.name)
        col.addWidget(self.sub)
        top.addLayout(col, 1)
        self.state = QLabel()
        top.addWidget(self.state, 0, Qt.AlignTop)
        more = QPushButton()
        more.setFixedSize(28, 26)
        more.setIcon(hicon("more", "#cbd5e1", 14))
        more.setCursor(Qt.PointingHandCursor)
        more.clicked.connect(lambda: view.device_menu(dev_id))
        top.addWidget(more, 0, Qt.AlignTop)
        lo.addLayout(top)
        self.details = _lbl("", SOFT, 11, 500)
        self.details.setWordWrap(True)
        lo.addWidget(self.details)
        row = QHBoxLayout()
        row.addWidget(_lbl("Plugged in:", MUTED, 11, 600))
        self.link = QComboBox()
        self.link.currentIndexChanged.connect(self._linked)
        row.addWidget(self.link, 1)
        lo.addLayout(row)
        self.control = _lbl("", DIM, 10, 500)
        self.control.setWordWrap(True)
        lo.addWidget(self.control)
        self._filling = False

    def sync(self, d, online, appliances):
        kind = d.get("kind", "")
        icon = next((v for k, v in KIND_ICON.items() if k in kind), "plug")
        linked = d.get("linked_item")
        self.icon.setPixmap(get_pixmap(icon, "#04131d" if online else SOFT, 18))
        self.icon.setStyleSheet(f"background:{ACCENT if online else 'rgba(255,255,255,0.08)'};border-radius:17px;")
        self.name.setText(self.view.book.label(self.dev_id))
        self.sub.setText(f"{d.get('brand', '')} · {kind}")
        self.state.setText("Online" if online else "Not seen")
        self.state.setStyleSheet(_chip_style(GOOD if online else DIM))
        bits = [f"IP {d.get('ip') or '—'}"]
        if d.get("model"):
            bits.append(f"model {d['model']}")
        if (d.get("extra") or {}).get("product_key"):
            bits.append(f"product key {d['extra']['product_key']}")
        ver = (d.get("extra") or {}).get("version")
        if ver:
            bits.append(f"protocol v{ver}")
        bits.append(f"seen {_ago(d.get('last_seen'))}")
        self.details.setText("  ·  ".join(bits))
        self.control.setText(d.get("control", ""))
        self._filling = True
        self.link.clear()
        self.link.addItem("— not linked —", None)
        for item_id, label in appliances:
            self.link.addItem(label, item_id)
        idx = self.link.findData(linked) if linked else 0
        self.link.setCurrentIndex(max(0, idx))
        self._filling = False
        n = self.objectName()
        border = "rgba(56,189,248,0.55)" if linked else "rgba(255,255,255,0.10)"
        self.setStyleSheet(f"QFrame#{n}{{background:rgba(255,255,255,0.04);border:1px solid {border};"
                           f"border-radius:16px;}}")

    def _linked(self, _i):
        if not self._filling:
            self.view.link(self.dev_id, self.link.currentData())


class SmartDevicesView(QWidget):
    def __init__(self, manager, smart_home, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.svc = manager.get("discovery")
        self.book = self.svc.book
        self.home = smart_home
        self.cards = {}
        self._sig = None
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2000)

    def _build(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(12)
        bar = QFrame()
        bar.setObjectName("panel")
        tb = QHBoxLayout(bar)
        tb.setContentsMargins(14, 8, 10, 8)
        t = QLabel("SMART DEVICES // ON YOUR WI-FI")
        t.setObjectName("section-header")
        tb.addWidget(t)
        tb.addSpacing(12)
        self.summary = _lbl("", MUTED, 11, 600)
        tb.addWidget(self.summary, 1)
        self.start_btn = _action("Start discovery", "play", self._start, primary=True)
        tb.addWidget(self.start_btn)
        main.addWidget(bar)

        self.empty, lo, _ = _card("Nothing found yet", "plug")
        how = _lbl(HOW_TO, SOFT, 12, 500)
        how.setWordWrap(True)
        lo.addWidget(how)
        self.empty_status = _lbl("", MUTED, 11, 600)
        self.empty_status.setWordWrap(True)
        lo.addWidget(self.empty_status)
        main.addWidget(self.empty)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;}")
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        self.grid = QGridLayout(holder)
        self.grid.setContentsMargins(0, 0, 4, 0)
        self.grid.setSpacing(10)
        scroll.setWidget(holder)
        main.addWidget(scroll, 1)
        self.scroll = scroll
        self.filler = QWidget()                      # takes the spare room while the list is empty
        self.filler.setStyleSheet("background:transparent;")
        main.addWidget(self.filler, 1)

    # --------------------------------------------------------------- refresh --

    def showEvent(self, e):
        super().showEvent(e)
        self._sig = None
        self.refresh()

    def _appliances(self):
        rooms = {r["id"]: r["name"] for r in self.home.model.rooms}
        return [(d["id"], f"{d['name']} ({rooms.get(d['room'], '')})")
                for d in sorted(self.home.model.devices(), key=lambda d: (d["room"], d["name"]))]

    def refresh(self):
        if not self.isVisible():
            return
        running = self.svc.status == "running"
        self.start_btn.setText(" Scan now" if running else " Start discovery")
        devices = dict(self.book.devices)
        online = {k: self.book.online(k) for k in devices}
        linked = sum(1 for d in devices.values() if d.get("linked_item"))
        self.summary.setText(f"{len(devices)} found · {sum(online.values())} online · {linked} linked to appliances"
                             + ("" if running else "  ·  discovery is off"))
        self.empty.setVisible(not devices)
        self.scroll.setVisible(bool(devices))
        self.filler.setVisible(not devices)
        self.empty_status.setText("Discovery is running — waiting for devices…" if running else
                                  "Discovery is off. Press Start discovery.")
        appliances = self._appliances()
        sig = (tuple(sorted((k, d.get("last_seen", 0) // 30, d.get("label"), d.get("linked_item"), online[k])
                            for k, d in devices.items())), tuple(appliances))
        if sig == self._sig:
            return
        self._sig = sig
        order = sorted(devices, key=lambda k: (not online[k], self.book.label(k).lower()))
        for k in list(self.cards):
            if k not in devices:
                self.cards.pop(k).deleteLater()
        while self.grid.count():
            self.grid.takeAt(0)
        cols = 2 if self.width() > 900 else 1
        for i, k in enumerate(order):
            card = self.cards.get(k) or DeviceCard(self, k)
            self.cards[k] = card
            card.sync(devices[k], online[k], appliances)
            self.grid.addWidget(card, i // cols, i % cols)
        self.grid.setRowStretch(len(order) // cols + 1, 1)

    # --------------------------------------------------------------- actions --

    def _start(self):
        if self.svc.status != "running":
            self.manager.start("discovery")
        else:
            try:
                msg = self.svc.actions()[0][1]()
                self.summary.setText(msg.split(".")[0] + "…")
            except Exception as e:
                QMessageBox.information(self, "Smart devices", str(e))
        self.refresh()

    def link(self, dev_id, item_id):
        self.book.link(dev_id, item_id)
        it = self.home.model.item(item_id) if item_id else None
        try:
            from app.database import Database
            Database.get_instance().log_operation(
                "Smart Devices", f"{self.book.label(dev_id)} linked to {it['name']}" if it else
                f"{self.book.label(dev_id)} unlinked", "Success")
        except Exception:
            pass
        self.home.refresh()
        self._sig = None
        self.refresh()

    def device_menu(self, dev_id):
        m = make_menu(self)
        m.addAction(hicon("file_text", "#e2e8f0", 14), "Rename…", lambda: self._rename(dev_id))
        m.addSeparator()
        m.addAction(hicon("trash", "#f87171", 14), "Forget this device", lambda: self._forget(dev_id))
        m.exec(QCursor.pos())

    def _rename(self, dev_id):
        name, ok = QInputDialog.getText(self, "Rename device", "Name:", text=self.book.label(dev_id))
        if ok and name.strip():
            self.book.rename(dev_id, name)
            self._sig = None
            self.refresh()

    def _forget(self, dev_id):
        if QMessageBox.question(self, "Forget device", f"Forget {self.book.label(dev_id)}? It shows up again "
                                                       "if it's still on the Wi-Fi.") == QMessageBox.Yes:
            self.book.forget(dev_id)
            self._sig = None
            self.refresh()

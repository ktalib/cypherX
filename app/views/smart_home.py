"""
Smart Home — a 3D model of the flat (living room, bedroom, kitchen) built from
the room photos, with a power dashboard for the home power system.

  • orbit / pan / zoom the 3D house; click any appliance to switch it
  • live load (W) per room and in total, against the inverter capacity
  • battery runtime at the current load, daily kWh and cost at your tariff
  • add appliances, edit watts / hours-per-day, remove them
  • the layout lives in smart_home.json — new rooms can be added there
  • prepaid meter tracker: tokens + meter readings give the real burn rate,
    units left, days until the meter runs out and the real price per kWh
  • battery readings typed in from the inverter / charge controller display
  • power cuts detected through the laptop charger (grid-only socket)

Switching is recorded in the operation history. Device states are set by hand
for now; real smart plugs / meters can drive the same model later.
"""
import os
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea,
    QComboBox, QSpinBox, QDoubleSpinBox, QInputDialog, QGridLayout, QProgressBar,
    QMessageBox, QButtonGroup, QCheckBox, QDialog, QFormLayout, QDialogButtonBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)

from app.icons import get_icon
from app.database import Database
from app.home3d.model import HomeModel, HOME_FILE
from app.home3d.view3d import House3DView
from app.home3d.energy import EnergyLog, read_grid_from_charger
from app.server.events import bus
from app.widgets.home.common import make_menu, hicon


def _card(title):
    box = QFrame()
    box.setObjectName("panel")
    lo = QVBoxLayout(box)
    lo.setContentsMargins(14, 10, 14, 12)
    lo.setSpacing(6)
    head = QLabel(title)
    head.setObjectName("section-header")
    lo.addWidget(head)
    return box, lo


def _fmt_hours(h):
    if h is None:
        return "—"
    if h >= 48:
        return f"{h / 24:.1f} days"
    m = int(round(h * 60))
    return f"{m // 60}h {m % 60:02d}m"


def _ago(ts):
    mins = int((time.time() - ts) / 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins} min ago"
    if mins < 48 * 60:
        return f"{mins // 60} h ago"
    return f"{mins // 1440} days ago"


def _when(ts):
    return datetime.fromtimestamp(ts).strftime("%a %d %b %H:%M")


_SUB = "color:#94a3b8;font-size:11px;background:transparent;"
_BIG = "color:#ffffff;font-size:26px;font-weight:300;background:transparent;"
_INFO = "color:#e2e8f0;font-size:12px;font-weight:600;background:transparent;"

GRID_POLL_MS = 10_000


def ask_numbers(parent, title, note, fields):
    """Small form dialog. fields: (label, value, lo, hi, decimals, prefix, suffix,
    optional). An optional field left at its minimum (shown as "—") returns None.
    Returns the list of values, or None when cancelled."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    form = QFormLayout(dlg)
    if note:
        n = QLabel(note)
        n.setWordWrap(True)
        n.setStyleSheet(_SUB)
        form.addRow(n)
    boxes = []
    for label, value, lo, hi, dec, prefix, suffix, optional in fields:
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(dec)
        sb.setPrefix(prefix)
        sb.setSuffix(suffix)
        if optional:
            sb.setSpecialValueText("—  (not shown)")
        sb.setValue(value)
        form.addRow(label, sb)
        boxes.append((sb, optional))
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    form.addRow(bb)
    if dlg.exec() != QDialog.Accepted:
        return None
    return [None if opt and sb.value() <= sb.minimum() else sb.value() for sb, opt in boxes]


class EnergyHistoryDialog(QDialog):
    """Every logged token, meter reading, battery reading and power cut, newest
    first, with delete for typos."""

    def __init__(self, energy, currency, parent=None):
        super().__init__(parent)
        self.energy = energy
        self.currency = currency
        self.setWindowTitle("Energy log")
        self.resize(560, 460)
        lo = QVBoxLayout(self)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["When", "Entry", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        lo.addWidget(self.table)
        row = QHBoxLayout()
        delete = QPushButton(" Delete selected")
        delete.setIcon(get_icon("trash", "#f87171", 13))
        delete.clicked.connect(self._delete)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(delete)
        row.addStretch()
        row.addWidget(close)
        lo.addLayout(row)
        self._fill()

    def _rows(self):
        e, cur = self.energy, self.currency
        rows = []
        for t in e.tokens:
            rows.append((t["ts"], "tokens", t, "Token bought",
                         f"{cur}{t['amount']:,.0f}  →  {t['units']:g} kWh"))
        for r in e.readings:
            rows.append((r["ts"], "readings", r, "Meter reading", f"{r['units']:g} kWh left"))
        for b in e.battery:
            parts = []
            if "pct" in b:
                parts.append(f"{b['pct']:g} %")
            if "volts" in b:
                parts.append(f"{b['volts']:g} V")
            rows.append((b["ts"], "battery", b, "Battery reading", "  ·  ".join(parts)))
        for o in e.outages:
            end = o.get("end")
            dur = _fmt_hours(((end or time.time()) - o["start"]) / 3600.0)
            rows.append((o["start"], "outages", o, "Power cut",
                         f"{dur}" + ("" if end else "  (still off)")))
        return sorted(rows, key=lambda r: r[0], reverse=True)

    def _fill(self):
        self.rows = self._rows()
        self.table.setRowCount(len(self.rows))
        for i, (ts, _, _, kind, value) in enumerate(self.rows):
            for c, text in enumerate((_when(ts), kind, value)):
                self.table.setItem(i, c, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()

    def _delete(self):
        picked = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not picked:
            return
        if QMessageBox.question(self, "Delete entries", f"Delete {len(picked)} entr"
                                f"{'y' if len(picked) == 1 else 'ies'}?") != QMessageBox.Yes:
            return
        for i in picked:
            _, kind, entry, _, _ = self.rows[i]
            self.energy.remove(kind, entry)
        self._fill()


class SmartHomeView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = HomeModel()
        self.energy = EnergyLog()
        self.db = Database.get_instance()
        self._setup_ui()
        self.refresh()
        self.grid_timer = QTimer(self)
        self.grid_timer.timeout.connect(self._poll_grid)
        self.grid_timer.start(GRID_POLL_MS)
        QTimer.singleShot(0, self._poll_grid)

    # ------------------------------------------------------------------ UI --

    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(12)

        title_box = QFrame()
        title_box.setObjectName("panel")
        tb = QHBoxLayout(title_box)
        tb.setContentsMargins(14, 8, 10, 8)
        title = QLabel("SMART HOME // 3D POWER MAP")
        title.setObjectName("section-header")
        tb.addWidget(title)
        tb.addSpacing(12)
        self.mode_group = QButtonGroup(self)
        for i, (mode, text) in enumerate((("cutaway", "Cut-away"), ("walls", "Full walls"),
                                          ("plan", "Floor plan"))):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setChecked(mode == "cutaway")
            b.clicked.connect(lambda _=False, m=mode: self.view.set_mode(m))
            self.mode_group.addButton(b, i)
            tb.addWidget(b)
        tb.addSpacing(8)
        self.labels_btn = QPushButton("Labels")
        self.labels_btn.setCheckable(True)
        self.labels_btn.setChecked(True)
        self.flows_btn = QPushButton("Power flow")
        self.flows_btn.setCheckable(True)
        self.flows_btn.setChecked(True)
        tb.addWidget(self.labels_btn)
        tb.addWidget(self.flows_btn)
        tb.addStretch()
        reset = QPushButton(" Reset view")
        reset.setIcon(get_icon("refresh", "#e2e8f0", 13))
        reset.clicked.connect(lambda: self.view.reset_camera())
        tb.addWidget(reset)
        layout_btn = QPushButton(" Layout file")
        layout_btn.setIcon(get_icon("file_text", "#e2e8f0", 13))
        layout_btn.setToolTip("Open smart_home.json to add rooms or move furniture, then Reload")
        layout_btn.clicked.connect(self._layout_menu)
        tb.addWidget(layout_btn)
        main.addWidget(title_box)

        body = QHBoxLayout()
        body.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(6)
        view_frame = QFrame()
        view_frame.setObjectName("panel")
        vf = QVBoxLayout(view_frame)
        vf.setContentsMargins(2, 2, 2, 2)
        self.view = House3DView(self.model)
        self.view.device_clicked.connect(self._toggle)
        vf.addWidget(self.view)
        left.addWidget(view_frame, 1)
        hint = QLabel("Drag: orbit  ·  right-drag: pan  ·  scroll: zoom  ·  click an appliance to switch it")
        hint.setStyleSheet("color:#64748b;font-size:11px;background:transparent;")
        left.addWidget(hint)
        body.addLayout(left, 1)
        self.labels_btn.toggled.connect(lambda on: (setattr(self.view, "show_labels", on), self.view.update()))
        self.flows_btn.toggled.connect(lambda on: (setattr(self.view, "show_flows", on), self.view.update()))

        # ---- side panel
        side = QWidget()
        side.setStyleSheet("background:transparent;")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 4, 0)
        sl.setSpacing(12)

        card, lo = _card("LIVE LOAD")
        self.load_lbl = QLabel()
        self.load_lbl.setStyleSheet("color:#ffffff;font-size:34px;font-weight:300;background:transparent;")
        lo.addWidget(self.load_lbl)
        self.load_bar = QProgressBar()
        self.load_bar.setTextVisible(False)
        self.load_bar.setFixedHeight(10)
        lo.addWidget(self.load_bar)
        self.load_sub = QLabel()
        self.load_sub.setStyleSheet("color:#94a3b8;font-size:11px;background:transparent;")
        self.load_sub.setWordWrap(True)
        lo.addWidget(self.load_sub)
        self.energy_lbl = QLabel()
        self.energy_lbl.setStyleSheet("color:#e2e8f0;font-size:12px;font-weight:600;background:transparent;")
        self.energy_lbl.setWordWrap(True)
        lo.addWidget(self.energy_lbl)
        sl.addWidget(card)

        card, lo = _card("POWER SOURCE")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        pw = self.model.power
        self.source = QComboBox()
        self.source.addItems(["Grid", "Inverter (battery)", "Solar + inverter", "Generator"])
        self.source.setCurrentText(pw.get("source", "Grid"))
        self.inv = QSpinBox()
        self.inv.setRange(100, 50000)
        self.inv.setSingleStep(500)
        self.inv.setSuffix(" W")
        self.inv.setValue(int(pw.get("inverter_w", 3000)))
        self.bat = QSpinBox()
        self.bat.setRange(0, 100000)
        self.bat.setSingleStep(100)
        self.bat.setSuffix(" Wh")
        self.bat.setValue(int(pw.get("battery_wh", 2400)))
        self.pct = QSpinBox()
        self.pct.setRange(0, 100)
        self.pct.setSuffix(" %")
        self.pct.setValue(int(pw.get("battery_pct", 100)))
        self.tariff = QDoubleSpinBox()
        self.tariff.setRange(0, 100000)
        self.tariff.setDecimals(1)
        self.tariff.setPrefix(pw.get("currency", "₦") + " ")
        self.tariff.setSuffix(" / kWh")
        self.tariff.setValue(float(pw.get("tariff", 225)))
        for r, (name, w) in enumerate((("Source", self.source), ("Inverter", self.inv),
                                       ("Battery", self.bat), ("Charge", self.pct),
                                       ("Tariff", self.tariff))):
            l = QLabel(name)
            l.setStyleSheet("color:#94a3b8;font-size:11px;font-weight:600;background:transparent;")
            grid.addWidget(l, r, 0)
            grid.addWidget(w, r, 1)
        lo.addLayout(grid)
        self.runtime_lbl = QLabel()
        self.runtime_lbl.setWordWrap(True)
        self.runtime_lbl.setStyleSheet("color:#7fd4ff;font-size:12px;font-weight:600;background:transparent;")
        lo.addWidget(self.runtime_lbl)
        self.source.currentTextChanged.connect(self._power_changed)
        for w in (self.inv, self.bat, self.pct):
            w.valueChanged.connect(self._power_changed)
        self.tariff.valueChanged.connect(self._power_changed)
        sl.addWidget(card)

        self._build_energy_cards(sl)

        card, lo = _card("ROOMS")
        self.rooms_box = QVBoxLayout()
        self.rooms_box.setSpacing(6)
        lo.addLayout(self.rooms_box)
        sl.addWidget(card)

        card, lo = _card("APPLIANCES")
        self.dev_box = QVBoxLayout()
        self.dev_box.setSpacing(4)
        lo.addLayout(self.dev_box)
        row = QHBoxLayout()
        add = QPushButton(" Add appliance")
        add.setIcon(get_icon("plus", "#e2e8f0", 13))
        add.clicked.connect(self._add_device)
        off = QPushButton(" All off")
        off.setIcon(get_icon("power", "#e2e8f0", 13))
        off.setToolTip("Switch everything off except the fridge")
        off.clicked.connect(self._all_off)
        row.addWidget(add)
        row.addWidget(off)
        lo.addLayout(row)
        sl.addWidget(card)
        sl.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(330)
        scroll.setWidget(side)
        body.addWidget(scroll)
        main.addLayout(body, 1)

    def _build_energy_cards(self, sl):
        card, lo = _card("PREPAID METER")
        self.meter_big = QLabel()
        self.meter_big.setStyleSheet(_BIG)
        lo.addWidget(self.meter_big)
        self.meter_info = QLabel()
        self.meter_info.setWordWrap(True)
        self.meter_info.setStyleSheet(_INFO)
        lo.addWidget(self.meter_info)
        self.meter_sub = QLabel()
        self.meter_sub.setWordWrap(True)
        self.meter_sub.setStyleSheet(_SUB)
        lo.addWidget(self.meter_sub)
        self.use_price_btn = QPushButton()
        self.use_price_btn.setToolTip("Set the tariff above to the average price you paid for tokens")
        self.use_price_btn.clicked.connect(self._use_paid_price)
        lo.addWidget(self.use_price_btn)
        row = QHBoxLayout()
        token = QPushButton(" Bought token")
        token.setIcon(get_icon("plus", "#e2e8f0", 13))
        token.clicked.connect(self._log_token)
        reading = QPushButton(" Meter reading")
        reading.setIcon(get_icon("zap", "#e2e8f0", 13))
        reading.setToolTip("Type in the units left shown on the meter's display")
        reading.clicked.connect(self._log_reading)
        row.addWidget(token)
        row.addWidget(reading)
        lo.addLayout(row)
        sl.addWidget(card)

        card, lo = _card("BATTERY READINGS")
        self.bat_big = QLabel()
        self.bat_big.setStyleSheet(_BIG)
        lo.addWidget(self.bat_big)
        self.bat_sub = QLabel()
        self.bat_sub.setWordWrap(True)
        self.bat_sub.setStyleSheet(_SUB)
        lo.addWidget(self.bat_sub)
        log_bat = QPushButton(" Log reading")
        log_bat.setIcon(get_icon("battery", "#e2e8f0", 13))
        log_bat.setToolTip("Type in what the inverter or charge controller display shows")
        log_bat.clicked.connect(self._log_battery)
        lo.addWidget(log_bat)
        sl.addWidget(card)

        card, lo = _card("GRID SUPPLY")
        self.grid_big = QLabel()
        self.grid_big.setStyleSheet(_BIG)
        lo.addWidget(self.grid_big)
        self.grid_info = QLabel()
        self.grid_info.setWordWrap(True)
        self.grid_info.setStyleSheet(_INFO)
        lo.addWidget(self.grid_info)
        self.grid_detect = QCheckBox("Detect power cuts with this laptop's charger")
        self.grid_detect.setToolTip("Plug the laptop charger into a socket that is NOT on the inverter. "
                                    "When the charger loses power, CypherX logs a power cut.")
        self.grid_detect.setChecked(self.energy.grid_detect)
        self.grid_detect.toggled.connect(self._grid_detect_toggled)
        lo.addWidget(self.grid_detect)
        self.grid_sub = QLabel()
        self.grid_sub.setWordWrap(True)
        self.grid_sub.setStyleSheet(_SUB)
        lo.addWidget(self.grid_sub)
        hist = QPushButton(" Energy log")
        hist.setIcon(get_icon("history", "#e2e8f0", 13))
        hist.setToolTip("All tokens, meter readings, battery readings and power cuts")
        hist.clicked.connect(self._show_history)
        lo.addWidget(hist)
        sl.addWidget(card)

    # ------------------------------------------------------------- refresh --

    def refresh(self):
        m = self.model
        pw = m.power
        load = m.load_w()
        cap = max(1, pw.get("inverter_w", 3000))
        frac = load / cap
        self.load_lbl.setText(f"{load:,.0f} W")
        self.load_bar.setValue(int(min(100, frac * 100)))
        color = "#ff5d6c" if frac > 0.9 else "#ffb547" if frac > 0.7 else "#38bdf8"
        self.load_bar.setStyleSheet(f"QProgressBar::chunk{{background:{color};border-radius:4px;}}")
        on = [d for d in m.devices() if d["device"]["on"]]
        self.load_sub.setText(f"{len(on)} of {len(m.devices())} appliances running  ·  "
                              f"{frac * 100:.0f}% of the {cap:,} W inverter")
        kwh = m.daily_kwh()
        cur = pw.get("currency", "₦")
        cost = kwh * pw.get("tariff", 0)
        self.energy_lbl.setText(f"Typical day: {kwh:.2f} kWh  ·  {cur}{cost:,.0f} / day  ·  "
                                f"{cur}{cost * 30:,.0f} / month")
        rt = m.runtime_hours()
        if pw.get("source", "Grid") == "Grid":
            self.runtime_lbl.setText(f"On grid power. If it goes off, the battery would run "
                                     f"this load for {_fmt_hours(rt)}." if rt else
                                     "On grid power. Nothing is running.")
        else:
            self.runtime_lbl.setText(f"Battery runs the current load for {_fmt_hours(rt)}"
                                     if rt else "Nothing is running — no drain on the battery.")

        self._clear(self.rooms_box)
        top = max([m.load_w(r["id"]) for r in m.rooms] + [1])
        for r in m.rooms:
            rl = m.load_w(r["id"])
            btn = QPushButton(f"{r['name']}")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip("Fly the camera to this room")
            btn.setStyleSheet("QPushButton{text-align:left;padding:4px 10px;}")
            btn.clicked.connect(lambda _=False, rid=r["id"]: self.view.focus_room(rid))
            val = QLabel(f"{rl:.0f} W")
            val.setStyleSheet("color:#e2e8f0;font-size:12px;font-weight:700;background:transparent;")
            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            bar.setValue(int(rl / top * 100))
            row = QHBoxLayout()
            row.addWidget(btn, 1)
            row.addWidget(val)
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addLayout(row)
            col.addWidget(bar)
            self.rooms_box.addLayout(col)

        self._clear(self.dev_box)
        names = {r["id"]: r["name"] for r in m.rooms}
        for d in sorted(m.devices(), key=lambda d: (d["room"], d["name"])):
            dev = d["device"]
            row = QHBoxLayout()
            sw = QPushButton("ON" if dev["on"] else "OFF")
            sw.setFixedSize(46, 24)
            sw.setCursor(Qt.PointingHandCursor)
            sw.setStyleSheet(
                "QPushButton{background:#10b981;color:#04140d;border:none;border-radius:12px;"
                "font-size:10px;font-weight:800;padding:0;}" if dev["on"] else
                "QPushButton{background:rgba(255,255,255,0.08);color:#94a3b8;border:1px solid "
                "rgba(255,255,255,0.14);border-radius:12px;font-size:10px;font-weight:800;padding:0;}")
            sw.clicked.connect(lambda _=False, i=d["id"]: self._toggle(i))
            name = QLabel(f"{d['name']}<br><span style='color:#64748b;font-size:10px'>"
                          f"{names.get(d['room'], '')} · {dev['hours']:g} h/day</span>")
            name.setStyleSheet("color:#e2e8f0;font-size:12px;font-weight:600;background:transparent;")
            watts = QPushButton(f"{dev['watts']:g} W")
            watts.setCursor(Qt.PointingHandCursor)
            watts.setToolTip("Edit, or remove this appliance")
            watts.setStyleSheet("QPushButton{background:transparent;border:none;color:#7fd4ff;"
                                "font-size:12px;font-weight:700;padding:0 4px;}"
                                "QPushButton:hover{text-decoration:underline;}")
            watts.clicked.connect(lambda _=False, i=d["id"]: self._device_menu(i))
            row.addWidget(sw)
            row.addWidget(name, 1)
            row.addWidget(watts)
            self.dev_box.addLayout(row)
        self.refresh_energy()
        self.view.invalidate()

    def refresh_energy(self):
        e = self.energy
        cur = self.model.power.get("currency", "₦")

        # ---- prepaid meter
        left, rate, days = e.units_left(), e.burn_rate(), e.days_left()
        price = e.price_per_kwh()
        last = e.last_reading()
        if left is None:
            self.meter_big.setText("— kWh")
            self.meter_info.setText("Type in the units left on the meter to start tracking.")
        else:
            self.meter_big.setText(f"{left:,.1f} kWh left")
            if rate:
                cost = f"  ·  {cur}{rate * price:,.0f} / day" if price else ""
                warn = "  — buy soon" if days is not None and days < 2 else ""
                self.meter_info.setText(f"≈ {_fmt_hours(days * 24)} left at "
                                        f"{rate:.1f} kWh / day{cost}{warn}")
                self.meter_info.setStyleSheet(_INFO.replace("#e2e8f0", "#ffb547") if warn else _INFO)
            else:
                self.meter_info.setText("Log another reading later (6 h+) to get your daily usage.")
                self.meter_info.setStyleSheet(_INFO)
        bits = []
        if last:
            bits.append(f"Last reading {_ago(last['ts'])} ({last['units']:g} kWh)")
        if price:
            bits.append(f"you pay {cur}{price:,.1f} / kWh on average")
        self.meter_sub.setText("  ·  ".join(bits))
        tariff = self.model.power.get("tariff", 0)
        show = bool(price) and abs(price - tariff) >= 0.5
        self.use_price_btn.setVisible(show)
        if show:
            self.use_price_btn.setText(f"Use {cur}{price:,.1f} / kWh as tariff")

        # ---- battery
        b = e.last_battery()
        if b is None:
            self.bat_big.setText("—")
            self.bat_sub.setText("Log what the inverter / charge controller shows; the charge % "
                                 "also updates the runtime estimate.")
        else:
            parts = []
            if "pct" in b:
                parts.append(f"{b['pct']:g} %")
            if "volts" in b:
                parts.append(f"{b['volts']:g} V")
            self.bat_big.setText("  ·  ".join(parts))
            self.bat_sub.setText(f"Read {_ago(b['ts'])}  ·  {_when(b['ts'])}")

        # ---- grid
        now = time.time()
        out = e.open_outage()
        if out:
            self.grid_big.setText("Grid OFF")
            self.grid_big.setStyleSheet(_BIG.replace("#ffffff", "#ff5d6c"))
            self.grid_info.setText(f"Off for {_fmt_hours((now - out['start']) / 3600)}  "
                                   f"(since {_when(out['start'])})")
        elif e.grid_detect:
            self.grid_big.setText("Grid ON")
            self.grid_big.setStyleSheet(_BIG.replace("#ffffff", "#10b981"))
            self.grid_info.setText("Watching the laptop charger.")
        else:
            self.grid_big.setText("Not watching")
            self.grid_big.setStyleSheet(_BIG)
            self.grid_info.setText("Tick the box below to log power cuts automatically.")
        if e.grid_detect and read_grid_from_charger() is None:
            self.grid_info.setText("This PC has no battery sensor, so it can't see the charger. "
                                   "Power cuts can't be detected here.")
        stats = [f"No grid: {_fmt_hours(e.outage_hours(now - 86400, now))} in 24 h, "
                 f"{_fmt_hours(e.outage_hours(now - 7 * 86400, now))} in 7 days"]
        done = [o for o in e.outages if o.get("end")]
        if done:
            o = done[-1]
            stats.append(f"Last cut {_when(o['start'])}, {_fmt_hours((o['end'] - o['start']) / 3600)}")
        self.grid_sub.setText("  ·  ".join(stats) if e.outages else "No power cuts logged yet.")

    @staticmethod
    def _clear(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                SmartHomeView._clear(item.layout())

    # ------------------------------------------------------------- actions --

    def _toggle(self, item_id):
        self.model.toggle(item_id)
        it = self.model.item(item_id)
        if it:
            state = "ON" if it["device"]["on"] else "OFF"
            try:
                self.db.log_operation("Smart Home", f"{it['name']} switched {state}", "Success")
            except Exception:
                pass
        self.refresh()

    def _all_off(self):
        self.model.all_off()
        try:
            self.db.log_operation("Smart Home", "All appliances off (fridge kept on)", "Success")
        except Exception:
            pass
        self.refresh()

    def _power_changed(self, *_):
        pw = self.model.power
        pw["source"] = self.source.currentText()
        pw["inverter_w"] = self.inv.value()
        pw["battery_wh"] = self.bat.value()
        pw["battery_pct"] = self.pct.value()
        pw["tariff"] = self.tariff.value()
        self.model.save()
        self.refresh()

    # ------------------------------------------------------- energy log --

    def _log(self, action):
        try:
            self.db.log_operation("Smart Home", action, "Success")
        except Exception:
            pass

    def _notify(self, title, message):
        win = self.window()
        if hasattr(win, "notify"):
            win.notify(title, message)

    def _log_token(self):
        cur = self.model.power.get("currency", "₦")
        price = self.energy.price_per_kwh() or self.model.power.get("tariff", 225) or 1
        vals = ask_numbers(self, "Bought token",
                           "Log the token when you load it into the meter. The units are on the "
                           "receipt / SMS.",
                           [("Amount paid", 5000, 0, 10_000_000, 0, cur + " ", "", False),
                            ("Units (kWh)", round(5000 / price, 1), 0.1, 100_000, 1, "", " kWh", False)])
        if not vals:
            return
        amount, units = vals
        self.energy.add_token(amount, units)
        self._log(f"Prepaid token: {cur}{amount:,.0f} for {units:g} kWh")
        self.refresh_energy()

    def _log_reading(self):
        left = self.energy.units_left()
        vals = ask_numbers(self, "Meter reading",
                           "Units left, as shown on the meter's display.",
                           [("Units left", round(left, 1) if left is not None else 50,
                             0, 100_000, 1, "", " kWh", False)])
        if not vals:
            return
        self.energy.add_reading(vals[0])
        self._log(f"Meter reading: {vals[0]:g} kWh left")
        self.refresh_energy()

    def _log_battery(self):
        b = self.energy.last_battery() or {}
        vals = ask_numbers(self, "Battery reading",
                           "Fill in whatever the display shows; leave the other at —.",
                           [("Charge", b.get("pct", self.model.power.get("battery_pct", 100)),
                             0, 100, 0, "", " %", True),
                            ("Battery voltage", b.get("volts", 0), 0, 100, 1, "", " V", True)])
        if not vals or vals == [None, None]:
            return
        pct, volts = vals
        self.energy.add_battery(pct=pct, volts=volts)
        if pct is not None:
            self.pct.setValue(int(round(pct)))     # saves and refreshes via _power_changed
        self._log("Battery reading: " + "  ".join(
            x for x in (f"{pct:g} %" if pct is not None else "",
                        f"{volts:g} V" if volts is not None else "") if x))
        self.refresh_energy()

    def _use_paid_price(self):
        price = self.energy.price_per_kwh()
        if price:
            self.tariff.setValue(round(price, 1))

    def _show_history(self):
        EnergyHistoryDialog(self.energy, self.model.power.get("currency", "₦"), self).exec()
        self.refresh_energy()

    def _grid_detect_toggled(self, on):
        self.energy.grid_detect = on
        if not on and self.energy.open_outage():
            self.energy.grid_changed(True)       # stop counting an outage nobody watches
        self._poll_grid()
        self.refresh_energy()

    def _poll_grid(self):
        if not self.energy.grid_detect:
            return
        grid = read_grid_from_charger()
        if grid is None:
            return
        change = self.energy.grid_changed(grid)
        if change is None:
            if self.energy.open_outage():
                self.refresh_energy()            # keep the "off for …" timer moving
            return
        pw = self.model.power
        if change == "off":
            self._log("Power cut: grid went off (laptop charger lost power)")
            self._notify("Power cut", "Grid is off — running on the inverter.")
            rt = self.model.runtime_hours()
            bus.publish("power", "Power cut", "Grid is off — running on the inverter."
                        + (f" Battery lasts about {_fmt_hours(rt)} at the current load." if rt else ""))
            if pw.get("source") == "Grid":
                self.source.setCurrentText("Inverter (battery)")
        else:
            o = self.energy.outages[-1]
            dur = _fmt_hours((o["end"] - o["start"]) / 3600)
            self._log(f"Grid restored after {dur}")
            self._notify("Grid restored", f"Power is back after {dur}.")
            bus.publish("power", "Grid restored", f"Power is back after {dur}.")
            if pw.get("source") == "Inverter (battery)":
                self.source.setCurrentText("Grid")
        self.refresh()

    def _device_menu(self, item_id):
        it = self.model.item(item_id)
        if not it:
            return
        m = make_menu(self)
        m.addAction(hicon("zap", "#e2e8f0", 14), "Set watts…", lambda: self._edit(item_id, "watts"))
        m.addAction(hicon("timer", "#e2e8f0", 14), "Set hours per day…", lambda: self._edit(item_id, "hours"))
        m.addAction(hicon("edit" if False else "file_text", "#e2e8f0", 14), "Rename…",
                    lambda: self._rename(item_id))
        m.addSeparator()
        m.addAction(hicon("trash", "#f87171", 14), "Remove appliance", lambda: self._remove(item_id))
        m.exec(QCursor.pos())

    def _edit(self, item_id, field):
        it = self.model.item(item_id)
        cur = it["device"][field]
        if field == "watts":
            val, ok = QInputDialog.getDouble(self, "Power draw", f"Watts for {it['name']}:", cur, 0, 20000, 0)
        else:
            val, ok = QInputDialog.getDouble(self, "Daily use", f"Hours per day for {it['name']}:",
                                             cur, 0, 24, 1)
        if ok:
            self.model.update_device(item_id, **{field: val})
            self.refresh()

    def _rename(self, item_id):
        it = self.model.item(item_id)
        name, ok = QInputDialog.getText(self, "Rename appliance", "Name:", text=it["name"])
        if ok and name.strip():
            it["name"] = name.strip()
            self.model.save()
            self.refresh()

    def _remove(self, item_id):
        it = self.model.item(item_id)
        if QMessageBox.question(self, "Remove appliance", f"Remove {it['name']} from the home model?") \
                == QMessageBox.Yes:
            self.model.remove_item(item_id)
            self.refresh()

    def _add_device(self):
        name, ok = QInputDialog.getText(self, "Add appliance", "Appliance name (e.g. Air conditioner):")
        if not ok or not name.strip():
            return
        rooms = [r["name"] for r in self.model.rooms]
        room, ok = QInputDialog.getItem(self, "Add appliance", "Room:", rooms, 0, False)
        if not ok:
            return
        watts, ok = QInputDialog.getDouble(self, "Add appliance", "Power draw (watts):", 100, 0, 20000, 0)
        if not ok:
            return
        hours, ok = QInputDialog.getDouble(self, "Add appliance", "Hours used per day:", 4, 0, 24, 1)
        if not ok:
            return
        room_id = next(r["id"] for r in self.model.rooms if r["name"] == room)
        self.model.add_device(name.strip(), room_id, watts, hours)
        self.refresh()

    def _layout_menu(self):
        m = make_menu(self)
        m.addAction(hicon("file_text", "#e2e8f0", 14), "Open layout file (add rooms / move items)",
                    lambda: os.startfile(str(HOME_FILE)))
        m.addAction(hicon("refresh", "#e2e8f0", 14), "Reload layout file", self._reload)
        m.addSeparator()
        m.addAction(hicon("rotate_ccw", "#f87171", 14), "Reset to the original 3 rooms…", self._reset)
        m.exec(QCursor.pos())

    def _reload(self):
        self.model = HomeModel()
        self.view.model = self.model
        self.view.reset_camera()
        self.refresh()

    def _reset(self):
        if QMessageBox.question(self, "Reset home model",
                                "Replace the layout with the original living room, bedroom and kitchen? "
                                "Added appliances will be removed.") == QMessageBox.Yes:
            self.model.reset()
            self._reload()

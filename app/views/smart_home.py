"""
Smart Home — a 3D model of the flat (living room, bedroom, kitchen) built from
the room photos, with a power dashboard for the home power system.

  • orbit / pan / zoom the 3D house; click any appliance to switch it
  • live load (W) per room and in total, against the inverter capacity
  • battery runtime at the current load, daily kWh and cost at your tariff
  • add appliances, edit watts / hours-per-day, remove them
  • the layout lives in smart_home.json — new rooms can be added there

Switching is recorded in the operation history. Device states are set by hand
for now; real smart plugs / meters can drive the same model later.
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea,
    QComboBox, QSpinBox, QDoubleSpinBox, QInputDialog, QGridLayout, QProgressBar,
    QMessageBox, QButtonGroup
)

from app.icons import get_icon
from app.database import Database
from app.home3d.model import HomeModel, HOME_FILE
from app.home3d.view3d import House3DView
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


class SmartHomeView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = HomeModel()
        self.db = Database.get_instance()
        self._setup_ui()
        self.refresh()

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
        self.view.invalidate()

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

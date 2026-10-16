"""
Clock & Calendar — big clock, world clocks, calendar, stopwatch with laps,
countdown timer with presets and alarms (with snooze).
"""
import time
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QTimer, QTime, QSize
from PySide6.QtGui import QTextCharFormat, QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QCalendarWidget, QSpinBox, QListWidget, QListWidgetItem, QTimeEdit, QLineEdit,
    QInputDialog, QMessageBox, QApplication, QToolButton, QSizePolicy
)

from app.icons import get_icon
from app.widgets.home.common import load_setting, save_setting, hicon
from app.widgets.home.cards import RingProgress, HAS_TZ

if HAS_TZ:
    from zoneinfo import ZoneInfo, available_timezones

ACCENT = "#38bdf8"
H_STYLE = "color:#94a3b8;font-size:10px;font-weight:800;letter-spacing:1.2px;background:transparent;"


def _panel():
    f = QFrame()
    f.setObjectName("panel")
    return f


def _header(text, icon):
    row = QHBoxLayout()
    row.setSpacing(6)
    ic = QLabel()
    ic.setPixmap(hicon(icon, "#94a3b8", 13).pixmap(13, 13))
    ic.setStyleSheet("background:transparent;")
    t = QLabel(text.upper())
    t.setStyleSheet(H_STYLE)
    row.addWidget(ic)
    row.addWidget(t)
    row.addStretch()
    return row


def _lbl(text, size, color="#f8fafc", weight=400, mono=False):
    l = QLabel(text)
    fam = "font-family:'Cascadia Mono','Consolas',monospace;" if mono else ""
    l.setStyleSheet(f"color:{color};font-size:{size}px;font-weight:{weight};{fam}background:transparent;")
    return l


class ClockCalendarView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_24h = bool(load_setting("clock_24h", True))

        self.sw_running = False
        self.sw_start = 0.0
        self.sw_elapsed = 0.0
        self.sw_last_lap = 0.0

        self.cd_total = 300
        self.cd_left = 300.0
        self.cd_end = 0.0
        self.cd_running = False

        self.alarms = load_setting("alarms", [])
        self._fired_minute = None
        self.zones = load_setting("page_world_zones",
                                  ["Europe/London", "America/New_York", "Asia/Dubai", "Asia/Tokyo"])

        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(100)
        self._tick()

    # ------------------------------------------------------------------ UI --

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # Header
        head = _panel()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(14, 8, 10, 8)
        t = QLabel("CLOCK & CALENDAR // TIME, TIMERS & ALARMS")
        t.setObjectName("section-header")
        hl.addWidget(t)
        hl.addStretch()
        self.mode_btn = QPushButton()
        self.mode_btn.clicked.connect(self._toggle_mode)
        hl.addWidget(self.mode_btn)
        root.addWidget(head)

        # Row 1: big clock | world clocks
        row1 = QHBoxLayout()
        row1.setSpacing(12)

        clock = _panel()
        cl = QVBoxLayout(clock)
        cl.setContentsMargins(22, 14, 22, 14)
        cl.setSpacing(0)
        trow = QHBoxLayout()
        trow.setSpacing(6)
        trow.addStretch()
        self.lbl_time = _lbl("00:00", 76, "#ffffff", 200)
        self.lbl_secs = _lbl("00", 26, ACCENT, 300)
        self.lbl_ampm = _lbl("", 16, "#94a3b8", 600)
        trow.addWidget(self.lbl_time, 0, Qt.AlignBottom)
        sv = QVBoxLayout()
        sv.setSpacing(0)
        sv.addStretch()
        sv.addWidget(self.lbl_ampm)
        sv.addWidget(self.lbl_secs)
        sv.addSpacing(14)
        trow.addLayout(sv)
        trow.addStretch()
        cl.addLayout(trow)
        self.lbl_date = _lbl("", 15, "#e2e8f0", 600)
        self.lbl_date.setAlignment(Qt.AlignCenter)
        self.lbl_info = _lbl("", 11, "#64748b", 600)
        self.lbl_info.setAlignment(Qt.AlignCenter)
        cl.addWidget(self.lbl_date)
        cl.addSpacing(4)
        cl.addWidget(self.lbl_info)
        row1.addWidget(clock, 3)

        world = _panel()
        wl = QVBoxLayout(world)
        wl.setContentsMargins(14, 12, 12, 12)
        wl.setSpacing(6)
        wh = _header("World clocks", "network_monitor")
        add_city = QToolButton()
        add_city.setIcon(get_icon("plus", "#e2e8f0", 14))
        add_city.setToolTip("Add a city")
        add_city.setCursor(Qt.PointingHandCursor)
        add_city.setStyleSheet("QToolButton{background:rgba(255,255,255,0.08);border:none;border-radius:8px;padding:3px;}"
                               "QToolButton:hover{background:rgba(255,255,255,0.18);}")
        add_city.clicked.connect(self._add_zone)
        wh.addWidget(add_city)
        wl.addLayout(wh)
        self.world_grid = QGridLayout()
        self.world_grid.setHorizontalSpacing(10)
        self.world_grid.setVerticalSpacing(4)
        wl.addLayout(self.world_grid)
        wl.addStretch()
        row1.addWidget(world, 2)
        root.addLayout(row1)

        # Row 2: calendar | stopwatch | (countdown + alarms)
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        row2.addWidget(self._build_calendar(), 5)
        row2.addWidget(self._build_stopwatch(), 4)
        col = QVBoxLayout()
        col.setSpacing(12)
        col.addWidget(self._build_countdown())
        col.addWidget(self._build_alarms(), 1)
        row2.addLayout(col, 5)
        root.addLayout(row2, 1)

        self._render_world()
        self._render_alarms()
        self._sync_mode_btn()

    def _build_calendar(self):
        card = _panel()
        lo = QVBoxLayout(card)
        lo.setContentsMargins(12, 12, 12, 12)
        lo.setSpacing(6)
        lo.addLayout(_header("Calendar", "calendar"))
        cal = QCalendarWidget()
        cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        cal.setHorizontalHeaderFormat(QCalendarWidget.SingleLetterDayNames)
        cal.setGridVisible(False)
        cal.setFirstDayOfWeek(Qt.Monday)
        cal.setStyleSheet("""
            QCalendarWidget QWidget#qt_calendar_navigationbar { background: transparent; }
            QCalendarWidget QToolButton { color: #f8fafc; background: transparent; border: none;
                font-size: 13px; font-weight: 700; padding: 4px 8px; border-radius: 8px; }
            QCalendarWidget QToolButton:hover { background: rgba(255,255,255,0.10); }
            QCalendarWidget QToolButton::menu-indicator { image: none; width: 0px; }
            QCalendarWidget QMenu { background: #111a22; color: #f1f5f9; }
            QCalendarWidget QSpinBox { min-height: 20px; font-size: 13px; font-weight: 700; }
            QCalendarWidget QAbstractItemView { background: transparent; color: #e2e8f0; font-size: 12px;
                selection-background-color: #0284c7; selection-color: #ffffff; outline: none; border: none; }
            QCalendarWidget QAbstractItemView:disabled { color: #475569; }
        """)
        for name, icon in (("qt_calendar_prevmonth", "chevron_left"), ("qt_calendar_nextmonth", "chevron_right")):
            btn = cal.findChild(QToolButton, name)
            if btn:
                btn.setIcon(get_icon(icon, "#e2e8f0", 16))
                btn.setIconSize(QSize(16, 16))
        weekend = QTextCharFormat()
        weekend.setForeground(QColor("#f87171"))
        cal.setWeekdayTextFormat(Qt.Saturday, weekend)
        cal.setWeekdayTextFormat(Qt.Sunday, weekend)
        hdr = QTextCharFormat()
        hdr.setForeground(QColor("#64748b"))
        hdr.setFontWeight(QFont.Bold)
        cal.setHeaderTextFormat(hdr)
        today = QTextCharFormat()
        today.setBackground(QColor("#ef4444"))
        today.setForeground(QColor("#ffffff"))
        today.setFontWeight(QFont.Bold)
        cal.setDateTextFormat(cal.selectedDate(), today)
        self.calendar = cal
        lo.addWidget(cal, 1)
        go_today = QPushButton("Today")
        go_today.clicked.connect(lambda: (cal.setSelectedDate(datetime.now().date()),
                                          cal.showToday()))
        lo.addWidget(go_today, 0, Qt.AlignRight)
        return card

    def _build_stopwatch(self):
        card = _panel()
        lo = QVBoxLayout(card)
        lo.setContentsMargins(14, 12, 14, 12)
        lo.setSpacing(8)
        lo.addLayout(_header("Stopwatch", "clock"))
        self.lbl_sw = _lbl("00:00.0", 40, "#ffffff", 300, mono=True)
        self.lbl_sw.setAlignment(Qt.AlignCenter)
        lo.addWidget(self.lbl_sw)
        btns = QHBoxLayout()
        self.sw_btn = QPushButton("Start")
        self.sw_btn.setObjectName("action-btn-primary")
        self.sw_btn.clicked.connect(self._sw_toggle)
        self.lap_btn = QPushButton("Lap")
        self.lap_btn.clicked.connect(self._sw_lap)
        reset = QPushButton("Reset")
        reset.clicked.connect(self._sw_reset)
        for b in (self.sw_btn, self.lap_btn, reset):
            btns.addWidget(b)
        lo.addLayout(btns)
        self.laps = QListWidget()
        self.laps.setStyleSheet("QListWidget{font-family:'Cascadia Mono','Consolas',monospace;font-size:12px;}")
        lo.addWidget(self.laps, 1)
        return card

    def _build_countdown(self):
        card = _panel()
        lo = QVBoxLayout(card)
        lo.setContentsMargins(14, 12, 14, 12)
        lo.setSpacing(8)
        lo.addLayout(_header("Timer", "timer"))
        body = QHBoxLayout()
        body.setSpacing(12)
        self.ring = RingProgress()
        self.ring.setFixedSize(116, 116)
        self.ring.color = QColor(245, 190, 75)
        self.ring.sub = "TIMER"
        body.addWidget(self.ring)
        side = QVBoxLayout()
        side.setSpacing(6)
        presets = QGridLayout()
        presets.setSpacing(5)
        for i, m in enumerate((1, 3, 5, 10, 15, 30)):
            b = QPushButton(f"{m} min")
            b.setStyleSheet("padding:3px 6px;font-size:11px;")
            b.clicked.connect(lambda _=False, mm=m: self._cd_set(mm * 60))
            presets.addWidget(b, i // 3, i % 3)
        side.addLayout(presets)
        crow = QHBoxLayout()
        crow.addWidget(_lbl("Custom", 11, "#94a3b8", 600))
        self.cd_spin = QSpinBox()
        self.cd_spin.setRange(1, 600)
        self.cd_spin.setValue(5)
        self.cd_spin.setSuffix(" min")
        self.cd_spin.valueChanged.connect(lambda v: self._cd_set(v * 60))
        crow.addWidget(self.cd_spin, 1)
        side.addLayout(crow)
        brow = QHBoxLayout()
        self.cd_btn = QPushButton("Start")
        self.cd_btn.setObjectName("action-btn-primary")
        self.cd_btn.clicked.connect(self._cd_toggle)
        r = QPushButton("Reset")
        r.clicked.connect(lambda: self._cd_set(self.cd_total))
        brow.addWidget(self.cd_btn)
        brow.addWidget(r)
        side.addLayout(brow)
        body.addLayout(side, 1)
        lo.addLayout(body)
        self._cd_render()
        return card

    def _build_alarms(self):
        card = _panel()
        lo = QVBoxLayout(card)
        lo.setContentsMargins(14, 12, 14, 12)
        lo.setSpacing(8)
        lo.addLayout(_header("Alarms", "bell"))
        add = QHBoxLayout()
        add.setSpacing(6)
        self.al_time = QTimeEdit(QTime.currentTime().addSecs(3600))
        self.al_time.setDisplayFormat("HH:mm")
        self.al_label = QLineEdit()
        self.al_label.setPlaceholderText("Label (optional)")
        self.al_label.returnPressed.connect(self._add_alarm)
        add_btn = QPushButton("Add")
        add_btn.setObjectName("action-btn-primary")
        add_btn.clicked.connect(self._add_alarm)
        add.addWidget(self.al_time)
        add.addWidget(self.al_label, 1)
        add.addWidget(add_btn)
        lo.addLayout(add)
        self.alarm_list = QVBoxLayout()
        self.alarm_list.setSpacing(4)
        lo.addLayout(self.alarm_list)
        lo.addStretch()
        note = _lbl("Alarms ring while CYPHER-X is running.", 10, "#475569", 600)
        lo.addWidget(note)
        return card

    # ---------------------------------------------------------- rendering --

    def _toggle_mode(self):
        self.is_24h = not self.is_24h
        save_setting("clock_24h", self.is_24h)
        self._sync_mode_btn()
        self._render_world()
        self._render_alarms()

    def _sync_mode_btn(self):
        self.mode_btn.setText("Use 12-hour" if self.is_24h else "Use 24-hour")

    def _fmt(self, dt):
        return dt.strftime("%H:%M") if self.is_24h else dt.strftime("%I:%M %p").lstrip("0")

    def _tick(self):
        now = datetime.now()
        if self.is_24h:
            self.lbl_time.setText(now.strftime("%H:%M"))
            self.lbl_ampm.setText("")
        else:
            self.lbl_time.setText(now.strftime("%I:%M").lstrip("0"))
            self.lbl_ampm.setText(now.strftime("%p"))
        self.lbl_secs.setText(now.strftime("%S"))
        self.lbl_date.setText(now.strftime("%A, %d %B %Y"))
        doy = now.timetuple().tm_yday
        tz = now.astimezone().tzname()
        self.lbl_info.setText(f"WEEK {now.isocalendar()[1]}  ·  DAY {doy}  ·  {tz}")

        if self.sw_running:
            self.lbl_sw.setText(self._fmt_sw(self._sw_now()))
        if self.cd_running:
            self.cd_left = max(0.0, self.cd_end - time.monotonic())
            self._cd_render()
            if self.cd_left <= 0:
                self._cd_done()
        if now.second == 0 or self._fired_minute is None:
            self._render_world()
        self._check_alarms(now)

    def _render_world(self):
        while self.world_grid.count():
            w = self.world_grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not HAS_TZ:
            self.world_grid.addWidget(_lbl("Install the 'tzdata' package for world clocks.", 11, "#94a3b8"), 0, 0)
            return
        local = datetime.now().astimezone()
        for r, zone in enumerate(self.zones):
            try:
                t = datetime.now(ZoneInfo(zone))
            except Exception:
                continue
            diff = (t.utcoffset() - local.utcoffset()).total_seconds() / 3600
            rel = "Same time" if diff == 0 else f"{diff:+g} h"
            if t.date() != local.date():
                rel += " · " + ("tomorrow" if t.date() > local.date() else "yesterday")
            name = _lbl(zone.split("/")[-1].replace("_", " "), 13, "#f1f5f9", 600)
            sub = _lbl(rel, 10, "#64748b", 600)
            tm = _lbl(self._fmt(t), 18, "#ffffff", 300)
            rm = QToolButton()
            rm.setIcon(get_icon("x", "#64748b", 12))
            rm.setToolTip("Remove")
            rm.setCursor(Qt.PointingHandCursor)
            rm.setStyleSheet("QToolButton{background:transparent;border:none;}"
                             "QToolButton:hover{background:rgba(255,255,255,0.12);border-radius:6px;}")
            rm.clicked.connect(lambda _=False, z=zone: self._remove_zone(z))
            self.world_grid.addWidget(name, r, 0)
            self.world_grid.addWidget(sub, r, 1)
            self.world_grid.addWidget(tm, r, 2, Qt.AlignRight)
            self.world_grid.addWidget(rm, r, 3)
        self.world_grid.setColumnStretch(1, 1)

    def _add_zone(self):
        if not HAS_TZ:
            return
        zones = sorted(z for z in available_timezones() if "/" in z and not z.startswith(("Etc", "SystemV")))
        zone, ok = QInputDialog.getItem(self, "Add City", "Time zone:", zones, 0, True)
        if ok and zone in zones and zone not in self.zones:
            self.zones = (self.zones + [zone])[-6:]
            save_setting("page_world_zones", self.zones)
            self._render_world()

    def _remove_zone(self, zone):
        self.zones = [z for z in self.zones if z != zone]
        save_setting("page_world_zones", self.zones)
        self._render_world()

    # ---------------------------------------------------------- stopwatch --

    def _sw_now(self):
        return self.sw_elapsed + (time.monotonic() - self.sw_start if self.sw_running else 0)

    @staticmethod
    def _fmt_sw(sec):
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        tenth = int((sec * 10) % 10)
        return f"{int(h)}:{int(m):02d}:{int(s):02d}.{tenth}" if h >= 1 else f"{int(m):02d}:{int(s):02d}.{tenth}"

    def _sw_toggle(self):
        if self.sw_running:
            self.sw_elapsed = self._sw_now()
            self.sw_running = False
            self.sw_btn.setText("Resume")
        else:
            self.sw_start = time.monotonic()
            self.sw_running = True
            self.sw_btn.setText("Pause")

    def _sw_lap(self):
        if not self.sw_running:
            return
        now = self._sw_now()
        n = self.laps.count() + 1
        self.laps.insertItem(0, QListWidgetItem(
            f"Lap {n:<3}  {self._fmt_sw(now - self.sw_last_lap):>10}   {self._fmt_sw(now):>10}"))
        self.sw_last_lap = now

    def _sw_reset(self):
        self.sw_running = False
        self.sw_elapsed = self.sw_last_lap = 0.0
        self.sw_btn.setText("Start")
        self.lbl_sw.setText("00:00.0")
        self.laps.clear()

    # ---------------------------------------------------------- countdown --

    def _cd_set(self, seconds):
        self.cd_running = False
        self.cd_total = int(seconds)
        self.cd_left = float(seconds)
        self.cd_btn.setText("Start")
        self._cd_render()

    def _cd_toggle(self):
        if self.cd_running:
            self.cd_left = max(0.0, self.cd_end - time.monotonic())
            self.cd_running = False
            self.cd_btn.setText("Resume")
        else:
            if self.cd_left <= 0:
                self.cd_left = float(self.cd_total)
            self.cd_end = time.monotonic() + self.cd_left
            self.cd_running = True
            self.cd_btn.setText("Pause")
        self._cd_render()

    def _cd_render(self):
        left = int(self.cd_left + 0.999)
        h, rem = divmod(left, 3600)
        m, s = divmod(rem, 60)
        self.ring.text = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        self.ring.sub = "RUNNING" if self.cd_running else ("PAUSED" if 0 < self.cd_left < self.cd_total else "TIMER")
        self.ring.progress = 1 - self.cd_left / self.cd_total if self.cd_total else 0
        self.ring.update()

    def _cd_done(self):
        self.cd_running = False
        self.cd_btn.setText("Start")
        self._ring_bell("Timer finished", f"Your {self.cd_total // 60} minute timer is done.")

    # ------------------------------------------------------------- alarms --

    def _add_alarm(self):
        t = self.al_time.time().toString("HH:mm")
        self.alarms.append({"time": t, "label": self.al_label.text().strip(), "on": True})
        self.alarms.sort(key=lambda a: a["time"])
        self.al_label.clear()
        save_setting("alarms", self.alarms)
        self._render_alarms()

    def _render_alarms(self):
        while self.alarm_list.count():
            w = self.alarm_list.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not self.alarms:
            self.alarm_list.addWidget(_lbl("No alarms set.", 12, "#64748b"))
            return
        for i, a in enumerate(self.alarms):
            row = QWidget()
            row.setStyleSheet("QWidget{background:rgba(255,255,255,0.04);border-radius:10px;}")
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 4, 6, 4)
            t = datetime.strptime(a["time"], "%H:%M")
            color = "#ffffff" if a["on"] else "#475569"
            h.addWidget(_lbl(self._fmt(t), 20, color, 300))
            h.addWidget(_lbl(a["label"] or "Alarm", 12, "#94a3b8" if a["on"] else "#475569", 600), 1)
            tog = QPushButton("On" if a["on"] else "Off")
            tog.setCheckable(True)
            tog.setChecked(a["on"])
            tog.setFixedWidth(52)
            tog.setStyleSheet("QPushButton{padding:3px;font-size:11px;}"
                              "QPushButton:checked{background:#0284c7;border:1px solid #38bdf8;}")
            tog.clicked.connect(lambda on, j=i: self._set_alarm(j, on))
            rm = QToolButton()
            rm.setIcon(get_icon("trash", "#94a3b8", 13))
            rm.setStyleSheet("QToolButton{background:transparent;border:none;padding:4px;}"
                             "QToolButton:hover{background:rgba(239,68,68,0.25);border-radius:6px;}")
            rm.clicked.connect(lambda _=False, j=i: self._delete_alarm(j))
            h.addWidget(tog)
            h.addWidget(rm)
            self.alarm_list.addWidget(row)

    def _set_alarm(self, i, on):
        self.alarms[i]["on"] = on
        save_setting("alarms", self.alarms)
        self._render_alarms()

    def _delete_alarm(self, i):
        self.alarms.pop(i)
        save_setting("alarms", self.alarms)
        self._render_alarms()

    def _check_alarms(self, now):
        key = now.strftime("%Y-%m-%d %H:%M")
        if key == self._fired_minute:
            return
        self._fired_minute = key
        hm = now.strftime("%H:%M")
        for a in self.alarms:
            if a["on"] and a["time"] == hm:
                if a.get("snooze"):
                    self.alarms.remove(a)
                    save_setting("alarms", self.alarms)
                    self._render_alarms()
                self._ring_bell("Alarm", f"{self._fmt(now)}  —  {a['label'] or 'Alarm'}", snooze=True)
                break

    def _ring_bell(self, title, text, snooze=False):
        beeper = QTimer(self)
        beeper.timeout.connect(QApplication.beep)
        beeper.start(900)
        QApplication.beep()
        win = self.window()
        if win.isMinimized():
            win.showNormal()
        win.raise_()
        win.activateWindow()
        box = QMessageBox(QMessageBox.Information, title, text, parent=self)
        snooze_btn = box.addButton("Snooze 5 min", QMessageBox.ActionRole) if snooze else None
        box.addButton("Dismiss", QMessageBox.AcceptRole)
        box.exec()
        beeper.stop()
        if snooze_btn is not None and box.clickedButton() is snooze_btn:
            t = (datetime.now() + timedelta(minutes=5)).strftime("%H:%M")
            self.alarms.append({"time": t, "label": "Snoozed", "on": True, "snooze": True})
            save_setting("alarms", self.alarms)
            self._render_alarms()

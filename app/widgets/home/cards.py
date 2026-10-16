"""
Smaller home cards: calendar, notes, tasks, focus timer, system gauges,
world clocks and the quick-launch dock.
"""
import calendar
import math
import os
import shutil
import subprocess
import time
import webbrowser
from datetime import datetime, date

import psutil
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, QSize, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QLinearGradient, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QPlainTextEdit, QLineEdit, QInputDialog, QApplication, QSizePolicy
)

from app.widgets.home.skins import skin_color
from app.widgets.home.common import (
    GlassCard, label, card_header, icon_button, pill_button, hicon, hpix,
    load_setting, save_setting, TEXT, TEXT_SOFT, MUTED, DIM, ACCENT, DANGER
)

try:
    from zoneinfo import ZoneInfo, available_timezones
    ZoneInfo("Europe/London")
    HAS_TZ = True
except Exception:  # tzdata missing on this Windows install
    HAS_TZ = False


# ---------------------------------------------------------------------------
#  Calendar
# ---------------------------------------------------------------------------

class CalendarWidget(GlassCard):
    def __init__(self, parent=None):
        super().__init__("CalendarCard", parent=parent)
        today = date.today()
        self._year, self._month = today.year, today.month
        self._shown_day = today

        lo = QHBoxLayout(self)
        lo.setContentsMargins(16, 12, 12, 12)
        lo.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(0)
        self._dow = label("", DANGER, 10, 800, 0.4)
        self._day = label("", TEXT, 46, 200)
        self._mon = label("", MUTED, 11, 600)
        self._info = label("", DIM, 10, 600)
        self._info.setWordWrap(True)
        left.addWidget(self._dow)
        left.addWidget(self._day)
        left.addWidget(self._mon)
        left.addSpacing(6)
        left.addWidget(self._info)
        left.addStretch()
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(84)
        lw.setStyleSheet("background:transparent;")
        lo.addWidget(lw)

        right = QVBoxLayout()
        right.setSpacing(4)
        nav = QHBoxLayout()
        nav.setSpacing(2)
        self._title = QPushButton()
        self._title.setCursor(Qt.PointingHandCursor)
        self._title.setToolTip("Back to today")
        self._title.setStyleSheet("""QPushButton{background:transparent;border:none;color:#e2e8f0;
            font-size:11px;font-weight:700;text-align:left;padding:0;}
            QPushButton:hover{color:#7dd3fc;}""")
        self._title.clicked.connect(self.go_today)
        prev = icon_button("chevron_left", "Previous month", 20, 12, MUTED)
        nxt = icon_button("chevron_right", "Next month", 20, 12, MUTED)
        prev.clicked.connect(lambda: self._shift(-1))
        nxt.clicked.connect(lambda: self._shift(1))
        nav.addWidget(self._title, 1)
        nav.addWidget(prev)
        nav.addWidget(nxt)
        right.addLayout(nav)

        self._grid = QGridLayout()
        self._grid.setSpacing(1)
        for c, d in enumerate("MTWTFSS"):
            h = label(d, DIM, 9, 800)
            h.setAlignment(Qt.AlignCenter)
            self._grid.addWidget(h, 0, c)
        self._cells = []
        for r in range(6):
            for c in range(7):
                cell = QLabel()
                cell.setAlignment(Qt.AlignCenter)
                cell.setFixedSize(19, 17)
                self._grid.addWidget(cell, r + 1, c)
                self._cells.append(cell)
        right.addLayout(self._grid)
        right.addStretch()
        lo.addLayout(right, 1)

        self._render()
        self._midnight = QTimer(self)
        self._midnight.timeout.connect(self._check_day)
        self._midnight.start(60_000)

    def _shift(self, delta):
        m = self._month + delta
        self._year += (m - 1) // 12
        self._month = (m - 1) % 12 + 1
        self._render()

    def go_today(self):
        t = date.today()
        self._year, self._month = t.year, t.month
        self._render()

    def _check_day(self):
        if date.today() != self._shown_day:
            self._shown_day = date.today()
            self.go_today()

    def _render(self):
        today = date.today()
        self._dow.setText(today.strftime("%A").upper())
        self._day.setText(str(today.day))
        self._mon.setText(today.strftime("%B"))
        doy = today.timetuple().tm_yday
        days_in_year = 366 if calendar.isleap(today.year) else 365
        self._info.setText(f"Week {today.isocalendar()[1]}\n{days_in_year - doy} days left")
        self._title.setText(date(self._year, self._month, 1).strftime("%B %Y"))

        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(self._year, self._month)
        flat = [d for w in weeks for d in w]
        for i, cell in enumerate(self._cells):
            if i >= len(flat):
                cell.setText("")
                cell.setStyleSheet("background:transparent;")
                continue
            d = flat[i]
            cell.setText(str(d.day))
            if d == today:
                st = "background:#ef4444;color:#fff;font-weight:800;border-radius:8px;"
            elif d.month != self._month:
                st = "color:rgba(148,163,184,0.35);"
            elif d.weekday() >= 5:
                st = "color:#94a3b8;"
            else:
                st = "color:#e2e8f0;"
            cell.setStyleSheet(st + "font-size:10px;background-color:" +
                               ("#ef4444;" if d == today else "transparent;"))


# ---------------------------------------------------------------------------
#  Notes (sticky memo, auto-saved)
# ---------------------------------------------------------------------------

class NotesCard(GlassCard):
    def __init__(self, parent=None):
        super().__init__("NotesCard", bg="qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                         "stop:0 rgba(250,204,21,0.72), stop:1 rgba(234,179,8,0.62))",
                         border="rgba(255,240,180,0.35)", parent=parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(14, 12, 10, 10)
        lo.setSpacing(4)

        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(hpix("notes", "#422006", 13))
        ic.setStyleSheet("background:transparent;border:none;")
        head.addWidget(ic)
        head.addWidget(label("NOTES", "#422006", 10, 800, 1.0))
        head.addStretch()
        self._saved = label("", "#713f12", 9, 700)
        head.addWidget(self._saved)
        lo.addLayout(head)

        self._edit = QPlainTextEdit()
        self._edit.setPlainText(load_setting("memo_text", "Laptop\nWallet\nKeys\nPhone"))
        self._edit.setPlaceholderText("Write something…")
        self._edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._edit.setStyleSheet("""
            QPlainTextEdit { background: transparent; border: none; padding: 0;
                             color: #1c1917; font-size: 13px; font-weight: 600; }
            QPlainTextEdit:focus { background: rgba(255,255,255,0.18); border-radius: 8px; border: none; }
        """)
        self._edit.textChanged.connect(self._schedule_save)
        lo.addWidget(self._edit, 1)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save)

    def _schedule_save(self):
        self._saved.setText("…")
        self._save_timer.start(600)

    def _save(self):
        save_setting("memo_text", self._edit.toPlainText())
        self._saved.setText("SAVED")
        QTimer.singleShot(1500, lambda: self._saved.setText(""))


# ---------------------------------------------------------------------------
#  Tasks (shares the Notes & Tasks SQLite table)
# ---------------------------------------------------------------------------

class TasksWidget(GlassCard):
    MAX_ROWS = 5

    def __init__(self, parent=None):
        super().__init__("TasksCard", parent=parent)
        from app.database import Database
        self.db = Database.get_instance()

        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 12, 12, 12)
        lo.setSpacing(6)

        head = QHBoxLayout()
        ic, title = card_header("Tasks", "check_square")
        head.addWidget(ic)
        head.addWidget(title)
        head.addStretch()
        self._count = label("", ACCENT, 10, 800)
        head.addWidget(self._count)
        lo.addLayout(head)

        self._rows = QVBoxLayout()
        self._rows.setSpacing(2)
        lo.addLayout(self._rows)
        lo.addStretch()

        self._input = QLineEdit()
        self._input.setPlaceholderText("Add a task and press Enter")
        self._input.setStyleSheet("""
            QLineEdit { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.10);
                        border-radius: 10px; padding: 5px 10px; color: #fff; font-size: 12px; }
            QLineEdit:focus { border: 1px solid rgba(56,189,248,0.6); background: rgba(255,255,255,0.10); }
        """)
        self._input.returnPressed.connect(self._add)
        lo.addWidget(self._input)
        self.refresh()

    def refresh(self):
        while self._rows.count():
            item = self._rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        try:
            tasks = self.db.get_tasks(include_completed=False)
        except Exception:
            tasks = []
        self._count.setText(f"{len(tasks)} OPEN" if tasks else "")
        if not tasks:
            empty = label("All clear — nothing pending.", MUTED, 12, 500)
            self._rows.addWidget(empty)
            return
        for t in tasks[: self.MAX_ROWS]:
            self._rows.addWidget(self._row(t))
        if len(tasks) > self.MAX_ROWS:
            self._rows.addWidget(label(f"+ {len(tasks) - self.MAX_ROWS} more in Notes & Tasks", DIM, 10, 600))

    def _row(self, task):
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        chk = icon_button("square", "Mark done", 22, 15, TEXT_SOFT)
        prio = {"High": DANGER, "Low": DIM}.get(task.get("priority"), ACCENT)
        txt = label(task["title"], TEXT, 12, 500, elide=True)
        dot = QLabel()
        dot.setFixedSize(6, 6)
        dot.setStyleSheet(f"background:{prio};border-radius:3px;")
        rm = icon_button("x", "Delete", 18, 11, DIM)

        def done():
            chk.setIcon(hicon("check_square", "#34d399", 15))
            txt.setStyleSheet("color:#64748b;font-size:12px;text-decoration:line-through;background:transparent;")
            self.db.update_task_status(task["id"], True)
            QTimer.singleShot(650, self.refresh)

        def delete():
            self.db.delete_task(task["id"])
            self.refresh()

        chk.clicked.connect(done)
        rm.clicked.connect(delete)
        h.addWidget(chk)
        h.addWidget(txt, 1)
        h.addWidget(dot)
        h.addWidget(rm)
        return w

    def _add(self):
        text = self._input.text().strip()
        if text:
            self.db.add_task(text, category="Home")
            self._input.clear()
            self.refresh()


# ---------------------------------------------------------------------------
#  Focus timer (Pomodoro)
# ---------------------------------------------------------------------------

class RingProgress(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.progress = 0.0
        self.text = "25:00"
        self.sub = "FOCUS"
        self.color = QColor(248, 113, 113)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(96, 96)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        side = min(self.width(), self.height()) - 8
        r = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        p.setPen(QPen(skin_color(self, QColor(255, 255, 255, 30)), 7, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r, 0, 360 * 16)
        if self.progress > 0:
            p.setPen(QPen(skin_color(self, self.color), 7, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(r, 90 * 16, -int(360 * 16 * min(1.0, self.progress)))
        f = QFont(self.font())
        f.setPixelSize(max(12, int(side * 0.22)))
        f.setWeight(QFont.Light)
        p.setFont(f)
        p.setPen(skin_color(self, QColor(255, 255, 255)))
        p.drawText(r.adjusted(0, -side * 0.08, 0, -side * 0.08), Qt.AlignCenter, self.text)
        f.setPixelSize(max(8, int(side * 0.085)))
        f.setWeight(QFont.Bold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        p.setFont(f)
        p.setPen(skin_color(self, QColor(148, 163, 184)))
        p.drawText(r.adjusted(0, side * 0.24, 0, side * 0.24), Qt.AlignCenter, self.sub)


class FocusTimerWidget(GlassCard):
    finished = Signal(str)

    MODES = {"focus": (25, "FOCUS", QColor(248, 113, 113)),
             "short": (5, "SHORT BREAK", QColor(52, 211, 153)),
             "long": (15, "LONG BREAK", QColor(56, 189, 248))}

    def __init__(self, parent=None):
        super().__init__("FocusCard", parent=parent)
        self._mode = "focus"
        self._running = False
        self._end_at = 0.0
        self._remaining = self.MODES["focus"][0] * 60
        self._sessions = int(load_setting("focus_sessions_" + date.today().isoformat(), 0))

        lo = QVBoxLayout(self)
        lo.setContentsMargins(14, 12, 14, 12)
        lo.setSpacing(6)

        head = QHBoxLayout()
        ic, title = card_header("Focus", "timer")
        head.addWidget(ic)
        head.addWidget(title)
        head.addStretch()
        self._sess = label("", MUTED, 10, 700)
        head.addWidget(self._sess)
        lo.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(10)
        self._ring = RingProgress()
        body.addWidget(self._ring, 1)

        side = QVBoxLayout()
        side.setSpacing(5)
        self._mode_btns = {}
        for key, text in [("focus", "Focus 25"), ("short", "Break 5"), ("long", "Long 15")]:
            b = pill_button(text)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.set_mode(k))
            side.addWidget(b)
            self._mode_btns[key] = b
        side.addStretch()
        body.addLayout(side)
        lo.addLayout(body, 1)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)
        self._start = pill_button("Start", "play", accent=True)
        self._start.clicked.connect(self.toggle)
        reset = pill_button("Reset", "rotate_ccw")
        reset.clicked.connect(self.reset)
        ctrl.addWidget(self._start, 1)
        ctrl.addWidget(reset, 1)
        lo.addLayout(ctrl)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.set_mode("focus")

    def set_mode(self, mode):
        self._mode = mode
        self._running = False
        self._timer.stop()
        self._remaining = self.MODES[mode][0] * 60
        for k, b in self._mode_btns.items():
            b.setChecked(k == mode)
        self._render()

    def toggle(self):
        if self._running:
            self._remaining = max(0, self._end_at - time.monotonic())
            self._running = False
            self._timer.stop()
        else:
            self._end_at = time.monotonic() + self._remaining
            self._running = True
            self._timer.start(250)
        self._render()

    def reset(self):
        self.set_mode(self._mode)

    def _tick(self):
        left = self._end_at - time.monotonic()
        if left <= 0:
            self._complete()
            return
        self._remaining = left
        self._render()

    def _complete(self):
        self._timer.stop()
        self._running = False
        QApplication.beep()
        if self._mode == "focus":
            self._sessions += 1
            save_setting("focus_sessions_" + date.today().isoformat(), self._sessions)
            nxt = "long" if self._sessions % 4 == 0 else "short"
            self.finished.emit("Focus session complete — time for a break")
        else:
            nxt = "focus"
            self.finished.emit("Break over — ready to focus?")
        self.set_mode(nxt)

    def _render(self):
        total = self.MODES[self._mode][0] * 60
        secs = int(math.ceil(self._remaining))
        self._ring.text = f"{secs // 60:02d}:{secs % 60:02d}"
        self._ring.sub = self.MODES[self._mode][1] if not (not self._running and secs < total) else "PAUSED"
        self._ring.color = self.MODES[self._mode][2]
        self._ring.progress = 1.0 - self._remaining / total if total else 0
        self._ring.update()
        self._start.setText("Pause" if self._running else ("Resume" if secs < total else "Start"))
        self._start.setIcon(hicon("pause" if self._running else "play", "#0b1116", 13))
        self._sess.setText(f"{self._sessions} TODAY" if self._sessions else "")


# ---------------------------------------------------------------------------
#  System gauges
# ---------------------------------------------------------------------------

class RingGauge(QWidget):
    def __init__(self, caption, color, parent=None):
        super().__init__(parent)
        self.caption = caption
        self.color = QColor(color)
        self.value = 0.0
        self.text = "--"
        self.setMinimumSize(54, 64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_value(self, pct, text=None):
        self.value = max(0.0, min(100.0, pct))
        self.text = text if text is not None else f"{pct:.0f}%"
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        cap_h = 14
        side = min(self.width(), self.height() - cap_h) - 6
        r = QRectF((self.width() - side) / 2, 3, side, side)
        p.setPen(QPen(skin_color(self, QColor(255, 255, 255, 28)), 5, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r, 0, 360 * 16)
        col = QColor(self.color)
        if self.value >= 90:
            col = QColor(248, 113, 113)
        p.setPen(QPen(skin_color(self, col), 5, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r, 90 * 16, -int(360 * 16 * self.value / 100))
        f = QFont(self.font())
        f.setPixelSize(max(9, int(side * 0.24)))
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(skin_color(self, QColor(255, 255, 255)))
        p.drawText(r, Qt.AlignCenter, self.text)
        f.setPixelSize(9)
        f.setWeight(QFont.Bold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)
        p.setFont(f)
        p.setPen(skin_color(self, QColor(148, 163, 184)))
        p.drawText(QRectF(0, r.bottom() + 2, self.width(), cap_h), Qt.AlignCenter, self.caption)


def _fmt_rate(bps: float) -> str:
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024:
            return f"{bps:.0f} {unit}" if unit == "B/s" else f"{bps:.1f} {unit}"
        bps /= 1024
    return f"{bps:.1f} TB/s"


class SystemWidget(GlassCard):
    open_monitor = Signal()

    def __init__(self, parent=None):
        super().__init__("SystemCard", parent=parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(14, 12, 12, 10)
        lo.setSpacing(6)

        head = QHBoxLayout()
        ic, title = card_header("System", "system_monitor")
        head.addWidget(ic)
        head.addWidget(title)
        head.addStretch()
        self._uptime = label("", DIM, 10, 700)
        head.addWidget(self._uptime)
        more = icon_button("chevron_right", "Open System Monitor", 20, 12, MUTED)
        more.clicked.connect(self.open_monitor.emit)
        head.addWidget(more)
        lo.addLayout(head)

        gauges = QHBoxLayout()
        gauges.setSpacing(4)
        self._cpu = RingGauge("CPU", "#38bdf8")
        self._ram = RingGauge("RAM", "#a78bfa")
        self._disk = RingGauge("DISK", "#f5be4b")
        self._bat = RingGauge("BATTERY", "#34d399")
        for g in (self._cpu, self._ram, self._disk, self._bat):
            gauges.addWidget(g, 1)
        lo.addLayout(gauges, 1)

        net = QHBoxLayout()
        net.setSpacing(4)
        for attr, icon, color in [("_down", "arrow_down", "#34d399"), ("_up", "arrow_up", "#38bdf8")]:
            ic = QLabel()
            ic.setPixmap(hpix(icon, color, 12))
            ic.setStyleSheet("background:transparent;border:none;")
            val = label("--", TEXT_SOFT, 11, 700)
            net.addWidget(ic)
            net.addWidget(val)
            net.addSpacing(10)
            setattr(self, attr, val)
        net.addStretch()
        self._procs = label("", DIM, 10, 700)
        net.addWidget(self._procs)
        lo.addLayout(net)

        self._last_net = psutil.net_io_counters()
        self._last_t = time.monotonic()
        psutil.cpu_percent(interval=None)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2000)
        QTimer.singleShot(300, self.refresh)

    def refresh(self):
        if not self.isVisible():
            return
        try:
            self._cpu.set_value(psutil.cpu_percent(interval=None))
            self._ram.set_value(psutil.virtual_memory().percent)
            drive = os.environ.get("SystemDrive", "C:") + "\\"
            self._disk.set_value(psutil.disk_usage(drive).percent)
            bat = psutil.sensors_battery()
            if bat:
                self._bat.caption = "CHARGING" if bat.power_plugged else "BATTERY"
                self._bat.set_value(bat.percent)
            else:
                self._bat.caption = "POWER"
                self._bat.set_value(100, "AC")
            now_net, now_t = psutil.net_io_counters(), time.monotonic()
            dt = max(0.001, now_t - self._last_t)
            self._down.setText(_fmt_rate((now_net.bytes_recv - self._last_net.bytes_recv) / dt))
            self._up.setText(_fmt_rate((now_net.bytes_sent - self._last_net.bytes_sent) / dt))
            self._last_net, self._last_t = now_net, now_t
            up = int(time.time() - psutil.boot_time())
            d, rem = divmod(up, 86400)
            self._uptime.setText(f"UP {d}d {rem // 3600}h" if d else f"UP {rem // 3600}h {rem % 3600 // 60}m")
            self._procs.setText(f"{len(psutil.pids())} PROCS")
        except Exception:
            pass


# ---------------------------------------------------------------------------
#  Analog + world clocks
# ---------------------------------------------------------------------------

class AnalogClock(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(96, 96)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        t = QTimer(self)
        t.timeout.connect(self.update)
        t.start(1000)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = min(self.width(), self.height()) / 2.0 - 4
        c = QPointF(self.width() / 2.0, self.height() / 2.0)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(255, 255, 255, 235))
        g.setColorAt(1, QColor(226, 232, 240, 225))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(c, r, r)

        f = QFont(self.font())
        f.setPixelSize(max(8, int(r * 0.2)))
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(30, 41, 59))
        for h in range(1, 13):
            a = math.radians(h * 30)
            pt = QPointF(c.x() + r * 0.78 * math.sin(a), c.y() - r * 0.78 * math.cos(a))
            p.drawText(QRectF(pt.x() - 10, pt.y() - 8, 20, 16), Qt.AlignCenter, str(h))

        now = datetime.now()
        hr, mn, sc = now.hour % 12, now.minute, now.second

        def hand(angle_deg, length, width, color):
            a = math.radians(angle_deg)
            p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(c, QPointF(c.x() + r * length * math.sin(a), c.y() - r * length * math.cos(a)))

        hand((hr + mn / 60) * 30, 0.5, max(2.5, r * 0.06), QColor(15, 23, 42))
        hand((mn + sc / 60) * 6, 0.72, max(2.0, r * 0.045), QColor(15, 23, 42))
        hand(sc * 6, 0.8, 1.3, QColor(249, 115, 22))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(249, 115, 22))
        p.drawEllipse(c, 3, 3)


DEFAULT_ZONES = ["Europe/London", "America/New_York", "Asia/Tokyo"]


class ClocksWidget(GlassCard):
    def __init__(self, parent=None):
        super().__init__("ClocksCard", parent=parent)
        self.zones = load_setting("world_zones", DEFAULT_ZONES)[:3]
        lo = QHBoxLayout(self)
        lo.setContentsMargins(12, 12, 14, 12)
        lo.setSpacing(12)
        lo.addWidget(AnalogClock(), 1)

        col = QVBoxLayout()
        col.setSpacing(4)
        self._rows = []
        for i in range(3):
            btn = QPushButton()
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip("Click to change city")
            btn.setStyleSheet("""
                QPushButton { background: rgba(255,255,255,0.05); border: none; border-radius: 10px;
                              text-align: left; padding: 5px 8px; }
                QPushButton:hover { background: rgba(255,255,255,0.12); }
            """)
            v = QVBoxLayout(btn)
            v.setContentsMargins(8, 4, 8, 4)
            v.setSpacing(0)
            city = label("", MUTED, 9, 800, 0.8, elide=True)
            tm = label("", TEXT, 16, 400)
            v.addWidget(city)
            v.addWidget(tm)
            btn.setMinimumHeight(42)
            btn.clicked.connect(lambda _=False, j=i: self._change(j))
            col.addWidget(btn)
            self._rows.append((city, tm))
        if not HAS_TZ:
            col.addWidget(label("Install 'tzdata' for world clocks", DIM, 9, 600))
        lo.addLayout(col, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    def _tick(self):
        local_now = datetime.now().astimezone()
        for zone, (city, tm) in zip(self.zones, self._rows):
            name = zone.split("/")[-1].replace("_", " ").upper()
            if HAS_TZ:
                t = datetime.now(ZoneInfo(zone))
                diff = (t.utcoffset() - local_now.utcoffset()).total_seconds() / 3600
                rel = "" if diff == 0 else f"  {diff:+g}H"
                day = ""
                if t.date() > local_now.date():
                    day = " · TMRW"
                elif t.date() < local_now.date():
                    day = " · YDAY"
                city.setText(f"{name}{rel}{day}")
                tm.setText(t.strftime("%H:%M"))
            else:
                city.setText(name)
                tm.setText("--:--")

    def _change(self, i):
        if not HAS_TZ:
            return
        zones = sorted(z for z in available_timezones() if "/" in z and not z.startswith(("Etc", "SystemV")))
        cur = zones.index(self.zones[i]) if self.zones[i] in zones else 0
        zone, ok = QInputDialog.getItem(self, "World Clock", "Time zone:", zones, cur, False)
        if ok:
            self.zones[i] = zone
            save_setting("world_zones", self.zones)
            self._tick()


# ---------------------------------------------------------------------------
#  Quick-launch dock
# ---------------------------------------------------------------------------

def _launch(target):
    try:
        if target.startswith(("http", "ms-settings:")):
            if target.startswith("http"):
                webbrowser.open(target)
            else:
                os.startfile(target)
        elif target == "terminal":
            exe = shutil.which("wt.exe") or shutil.which("powershell.exe") or "cmd.exe"
            subprocess.Popen([exe], creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        else:
            subprocess.Popen([target])
    except Exception:
        pass


class QuickDock(GlassCard):
    """macOS-style dock: Windows apps + jump links into CYPHER-X modules."""
    navigate = Signal(str)

    APPS = [
        ("file_explorer", "File Explorer", "explorer.exe", "#fbbf24"),
        ("network_monitor", "Web Browser", "https://www.google.com", "#38bdf8"),
        ("terminal", "Terminal", "terminal", "#e2e8f0"),
        ("calculator", "Calculator", "calc.exe", "#a78bfa"),
        ("file_text", "Notepad", "notepad.exe", "#93c5fd"),
        ("process_manager", "Task Manager", "taskmgr.exe", "#34d399"),
        ("settings", "Windows Settings", "ms-settings:", "#cbd5e1"),
    ]
    MODULES = [
        ("dashboard", "Command Center", "dashboard"),
        ("cleaner", "Disk Cleaner", "disk_cleaner"),
        ("pie_chart", "Disk Analyzer", "disk_analyzer"),
        ("notes", "Notes & Tasks", "notes_tasks"),
    ]

    def __init__(self, parent=None):
        super().__init__("DockCard", bg="rgba(16,22,30,0.55)", radius=22, parent=parent)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(10, 7, 10, 7)
        lo.setSpacing(6)
        for icon, tip, target, color in self.APPS:
            b = self._btn(icon, tip, color)
            b.clicked.connect(lambda _=False, t=target: _launch(t))
            lo.addWidget(b)
        sep = QWidget()
        sep.setFixedSize(1, 30)
        sep.setStyleSheet("background:rgba(255,255,255,0.18);")
        lo.addWidget(sep)
        for icon, tip, mod in self.MODULES:
            b = self._btn(icon, tip, ACCENT)
            b.clicked.connect(lambda _=False, m=mod: self.navigate.emit(m))
            lo.addWidget(b)

    @staticmethod
    def _btn(icon, tip, color):
        b = QPushButton()
        b.setIcon(hicon(icon, color, 20))
        b.setFixedSize(40, 40)
        b.setIconSize(QSize(20, 20))
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet("""
            QPushButton { background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.08);
                          border-radius: 12px; }
            QPushButton:hover { background: rgba(255,255,255,0.20); border: 1px solid rgba(255,255,255,0.25); }
            QPushButton:pressed { background: rgba(255,255,255,0.28); }
        """)
        return b

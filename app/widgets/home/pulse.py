"""
Pulse tiles — fitness-tracker style widgets for the Pulse skin.

  • CPU pulse        heart-rate style bar chart of the last minute of CPU load
  • Activity         GitHub-like dot grid (weekday x week) of what you did in CYPHER-X:
                     operations run, tasks added and focus sessions finished
  • Focus streak     this week's focus sessions as stacked dots
  • Uptime / Network big dot-matrix numbers

Dot-matrix digits are drawn by DotText from a 5x7 font so they look like the
LED read-outs in fitness apps.
"""
import time
from collections import deque
from datetime import date, datetime, timedelta

import psutil
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QLinearGradient
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QToolTip

from app.widgets.home.common import (
    GlassCard, label, card_header, hpix, load_setting, TEXT, TEXT_SOFT, MUTED, DIM, ACCENT
)
from app.widgets.home.skins import skin_color
from app.widgets.home.bento import fmt_bytes, fmt_rate, fmt_span


# ---------------------------------------------------------------------------
#  5x7 dot-matrix text
# ---------------------------------------------------------------------------

GLYPHS = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11111", "00010", "00100", "00010", "00001", "10001", "01110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    ":": ["000", "010", "010", "000", "010", "010", "000"],
    ".": ["00", "00", "00", "00", "00", "11", "11"],
    "-": ["000", "000", "000", "111", "000", "000", "000"],
    "%": ["11000", "11001", "00010", "00100", "01000", "10011", "00011"],
    " ": ["00", "00", "00", "00", "00", "00", "00"],
}


class DotText(QWidget):
    """Renders digits as a dot-matrix read-out; unsupported characters are skipped."""

    def __init__(self, text="", color=None, parent=None):
        super().__init__(parent)
        self.text = text
        self.color = QColor(color or "#ffffff")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(40)

    def set_text(self, text):
        if text != self.text:
            self.text = text
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        glyphs = [GLYPHS[ch] for ch in self.text if ch in GLYPHS]
        if not glyphs:
            return
        cols = sum(len(g[0]) + 1 for g in glyphs) - 1
        cell = min(self.height() / 7.0, self.width() / max(1, cols))
        dot = cell * 0.78
        p.setPen(Qt.NoPen)
        p.setBrush(skin_color(self, self.color))
        x0 = 0.0
        y0 = (self.height() - cell * 7) / 2
        for g in glyphs:
            for r, row in enumerate(g):
                for c, bit in enumerate(row):
                    if bit == "1":
                        p.drawRoundedRect(QRectF(x0 + c * cell, y0 + r * cell, dot, dot),
                                          dot * 0.28, dot * 0.28)
            x0 += (len(g[0]) + 1) * cell


def _header(text, icon):
    row = QHBoxLayout()
    row.setSpacing(6)
    ic, title = card_header(text, icon)
    row.addWidget(ic)
    row.addWidget(title)
    row.addStretch(1)
    return row


# ---------------------------------------------------------------------------
#  Activity history (shared by Activity + Streak + Uptime cards)
# ---------------------------------------------------------------------------

def focus_sessions(day: date) -> int:
    v = load_setting("focus_sessions_" + day.isoformat(), 0)
    return v if isinstance(v, int) else 0


def activity_by_day(days: int) -> dict:
    """{date: count} of operations run, tasks added and focus sessions finished."""
    since = date.today() - timedelta(days=days)
    counts = {}
    try:
        from app.database import Database
        db = Database.get_instance()
        with db._get_connection() as conn:
            for table, col in (("operation_history", "timestamp"), ("tasks", "created_at")):
                rows = conn.execute(
                    f"SELECT substr({col}, 1, 10) AS d, COUNT(*) FROM {table} "
                    f"WHERE {col} >= ? GROUP BY d", (since.isoformat(),)).fetchall()
                for d, n in rows:
                    try:
                        k = date.fromisoformat(d)
                    except (TypeError, ValueError):
                        continue
                    counts[k] = counts.get(k, 0) + n
    except Exception:
        pass
    for i in range(days + 1):
        d = since + timedelta(days=i)
        n = focus_sessions(d)
        if n:
            counts[d] = counts.get(d, 0) + n
    return counts


def streak_days(counts: dict) -> int:
    d, n = date.today(), 0
    if not counts.get(d):
        d -= timedelta(days=1)          # today not started yet doesn't break the streak
    while counts.get(d):
        n += 1
        d -= timedelta(days=1)
    return n


# ---------------------------------------------------------------------------
#  CPU pulse
# ---------------------------------------------------------------------------

class PulseBars(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.buckets = [0.0] * 6
        self.current = 0.0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        axis_w = 30
        cw = w - axis_w
        f = QFont(self.font())
        f.setPixelSize(8)
        p.setFont(f)
        for pct in (100, 75, 50, 25, 0):
            y = 4 + (h - 8) * (1 - pct / 100)
            p.setPen(QPen(skin_color(self, QColor(255, 255, 255, 22)), 1))
            p.drawLine(QPointF(0, y), QPointF(cw - 4, y))
            p.setPen(skin_color(self, QColor(100, 116, 139)))
            p.drawText(QRectF(cw, y - 6, axis_w, 12), Qt.AlignRight | Qt.AlignVCenter, str(pct))
        n = len(self.buckets)
        gap = 8
        bw = (cw - 4 - gap * (n - 1)) / n
        accent = skin_color(self, QColor(56, 189, 248))
        for i, v in enumerate(self.buckets):
            bh = max(4.0, (h - 8) * min(100.0, v) / 100)
            r = QRectF(i * (bw + gap), h - 4 - bh, bw, bh)
            g = QLinearGradient(0, r.top(), 0, r.bottom())
            top = QColor(accent)
            bottom = QColor(accent)
            bottom.setAlpha(120)
            g.setColorAt(0, top)
            g.setColorAt(1, bottom)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(r, 4, 4)
        y = 4 + (h - 8) * (1 - min(100.0, self.current) / 100)
        p.setPen(QPen(accent, 1, Qt.DashLine))
        p.drawLine(QPointF(0, y), QPointF(cw - 4, y))
        p.setBrush(accent)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cw - 4, y), 3, 3)


class PulseCard(GlassCard):
    def __init__(self, parent=None):
        super().__init__("PulseCard", parent=parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 12, 14, 12)
        lo.setSpacing(4)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(hpix("heart", ACCENT, 15))
        ic.setStyleSheet("background:transparent;")
        head.addWidget(ic)
        tl = QVBoxLayout()
        tl.setSpacing(0)
        tl.addWidget(label("CPU pulse", TEXT, 13, 700))
        self._date = label("", DIM, 9, 600)
        tl.addWidget(self._date)
        head.addLayout(tl)
        head.addStretch(1)
        lo.addLayout(head)
        stats = QHBoxLayout()
        self._avg = label("", TEXT, 20, 600)
        self._range = label("", TEXT, 20, 600)
        for cap, val in (("AVG", self._avg), ("RANGE", self._range)):
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(cap, DIM, 9, 700, 1.0))
            col.addWidget(val)
            stats.addLayout(col)
        stats.addStretch(1)
        lo.addLayout(stats)
        self.bars = PulseBars()
        lo.addWidget(self.bars, 1)
        self._samples = deque(maxlen=60)
        psutil.cpu_percent(None)
        t = QTimer(self)
        t.timeout.connect(self._sample)
        t.start(1000)

    def _sample(self):
        v = psutil.cpu_percent(None)
        self._samples.append(v)
        s = list(self._samples)
        self._date.setText(datetime.now().strftime("%a, %d %b %Y · last 60 s"))
        self._avg.setText(f"{sum(s) / len(s):.0f}<span style='font-size:10px;color:#64748b'> %</span>")
        self._range.setText(f"{min(s):.0f}-{max(s):.0f}<span style='font-size:10px;color:#64748b'> %</span>")
        buckets = []
        for i in range(6):
            chunk = s[max(0, len(s) - 60 + i * 10): max(0, len(s) - 60 + (i + 1) * 10)]
            buckets.append(sum(chunk) / len(chunk) if chunk else 0.0)
        self.bars.buckets = buckets
        self.bars.current = v
        if self.isVisible():
            self.bars.update()


# ---------------------------------------------------------------------------
#  Activity dot grid
# ---------------------------------------------------------------------------

class ActivityGrid(QWidget):
    WEEKS = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self.counts = {}
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _geom(self):
        label_w = 34
        cols, rows = self.WEEKS, 7
        cell = min((self.width() - label_w) / cols, (self.height() - 14) / rows)
        return label_w, cell

    def _day_at(self, col, row):
        today = date.today()
        start = today - timedelta(days=today.weekday()) - timedelta(weeks=self.WEEKS - 1)
        return start + timedelta(weeks=col, days=row)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        label_w, cell = self._geom()
        grid_w = self.width() - label_w
        x_off = (grid_w - cell * self.WEEKS) / 2
        ink = skin_color(self, QColor(255, 255, 255))
        empty = skin_color(self, QColor(16, 16, 16))
        today = date.today()
        f = QFont(self.font())
        f.setPixelSize(9)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        for col in range(self.WEEKS):
            for row in range(7):
                d = self._day_at(col, row)
                if d > today:
                    continue
                n = self.counts.get(d, 0)
                c = QPointF(x_off + col * cell + cell / 2, row * cell + cell / 2)
                rad = cell * 0.42
                p.setPen(Qt.NoPen)
                if n:
                    p.setBrush(ink)
                    p.drawEllipse(c, rad, rad)
                else:
                    p.setBrush(empty)
                    p.drawEllipse(c, rad, rad)
                if d == today:
                    p.setPen(QPen(ink, 1.5))
                    p.setBrush(Qt.NoBrush)
                    p.drawEllipse(c, rad + 2, rad + 2)
            d0 = self._day_at(col, 0)
            if d0.day <= 7:
                p.setPen(ink)
                p.drawText(QRectF(x_off + col * cell - 10, 7 * cell + 1, 40, 12),
                           Qt.AlignLeft, d0.strftime("%b").upper())
        p.setPen(ink)
        for row, name in enumerate(["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]):
            p.drawText(QRectF(self.width() - label_w + 6, row * cell, label_w, cell),
                       Qt.AlignLeft | Qt.AlignVCenter, name)

    def mouseMoveEvent(self, event):
        label_w, cell = self._geom()
        x_off = (self.width() - label_w - cell * self.WEEKS) / 2
        col = int((event.position().x() - x_off) // cell)
        row = int(event.position().y() // cell)
        if 0 <= col < self.WEEKS and 0 <= row < 7:
            d = self._day_at(col, row)
            if d <= date.today():
                n = self.counts.get(d, 0)
                QToolTip.showText(event.globalPosition().toPoint(),
                                  f"{d:%a %d %b} · {n} action{'s' if n != 1 else ''}", self)
                return
        QToolTip.hideText()


class ActivityCard(GlassCard):
    def __init__(self, parent=None):
        super().__init__("ActivityCard", parent=parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(18, 12, 16, 10)
        lo.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(label("Activity", TEXT, 14, 700))
        head.addStretch(1)
        self._sum = label("", MUTED, 10, 700)
        head.addWidget(self._sum)
        lo.addLayout(head)
        self.grid = ActivityGrid()
        lo.addWidget(self.grid, 1)
        t = QTimer(self)
        t.timeout.connect(self.refresh)
        t.start(5 * 60000)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        counts = activity_by_day(ActivityGrid.WEEKS * 7)
        self.grid.counts = counts
        active = sum(1 for v in counts.values() if v)
        self._sum.setText(f"{sum(counts.values())} ACTIONS · {active} ACTIVE DAYS · 16 WEEKS")
        self.grid.update()


# ---------------------------------------------------------------------------
#  Focus streak
# ---------------------------------------------------------------------------

class StreakDots(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sessions = [0] * 7
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        cell_w = w / 7
        rows = 4
        cell_h = min((h - 14) / rows, cell_w)
        on = skin_color(self, QColor(190, 242, 100))
        off = skin_color(self, QColor(255, 255, 255, 40))
        ink = skin_color(self, QColor(148, 163, 184))
        f = QFont(self.font())
        f.setPixelSize(9)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        today = date.today().weekday()
        for i, name in enumerate("MTWTFSS"):
            p.setPen(skin_color(self, QColor(255, 255, 255)) if i == today else ink)
            p.drawText(QRectF(i * cell_w, 0, cell_w, 12), Qt.AlignCenter, name)
            p.setPen(Qt.NoPen)
            for r in range(rows):
                filled = self.sessions[i] > r
                p.setBrush(on if filled else off)
                c = QPointF(i * cell_w + cell_w / 2, h - cell_h / 2 - r * cell_h)
                p.drawEllipse(c, cell_h * 0.32, cell_h * 0.32)


class StreakCard(GlassCard):
    def __init__(self, parent=None):
        super().__init__("StreakCard", parent=parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 12, 16, 12)
        lo.setSpacing(2)
        badge = QLabel()
        badge.setFixedSize(30, 30)
        badge.setAlignment(Qt.AlignCenter)
        badge.setPixmap(hpix("zap", ACCENT, 15))
        badge.setStyleSheet("background:rgba(56,189,248,0.18);border-radius:15px;")
        lo.addWidget(badge, 0, Qt.AlignHCenter)
        title = label("Focus streak", TEXT, 14, 700)
        title.setAlignment(Qt.AlignCenter)
        lo.addWidget(title)
        self._sub = label("", MUTED, 10, 600)
        self._sub.setAlignment(Qt.AlignCenter)
        lo.addWidget(self._sub)
        lo.addSpacing(4)
        self.dots = StreakDots()
        lo.addWidget(self.dots, 1)
        t = QTimer(self)
        t.timeout.connect(self.refresh)
        t.start(60000)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        sessions = [focus_sessions(monday + timedelta(days=i)) for i in range(7)]
        self.dots.sessions = sessions
        days = sum(1 for s in sessions if s)
        self._sub.setText(f"{days}/7 days · {sum(sessions)} sessions this week")
        self.dots.update()


# ---------------------------------------------------------------------------
#  Big dot-matrix numbers
# ---------------------------------------------------------------------------

class UptimeCard(GlassCard):
    """White 'steps' style card: uptime + activity streak."""

    def __init__(self, parent=None):
        super().__init__("UptimeCard", parent=parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 14, 16, 14)
        lo.setSpacing(2)
        lo.addWidget(label("UPTIME", TEXT, 10, 700, 1.0))
        self._up = DotText("0:00", "#ffffff")
        lo.addWidget(self._up)
        lo.addStretch(1)
        lo.addWidget(label("STREAK", TEXT, 10, 700, 1.0))
        row = QHBoxLayout()
        row.setSpacing(8)
        self._streak = DotText("0", "#ffffff")
        self._streak.setFixedWidth(70)
        row.addWidget(self._streak)
        self._unit = label("DAYS", TEXT, 22, 700)
        row.addWidget(self._unit, 0, Qt.AlignBottom)
        row.addStretch(1)
        lo.addLayout(row)
        t = QTimer(self)
        t.timeout.connect(self.refresh)
        t.start(30000)
        self.refresh()

    def refresh(self):
        up = int(time.time() - psutil.boot_time())
        h, m = divmod(up // 60, 60)
        self._up.set_text(f"{h}:{m:02d}")
        self.setToolTip(f"PC running for {fmt_span(up)} since last boot")
        n = streak_days(activity_by_day(60))
        self._streak.set_text(str(n))
        self._unit.setText("DAY" if n == 1 else "DAYS")


class NetDotCard(GlassCard):
    def __init__(self, parent=None):
        super().__init__("NetDotCard", parent=parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 12, 16, 14)
        lo.setSpacing(4)
        cap = label("DOWNLOADED", ACCENT, 10, 700, 1.2)
        cap.setAlignment(Qt.AlignCenter)
        lo.addWidget(cap)
        sub = label("since boot", DIM, 9, 600)
        sub.setAlignment(Qt.AlignCenter)
        lo.addWidget(sub)
        lo.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self._num = DotText("0", "#ffffff")
        self._num.setFixedHeight(46)
        self._num.setFixedWidth(150)
        row.addWidget(self._num)
        self._unit = label("GB", TEXT, 14, 700)
        row.addWidget(self._unit, 0, Qt.AlignBottom)
        row.addStretch(1)
        lo.addLayout(row)
        lo.addStretch(1)
        self._now = label("", TEXT_SOFT, 10, 600)
        self._now.setAlignment(Qt.AlignCenter)
        self._now.setStyleSheet(self._now.styleSheet() +
                                "background:rgba(255,255,255,0.08);border-radius:14px;padding:6px;")
        lo.addWidget(self._now)
        self._last = psutil.net_io_counters()
        self._t = time.monotonic()
        t = QTimer(self)
        t.timeout.connect(self.refresh)
        t.start(2000)
        self.refresh()

    def refresh(self):
        io = psutil.net_io_counters()
        now = time.monotonic()
        rate = max(0.0, (io.bytes_recv - self._last.bytes_recv) / max(0.2, now - self._t))
        self._last, self._t = io, now
        text = fmt_bytes(io.bytes_recv)
        num, unit = text.split(" ")
        self._num.set_text(num)
        self._unit.setText(unit)
        self._now.setText(f"↓ {fmt_rate(rate)} now  ·  ↑ {fmt_bytes(io.bytes_sent)} sent")

"""
Space HUD — a sci-fi cockpit for the Home screen.

Every piece is custom painted: chamfered panels with glowing corner brackets,
segmented meters and a big radar in the middle. All read-outs are live:

  • HudBar       status strip: callsign, system state, uptime, clock
  • HudSystems   segmented CPU / RAM / disk / battery meters
  • HudNet       uplink / downlink rates with a trace
  • HudMenu      numbered navigation buttons into the app's modules
  • HudReactor   radar: clock + date in the core, CPU and RAM arcs, wind heading
                 from the weather widget, and the busiest processes as blips
  • HudBadges    hexagon quick-jumps
  • HudFeatured  the current wallpaper as a scan-lined "visual feed" with ‹ ›
  • HudFeed      mission log paging through the real operation history
"""
import math
import time
import zlib
from collections import deque
from datetime import datetime

import psutil
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, Signal
from PySide6.QtGui import (
    QPainter, QColor, QPen, QFont, QPainterPath, QPixmap, QImage, QPolygonF,
    QConicalGradient, QLinearGradient
)
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy, QAbstractButton

from app.widgets.home.common import hpix

FONT = "Bahnschrift"
CYAN = QColor(127, 212, 255)
CYAN_SOFT = QColor(127, 212, 255, 110)
CYAN_FAINT = QColor(127, 212, 255, 40)
FILL = QColor(6, 18, 34, 185)
TEXT = QColor(223, 243, 255)
DIM = QColor(140, 175, 200)
AMBER = QColor(255, 181, 71)
RED = QColor(255, 93, 108)
GREEN = QColor(110, 240, 170)


_cpu_state = {"times": None, "t": 0.0, "value": 0.0}


def cpu_now() -> float:
    """System CPU % from our own cpu_times deltas, so other widgets calling
    psutil.cpu_percent(None) can't reset our baseline. Cached for 0.8 s."""
    st = _cpu_state
    now = time.monotonic()
    if now - st["t"] < 0.8:
        return st["value"]
    t = psutil.cpu_times()
    if st["times"] is not None:
        prev = st["times"]
        total = sum(t) - sum(prev)
        idle = t.idle - prev.idle
        if total > 0:
            st["value"] = max(0.0, min(100.0, 100.0 * (1 - idle / total)))
    st["times"], st["t"] = t, now
    return st["value"]


def hud_font(px, weight=QFont.Normal, spacing=0.0):
    f = QFont(FONT)
    f.setPixelSize(int(px))
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def level_color(pct):
    return RED if pct >= 90 else AMBER if pct >= 75 else CYAN


def chamfer_path(r: QRectF, c=10.0) -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(QPolygonF([
        QPointF(r.left() + c, r.top()), QPointF(r.right(), r.top()),
        QPointF(r.right(), r.bottom() - c), QPointF(r.right() - c, r.bottom()),
        QPointF(r.left(), r.bottom()), QPointF(r.left(), r.top() + c),
        QPointF(r.left() + c, r.top())]))
    return path


def paint_frame(p: QPainter, r: QRectF, title=None, fill=FILL):
    """Chamfered translucent panel with bright corner brackets and an optional header."""
    p.setRenderHint(QPainter.Antialiasing, True)
    path = chamfer_path(r)
    p.fillPath(path, fill)
    p.setPen(QPen(CYAN_SOFT, 1))
    p.drawPath(path)
    p.setPen(QPen(CYAN, 2, Qt.SolidLine, Qt.FlatCap))
    c = 10
    p.drawLine(QPointF(r.left(), r.top() + c + 16), QPointF(r.left(), r.top() + c))
    p.drawLine(QPointF(r.left(), r.top() + c), QPointF(r.left() + c, r.top()))
    p.drawLine(QPointF(r.left() + c, r.top()), QPointF(r.left() + c + 16, r.top()))
    p.drawLine(QPointF(r.right(), r.bottom() - c - 16), QPointF(r.right(), r.bottom() - c))
    p.drawLine(QPointF(r.right(), r.bottom() - c), QPointF(r.right() - c, r.bottom()))
    p.drawLine(QPointF(r.right() - c, r.bottom()), QPointF(r.right() - c - 16, r.bottom()))
    if title:
        p.setFont(hud_font(11, QFont.DemiBold, 2.4))
        p.setPen(CYAN)
        p.drawText(QRectF(r.left() + 16, r.top() + 6, r.width() - 60, 18),
                   Qt.AlignLeft | Qt.AlignVCenter, title.upper())
        for i in range(3):
            p.fillRect(QRectF(r.right() - 18 - i * 7, r.top() + 11, 4, 8),
                       CYAN if i == 0 else CYAN_SOFT)
        p.setPen(QPen(CYAN_FAINT, 1))
        p.drawLine(QPointF(r.left() + 16, r.top() + 28), QPointF(r.right() - 16, r.top() + 28))


class HudPanel(QWidget):
    """Base for framed panels; children go into self.body."""

    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self.title = title
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 36 if title else 14, 16, 12)
        self.body.setSpacing(6)

    def paintEvent(self, event):
        p = QPainter(self)
        paint_frame(p, QRectF(self.rect()).adjusted(1, 1, -1, -1), self.title)


# ---------------------------------------------------------------------------
#  Status strip
# ---------------------------------------------------------------------------

class HudBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._state, self._detail = "", ""
        cpu_now()
        t = QTimer(self)
        t.timeout.connect(self.refresh)
        t.start(1000)
        self.refresh()

    def refresh(self):
        cpu = cpu_now()
        ram = psutil.virtual_memory().percent
        self._alert = cpu > 85 or ram > 90
        self._state = "HIGH LOAD" if self._alert else "ALL SYSTEMS NOMINAL"
        up = int(time.time() - psutil.boot_time())
        h, m = divmod(up // 60, 60)
        self._detail = f"UPTIME {h:02d}:{m:02d}"
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        paint_frame(p, r, None, QColor(6, 18, 34, 150))
        w = r.width()
        # ticks
        p.setPen(QPen(CYAN_FAINT, 1))
        for x in range(int(w * 0.3), int(w * 0.7), 6):
            p.drawLine(QPointF(x, r.bottom() - 4), QPointF(x, r.bottom() - (8 if x % 30 == 0 else 6)))
        p.setFont(hud_font(13, QFont.DemiBold, 3))
        p.setPen(CYAN)
        p.drawText(r.adjusted(18, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, "CYPHER-X  //  COMMAND")
        p.setPen(RED if self._alert else GREEN)
        p.setBrush(RED if self._alert else GREEN)
        dot_x = r.center().x() - p.fontMetrics().horizontalAdvance(self._state) / 2 - 14
        p.drawEllipse(QPointF(dot_x, r.center().y()), 3.5, 3.5)
        p.setPen(TEXT)
        p.drawText(r, Qt.AlignCenter, self._state)
        p.setPen(DIM)
        p.drawText(r.adjusted(0, 0, -18, 0), Qt.AlignRight | Qt.AlignVCenter,
                   f"{self._detail}   ·   {datetime.now():%H:%M:%S}")


# ---------------------------------------------------------------------------
#  Systems meters
# ---------------------------------------------------------------------------

class SegMeter(QWidget):
    SEGMENTS = 22

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name
        self.value = 0.0
        self.text = "--"
        self.invert = name == "POWER"          # low is the warning for a battery
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        p.setFont(hud_font(11, QFont.DemiBold, 2))
        p.setPen(DIM)
        p.drawText(QRectF(0, 0, w, 16), Qt.AlignLeft | Qt.AlignVCenter, self.name)
        if self.invert:
            col = RED if self.value < 15 else AMBER if self.value < 30 else CYAN
        else:
            col = level_color(self.value)
        p.setFont(hud_font(14, QFont.DemiBold))
        p.setPen(col)
        p.drawText(QRectF(0, 0, w, 16), Qt.AlignRight | Qt.AlignVCenter, self.text)
        n = self.SEGMENTS
        gap = 3
        sw = (w - gap * (n - 1)) / n
        lit = round(n * min(100.0, self.value) / 100)
        for i in range(n):
            r = QRectF(i * (sw + gap), 22, sw, 14)
            if i < lit:
                c = QColor(col)
                c.setAlpha(150 + int(105 * i / n))
                p.fillRect(r, c)
            else:
                p.fillRect(r, QColor(127, 212, 255, 22))


class HudSystems(HudPanel):
    def __init__(self, parent=None):
        super().__init__("Systems")
        self.meters = {k: SegMeter(k) for k in ("CPU", "MEMORY", "STORAGE", "POWER")}
        for m in self.meters.values():
            self.body.addWidget(m)
        self.body.addStretch(1)
        cpu_now()
        t = QTimer(self)
        t.timeout.connect(self.refresh)
        t.start(1500)
        self.refresh()

    def refresh(self):
        cpu = cpu_now()
        vm = psutil.virtual_memory()
        try:
            disk = psutil.disk_usage("C:\\").percent
        except OSError:
            disk = 0.0
        try:
            bat = psutil.sensors_battery()
        except Exception:
            bat = None
        vals = {"CPU": (cpu, f"{cpu:.0f}%"),
                "MEMORY": (vm.percent, f"{vm.used / 2**30:.1f} / {vm.total / 2**30:.0f} GB"),
                "STORAGE": (disk, f"C:  {disk:.0f}%"),
                "POWER": ((bat.percent, f"{bat.percent:.0f}%{'  CHARGING' if bat.power_plugged else ''}")
                          if bat else (100, "MAINS"))}
        for k, (v, t) in vals.items():
            m = self.meters[k]
            m.value, m.text = v, t
            m.update()


# ---------------------------------------------------------------------------
#  Network
# ---------------------------------------------------------------------------

class Trace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.down = deque([0.0] * 50, maxlen=50)
        self.up = deque([0.0] * 50, maxlen=50)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(34)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        p.setPen(QPen(CYAN_FAINT, 1, Qt.DotLine))
        p.drawLine(QPointF(0, h / 2), QPointF(w, h / 2))
        peak = max(max(self.down), max(self.up), 2048.0)
        for vals, col in ((self.up, GREEN), (self.down, CYAN)):
            path = QPainterPath()
            for i, v in enumerate(vals):
                pt = QPointF(w * i / (len(vals) - 1), h - 2 - (h - 4) * v / peak)
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            p.setPen(QPen(col, 1.6))
            p.drawPath(path)


def _rate(bps):
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024 or unit == "GB/s":
            return f"{bps:.0f} {unit}" if unit == "B/s" else f"{bps:.1f} {unit}"
        bps /= 1024


class HudNet(HudPanel):
    def __init__(self, parent=None):
        super().__init__("Uplink")
        self._down = _Readout("DOWN", CYAN)
        self._up = _Readout("UP", GREEN)
        row = QHBoxLayout()
        row.addWidget(self._down)
        row.addWidget(self._up)
        self.body.addLayout(row)
        self.trace = Trace()
        self.body.addWidget(self.trace, 1)
        self._last, self._t = psutil.net_io_counters(), time.monotonic()
        t = QTimer(self)
        t.timeout.connect(self._sample)
        t.start(1000)

    def _sample(self):
        io, now = psutil.net_io_counters(), time.monotonic()
        dt = max(0.2, now - self._t)
        d = max(0.0, (io.bytes_recv - self._last.bytes_recv) / dt)
        u = max(0.0, (io.bytes_sent - self._last.bytes_sent) / dt)
        self._last, self._t = io, now
        self.trace.down.append(d)
        self.trace.up.append(u)
        self._down.set(_rate(d))
        self._up.set(_rate(u))
        if self.isVisible():
            self.trace.update()


class _Readout(QWidget):
    def __init__(self, cap, color, parent=None):
        super().__init__(parent)
        self.cap, self.color, self.text = cap, color, "--"
        self.setFixedHeight(36)

    def set(self, text):
        self.text = text
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setFont(hud_font(10, QFont.DemiBold, 2))
        p.setPen(DIM)
        p.drawText(QRectF(0, 0, self.width(), 14), Qt.AlignLeft, self.cap)
        p.setFont(hud_font(17, QFont.DemiBold))
        p.setPen(self.color)
        p.drawText(QRectF(0, 14, self.width(), 22), Qt.AlignLeft | Qt.AlignVCenter, self.text)


# ---------------------------------------------------------------------------
#  Navigation
# ---------------------------------------------------------------------------

class HudButton(QAbstractButton):
    def __init__(self, index, text, parent=None):
        super().__init__(parent)
        self.index, self.label = index, text
        self.setFixedHeight(38)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        hot = self.underMouse() or self.isDown()
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = chamfer_path(r, 7)
        p.fillPath(path, QColor(127, 212, 255, 70 if hot else 18))
        p.setPen(QPen(CYAN if hot else CYAN_SOFT, 1))
        p.drawPath(path)
        if hot:
            p.fillRect(QRectF(r.left() + 1, r.top() + 8, 3, r.height() - 16), CYAN)
        p.setFont(hud_font(10, QFont.DemiBold, 1))
        p.setPen(CYAN if hot else DIM)
        p.drawText(r.adjusted(14, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, f"{self.index:02d}")
        p.setFont(hud_font(13, QFont.DemiBold, 2))
        p.setPen(TEXT)
        p.drawText(r.adjusted(42, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, self.label.upper())
        p.setPen(CYAN if hot else CYAN_SOFT)
        p.drawText(r.adjusted(0, 0, -14, 0), Qt.AlignRight | Qt.AlignVCenter, "›")


class HudMenu(HudPanel):
    navigate = Signal(str)

    ITEMS = [("Command Center", "dashboard"), ("Disk Cleaner", "disk_cleaner"),
             ("Process Manager", "process_manager"), ("Settings", "settings"),
             ("Exit to desktop", None)]

    def __init__(self, parent=None):
        super().__init__("Navigation")
        self.body.setSpacing(6)
        for i, (text, mod) in enumerate(self.ITEMS, start=1):
            b = HudButton(i, text)
            if mod:
                b.clicked.connect(lambda _=False, m=mod: self.navigate.emit(m))
            else:
                b.setToolTip("Minimise CYPHER-X")
                b.clicked.connect(lambda: self.window().showMinimized())
            self.body.addWidget(b)


# ---------------------------------------------------------------------------
#  Radar core
# ---------------------------------------------------------------------------

class HudReactor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(300, 300)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._sweep = 0.0
        self._cpu = 0.0
        self._ram = 0.0
        self._wind = None       # (speed, unit, direction°)
        self._blips = []        # (angle, radius 0..1, name, cpu)
        cpu_now()
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._step)
        self._anim.start(50)
        self._stats = QTimer(self)
        self._stats.timeout.connect(self._refresh)
        self._stats.start(1500)
        self._procs = QTimer(self)
        self._procs.timeout.connect(self._scan_procs)
        self._procs.start(4000)
        self._refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self._scan_procs()                              # primes per-process counters
        QTimer.singleShot(1500, self._scan_procs)       # first real numbers

    def set_weather(self, data):
        try:
            cur = data["current"]
            spd = float(cur["wind_speed_10m"])
            deg = float(cur.get("wind_direction_10m", 0.0))
        except (KeyError, TypeError, ValueError):
            return
        if data.get("_unit") == "F":
            self._wind = (spd, "mph", deg)
        else:
            self._wind = (spd / 3.6, "m/s", deg)
        self.update()

    def _step(self):
        if self.isVisible():
            self._sweep = (self._sweep + 3.0) % 360
            self.update()

    def _refresh(self):
        self._cpu = cpu_now()
        self._ram = psutil.virtual_memory().percent

    def _scan_procs(self):
        if not self.isVisible():
            return
        procs = []
        for pr in psutil.process_iter(["name", "cpu_percent"]):
            try:
                cpu = pr.info["cpu_percent"] or 0.0
                name = pr.info["name"] or ""
            except (psutil.Error, KeyError):
                continue
            if name and name.lower() not in ("system idle process", "idle"):
                procs.append((cpu, name))
        cores = psutil.cpu_count() or 1
        merged = {}
        for cpu, name in procs:                                      # chrome.exe x 30 -> one blip
            merged[name] = merged.get(name, 0.0) + cpu
        procs = [(cpu / cores, name) for name, cpu in merged.items()]   # share of the whole CPU
        procs.sort(reverse=True)
        blips = []
        for cpu, name in procs[:6]:
            angle = zlib.crc32(name.encode()) % 360          # stable spot per process
            radius = 0.92 - min(0.38, cpu / 100.0 * 0.6)      # busier = closer to the core
            blips.append((angle, radius, name.rsplit(".", 1)[0][:14], cpu))
        self._blips = blips

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        c = QPointF(w / 2, h / 2)
        R = min(w, h) / 2 - 8

        # radar disc + sweep
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(4, 14, 28, 150))
        p.drawEllipse(c, R * 0.86, R * 0.86)
        cg = QConicalGradient(c, -self._sweep + 90)
        cg.setColorAt(0.0, QColor(127, 212, 255, 90))
        cg.setColorAt(0.12, QColor(127, 212, 255, 0))
        cg.setColorAt(1.0, QColor(127, 212, 255, 0))
        p.setBrush(cg)
        p.drawEllipse(c, R * 0.86, R * 0.86)
        a = math.radians(self._sweep)
        p.setPen(QPen(QColor(127, 212, 255, 160), 1.2))
        p.drawLine(c, QPointF(c.x() + R * 0.86 * math.sin(a), c.y() - R * 0.86 * math.cos(a)))

        # rings
        for frac, alpha, style in ((0.86, 120, Qt.SolidLine), (0.62, 60, Qt.DashLine),
                                   (0.40, 60, Qt.DotLine)):
            p.setPen(QPen(QColor(127, 212, 255, alpha), 1, style))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, R * frac, R * frac)
        p.setPen(QPen(QColor(127, 212, 255, 35), 1))
        p.drawLine(QPointF(c.x() - R * 0.86, c.y()), QPointF(c.x() + R * 0.86, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - R * 0.86), QPointF(c.x(), c.y() + R * 0.86))

        # outer tick ring + compass letters
        for i in range(120):
            deg = i * 3
            ar = math.radians(deg)
            major = deg % 30 == 0
            r1 = R * (0.91 if major else 0.94)
            p.setPen(QPen(CYAN if major else CYAN_SOFT, 2 if major else 1))
            p.drawLine(QPointF(c.x() + r1 * math.sin(ar), c.y() - r1 * math.cos(ar)),
                       QPointF(c.x() + R * 0.98 * math.sin(ar), c.y() - R * 0.98 * math.cos(ar)))
        p.setFont(hud_font(max(10, R * 0.05), QFont.DemiBold, 1))
        for deg, letter in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            ar = math.radians(deg)
            pt = QPointF(c.x() + R * 0.80 * math.sin(ar), c.y() - R * 0.80 * math.cos(ar))
            p.setPen(CYAN)
            p.drawText(QRectF(pt.x() - 12, pt.y() - 10, 24, 20), Qt.AlignCenter, letter)

        # CPU + RAM arcs
        for frac, val, width in ((0.72, self._cpu, 6), (0.67, self._ram, 3)):
            rr = R * frac
            rect = QRectF(c.x() - rr, c.y() - rr, rr * 2, rr * 2)
            p.setPen(QPen(QColor(127, 212, 255, 25), width, Qt.SolidLine, Qt.FlatCap))
            p.drawArc(rect, 90 * 16, -360 * 16)
            p.setPen(QPen(level_color(val) if width > 4 else QColor(190, 160, 255), width,
                          Qt.SolidLine, Qt.FlatCap))
            p.drawArc(rect, 90 * 16, -int(360 * 16 * val / 100))

        # process blips
        p.setFont(hud_font(max(9, R * 0.036), QFont.DemiBold, 0.5))
        for angle, rad, name, cpu in self._blips:
            ar = math.radians(angle)
            rr = R * 0.86 * rad
            pt = QPointF(c.x() + rr * math.sin(ar), c.y() - rr * math.cos(ar))
            col = level_color(cpu * 2)
            glow = QColor(col)
            glow.setAlpha(60)
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(pt, 7, 7)
            p.setBrush(col)
            p.drawEllipse(pt, 3, 3)
            p.setPen(QColor(223, 243, 255, 200))
            p.drawText(QRectF(pt.x() + 8, pt.y() - 8, 140, 16), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{name.upper()}  {cpu:.0f}%")

        # wind heading marker on the outer ring
        if self._wind:
            spd, unit, deg = self._wind
            ar = math.radians(deg)
            tip = QPointF(c.x() + R * 0.89 * math.sin(ar), c.y() - R * 0.89 * math.cos(ar))
            base = R * 1.0
            left = QPointF(c.x() + base * math.sin(ar - 0.05), c.y() - base * math.cos(ar - 0.05))
            right = QPointF(c.x() + base * math.sin(ar + 0.05), c.y() - base * math.cos(ar + 0.05))
            p.setPen(Qt.NoPen)
            p.setBrush(AMBER)
            p.drawPolygon(QPolygonF([tip, left, right]))

        # core read-out
        core = R * 0.36
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(2, 10, 20, 200))
        p.drawEllipse(c, core, core)
        p.setPen(QPen(CYAN_SOFT, 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, core, core)
        now = datetime.now()
        p.setFont(hud_font(core * 0.52, QFont.DemiBold, 1))
        p.setPen(TEXT)
        p.drawText(QRectF(c.x() - core, c.y() - core * 0.55, core * 2, core * 0.62),
                   Qt.AlignCenter, now.strftime("%H:%M"))
        p.setFont(hud_font(core * 0.15, QFont.DemiBold, 2.5))
        p.setPen(CYAN)
        p.drawText(QRectF(c.x() - core, c.y() + core * 0.10, core * 2, core * 0.2),
                   Qt.AlignCenter, now.strftime("%a %d %b %Y").upper())
        p.setPen(DIM)
        p.setFont(hud_font(core * 0.12, QFont.DemiBold, 1.5))
        p.drawText(QRectF(c.x() - core, c.y() + core * 0.34, core * 2, core * 0.2),
                   Qt.AlignCenter, f"CPU {self._cpu:.0f}%  ·  RAM {self._ram:.0f}%")
        # seconds ring
        p.setPen(QPen(CYAN, 2, Qt.SolidLine, Qt.FlatCap))
        sr = core + 6
        p.drawArc(QRectF(c.x() - sr, c.y() - sr, sr * 2, sr * 2), 90 * 16,
                  -int(360 * 16 * now.second / 60))

        # corner captions
        p.setFont(hud_font(11, QFont.DemiBold, 2))
        p.setPen(CYAN)
        p.drawText(QRectF(0, 0, w / 2, 18), Qt.AlignLeft | Qt.AlignVCenter, "// SCAN  ·  TOP PROCESSES")
        if self._wind:
            spd, unit, deg = self._wind
            p.setPen(AMBER)
            p.drawText(QRectF(w / 2, 0, w / 2, 18), Qt.AlignRight | Qt.AlignVCenter,
                       f"WIND {spd:.1f} {unit}  ·  {deg:.0f}°")
        p.setPen(DIM)
        p.drawText(QRectF(0, h - 18, w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   "OUTER ARC CPU  ·  INNER ARC RAM")


# ---------------------------------------------------------------------------
#  Hex quick-jumps
# ---------------------------------------------------------------------------

class HexBadge(QAbstractButton):
    def __init__(self, icon, text, parent=None):
        super().__init__(parent)
        self.icon_name, self.text_ = icon, text
        self.setToolTip(text.title())
        self.setFixedSize(84, 84)
        self.setCursor(Qt.PointingHandCursor)

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        hot = self.underMouse()
        c = QPointF(self.width() / 2, 30)

        def hexagon(r):
            return QPolygonF([QPointF(c.x() + r * math.cos(math.radians(60 * i - 90)),
                                      c.y() + r * math.sin(math.radians(60 * i - 90)))
                              for i in range(6)])

        p.setPen(QPen(CYAN if hot else CYAN_SOFT, 2 if hot else 1.4))
        p.setBrush(QColor(127, 212, 255, 70 if hot else 22))
        p.drawPolygon(hexagon(26))
        p.setPen(QPen(CYAN_FAINT, 1))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(hexagon(20))
        p.drawPixmap(int(c.x() - 10), int(c.y() - 10), 20, 20, hpix(self.icon_name, "#dff3ff", 20))
        p.setFont(hud_font(10, QFont.DemiBold, 1.6))
        p.setPen(TEXT if hot else DIM)
        p.drawText(QRectF(0, 62, self.width(), 18), Qt.AlignCenter, self.text_)


class HudBadges(QWidget):
    navigate = Signal(str)

    BADGES = [("computer", "SYSTEM", "my_computer"), ("cleaner", "CLEAN", "disk_cleaner"),
              ("pie_chart", "STORAGE", "disk_analyzer"), ("network_monitor", "NETWORK", "network_monitor"),
              ("notes", "TASKS", "notes_tasks"), ("history", "LOG", "operation_history")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background:transparent;")
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(4)
        lo.addStretch(1)
        for icon, text, mod in self.BADGES:
            b = HexBadge(icon, text)
            b.clicked.connect(lambda _=False, m=mod: self.navigate.emit(m))
            lo.addWidget(b)
        lo.addStretch(1)


# ---------------------------------------------------------------------------
#  Visual feed (wallpaper)
# ---------------------------------------------------------------------------

class HudFeatured(QWidget):
    prev = Signal()
    next = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.pm = None
        self.caption = ""
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click the left / right half for the previous / next wallpaper")

    def set_image(self, img: QImage):
        if img is not None and not img.isNull():
            self.pm = QPixmap.fromImage(img.scaledToWidth(720, Qt.SmoothTransformation))
            self.update()

    def set_caption(self, text):
        self.caption = text
        self.update()

    def mousePressEvent(self, event):
        (self.prev if event.position().x() < self.width() / 2 else self.next).emit()

    def paintEvent(self, event):
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        paint_frame(p, r, "Visual feed")
        img = r.adjusted(12, 34, -12, -34)
        clip = chamfer_path(img, 8)
        p.save()
        p.setClipPath(clip)
        if self.pm is not None:
            iw, ih = int(img.width()), int(img.height())
            src = self.pm.scaled(iw, ih, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(int(img.left()), int(img.top()), src,
                         (src.width() - iw) // 2, (src.height() - ih) // 2, iw, ih)
        else:
            p.fillRect(img, QColor(10, 24, 44))
        for y in range(int(img.top()), int(img.bottom()), 3):        # scanlines
            p.fillRect(QRectF(img.left(), y, img.width(), 1), QColor(0, 0, 0, 45))
        g = QLinearGradient(0, img.top(), 0, img.bottom())
        g.setColorAt(0, QColor(127, 212, 255, 25))
        g.setColorAt(1, QColor(0, 0, 0, 60))
        p.fillRect(img, g)
        p.restore()
        p.setPen(QPen(CYAN_SOFT, 1))
        p.drawPath(clip)
        # targeting brackets
        p.setPen(QPen(CYAN, 2))
        cx, cy, s = img.center().x(), img.center().y(), 14
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            x, y = cx + dx * 26, cy + dy * 18
            p.drawLine(QPointF(x, y), QPointF(x - dx * s * 0.6, y))
            p.drawLine(QPointF(x, y), QPointF(x, y - dy * s * 0.6))
        p.setFont(hud_font(11, QFont.DemiBold, 1.5))
        p.setPen(CYAN)
        p.drawText(QRectF(r.left() + 14, r.bottom() - 30, 24, 24), Qt.AlignCenter, "‹")
        p.drawText(QRectF(r.right() - 38, r.bottom() - 30, 24, 24), Qt.AlignCenter, "›")
        p.setPen(TEXT)
        cap = p.fontMetrics().elidedText(self.caption.upper(), Qt.ElideRight, int(r.width() - 84))
        p.drawText(QRectF(r.left() + 40, r.bottom() - 30, r.width() - 80, 24), Qt.AlignCenter, cap)


# ---------------------------------------------------------------------------
#  Mission log
# ---------------------------------------------------------------------------

class HudFeed(QWidget):
    navigate = Signal(str)
    PAGE = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        from app.database import Database
        self.db = Database.get_instance()
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._ops, self._page = [], 0
        self.setMouseTracking(True)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        try:
            self._ops = self.db.get_operations(limit=400)
        except Exception:
            self._ops = []
        self._page = min(self._page, max(0, (len(self._ops) - 1) // self.PAGE))
        self.update()

    def _pages(self):
        return max(1, math.ceil(len(self._ops) / self.PAGE))

    def mousePressEvent(self, event):
        x, y = event.position().x(), event.position().y()
        if y > self.height() - 34:
            if x < 60:
                self._page = (self._page - 1) % self._pages()
            elif x > self.width() - 60:
                self._page = (self._page + 1) % self._pages()
            else:
                self.navigate.emit("operation_history")
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        paint_frame(p, r, "Mission log")
        chunk = self._ops[self._page * self.PAGE:(self._page + 1) * self.PAGE]
        y = r.top() + 38
        row_h = (r.height() - 38 - 40) / self.PAGE
        if not chunk:
            p.setFont(hud_font(12))
            p.setPen(DIM)
            p.drawText(r.adjusted(16, 40, -16, -40), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                       "NO OPERATIONS LOGGED YET.\nRun Disk Cleaner or Folder Organizer — "
                       "every action is recorded here.")
        for op in chunk:
            ts = str(op.get("timestamp", ""))
            ok = str(op.get("result", "")).lower().startswith(("success", "ok", "done", "complete"))
            p.setPen(Qt.NoPen)
            p.setBrush(GREEN if ok else AMBER)
            p.drawEllipse(QPointF(r.left() + 20, y + 9), 3, 3)
            p.setFont(hud_font(10, QFont.DemiBold, 1))
            p.setPen(CYAN)
            p.drawText(QRectF(r.left() + 30, y, 110, 18), Qt.AlignLeft | Qt.AlignVCenter,
                       ts[5:16].replace("-", "/"))
            p.setPen(DIM)
            p.drawText(QRectF(r.left() + 120, y, r.width() - 136, 18), Qt.AlignLeft | Qt.AlignVCenter,
                       str(op.get("operation_type", "")).upper())
            p.setFont(hud_font(12))
            p.setPen(TEXT)
            act = (op.get("action") or "").strip()
            act = p.fontMetrics().elidedText(act, Qt.ElideRight, int(r.width() - 46))
            p.drawText(QRectF(r.left() + 30, y + 17, r.width() - 46, 18), Qt.AlignLeft | Qt.AlignVCenter, act)
            y += row_h
        p.setPen(QPen(CYAN_FAINT, 1))
        p.drawLine(QPointF(r.left() + 16, r.bottom() - 36), QPointF(r.right() - 16, r.bottom() - 36))
        p.setFont(hud_font(12, QFont.DemiBold, 1.5))
        p.setPen(CYAN)
        p.drawText(QRectF(r.left() + 16, r.bottom() - 34, 40, 30), Qt.AlignCenter, "‹")
        p.drawText(QRectF(r.right() - 56, r.bottom() - 34, 40, 30), Qt.AlignCenter, "›")
        p.setPen(TEXT)
        p.drawText(QRectF(r.left(), r.bottom() - 34, r.width(), 30), Qt.AlignCenter,
                   f"{self._page + 1} / {self._pages()}   ·   FULL LOG ↗")

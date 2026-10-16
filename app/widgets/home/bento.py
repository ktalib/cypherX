"""
Bento tiles — the widgets that belong to the Midnight and Daylight skins.

Midnight (night-time control centre): watch face, quick toggles, live network
graph, battery. Daylight (planning the day): agenda, device storage, sun arc,
time-left bars. Everything shows real data from this PC.

Colours are written in the glass palette like every other card; the skin engine
translates them (painted parts go through skin_color).
"""
import ctypes
import math
import os
import time
from collections import deque
from datetime import datetime, date, timedelta

import psutil
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, QSize, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QBrush, QPainterPath, QLinearGradient
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QSizePolicy, QFrame
)

from app.widgets.home.common import (
    GlassCard, label, card_header, pill_button, hpix, hicon,
    TEXT, TEXT_SOFT, MUTED, DIM, ACCENT, WARM, DANGER
)
from app.widgets.home.skins import skin_color


def fmt_bytes(n: float, digits=1) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.{digits}f} {unit}"
        n /= 1024.0


def fmt_rate(bps: float) -> str:
    return fmt_bytes(bps) + "/s"


def fmt_span(seconds: float) -> str:
    m = int(seconds // 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _header_row(text, icon, right=None):
    row = QHBoxLayout()
    row.setSpacing(6)
    ic, title = card_header(text, icon)
    row.addWidget(ic)
    row.addWidget(title)
    row.addStretch(1)
    if right is not None:
        row.addWidget(right)
    return row


# ---------------------------------------------------------------------------
#  Watch face (Midnight)
# ---------------------------------------------------------------------------

class WatchFace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(120, 120)
        t = QTimer(self)
        t.timeout.connect(self.update)
        t.start(1000)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = min(self.width(), self.height()) / 2.0 - 3
        c = QPointF(self.width() / 2.0, self.height() / 2.0)
        ink = skin_color(self, QColor(248, 250, 252))
        soft = skin_color(self, QColor(148, 163, 184))
        red = skin_color(self, QColor(248, 113, 113))

        p.setPen(Qt.NoPen)
        p.setBrush(skin_color(self, QColor(8, 9, 12)))
        p.drawEllipse(c, r, r)

        for i in range(60):
            a = math.radians(i * 6)
            major = i % 5 == 0
            r1 = r * (0.86 if major else 0.91)
            p.setPen(QPen(ink if major else soft, 2.2 if major else 1.0, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(c.x() + r1 * math.sin(a), c.y() - r1 * math.cos(a)),
                       QPointF(c.x() + r * 0.95 * math.sin(a), c.y() - r * 0.95 * math.cos(a)))

        f = QFont(self.font())
        f.setPixelSize(max(9, int(r * 0.19)))
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(ink)
        for h in range(1, 13):
            a = math.radians(h * 30)
            pt = QPointF(c.x() + r * 0.70 * math.sin(a), c.y() - r * 0.70 * math.cos(a))
            p.drawText(QRectF(pt.x() - 14, pt.y() - 10, 28, 20), Qt.AlignCenter, str(h))

        now = datetime.now()
        # date complication under 12
        f.setPixelSize(max(7, int(r * 0.11)))
        f.setWeight(QFont.Bold)
        p.setFont(f)
        p.setPen(red)
        p.drawText(QRectF(c.x() - 30, c.y() - r * 0.44, 60, r * 0.13), Qt.AlignCenter,
                   now.strftime("%a").upper())
        f.setPixelSize(max(9, int(r * 0.17)))
        p.setFont(f)
        p.setPen(ink)
        p.drawText(QRectF(c.x() - 30, c.y() - r * 0.33, 60, r * 0.2), Qt.AlignCenter, str(now.day))

        # seconds sub-dial under the centre
        sc = QPointF(c.x(), c.y() + r * 0.38)
        sr = r * 0.16
        p.setPen(QPen(skin_color(self, QColor(255, 255, 255, 40)), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(sc, sr, sr)
        p.setPen(QPen(red, 2.2, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(sc.x() - sr, sc.y() - sr, sr * 2, sr * 2), 90 * 16,
                  -int(360 * 16 * now.second / 60))

        def hand(deg, length, width, color):
            a = math.radians(deg)
            p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(c.x() - r * 0.08 * math.sin(a), c.y() + r * 0.08 * math.cos(a)),
                       QPointF(c.x() + r * length * math.sin(a), c.y() - r * length * math.cos(a)))

        hr, mn, s = now.hour % 12, now.minute, now.second
        hand((hr + mn / 60) * 30, 0.48, max(3.0, r * 0.055), ink)
        hand((mn + s / 60) * 6, 0.74, max(2.2, r * 0.04), ink)
        hand(s * 6, 0.82, 1.2, QColor(249, 115, 22))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(249, 115, 22))
        p.drawEllipse(c, 3.2, 3.2)


class WatchCard(GlassCard):
    def __init__(self, parent=None):
        super().__init__("WatchCard", parent=parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(10, 10, 10, 10)
        lo.addWidget(WatchFace())


# ---------------------------------------------------------------------------
#  Quick toggles (Midnight + Daylight)
# ---------------------------------------------------------------------------

def _wifi_up() -> bool:
    try:
        for name, st in psutil.net_if_stats().items():
            n = name.lower()
            if st.isup and ("wi-fi" in n or "wifi" in n or "wlan" in n or "wireless" in n):
                return True
    except Exception:
        pass
    return False


def _bluetooth_on() -> bool:
    try:
        return psutil.win_service_get("bthserv").status() == "running"
    except Exception:
        return False


class ToggleCard(GlassCard):
    """Wi-Fi / Bluetooth / theme / lock — round buttons like a phone control centre."""
    theme_toggle = Signal()

    def __init__(self, parent=None):
        super().__init__("ToggleCard", parent=parent)
        self.is_light = False
        lo = QGridLayout(self)
        lo.setContentsMargins(14, 14, 14, 14)
        lo.setHorizontalSpacing(8)
        lo.setVerticalSpacing(4)
        self._btns = {}
        spec = [("wifi", "wifi", "Wi-Fi", "ms-settings:network-wifi"),
                ("bt", "bluetooth", "Bluetooth", "ms-settings:bluetooth"),
                ("theme", "moon", "Dark mode", None),
                ("lock", "lock", "Lock PC", None)]
        for i, (key, icon, text, uri) in enumerate(spec):
            b = QPushButton()
            b.setFixedSize(54, 54)
            b.setIconSize(QSize(22, 22))
            b.setCursor(Qt.PointingHandCursor)
            cap = label(text, MUTED, 10, 600)
            cap.setAlignment(Qt.AlignCenter)
            r, col = divmod(i, 2)
            lo.addWidget(b, r * 2, col, Qt.AlignHCenter | Qt.AlignBottom)
            lo.addWidget(cap, r * 2 + 1, col, Qt.AlignHCenter | Qt.AlignTop)
            self._btns[key] = (b, icon)
            if uri:
                b.clicked.connect(lambda _=False, u=uri: os.startfile(u))
        self._btns["theme"][0].clicked.connect(self.theme_toggle.emit)
        self._btns["lock"][0].clicked.connect(lambda: ctypes.windll.user32.LockWorkStation())
        self._btns["theme"][0].setToolTip("Switch between the Midnight and Daylight skins")
        self._btns["lock"][0].setToolTip("Lock this PC (Win + L)")
        t = QTimer(self)
        t.timeout.connect(self.refresh)
        t.start(5000)
        self.refresh()

    def set_light(self, light: bool):
        self.is_light = light
        self.refresh()

    def refresh(self):
        wifi, bt = _wifi_up(), _bluetooth_on()
        self._btns["wifi"][0].setToolTip("Wi-Fi connected — open Wi-Fi settings" if wifi
                                         else "Wi-Fi off / not connected — open Wi-Fi settings")
        self._btns["bt"][0].setToolTip("Bluetooth service running — open settings" if bt
                                       else "Bluetooth off — open settings")
        states = {"wifi": wifi, "bt": bt, "theme": not self.is_light, "lock": False}
        for key, (b, icon) in self._btns.items():
            on = states[key]
            if key == "theme":
                icon = "moon" if not self.is_light else "sun"
            b.setIcon(hicon(icon, "#ffffff", 22))
            bg = ACCENT if on else "rgba(255,255,255,0.10)"
            hover = "#7dd3fc" if on else "rgba(255,255,255,0.18)"
            b.setStyleSheet(f"QPushButton{{background:{bg};border:none;border-radius:27px;}}"
                            f"QPushButton:hover{{background:{hover};}}")


# ---------------------------------------------------------------------------
#  Live network graph (Midnight)
# ---------------------------------------------------------------------------

class Sparkline(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.down = deque([0.0] * 60, maxlen=60)
        self.up = deque([0.0] * 60, maxlen=60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(50)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        peak = max(max(self.down), max(self.up), 1024.0)
        p.setPen(QPen(skin_color(self, QColor(255, 255, 255, 18)), 1, Qt.DashLine))
        for frac in (0.25, 0.5, 0.75):
            p.drawLine(QPointF(0, h * frac), QPointF(w, h * frac))

        def series(values, color, fill):
            path = QPainterPath()
            n = len(values)
            for i, v in enumerate(values):
                pt = QPointF(w * i / (n - 1), h - 2 - (h - 6) * v / peak)
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            if fill:
                area = QPainterPath(path)
                area.lineTo(w, h)
                area.lineTo(0, h)
                g = QLinearGradient(0, 0, 0, h)
                c1 = QColor(color)
                c1.setAlpha(90)
                c2 = QColor(color)
                c2.setAlpha(0)
                g.setColorAt(0, c1)
                g.setColorAt(1, c2)
                p.fillPath(area, g)
            p.setPen(QPen(color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)

        series(self.up, skin_color(self, QColor(52, 211, 153)), False)
        series(self.down, skin_color(self, QColor(56, 189, 248)), True)


class NetSpeedCard(GlassCard):
    def __init__(self, parent=None):
        super().__init__("NetCard", parent=parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 12, 16, 12)
        lo.setSpacing(6)
        self._peak = label("", DIM, 10, 600)
        lo.addLayout(_header_row("Network", "network_monitor", self._peak))
        row = QHBoxLayout()
        row.setSpacing(18)
        self._down = label("—", TEXT, 26, 300)
        self._up = label("—", TEXT, 26, 300)
        for arrow, color, val, cap in (("arrow_down", ACCENT, self._down, "DOWNLOAD"),
                                       ("arrow_up", "#34d399", self._up, "UPLOAD")):
            col = QVBoxLayout()
            col.setSpacing(0)
            top = QHBoxLayout()
            top.setSpacing(4)
            ic = QLabel()
            ic.setPixmap(hpix(arrow, color, 12))
            ic.setStyleSheet("background:transparent;")
            top.addWidget(ic)
            top.addWidget(label(cap, MUTED, 9, 700, 1.0))
            top.addStretch(1)
            col.addLayout(top)
            col.addWidget(val)
            row.addLayout(col)
        row.addStretch(1)
        self._total = label("", DIM, 10, 600)
        self._total.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        row.addWidget(self._total)
        lo.addLayout(row)
        self.graph = Sparkline()
        lo.addWidget(self.graph, 1)

        self._last = psutil.net_io_counters()
        self._t = time.monotonic()
        t = QTimer(self)
        t.timeout.connect(self._sample)
        t.start(1000)

    def _sample(self):
        now, io = time.monotonic(), psutil.net_io_counters()
        dt = max(0.2, now - self._t)
        d = max(0.0, (io.bytes_recv - self._last.bytes_recv) / dt)
        u = max(0.0, (io.bytes_sent - self._last.bytes_sent) / dt)
        self._last, self._t = io, now
        self.graph.down.append(d)
        self.graph.up.append(u)
        self._down.setText(fmt_rate(d))
        self._up.setText(fmt_rate(u))
        self._peak.setText(f"peak {fmt_rate(max(self.graph.down))} · 60 s")
        self._total.setText(f"{fmt_bytes(io.bytes_recv)} in\n{fmt_bytes(io.bytes_sent)} out\nsince boot")
        if self.isVisible():
            self.graph.update()


# ---------------------------------------------------------------------------
#  Battery (Midnight)
# ---------------------------------------------------------------------------

class BatteryGlyph(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pct, self.charging, self.present = 0, False, True
        self.setFixedHeight(46)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width() - 10, self.height() - 4
        body = QRectF(1, 2, w, h)
        p.setPen(QPen(skin_color(self, QColor(255, 255, 255, 110)), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(body, 12, 12)
        p.setPen(Qt.NoPen)
        p.setBrush(skin_color(self, QColor(255, 255, 255, 110)))
        p.drawRoundedRect(QRectF(w + 3, h / 2 - 6, 5, 16), 2, 2)
        if not self.present:
            return
        col = QColor(52, 211, 153) if self.pct > 20 or self.charging else QColor(248, 113, 113)
        fill = QRectF(5, 6, max(0.0, (w - 8) * self.pct / 100), h - 8)
        p.setBrush(skin_color(self, col))
        p.drawRoundedRect(fill, 9, 9)


class BatteryCard(GlassCard):
    def __init__(self, parent=None):
        super().__init__("BatteryCard", parent=parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 12, 16, 14)
        lo.setSpacing(6)
        lo.addLayout(_header_row("Power", "battery"))
        lo.addStretch(1)
        self._pct = label("", TEXT, 34, 300)
        lo.addWidget(self._pct)
        self.glyph = BatteryGlyph()
        lo.addWidget(self.glyph)
        self._state = label("", TEXT_SOFT, 11, 600, elide=True)
        self._up = label("", DIM, 10, 600, elide=True)
        lo.addWidget(self._state)
        lo.addWidget(self._up)
        t = QTimer(self)
        t.timeout.connect(self.refresh)
        t.start(10000)
        self.refresh()

    def refresh(self):
        try:
            b = psutil.sensors_battery()
        except Exception:
            b = None
        up = time.time() - psutil.boot_time()
        self._up.setText(f"Up {fmt_span(up)} since boot")
        if b is None:
            self.glyph.present = False
            self._pct.setText("AC")
            self._state.setText("No battery — running on mains power")
        else:
            self.glyph.present = True
            self.glyph.pct = b.percent
            self.glyph.charging = bool(b.power_plugged)
            self._pct.setText(f"{b.percent:.0f}%")
            if b.power_plugged:
                self._state.setText("Charging" if b.percent < 100 else "Fully charged · plugged in")
            elif b.secsleft not in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED):
                self._state.setText(f"On battery · {fmt_span(b.secsleft)} left")
            else:
                self._state.setText("On battery")
        self.glyph.update()


# ---------------------------------------------------------------------------
#  Device storage (Daylight)
# ---------------------------------------------------------------------------

DRIVE_COLORS = ["#fb923c", "#38bdf8", "#facc15", "#34d399", "#f472b6", "#a78bfa"]


def fixed_drives():
    out = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        out.append((part.mountpoint.rstrip("\\"), u.used, u.total))
    return out


class StorageBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.drives = []
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), 9, 9)
        p.setClipPath(clip)
        p.fillRect(0, 0, w, h, skin_color(self, QColor(255, 255, 255, 20)))
        # free space hatch
        p.setPen(QPen(skin_color(self, QColor(255, 255, 255, 30)), 3))
        for x in range(-h, w + h, 9):
            p.drawLine(QPointF(x, h), QPointF(x + h, 0))
        total = sum(t for _, _, t in self.drives) or 1
        x = 0.0
        for i, (_, used, tot) in enumerate(self.drives):
            seg = w * tot / total
            uw = seg * used / max(1, tot)
            p.fillRect(QRectF(x, 0, max(0.0, uw - 2), h),
                       skin_color(self, QColor(DRIVE_COLORS[i % len(DRIVE_COLORS)])))
            x += seg
            if i < len(self.drives) - 1:
                p.fillRect(QRectF(x - 1.5, 0, 3, h), skin_color(self, QColor(16, 22, 30)))


class StorageCard(GlassCard):
    navigate = Signal(str)

    def __init__(self, parent=None):
        super().__init__("StorageCard", parent=parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Open Disk Analyzer")
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 12, 16, 12)
        lo.setSpacing(6)
        lo.addWidget(label("Device Storage", TEXT_SOFT, 12, 600))
        row = QHBoxLayout()
        row.setSpacing(4)
        self._used = label("", TEXT, 28, 700, -0.5)
        self._total = label("", DIM, 14, 600)
        row.addWidget(self._used)
        row.addWidget(self._total, 0, Qt.AlignBottom)
        row.addStretch(1)
        lo.addLayout(row)
        self.bar = StorageBar()
        lo.addWidget(self.bar)
        self._legend = QGridLayout()
        self._legend.setHorizontalSpacing(10)
        self._legend.setVerticalSpacing(2)
        lo.addLayout(self._legend)
        lo.addStretch(1)
        t = QTimer(self)
        t.timeout.connect(self.refresh)
        t.start(60000)
        self.refresh()

    def mousePressEvent(self, event):
        self.navigate.emit("disk_analyzer")

    def refresh(self):
        drives = fixed_drives()
        self.bar.drives = drives
        used = sum(u for _, u, _ in drives)
        total = sum(t for _, _, t in drives)
        self._used.setText(fmt_bytes(used, 0))
        self._total.setText(f"/ {fmt_bytes(total, 0)}")
        while self._legend.count():
            w = self._legend.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i, (mount, u, t) in enumerate(drives[:6]):
            color = DRIVE_COLORS[i % len(DRIVE_COLORS)]
            lbl = label(f"<span style='color:{color}'>●</span>  {mount}  {fmt_bytes(t - u, 0)} free",
                        MUTED, 10, 600)
            self._legend.addWidget(lbl, i // 2, i % 2)
        self.bar.update()


# ---------------------------------------------------------------------------
#  Agenda (Daylight, 2 columns)
# ---------------------------------------------------------------------------

TASK_COLORS = ["#a78bfa", "#34d399", "#38bdf8", "#fb923c"]


class AgendaCard(GlassCard):
    navigate = Signal(str)

    def __init__(self, parent=None):
        super().__init__("AgendaCard", parent=parent)
        from app.database import Database
        self.db = Database.get_instance()
        lo = QHBoxLayout(self)
        lo.setContentsMargins(18, 14, 18, 14)
        lo.setSpacing(18)

        left = QVBoxLayout()
        left.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(10)
        self._day = label("", DANGER, 52, 300, -1)
        meta = QVBoxLayout()
        meta.setSpacing(0)
        self._dow = label("", TEXT, 16, 700)
        self._sub = label("", MUTED, 11, 600)
        meta.addStretch(1)
        meta.addWidget(self._dow)
        meta.addWidget(self._sub)
        meta.addStretch(1)
        top.addWidget(self._day)
        top.addLayout(meta)
        top.addStretch(1)
        left.addLayout(top)
        left.addSpacing(6)
        self._week = QGridLayout()
        self._week.setHorizontalSpacing(4)
        self._week.setVerticalSpacing(2)
        left.addLayout(self._week)
        left.addStretch(1)
        self._hint = label("", DIM, 10, 600, elide=True)
        left.addWidget(self._hint)
        host = QWidget()
        host.setStyleSheet("background:transparent;")
        host.setLayout(left)
        host.setFixedWidth(220)
        lo.addWidget(host)

        self._list = QVBoxLayout()
        self._list.setSpacing(10)
        right = QVBoxLayout()
        right.setSpacing(6)
        right.addLayout(self._list)
        right.addStretch(1)
        open_btn = pill_button("Open Notes && Tasks", "notes")
        open_btn.clicked.connect(lambda: self.navigate.emit("notes_tasks"))
        right.addWidget(open_btn, 0, Qt.AlignRight)
        lo.addLayout(right, 1)

        t = QTimer(self)
        t.timeout.connect(self.refresh)
        t.start(60000)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        today = date.today()
        try:
            tasks = self.db.get_tasks(include_completed=False)
        except Exception:
            tasks = []
        self._day.setText(str(today.day))
        self._dow.setText(today.strftime("%A"))
        self._sub.setText(f"{today.strftime('%B')} · {len(tasks)} open task{'s' if len(tasks) != 1 else ''}")
        week_left = 6 - today.weekday()
        self._hint.setText(f"Week {today.isocalendar()[1]} · {week_left} day{'s' if week_left != 1 else ''} "
                           f"left this week")

        while self._week.count():
            w = self._week.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i in range(-2, 3):
            d = today + timedelta(days=i)
            num = label(str(d.day), TEXT if i == 0 else TEXT_SOFT, 13, 700 if i == 0 else 500)
            num.setAlignment(Qt.AlignCenter)
            num.setFixedSize(30, 30)
            if i == 0:
                num.setStyleSheet(num.styleSheet() + "border:2px solid #f87171;border-radius:15px;"
                                  "color:#f87171;")
            dl = label(d.strftime("%a")[0], DIM, 10, 600)
            dl.setAlignment(Qt.AlignCenter)
            self._week.addWidget(num, 0, i + 2, Qt.AlignCenter)
            self._week.addWidget(dl, 1, i + 2, Qt.AlignCenter)

        while self._list.count():
            item = self._list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not tasks:
            self._list.addWidget(label("No open tasks — add one from the Tasks widget "
                                       "or Notes & Tasks.", MUTED, 12, 500))
            return
        for i, t in enumerate(tasks[:3]):
            color = TASK_COLORS[i % len(TASK_COLORS)]
            row = QFrame()
            row.setStyleSheet(f"QFrame{{background:transparent;border:none;"
                              f"border-left:3px solid {color};}}")
            rl = QVBoxLayout(row)
            rl.setContentsMargins(10, 0, 0, 0)
            rl.setSpacing(1)
            title = label(t["title"], TEXT, 13, 600)
            title.setWordWrap(True)
            title.setStyleSheet(title.styleSheet() + "border:none;")
            try:
                added = datetime.strptime(t["created_at"], "%Y-%m-%d %H:%M:%S").strftime("%d %b · %H:%M")
            except (ValueError, TypeError):
                added = ""
            meta = label(f"{added}  ·  {t.get('category') or 'General'}  ·  {t.get('priority') or ''}",
                         MUTED, 10, 600)
            meta.setStyleSheet(meta.styleSheet() + "border:none;")
            rl.addWidget(title)
            rl.addWidget(meta)
            self._list.addWidget(row)


# ---------------------------------------------------------------------------
#  Time left (Daylight)
# ---------------------------------------------------------------------------

class ThinBar(QWidget):
    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.value = 0.0
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(0, 0, self.width(), self.height())
        p.setPen(Qt.NoPen)
        p.setBrush(skin_color(self, QColor(255, 255, 255, 26)))
        p.drawRoundedRect(r, 4, 4)
        p.setBrush(skin_color(self, self.color))
        p.drawRoundedRect(QRectF(0, 0, max(8.0, r.width() * self.value), r.height()), 4, 4)


class DayProgressCard(GlassCard):
    def __init__(self, parent=None):
        super().__init__("ProgressCard", parent=parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 12, 16, 12)
        lo.setSpacing(4)
        lo.addLayout(_header_row("Time left", "timer"))
        lo.addStretch(1)
        self._rows = {}
        for key, name, color in (("day", "Today", "#38bdf8"), ("week", "This week", "#a78bfa"),
                                 ("month", "This month", "#fb923c"), ("year", "This year", "#34d399")):
            head = QHBoxLayout()
            head.addWidget(label(name, TEXT_SOFT, 11, 600))
            head.addStretch(1)
            val = label("", TEXT, 11, 700)
            head.addWidget(val)
            bar = ThinBar(color)
            lo.addLayout(head)
            lo.addWidget(bar)
            lo.addSpacing(4)
            self._rows[key] = (val, bar)
        lo.addStretch(1)
        t = QTimer(self)
        t.timeout.connect(self.refresh)
        t.start(30000)
        self.refresh()

    def refresh(self):
        now = datetime.now()
        start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_week = start_day - timedelta(days=now.weekday())
        start_month = start_day.replace(day=1)
        next_month = (start_month + timedelta(days=32)).replace(day=1)
        start_year = start_day.replace(month=1, day=1)
        spans = {"day": (start_day, start_day + timedelta(days=1)),
                 "week": (start_week, start_week + timedelta(days=7)),
                 "month": (start_month, next_month),
                 "year": (start_year, start_year.replace(year=now.year + 1))}
        for key, (a, b) in spans.items():
            frac = (now - a).total_seconds() / (b - a).total_seconds()
            val, bar = self._rows[key]
            val.setText(f"{frac * 100:.0f}% done")
            bar.value = frac
            bar.update()


# ---------------------------------------------------------------------------
#  Sun arc (Daylight) — fed by the weather widget's data
# ---------------------------------------------------------------------------

class SunArc(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.frac = None         # 0..1 between sunrise and sunset, None = night
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(60)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        rx = w / 2 - 14
        ry = min(h - 14, rx * 0.75)
        base = h - 6
        rect = QRectF(w / 2 - rx, base - ry, rx * 2, ry * 2)
        p.setPen(QPen(skin_color(self, QColor(255, 255, 255, 50)), 2, Qt.DashLine))
        p.drawArc(rect, 0, 180 * 16)
        p.setPen(QPen(skin_color(self, QColor(255, 255, 255, 60)), 1))
        p.drawLine(QPointF(4, base), QPointF(w - 4, base))
        if self.frac is None:
            return
        f = min(1.0, max(0.0, self.frac))
        p.setPen(QPen(skin_color(self, QColor(245, 190, 75)), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 180 * 16, -int(180 * 16 * f))
        a = math.pi * (1 - f)
        sun = QPointF(w / 2 + rx * math.cos(a), base - ry * math.sin(a))
        p.setPen(Qt.NoPen)
        glow = QColor(245, 190, 75, 70)
        p.setBrush(glow)
        p.drawEllipse(sun, 13, 13)
        p.setBrush(QColor(245, 190, 75))
        p.drawEllipse(sun, 7, 7)


class SunCard(GlassCard):
    def __init__(self, parent=None):
        super().__init__("SunCard", parent=parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 12, 16, 12)
        lo.setSpacing(4)
        lo.addLayout(_header_row("Daylight", "sun"))
        self._left = label("Waiting for weather…", TEXT, 18, 600)
        lo.addWidget(self._left)
        self.arc = SunArc()
        lo.addWidget(self.arc, 1)
        row = QHBoxLayout()
        self._rise = label("", MUTED, 10, 700)
        self._set = label("", MUTED, 10, 700)
        row.addWidget(self._rise)
        row.addStretch(1)
        row.addWidget(self._set)
        lo.addLayout(row)
        self._times = None
        t = QTimer(self)
        t.timeout.connect(self._update)
        t.start(60000)

    def set_weather(self, data):
        try:
            daily = data["daily"]
            rise = datetime.fromisoformat(daily["sunrise"][0])
            sset = datetime.fromisoformat(daily["sunset"][0])
        except (KeyError, IndexError, TypeError, ValueError):
            return
        self._times = (rise, sset)
        self._update()

    def _update(self):
        if not self._times:
            return
        rise, sset = self._times
        now = datetime.now()
        self._rise.setText(f"↑ {rise:%H:%M}")
        self._set.setText(f"{sset:%H:%M} ↓")
        if rise <= now <= sset:
            self.arc.frac = (now - rise).total_seconds() / max(1, (sset - rise).total_seconds())
            self._left.setText(f"{fmt_span((sset - now).total_seconds())} of light left")
        else:
            self.arc.frac = None
            nxt = rise if now < rise else rise + timedelta(days=1)
            self._left.setText(f"Sunrise in {fmt_span((nxt - now).total_seconds())}")
        self.arc.update()

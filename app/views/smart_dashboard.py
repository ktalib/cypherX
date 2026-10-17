"""
Home Dashboard — one glance at the whole smart home.

  • hero: greeting, clock, a one-line status of the home and quick actions
  • tiles: live load against the inverter, battery, prepaid meter, energy cost
  • appliances: tap a tile to switch it (same model as the 3D Smart Home page)
  • load by room, grid supply over the last 24 h, meter units over two weeks
  • security: armed state, live cameras, motion today and the latest snapshot

Nothing is stored here: the page reads the Smart Home model / energy log and the
CCTV store through those pages, so a switch flipped here shows up there too.
"""
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal, QSize
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPainterPath, QLinearGradient, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QSizePolicy, QToolTip
)

from app.icons import get_icon, get_pixmap

ACCENT = "#38bdf8"
GOOD = "#10b981"
WARN = "#f59e0b"
CRIT = "#f43f5e"
TEXT = "#f8fafc"
SOFT = "#cbd5e1"
MUTED = "#94a3b8"
DIM = "#64748b"
TRACK = QColor(255, 255, 255, 22)

REFRESH_MS = 2000

DEVICE_ICONS = {"tv_wall": "tv", "fan": "fan", "ceiling_light": "lightbulb", "fridge": "fridge"}


def _lbl(text="", color=TEXT, size=12, weight=500, spacing=0.0):
    l = QLabel(text)
    l.setStyleSheet(f"color:{color};font-size:{size}px;font-weight:{weight};"
                    f"letter-spacing:{spacing}px;background:transparent;border:none;")
    return l


def _fmt_h(h):
    if h is None:
        return "—"
    if h >= 48:
        return f"{h / 24:.1f} days"
    m = int(round(h * 60))
    return f"{m // 60}h {m % 60:02d}m"


def _money(cur, v):
    return f"{cur}{v:,.0f}"


def _card(title, icon):
    box = QFrame()
    box.setObjectName("panel")
    lo = QVBoxLayout(box)
    lo.setContentsMargins(16, 14, 16, 14)
    lo.setSpacing(10)
    head = QHBoxLayout()
    head.setSpacing(7)
    ic = QLabel()
    ic.setPixmap(get_pixmap(icon, MUTED, 13))
    ic.setStyleSheet("background:transparent;border:none;")
    head.addWidget(ic)
    head.addWidget(_lbl(title.upper(), MUTED, 10, 700, 1.2))
    head.addStretch()
    lo.addLayout(head)
    return box, lo, head


def _chip_style(color):
    c = QColor(color)
    return (f"QLabel{{color:{TEXT};background:rgba({c.red()},{c.green()},{c.blue()},0.16);"
            f"border:1px solid rgba({c.red()},{c.green()},{c.blue()},0.45);border-radius:11px;"
            f"padding:3px 10px;font-size:11px;font-weight:700;}}")


def _action(text, icon, slot, primary=False):
    b = QPushButton(f" {text}")
    b.setIcon(get_icon(icon, "#04131d" if primary else "#e2e8f0", 13))
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(30)
    if primary:
        b.setStyleSheet(f"QPushButton{{background:{ACCENT};color:#04131d;border:none;border-radius:15px;"
                        f"padding:4px 14px;font-weight:700;}}QPushButton:hover{{background:#7dd3fc;}}")
    else:
        b.setStyleSheet("QPushButton{background:rgba(255,255,255,0.07);color:#e2e8f0;"
                        "border:1px solid rgba(255,255,255,0.14);border-radius:15px;padding:4px 14px;"
                        "font-weight:600;}QPushButton:hover{background:rgba(255,255,255,0.14);}")
    b.clicked.connect(slot)
    return b


# --------------------------------------------------------------- painted parts --

class Ring(QWidget):
    """Progress ring with the value in the middle."""

    def __init__(self, size=92, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.frac, self.text, self.sub, self.color = 0.0, "", "", ACCENT

    def set(self, frac, text, sub="", color=ACCENT):
        self.frac, self.text, self.sub, self.color = max(0.0, min(1.0, frac)), text, sub, color
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = 8
        r = QRectF(w / 2 + 1, w / 2 + 1, self.width() - w - 2, self.height() - w - 2)
        p.setPen(QPen(TRACK, w, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r, 0, 360 * 16)
        if self.frac > 0:
            p.setPen(QPen(QColor(self.color), w, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(r, 90 * 16, -int(self.frac * 360 * 16))
        f = QFont()
        f.setPixelSize(17)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(TEXT))
        inner = self.rect().adjusted(0, -8 if self.sub else 0, 0, 0)
        p.drawText(inner, Qt.AlignCenter, self.text)
        if self.sub:
            f.setPixelSize(10)
            f.setWeight(QFont.Medium)
            p.setFont(f)
            p.setPen(QColor(MUTED))
            p.drawText(self.rect().adjusted(0, 22, 0, 0), Qt.AlignCenter, self.sub)
        p.end()


class RoomBars(QWidget):
    """Horizontal bars: load per room (one hue, magnitude)."""

    room_clicked = Signal(str)
    ROW = 34

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []          # (room_id, name, watts)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def set_rows(self, rows):
        self.rows = rows
        self.setMinimumHeight(max(1, len(rows)) * self.ROW)
        self.update()

    def _row_at(self, y):
        i = int(y // self.ROW)
        return self.rows[i] if 0 <= i < len(self.rows) else None

    def mouseMoveEvent(self, e):
        row = self._row_at(e.position().y())
        if row:
            total = sum(r[2] for r in self.rows) or 1
            QToolTip.showText(e.globalPosition().toPoint(),
                              f"{row[1]}: {row[2]:,.0f} W  ({row[2] / total * 100:.0f}% of the load)\n"
                              "Click to fly the 3D map there", self)

    def mousePressEvent(self, e):
        row = self._row_at(e.position().y())
        if row:
            self.room_clicked.emit(row[0])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont()
        f.setPixelSize(12)
        top = max([r[2] for r in self.rows] + [1])
        name_w, val_w = 96, 64
        for i, (_, name, watts) in enumerate(self.rows):
            y = i * self.ROW
            f.setWeight(QFont.Medium)
            p.setFont(f)
            p.setPen(QColor(SOFT))
            p.drawText(QRectF(0, y, name_w, self.ROW), Qt.AlignVCenter | Qt.AlignLeft, name)
            bar = QRectF(name_w, y + self.ROW / 2 - 5, self.width() - name_w - val_w, 10)
            p.setPen(Qt.NoPen)
            p.setBrush(TRACK)
            p.drawRoundedRect(bar, 4, 4)
            if watts > 0:
                fill = QRectF(bar.x(), bar.y(), max(8.0, bar.width() * watts / top), bar.height())
                p.setBrush(QColor(ACCENT))
                p.drawRoundedRect(fill, 4, 4)
            f.setWeight(QFont.Bold)
            p.setFont(f)
            p.setPen(QColor(TEXT if watts else DIM))
            p.drawText(QRectF(self.width() - val_w, y, val_w, self.ROW), Qt.AlignVCenter | Qt.AlignRight,
                       f"{watts:,.0f} W")
        p.end()


class GridStrip(QWidget):
    """The last 24 hours of grid supply: on (green) vs power cut (red)."""

    SPAN = 24 * 3600

    def __init__(self, parent=None):
        super().__init__(parent)
        self.outages, self.watching, self.now = [], False, time.time()
        self.setMinimumHeight(58)
        self.setMouseTracking(True)

    def set_data(self, outages, watching):
        self.outages, self.watching, self.now = outages, watching, time.time()
        self.update()

    def _bar(self):
        return QRectF(0, 6, self.width(), 22)

    def _segments(self):
        start = self.now - self.SPAN
        segs = []
        for o in self.outages:
            s, e = o["start"], o.get("end") or self.now
            if e > start:
                segs.append((max(s, start), e, o))
        return segs

    def mouseMoveEvent(self, e):
        bar = self._bar()
        x = e.position().x()
        t = self.now - self.SPAN + (x - bar.x()) / max(1, bar.width()) * self.SPAN
        for s, end, o in self._segments():
            if s <= t <= end:
                done = o.get("end")
                QToolTip.showText(e.globalPosition().toPoint(),
                                  f"Power cut  {datetime.fromtimestamp(o['start']):%a %H:%M} – "
                                  f"{datetime.fromtimestamp(done):%H:%M}" if done else
                                  f"Power cut since {datetime.fromtimestamp(o['start']):%a %H:%M} (still off)",
                                  self)
                return
        QToolTip.showText(e.globalPosition().toPoint(),
                          f"{datetime.fromtimestamp(t):%a %H:%M}  —  "
                          + ("grid on" if self.watching else "not watching"), self)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bar = self._bar()
        p.setPen(Qt.NoPen)
        base = QColor(GOOD)
        base.setAlpha(150)
        p.setBrush(base if self.watching else TRACK)
        p.drawRoundedRect(bar, 6, 6)
        start = self.now - self.SPAN
        p.setBrush(QColor(CRIT))
        for s, e, _ in self._segments():
            x0 = bar.x() + (s - start) / self.SPAN * bar.width()
            x1 = bar.x() + (e - start) / self.SPAN * bar.width()
            seg = QRectF(x0, bar.y(), max(3.0, x1 - x0), bar.height())
            p.drawRoundedRect(seg.adjusted(1, 0, -1, 0) if seg.width() > 4 else seg, 4, 4)
        # hour ticks every 6 h, right edge = now
        f = QFont()
        f.setPixelSize(10)
        p.setFont(f)
        for k in range(0, 5):
            t = start + k * 6 * 3600
            x = bar.x() + k / 4 * bar.width()
            p.setPen(QPen(QColor(255, 255, 255, 40), 1))
            p.drawLine(QPointF(x, bar.bottom() + 3), QPointF(x, bar.bottom() + 7))
            p.setPen(QColor(DIM))
            text = "now" if k == 4 else f"{datetime.fromtimestamp(t):%H:%M}"
            align = Qt.AlignLeft if k == 0 else Qt.AlignRight if k == 4 else Qt.AlignHCenter
            rx = x if k == 0 else x - 60 if k == 4 else x - 30
            p.drawText(QRectF(rx, bar.bottom() + 8, 60, 16), align | Qt.AlignTop, text)
        p.end()


class Sparkline(QWidget):
    """Meter units left over time (one series), hover for each reading."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = []
        self.hover = None
        self.setMinimumHeight(120)
        self.setMouseTracking(True)

    def set_points(self, points):
        self.points = sorted(points)
        self.update()

    def _geom(self):
        return QRectF(36, 8, self.width() - 44, self.height() - 30)

    def _xy(self, area, t, v, t0, t1, lo, hi):
        x = area.x() + (t - t0) / max(1.0, t1 - t0) * area.width()
        y = area.bottom() - (v - lo) / max(1e-9, hi - lo) * area.height()
        return QPointF(x, y)

    def _range(self):
        ts = [t for t, _ in self.points]
        vs = [v for _, v in self.points]
        lo, hi = 0.0, max(vs) * 1.15 or 1.0
        return min(ts), max(ts), lo, hi

    def mouseMoveEvent(self, e):
        if len(self.points) < 2:
            return
        area = self._geom()
        t0, t1, lo, hi = self._range()
        x = e.position().x()
        best = min(range(len(self.points)),
                   key=lambda i: abs(self._xy(area, *self.points[i], t0, t1, lo, hi).x() - x))
        if best != self.hover:
            self.hover = best
            self.update()
        t, v = self.points[best]
        QToolTip.showText(e.globalPosition().toPoint(), f"{datetime.fromtimestamp(t):%a %d %b %H:%M}\n"
                                                        f"{v:,.1f} kWh left", self)

    def leaveEvent(self, _):
        self.hover = None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont()
        f.setPixelSize(11)
        p.setFont(f)
        if len(self.points) < 2:
            p.setPen(QColor(DIM))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Log two meter readings to see the trend.\nUse “Meter reading” above.")
            p.end()
            return
        area = self._geom()
        t0, t1, lo, hi = self._range()
        # recessive grid: baseline + half + top label
        f.setPixelSize(10)
        p.setFont(f)
        for frac in (0.0, 0.5, 1.0):
            y = area.bottom() - frac * area.height()
            p.setPen(QPen(QColor(255, 255, 255, 18 if frac else 40), 1))
            p.drawLine(QPointF(area.x(), y), QPointF(area.right(), y))
            p.setPen(QColor(DIM))
            p.drawText(QRectF(0, y - 8, area.x() - 6, 16), Qt.AlignRight | Qt.AlignVCenter,
                       f"{lo + frac * (hi - lo):.0f}")
        pts = [self._xy(area, t, v, t0, t1, lo, hi) for t, v in self.points]
        line = QPainterPath(pts[0])
        for q in pts[1:]:
            line.lineTo(q)
        fill = QPainterPath(line)
        fill.lineTo(pts[-1].x(), area.bottom())
        fill.lineTo(pts[0].x(), area.bottom())
        fill.closeSubpath()
        g = QLinearGradient(0, area.top(), 0, area.bottom())
        c = QColor(ACCENT)
        c.setAlpha(70)
        g.setColorAt(0, c)
        c.setAlpha(0)
        g.setColorAt(1, c)
        p.fillPath(fill, g)
        p.setPen(QPen(QColor(ACCENT), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(line)
        surface = QColor("#121a22")
        for i, q in enumerate(pts):
            big = i == self.hover or i == len(pts) - 1
            p.setPen(QPen(surface, 2))
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(q, 5 if big else 4, 5 if big else 4)
        if self.hover is not None:
            q = pts[self.hover]
            p.setPen(QPen(QColor(255, 255, 255, 60), 1, Qt.DashLine))
            p.drawLine(QPointF(q.x(), area.top()), QPointF(q.x(), area.bottom()))
        # first / last dates under the plot, last value labelled
        p.setPen(QColor(DIM))
        p.drawText(QRectF(area.x(), area.bottom() + 6, 120, 16), Qt.AlignLeft,
                   f"{datetime.fromtimestamp(t0):%d %b}")
        p.drawText(QRectF(area.right() - 120, area.bottom() + 6, 120, 16), Qt.AlignRight,
                   f"{datetime.fromtimestamp(t1):%d %b %H:%M}")
        f.setPixelSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(TEXT))
        last = pts[-1]
        p.drawText(QRectF(last.x() - 90, last.y() - 24, 84, 16), Qt.AlignRight,
                   f"{self.points[-1][1]:,.1f} kWh")
        p.end()


class ApplianceTile(QFrame):
    """Tap to switch. Glows when the appliance is on."""

    clicked = Signal(str)

    def __init__(self, item_id, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.setObjectName(f"app_{item_id}")
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumHeight(86)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 10, 12, 10)
        lo.setSpacing(4)
        top = QHBoxLayout()
        self.icon = QLabel()
        self.icon.setFixedSize(30, 30)
        self.icon.setAlignment(Qt.AlignCenter)
        self.state = _lbl("", MUTED, 10, 800, 0.8)
        top.addWidget(self.icon)
        top.addStretch()
        top.addWidget(self.state)
        lo.addLayout(top)
        self.name = _lbl("", TEXT, 12, 700)
        self.sub = _lbl("", MUTED, 10, 500)
        lo.addWidget(self.name)
        lo.addWidget(self.sub)
        self._sig = None

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.item_id)

    def set_item(self, it, room_name):
        dev = it["device"]
        sig = (it["name"], room_name, dev["watts"], dev["on"])
        if sig == self._sig:
            return
        self._sig = sig
        on = dev["on"]
        icon = DEVICE_ICONS.get(it.get("kind"), "plug")
        self.icon.setPixmap(get_pixmap(icon, "#04140d" if on else SOFT, 16))
        self.icon.setStyleSheet(f"background:{GOOD if on else 'rgba(255,255,255,0.08)'};border-radius:15px;")
        self.state.setText("ON" if on else "OFF")
        self.state.setStyleSheet(f"color:{GOOD if on else DIM};font-size:10px;font-weight:800;"
                                 "letter-spacing:0.8px;background:transparent;border:none;")
        self.name.setText(it["name"])
        self.sub.setText(f"{room_name}  ·  {dev['watts']:g} W")
        n = self.objectName()
        if on:
            self.setStyleSheet(f"QFrame#{n}{{background:rgba(16,185,129,0.13);border:1px solid "
                               f"rgba(16,185,129,0.55);border-radius:14px;}}"
                               f"QFrame#{n}:hover{{background:rgba(16,185,129,0.20);}}")
        else:
            self.setStyleSheet(f"QFrame#{n}{{background:rgba(255,255,255,0.04);border:1px solid "
                               f"rgba(255,255,255,0.10);border-radius:14px;}}"
                               f"QFrame#{n}:hover{{background:rgba(255,255,255,0.09);"
                               f"border:1px solid rgba(255,255,255,0.20);}}")
        self.setToolTip(f"Switch {it['name']} {'off' if on else 'on'}")


class StatTile(QFrame):
    """KPI tile: ring on the left, headline + detail on the right."""

    def __init__(self, title, icon, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 14, 16, 14)
        lo.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(7)
        ic = QLabel()
        ic.setPixmap(get_pixmap(icon, MUTED, 13))
        ic.setStyleSheet("background:transparent;border:none;")
        head.addWidget(ic)
        head.addWidget(_lbl(title.upper(), MUTED, 10, 700, 1.2))
        head.addStretch()
        self.chip = QLabel()
        self.chip.hide()
        head.addWidget(self.chip)
        lo.addLayout(head)
        body = QHBoxLayout()
        body.setSpacing(14)
        self.ring = Ring(84)
        body.addWidget(self.ring)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addStretch()
        self.value = _lbl("", TEXT, 24, 300)
        self.detail = _lbl("", SOFT, 11, 600)
        self.detail.setWordWrap(True)
        self.sub = _lbl("", MUTED, 10, 500)
        self.sub.setWordWrap(True)
        col.addWidget(self.value)
        col.addWidget(self.detail)
        col.addWidget(self.sub)
        col.addStretch()
        body.addLayout(col, 1)
        lo.addLayout(body)

    def set_chip(self, text, color):
        if not text:
            self.chip.hide()
            return
        self.chip.setText(text)
        self.chip.setStyleSheet(_chip_style(color))
        self.chip.show()


# -------------------------------------------------------------------- the page --

class SmartDashboardView(QWidget):
    def __init__(self, smart_view, cctv_view, parent=None):
        super().__init__(parent)
        self.sv = smart_view
        self.cv = cctv_view
        self.app_tiles = {}
        self._app_ids = None
        self._snap_path = None
        self._build()
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(REFRESH_MS)

    # ----------------------------------------------------------------- build --

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;}")
        page = QWidget()
        page.setStyleSheet("background:transparent;")
        scroll.setWidget(page)
        outer.addWidget(scroll)
        self.grid = QGridLayout(page)
        self.grid.setContentsMargins(14, 14, 14, 14)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(12)

        self.hero = self._build_hero()
        self.t_load = StatTile("Live load", "zap")
        self.t_bat = StatTile("Battery", "battery")
        self.t_meter = StatTile("Prepaid meter", "calculator")
        self.t_cost = StatTile("Energy cost", "activity")
        self.card_apps = self._build_appliances()
        self.card_rooms = self._build_rooms()
        self.card_sec = self._build_security()
        self.card_grid = self._build_grid_card()
        self.card_meter = self._build_meter_card()
        self._mode = None
        self._place("wide")

    def _place(self, mode):
        """Lay the cards out for the available width: wide (4 columns),
        medium (2 columns) or narrow (1 column)."""
        if mode == self._mode:
            return
        self._mode = mode
        g = self.grid
        while g.count():
            g.takeAt(0)
        for c in range(4):
            g.setColumnStretch(c, 0)
        for r in range(12):
            g.setRowStretch(r, 0)
        tiles = (self.t_load, self.t_bat, self.t_meter, self.t_cost)
        if mode == "wide":
            cols = 4
            g.addWidget(self.hero, 0, 0, 1, 4)
            for i, t in enumerate(tiles):
                g.addWidget(t, 1, i)
            g.addWidget(self.card_apps, 2, 0, 1, 2)
            g.addWidget(self.card_rooms, 2, 2)
            g.addWidget(self.card_sec, 2, 3)
            g.addWidget(self.card_grid, 3, 0, 1, 2)
            g.addWidget(self.card_meter, 3, 2, 1, 2)
            last = 4
        elif mode == "medium":
            cols = 2
            g.addWidget(self.hero, 0, 0, 1, 2)
            for i, t in enumerate(tiles):
                g.addWidget(t, 1 + i // 2, i % 2)
            g.addWidget(self.card_apps, 3, 0, 1, 2)
            g.addWidget(self.card_rooms, 4, 0)
            g.addWidget(self.card_sec, 4, 1)
            g.addWidget(self.card_grid, 5, 0, 1, 2)
            g.addWidget(self.card_meter, 6, 0, 1, 2)
            last = 7
        else:
            cols = 1
            for i, w in enumerate((self.hero, *tiles, self.card_apps, self.card_rooms, self.card_sec,
                                   self.card_grid, self.card_meter)):
                g.addWidget(w, i, 0)
            last = 11
        for c in range(cols):
            g.setColumnStretch(c, 1)
        g.setRowStretch(last, 1)
        self.hero_lo.setDirection(QHBoxLayout.LeftToRight if mode == "wide" else QHBoxLayout.TopToBottom)
        for row in (self.hero_chips, self.hero_acts):
            row.itemAt(0).changeSize(0 if mode != "wide" else 1, 0,
                                     QSizePolicy.Fixed if mode != "wide" else QSizePolicy.Expanding)
            row.setAlignment(Qt.AlignLeft if mode != "wide" else Qt.Alignment())
            row.invalidate()
        self._app_cols = 3 if mode != "narrow" else 2
        self._app_ids = None          # re-flow the appliance tiles

    def resizeEvent(self, e):
        super().resizeEvent(e)
        w = self.width()
        self._place("wide" if w >= 1180 else "medium" if w >= 640 else "narrow")
        if self._app_ids is None:
            self.refresh()

    def _build_hero(self):
        hero = QFrame()
        hero.setObjectName("dash_hero")
        hero.setAttribute(Qt.WA_StyledBackground, True)
        hero.setStyleSheet("QFrame#dash_hero{border-radius:20px;border:1px solid rgba(255,255,255,0.12);"
                           "background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 rgba(56,189,248,0.20),"
                           "stop:0.55 rgba(18,26,34,0.80),stop:1 rgba(16,185,129,0.16));}")
        lo = QHBoxLayout(hero)
        self.hero_lo = lo
        lo.setContentsMargins(22, 18, 22, 18)
        lo.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(4)
        self.greet = _lbl("", TEXT, 26, 300)
        self.date = _lbl("", SOFT, 12, 600, 0.4)
        self.summary = _lbl("", MUTED, 12, 500)
        self.summary.setWordWrap(True)
        left.addWidget(self.greet)
        left.addWidget(self.date)
        left.addSpacing(4)
        left.addWidget(self.summary)
        lo.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(10)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        chips.addStretch()
        self.hero_chips = chips
        self.c_grid, self.c_arm, self.c_meter = QLabel(), QLabel(), QLabel()
        for c in (self.c_grid, self.c_arm, self.c_meter):
            chips.addWidget(c)
        right.addLayout(chips)
        acts = QHBoxLayout()
        acts.setSpacing(8)
        acts.addStretch()
        self.hero_acts = acts
        acts.addWidget(_action("All off", "power", self._all_off))
        self.arm_btn = _action("Arm", "shield", self._toggle_arm)
        acts.addWidget(self.arm_btn)
        acts.addWidget(_action("Bought token", "plus", lambda: self._energy_action("_log_token")))
        acts.addWidget(_action("3D map", "home", lambda: self._go("smart_home"), primary=True))
        right.addLayout(acts)
        lo.addLayout(right)
        return hero

    def _build_appliances(self):
        card, lo, head = _card("Appliances", "power")
        self.app_count = _lbl("", MUTED, 11, 600)
        head.addWidget(self.app_count)
        self.app_grid = QGridLayout()
        self.app_grid.setHorizontalSpacing(8)
        self.app_grid.setVerticalSpacing(8)
        lo.addLayout(self.app_grid)
        lo.addStretch()
        return card

    def _build_rooms(self):
        card, lo, _ = _card("Load by room", "home")
        self.rooms = RoomBars()
        self.rooms.room_clicked.connect(self._focus_room)
        lo.addWidget(self.rooms)
        self.rooms_note = _lbl("", MUTED, 10, 500)
        self.rooms_note.setWordWrap(True)
        lo.addWidget(self.rooms_note)
        lo.addStretch()
        return card

    def _build_security(self):
        card, lo, head = _card("Security", "shield")
        self.sec_chip = QLabel()
        head.addWidget(self.sec_chip)
        self.snap = QLabel()
        self.snap.setAlignment(Qt.AlignCenter)
        self.snap.setMinimumHeight(110)
        self.snap.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.snap.setStyleSheet("background:#05080d;border-radius:10px;color:#64748b;font-size:11px;")
        lo.addWidget(self.snap)
        self.snap_cap = _lbl("", MUTED, 10, 500)
        lo.addWidget(self.snap_cap)
        self.sec_line = _lbl("", SOFT, 12, 600)
        self.sec_line.setWordWrap(True)
        lo.addWidget(self.sec_line)
        lo.addStretch()
        lo.addWidget(_action("Open CCTV", "video", lambda: self._go("cctv")))
        return card

    def _build_grid_card(self):
        card, lo, head = _card("Grid supply · last 24 h", "zap")
        self.grid_chip = QLabel()
        head.addWidget(self.grid_chip)
        self.strip = GridStrip()
        lo.addWidget(self.strip)
        legend = QHBoxLayout()
        legend.setSpacing(14)
        for text, color in (("Grid on", GOOD), ("Power cut", CRIT)):
            sw = QLabel()
            sw.setFixedSize(10, 10)
            sw.setStyleSheet(f"background:{color};border-radius:3px;")
            legend.addWidget(sw)
            legend.addWidget(_lbl(text, MUTED, 11, 600))
        legend.addStretch()
        self.grid_stats = _lbl("", SOFT, 11, 600)
        legend.addWidget(self.grid_stats)
        lo.addLayout(legend)
        return card

    def _build_meter_card(self):
        card, lo, head = _card("Meter units · last 14 days", "calculator")
        head.addWidget(_action("Meter reading", "zap", lambda: self._energy_action("_log_reading")))
        self.spark = Sparkline()
        lo.addWidget(self.spark)
        return card

    # --------------------------------------------------------------- refresh --

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def _tick(self):
        if self.isVisible():
            self.refresh()

    def refresh(self):
        m, e = self.sv.model, self.sv.energy
        pw = m.power
        cur = pw.get("currency", "₦")
        now = time.time()
        price = e.price_per_kwh() or pw.get("tariff", 0)

        # ---- hero
        hour = datetime.now().hour
        part = "morning" if 5 <= hour < 12 else "afternoon" if hour < 17 else "evening"
        self.greet.setText(f"Good {part}")
        self.date.setText(datetime.now().strftime("%A, %d %B  ·  %H:%M"))
        devices = m.devices()
        on = [d for d in devices if d["device"]["on"]]
        out = e.open_outage()
        armed = bool(self.cv.store.config.get("armed"))
        days = e.days_left()
        bits = [f"{len(on)} of {len(devices)} appliances on, drawing {m.load_w():,.0f} W"]
        if out:
            bits.append(f"grid off for {_fmt_h((now - out['start']) / 3600)}")
        if days is not None:
            bits.append(f"meter lasts about {_fmt_h(days * 24)}")
        self.summary.setText(" · ".join(bits) + ".")
        if out:
            self._chip(self.c_grid, "● Grid off", CRIT)
        elif e.grid_detect:
            self._chip(self.c_grid, "● Grid on", GOOD)
        else:
            self._chip(self.c_grid, "Grid not watched", DIM)
        self._chip(self.c_arm, "Armed" if armed else "Disarmed", GOOD if armed else DIM)
        if days is not None:
            self._chip(self.c_meter, f"Meter {_fmt_h(days * 24)}", WARN if days < 2 else ACCENT)
        else:
            self.c_meter.hide()
        self.arm_btn.setText(" Disarm" if armed else " Arm")

        # ---- KPI tiles
        load = m.load_w()
        cap = max(1, pw.get("inverter_w", 3000))
        frac = load / cap
        lc = CRIT if frac > 0.9 else WARN if frac > 0.7 else ACCENT
        self.t_load.ring.set(frac, f"{frac * 100:.0f}%", "of inverter", lc)
        self.t_load.value.setText(f"{load:,.0f} W")
        self.t_load.detail.setText(f"{len(on)} of {len(devices)} appliances on")
        self.t_load.sub.setText(f"Inverter capacity {cap:,} W")
        self.t_load.set_chip("Overload risk" if frac > 0.9 else "", CRIT)

        pct = pw.get("battery_pct", 100)
        bc = CRIT if pct < 20 else WARN if pct < 40 else GOOD
        self.t_bat.ring.set(pct / 100, f"{pct:.0f}%", "charge", bc)
        rt = m.runtime_hours()
        self.t_bat.value.setText(_fmt_h(rt) if rt else "Idle")
        self.t_bat.detail.setText("runtime at the current load" if rt else "nothing is drawing power")
        b = e.last_battery()
        src = pw.get("source", "Grid")
        sub = f"Source: {src}"
        if b and "volts" in b:
            sub += f"  ·  {b['volts']:g} V read {datetime.fromtimestamp(b['ts']):%H:%M}"
        self.t_bat.sub.setText(sub)
        self.t_bat.set_chip("Low" if pct < 20 else "", CRIT)

        left = e.units_left()
        rate = e.burn_rate()
        if left is None:
            self.t_meter.ring.set(0, "—", "", DIM)
            self.t_meter.value.setText("— kWh")
            self.t_meter.detail.setText("No meter reading yet")
            self.t_meter.sub.setText("Log one with “Meter reading”")
            self.t_meter.set_chip("", ACCENT)
        else:
            week = (rate or 0) * 7
            if days is None:
                self.t_meter.ring.set(0, "—", "days left", DIM)
            else:
                mc = CRIT if days < 1 else WARN if days < 2 else ACCENT
                self.t_meter.ring.set(min(1.0, days / 7), f"{days:.1f}" if days >= 2 else _fmt_h(days * 24),
                                      "days left" if days >= 2 else "left", mc)
            self.t_meter.value.setText(f"{left:,.1f} kWh")
            self.t_meter.detail.setText(f"{rate:.1f} kWh / day" if rate else "usage: needs a 2nd reading")
            self.t_meter.sub.setText(f"≈ {week:,.0f} kWh a week" if rate else "Ring = days left out of 7")
            self.t_meter.set_chip("Buy soon" if days is not None and days < 2 else "", WARN)

        kwh = m.daily_kwh()
        per_day = kwh * price
        per_hour = load / 1000 * price
        month = per_day * 30
        usual = per_day / 24
        ratio = per_hour / usual if usual else 0
        self.t_cost.ring.set(min(1.0, ratio / 2), f"{ratio * 100:.0f}%", "of usual / h",
                             WARN if ratio > 1.5 else ACCENT)
        self.t_cost.ring.setToolTip(f"Right now: {_money(cur, per_hour)} per hour. A typical hour costs "
                                    f"{_money(cur, usual)}. Full ring = twice the usual.")
        self.t_cost.value.setText(f"{_money(cur, per_day)} / day")
        self.t_cost.detail.setText(f"{_money(cur, per_hour)}/h now  ·  {_money(cur, month)}/mo")
        self.t_cost.sub.setText(f"{kwh:.2f} kWh/day at {cur}{price:,.1f}/kWh"
                                + (" paid" if e.price_per_kwh() else " tariff"))

        # ---- appliances, rooms, grid, meter, security
        self._refresh_appliances(m)
        rows = [(r["id"], r["name"], m.load_w(r["id"])) for r in m.rooms]
        self.rooms.set_rows(rows)
        busiest = max(rows, key=lambda r: r[2]) if rows else None
        self.rooms_note.setText(f"{busiest[1]} draws the most right now." if busiest and busiest[2] > 0
                                else "Everything is off.")

        self.strip.set_data(e.outages, e.grid_detect)
        hrs = e.outage_hours(now - 86400, now)
        self.grid_stats.setText(f"{_fmt_h(hrs)} without grid" if e.outages else
                                ("No power cuts" if e.grid_detect else "Turn on detection in Smart Home"))
        if out:
            self._chip(self.grid_chip, f"Off {_fmt_h((now - out['start']) / 3600)}", CRIT)
        elif e.grid_detect:
            self._chip(self.grid_chip, "On", GOOD)
        else:
            self._chip(self.grid_chip, "Not watched", DIM)

        cutoff = now - 14 * 86400
        self.spark.set_points([(r["ts"], r["units"]) for r in e.readings if r["ts"] >= cutoff])

        self._refresh_security(armed)

    def _refresh_appliances(self, m):
        names = {r["id"]: r["name"] for r in m.rooms}
        devices = sorted(m.devices(), key=lambda d: (d["room"], d["name"]))   # stable: tiles never jump
        ids = [d["id"] for d in devices]
        if ids != self._app_ids:
            self._app_ids = ids
            while self.app_grid.count():
                w = self.app_grid.takeAt(0).widget()
                if w:
                    w.setParent(None)
            keep = {}
            for i, d in enumerate(devices):
                tile = self.app_tiles.get(d["id"]) or ApplianceTile(d["id"])
                if d["id"] not in self.app_tiles:
                    tile.clicked.connect(self._toggle)
                keep[d["id"]] = tile
                self.app_grid.addWidget(tile, i // self._app_cols, i % self._app_cols)
            for iid, t in self.app_tiles.items():
                if iid not in keep:
                    t.deleteLater()
            self.app_tiles = keep
        for d in devices:
            self.app_tiles[d["id"]].set_item(d, names.get(d["room"], ""))
        on = sum(1 for d in devices if d["device"]["on"])
        self.app_count.setText(f"{on} on · tap to switch")

    def _refresh_security(self, armed):
        store, feeds = self.cv.store, self.cv.feeds
        self._chip(self.sec_chip, "Armed" if armed else "Disarmed", GOOD if armed else DIM)
        live = sum(1 for f in feeds.values() if f.running)
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        motions = [ev for ev in store.events_since(today) if ev["kind"] == "motion"]
        cams = len(store.cameras)
        self.sec_line.setText(f"{live} of {cams} camera{'s' if cams != 1 else ''} live  ·  "
                              f"{len(motions)} motion event{'s' if len(motions) != 1 else ''} today")
        latest = next((ev for ev in reversed(store.events) if ev.get("snapshot")), None)
        path = latest["snapshot"] if latest else None
        if path != self._snap_path or self.snap.width() != getattr(self, "_snap_w", 0):
            self._snap_path, self._snap_w = path, self.snap.width()
            pm = QPixmap(path) if path else QPixmap()
            if pm.isNull():
                self.snap.setPixmap(QPixmap())
                self.snap.setText("No snapshots yet")
            else:
                self.snap.setPixmap(pm.scaled(QSize(max(1, self.snap.width()), 110),
                                              Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if latest:
            kind = "Motion" if latest["kind"] == "motion" else "Snapshot"
            self.snap_cap.setText(f"{kind} · {latest['camera_name']} · "
                                  f"{datetime.fromtimestamp(latest['ts']):%a %H:%M}")
        else:
            self.snap_cap.setText("Motion snapshots appear here")

    @staticmethod
    def _chip(label, text, color):
        label.setText(text)
        label.setStyleSheet(_chip_style(color))
        label.show()

    # --------------------------------------------------------------- actions --

    def _toggle(self, item_id):
        self.sv._toggle(item_id)
        self.refresh()

    def _all_off(self):
        self.sv._all_off()
        self.refresh()

    def _toggle_arm(self):
        self.cv.arm_btn.toggle()
        self.refresh()

    def _energy_action(self, name):
        getattr(self.sv, name)()
        self.refresh()

    def _go(self, module_id):
        win = self.window()
        if hasattr(win, "navigate_by_id"):
            win.navigate_by_id(module_id)

    def _focus_room(self, room_id):
        self._go("smart_home")
        QTimer.singleShot(150, lambda: self.sv.view.focus_room(room_id))

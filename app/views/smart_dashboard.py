"""
Home Dashboard — the whole smart home on one page.

  • header: greeting, time, status pills and quick actions
  • hero: the real 3D house with live figures floating over it (load, battery, grid,
    weather) next to a room panel — pick a room to fly the house there and switch its
    appliances with toggles
  • power dial (load against the inverter), the live camera, power cuts this week
  • prepaid meter trend, what's in the fridge, energy cost by room

Nothing is stored here: the page reads the Smart Home model / energy log, the CCTV
store and the fridge through their pages, so a switch flipped here shows up there too.
"""
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal, QSize
from PySide6.QtGui import (QPainter, QColor, QPen, QFont, QFontMetrics, QPainterPath, QLinearGradient, QPixmap,
                           QRegion, QImage)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QSizePolicy, QToolTip, QButtonGroup
)

from app.icons import get_icon, get_pixmap
from app.views.home_ui import (ACCENT, ACCENT_HI, ON_ACCENT, GOOD, WARN, CRIT, TEXT, SOFT, MUTED, DIM, TRACK,
                               GLASS, Toggle, ArcDial, WeekBars, Clickable, pill_style, glass_style, rgba,
                               apply_home_style)

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


def _bubble(icon, size=30, color=SOFT, bg="rgba(255,255,255,0.06)"):
    ic = QLabel()
    ic.setFixedSize(size, size)
    ic.setAlignment(Qt.AlignCenter)
    ic.setPixmap(get_pixmap(icon, color, int(size * 0.5)))
    ic.setStyleSheet(f"background:{bg};border-radius:{size // 2}px;border:none;")
    return ic


def _card(title, icon):
    box = QFrame()
    box.setObjectName("panel")
    lo = QVBoxLayout(box)
    lo.setContentsMargins(18, 16, 18, 16)
    lo.setSpacing(12)
    head = QHBoxLayout()
    head.setSpacing(10)
    head.addWidget(_bubble(icon))
    head.addWidget(_lbl(title, TEXT, 14, 600))
    head.addStretch()
    lo.addLayout(head)
    return box, lo, head


def _chip_style(color):
    return pill_style(color)


def _action(text, icon, slot, primary=False):
    b = QPushButton(f" {text}")
    b.setIcon(get_icon(icon, ON_ACCENT if primary else "#e7e5e4", 13))
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(32)
    if primary:
        b.setStyleSheet(f"QPushButton{{background:{ACCENT};color:{ON_ACCENT};border:none;border-radius:16px;"
                        f"padding:4px 15px;font-weight:700;}}QPushButton:hover{{background:{ACCENT_HI};}}"
                        f"QPushButton:disabled{{background:rgba(255,122,26,0.4);}}")
    else:
        b.setStyleSheet("QPushButton{background:rgba(255,255,255,0.06);color:#e7e5e4;"
                        "border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:4px 15px;"
                        "font-weight:600;}QPushButton:hover{background:rgba(255,255,255,0.12);}"
                        "QPushButton:disabled{color:#78716c;}")
    b.clicked.connect(slot)
    return b


def _round_btn(icon, tip, slot, danger=False, size=38):
    b = QPushButton()
    b.setFixedSize(size, size)
    b.setIcon(get_icon(icon, "#ffffff" if danger else "#e7e5e4", 16))
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    bg = CRIT if danger else "rgba(255,255,255,0.08)"
    b.setStyleSheet(f"QPushButton{{background:{bg};border:1px solid rgba(255,255,255,0.10);"
                    f"border-radius:{size // 2}px;}}QPushButton:hover{{background:"
                    f"{'#fb9191' if danger else 'rgba(255,255,255,0.16)'};}}")
    b.clicked.connect(slot)
    return b


def rounded_pixmap(src, w, h, radius=16):
    """Fill w×h with the picture (cropped, centred) and round the corners."""
    out = QPixmap(max(1, w), max(1, h))
    out.fill(Qt.transparent)
    if src.isNull():
        return out
    scaled = src.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(int((w - scaled.width()) / 2), int((h - scaled.height()) / 2), scaled)
    p.end()
    return out


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
    """Horizontal bars, one hue (magnitude). Defaults to load per room in watts;
    fmt / share_of / click_hint make it reusable for other quantities."""

    room_clicked = Signal(str)
    ROW = 34

    def __init__(self, parent=None, fmt=lambda v: f"{v:,.0f} W", share_of="the load",
                 click_hint="Click to fly the 3D map there", name_w=96, val_w=64):
        super().__init__(parent)
        self.rows = []          # (key, name, value)
        self.fmt, self.share_of, self.click_hint = fmt, share_of, click_hint
        self.name_w, self.val_w = name_w, val_w
        self.setMouseTracking(True)
        if click_hint:
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
                              f"{row[1]}: {self.fmt(row[2])}  ({row[2] / total * 100:.0f}% of {self.share_of})"
                              + (f"\n{self.click_hint}" if self.click_hint else ""), self)

    def mousePressEvent(self, e):
        row = self._row_at(e.position().y())
        if row and self.click_hint:
            self.room_clicked.emit(row[0])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont()
        f.setPixelSize(12)
        top = max([r[2] for r in self.rows] + [1])
        name_w, val_w = self.name_w, self.val_w
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
                       self.fmt(watts))
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
        surface = QColor("#1c1a19")
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



class FitLabel(QLabel):
    """One-line label that shrinks its font (down to 13 px) to fit the width."""

    def __init__(self, text="", color=TEXT, size=24, weight=300):
        super().__init__(text)
        self._color, self._size, self._weight = color, size, weight
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setFixedHeight(int(size * 1.35))
        self.setStyleSheet("background:transparent;border:none;")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        f = QFont()
        f.setWeight(QFont.Light if self._weight <= 300 else QFont.Normal)
        size = self._size
        while size > 13:
            f.setPixelSize(size)
            if QFontMetrics(f).horizontalAdvance(self.text()) <= self.width():
                break
            size -= 1
        f.setPixelSize(size)
        p.setFont(f)
        p.setPen(QColor(self._color))
        p.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, self.text())
        p.end()



class StatTile(QFrame):
    """KPI tile: ring on the left, headline + detail on the right."""

    def __init__(self, title, icon, parent=None, ring=True):
        super().__init__(parent)
        self.setObjectName("panel")
        lo = QVBoxLayout(self)
        lo.setContentsMargins(18, 16, 18, 16)
        lo.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(_bubble(icon))
        head.addWidget(_lbl(title, TEXT, 13, 600))
        head.addStretch()
        self.chip = QLabel()
        self.chip.hide()
        head.addWidget(self.chip)
        lo.addLayout(head)
        body = QHBoxLayout()
        body.setSpacing(14)
        self.ring = Ring(84)
        self.ring.setVisible(ring)
        body.addWidget(self.ring)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addStretch()
        self.value = FitLabel("", TEXT, 26, 300)
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



# ---------------------------------------------------------------- page parts --

class DeviceRow(QFrame):
    """An appliance in the room panel: icon, name, watts and a switch."""
    switched = Signal(str, bool)

    def __init__(self, item_id, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.setObjectName(f"row_{item_id}")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(10, 8, 12, 8)
        lo.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFixedSize(38, 38)
        self.icon.setAlignment(Qt.AlignCenter)
        lo.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.name = _lbl("", TEXT, 13, 600)
        self.sub = _lbl("", MUTED, 11, 500)
        col.addWidget(self.name)
        col.addWidget(self.sub)
        lo.addLayout(col, 1)
        self.toggle = Toggle()
        self.toggle.toggled.connect(lambda on: self.switched.emit(self.item_id, on))
        lo.addWidget(self.toggle)
        self._sig = None

    def set_item(self, it, room_name, live=None):
        dev = it["device"]
        sig = (it["name"], room_name, dev["watts"], dev["on"], None if live is None else round(live))
        if sig == self._sig:
            return
        self._sig = sig
        on = dev["on"]
        icon = DEVICE_ICONS.get(it.get("kind"), "plug")
        self.icon.setPixmap(get_pixmap(icon, ON_ACCENT if on else SOFT, 18))
        self.icon.setStyleSheet(f"background:{ACCENT if on else 'rgba(255,255,255,0.06)'};border-radius:19px;")
        self.name.setText(it["name"])
        watts = f"{live:.0f} W live" if live is not None else f"{dev['watts']:g} W"
        self.sub.setText(f"{room_name}  ·  {watts}" if room_name else watts)
        self.toggle.set_on(on)
        n = self.objectName()
        self.setStyleSheet(f"QFrame#{n}{{background:{rgba(ACCENT, 0.08) if on else 'rgba(255,255,255,0.03)'};"
                           f"border-radius:18px;border:1px solid {rgba(ACCENT, 0.22) if on else 'transparent'};}}"
                           f"QFrame#{n}:hover{{background:rgba(255,255,255,0.07);}}")


class HeroHouse(QWidget):
    """The 3D house with rounded corners (masked) for the dashboard hero."""

    def __init__(self, model, radius=24, parent=None):
        super().__init__(parent)
        from app.home3d.view3d import House3DView
        self.radius = radius
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        self.view = House3DView(model)
        self.view.setMinimumSize(320, 300)
        self.view.use_warm_theme()
        lo.addWidget(self.view)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), self.radius, self.radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))


class GlassStat(QFrame):
    """Floating stat over the house: icon, label, big value, small line."""

    def __init__(self, icon, title, parent=None):
        super().__init__(parent)
        self.setObjectName("glass")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QFrame#glass{{{glass_style(18)}}}")
        lo = QHBoxLayout(self)
        lo.setContentsMargins(12, 10, 14, 10)
        lo.setSpacing(10)
        self.icon = _bubble(icon, 34, ACCENT, rgba(ACCENT, 0.16))
        lo.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = _lbl(title, MUTED, 10, 700, 0.6)
        self.value = _lbl("", TEXT, 19, 500)
        self.sub = _lbl("", SOFT, 10, 600)
        for w in (self.title, self.value, self.sub):
            col.addWidget(w)
        lo.addLayout(col)

    def set(self, value, sub="", icon=None, color=ACCENT):
        self.value.setText(value)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))
        if icon:
            self.icon.setPixmap(get_pixmap(icon, color, 17))
        self.icon.setStyleSheet(f"background:{rgba(color, 0.16)};border-radius:17px;border:none;")


# -------------------------------------------------------------------- the page --

class SmartDashboardView(QWidget):
    def __init__(self, smart_view, cctv_view, parent=None):
        super().__init__(parent)
        self.sv = smart_view
        self.cv = cctv_view
        self.rows = {}
        self._row_ids = None
        self._room = "all"
        self._cam_index = 0
        self._snap_key = None
        self._house_sig = None
        self._build()
        apply_home_style(self)
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
        self.grid.setContentsMargins(22, 20, 22, 22)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(16)

        self.header = self._build_header()
        self.hero = self._build_hero()
        self.card_rooms = self._build_rooms()
        self.card_power = self._build_power()
        self.card_cam = self._build_camera()
        self.card_week = self._build_week()
        self.card_meter = self._build_meter()
        self.card_fridge = self._build_fridge()
        self.card_energy = self._build_energy()
        self._mode = None
        self._place("wide")

    def _place(self, mode):
        """wide: 3 columns · medium: 2 · narrow: 1."""
        if mode == self._mode:
            return
        self._mode = mode
        g = self.grid
        while g.count():
            g.takeAt(0)
        for c in range(3):
            g.setColumnStretch(c, 0)
        for r in range(16):
            g.setRowStretch(r, 0)
        cards = (self.card_power, self.card_cam, self.card_week, self.card_meter, self.card_fridge, self.card_energy)
        if mode == "wide":
            g.addWidget(self.header, 0, 0, 1, 3)
            g.addWidget(self.hero, 1, 0, 1, 2)
            g.addWidget(self.card_rooms, 1, 2)
            for i, c in enumerate(cards):
                g.addWidget(c, 2 + i // 3, i % 3)
            cols, last = 3, 4
        elif mode == "medium":
            g.addWidget(self.header, 0, 0, 1, 2)
            g.addWidget(self.hero, 1, 0, 1, 2)
            seq = (self.card_rooms, *cards)
            for i, c in enumerate(seq[:-1]):
                g.addWidget(c, 2 + i // 2, i % 2)
            g.addWidget(seq[-1], 2 + (len(seq) - 1) // 2, 0, 1, 2)
            cols, last = 2, 7
        else:
            for i, w in enumerate((self.header, self.hero, self.card_rooms, *cards)):
                g.addWidget(w, i, 0)
            cols, last = 1, 10
        for c in range(cols):
            g.setColumnStretch(c, 1)
        g.setRowStretch(last, 1)
        self.hero.setMinimumHeight(430 if mode == "wide" else 360)
        self.header_lo.setDirection(QHBoxLayout.LeftToRight if mode == "wide" else QHBoxLayout.TopToBottom)
        self.header_lo.setAlignment(self.header_right, Qt.AlignVCenter if mode == "wide" else Qt.AlignLeft)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        w = self.width()
        self._place("wide" if w >= 1000 else "medium" if w >= 700 else "narrow")

    # header ------------------------------------------------------------------

    def _build_header(self):
        box = QWidget()
        box.setStyleSheet("background:transparent;")
        lo = QHBoxLayout(box)
        self.header_lo = lo
        lo.setContentsMargins(4, 0, 4, 0)
        lo.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(2)
        self.greet = _lbl("", TEXT, 28, 300)
        self.date = _lbl("", MUTED, 12, 600, 0.3)
        left.addWidget(self.greet)
        left.addWidget(self.date)
        lo.addLayout(left, 1)
        right = QHBoxLayout()
        right.setSpacing(8)
        self.c_grid, self.c_arm, self.c_meter = QLabel(), QLabel(), QLabel()
        for c in (self.c_grid, self.c_arm, self.c_meter):
            right.addWidget(c, 0, Qt.AlignVCenter)
        right.addSpacing(6)
        right.addWidget(_action("All off", "power", self._all_off))
        self.arm_btn = _action("Arm", "shield", self._toggle_arm)
        right.addWidget(self.arm_btn)
        right.addWidget(_action("Bought token", "plus", lambda: self._energy_action("_log_token"), primary=True))
        lo.addLayout(right)
        lo.setAlignment(right, Qt.AlignVCenter)
        self.header_right = right
        return box

    # hero: the house ----------------------------------------------------------

    def _build_hero(self):
        hero = QFrame()
        hero.setObjectName("dash_hero")
        hero.setAttribute(Qt.WA_StyledBackground, True)
        hero.setStyleSheet("QFrame#dash_hero{border-radius:24px;border:1px solid rgba(255,255,255,0.07);"
                           "background:#120f0d;}")
        g = QGridLayout(hero)
        g.setContentsMargins(0, 0, 0, 0)
        self.house = HeroHouse(self.sv.model)
        self.house.view.device_clicked.connect(self._toggle)
        g.addWidget(self.house, 0, 0)

        stats = QWidget()
        stats.setStyleSheet("background:transparent;")
        sl = QVBoxLayout(stats)
        sl.setContentsMargins(18, 18, 18, 18)
        sl.setSpacing(10)
        self.g_load = GlassStat("zap", "LIVE LOAD")
        self.g_bat = GlassStat("battery", "BATTERY")
        self.g_grid = GlassStat("power", "GRID")
        for w in (self.g_load, self.g_bat, self.g_grid):
            sl.addWidget(w)
        g.addWidget(stats, 0, 0, Qt.AlignTop | Qt.AlignLeft)

        self.g_weather = GlassStat("cloud_sun", "WEATHER")
        wbox = QWidget()
        wbox.setStyleSheet("background:transparent;")
        wl = QVBoxLayout(wbox)
        wl.setContentsMargins(18, 18, 18, 18)
        wl.addWidget(self.g_weather)
        g.addWidget(wbox, 0, 0, Qt.AlignTop | Qt.AlignRight)

        bottom = QWidget()
        bottom.setStyleSheet("background:transparent;")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(18, 14, 18, 16)
        hint = QLabel("Drag to turn  ·  click an appliance to switch it")
        hint.setStyleSheet(f"{glass_style(12)}padding:5px 10px;font-size:11px;color:{SOFT};")
        bl.addWidget(hint)
        bl.addStretch()
        open3d = QPushButton(" Open 3D")
        open3d.setIcon(get_icon("maximize", TEXT, 13))
        open3d.setCursor(Qt.PointingHandCursor)
        open3d.setStyleSheet(f"QPushButton{{{glass_style(14)}padding:6px 12px;font-weight:700;}}"
                             f"QPushButton:hover{{background:rgba(40,36,33,0.9);}}")
        open3d.clicked.connect(lambda: self._go("smart_home"))
        bl.addWidget(open3d)
        g.addWidget(bottom, 0, 0, Qt.AlignBottom)
        return hero

    # rooms ------------------------------------------------------------------------

    def _build_rooms(self):
        card, lo, head = _card("Rooms", "home")
        self.rooms_count = _lbl("", MUTED, 11, 600)
        head.addWidget(self.rooms_count)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        self.chip_btns = {}
        lo.addLayout(self.chips)
        self.rows_lo = QVBoxLayout()
        self.rows_lo.setSpacing(6)
        lo.addLayout(self.rows_lo)
        lo.addStretch()
        self.rooms_note = _lbl("", DIM, 11, 500)
        self.rooms_note.setWordWrap(True)
        lo.addWidget(self.rooms_note)
        return card

    def _chip_btn(self, key, text):
        b = QPushButton(text)
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedHeight(30)
        b.setStyleSheet(f"QPushButton{{background:rgba(255,255,255,0.06);color:{SOFT};border:none;"
                        f"border-radius:15px;padding:0 14px;font-weight:600;}}"
                        f"QPushButton:hover{{background:rgba(255,255,255,0.11);}}"
                        f"QPushButton:checked{{background:{ACCENT};color:{ON_ACCENT};font-weight:800;}}")
        b.clicked.connect(lambda _=False, k=key: self._pick_room(k))
        self.chip_group.addButton(b)
        return b

    # power, camera, week ------------------------------------------------------------

    def _build_power(self):
        card, lo, head = _card("Power", "zap")
        self.power_chip = QLabel()
        head.addWidget(self.power_chip)
        self.dial = ArcDial()
        self.dial.setMinimumHeight(190)
        lo.addWidget(self.dial, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.p_stats = []
        for title in ("Battery", "Runtime", "Cost now"):
            box = QFrame()
            box.setStyleSheet("QFrame{background:rgba(255,255,255,0.04);border-radius:14px;}")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(10, 8, 10, 8)
            bl.setSpacing(0)
            t = _lbl(title, MUTED, 10, 600)
            v = _lbl("", TEXT, 14, 600)
            bl.addWidget(t)
            bl.addWidget(v)
            row.addWidget(box, 1)
            self.p_stats.append(v)
        lo.addLayout(row)
        self.power_note = _lbl("", DIM, 11, 500)
        self.power_note.setWordWrap(True)
        lo.addWidget(self.power_note)
        return card

    def _build_camera(self):
        card, lo, head = _card("Camera", "video")
        self.cam_name = _lbl("", MUTED, 11, 600)
        head.addWidget(self.cam_name)
        prev_b = _round_btn("chevron_left", "Previous camera", lambda: self._cycle_cam(-1), size=28)
        next_b = _round_btn("chevron_right", "Next camera", lambda: self._cycle_cam(1), size=28)
        head.addWidget(prev_b)
        head.addWidget(next_b)
        self.cam_nav = (prev_b, next_b)
        holder = QWidget()
        hg = QGridLayout(holder)
        hg.setContentsMargins(0, 0, 0, 0)
        self.cam_img = QLabel()
        self.cam_img.setMinimumHeight(180)
        self.cam_img.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.cam_img.setAlignment(Qt.AlignCenter)
        self.cam_img.setStyleSheet(f"background:#0c0b0a;border-radius:16px;color:{DIM};font-size:12px;")
        hg.addWidget(self.cam_img, 0, 0)
        self.cam_badge = QLabel()
        badge_box = QWidget()
        badge_box.setStyleSheet("background:transparent;")
        bb = QHBoxLayout(badge_box)
        bb.setContentsMargins(10, 10, 10, 10)
        bb.addWidget(self.cam_badge)
        hg.addWidget(badge_box, 0, 0, Qt.AlignTop | Qt.AlignLeft)
        ctl = QWidget()
        ctl.setStyleSheet("background:transparent;")
        cl = QHBoxLayout(ctl)
        cl.setContentsMargins(10, 10, 10, 12)
        cl.setSpacing(8)
        cl.addStretch()
        cl.addWidget(_round_btn("camera", "Take a snapshot", self._snapshot))
        self.cam_arm = _round_btn("shield", "Arm / disarm motion alerts", self._toggle_arm)
        cl.addWidget(self.cam_arm)
        cl.addWidget(_round_btn("maximize", "Open CCTV", lambda: self._go("cctv")))
        self.cam_power = _round_btn("power", "Start / stop this camera", self._cam_power, danger=True)
        cl.addWidget(self.cam_power)
        cl.addStretch()
        hg.addWidget(ctl, 0, 0, Qt.AlignBottom)
        lo.addWidget(holder, 1)
        self.cam_line = _lbl("", MUTED, 11, 500)
        lo.addWidget(self.cam_line)
        return card

    def _build_week(self):
        card, lo, head = _card("Power cuts this week", "activity")
        self.week_chip = QLabel()
        head.addWidget(self.week_chip)
        self.week = WeekBars(fmt=lambda v: _fmt_h(v))
        lo.addWidget(self.week, 1)
        self.week_note = _lbl("", MUTED, 11, 500)
        self.week_note.setWordWrap(True)
        lo.addWidget(self.week_note)
        return card

    # meter, fridge, energy ---------------------------------------------------------

    def _build_meter(self):
        card, lo, head = _card("Prepaid meter", "calculator")
        head.addWidget(_action("Reading", "zap", lambda: self._energy_action("_log_reading")))
        self.m_big = _lbl("", TEXT, 30, 300)
        self.m_sub = _lbl("", SOFT, 12, 600)
        self.m_sub.setWordWrap(True)
        lo.addWidget(self.m_big)
        lo.addWidget(self.m_sub)
        self.spark = Sparkline()
        self.spark.setMinimumHeight(110)
        lo.addWidget(self.spark, 1)
        return card

    def _build_fridge(self):
        card, lo, head = _card("Fridge", "fridge")
        self.f_chip = QLabel()
        head.addWidget(self.f_chip)
        self.f_rows = QVBoxLayout()
        self.f_rows.setSpacing(4)
        lo.addLayout(self.f_rows)
        lo.addStretch()
        lo.addWidget(_action("Open fridge", "fridge", lambda: self._go("fridge")))
        self._f_labels = []
        return card

    def _build_energy(self):
        card, lo, _ = _card("Energy cost", "activity")
        self.e_big = _lbl("", TEXT, 30, 300)
        self.e_sub = _lbl("", SOFT, 12, 600)
        self.e_sub.setWordWrap(True)
        lo.addWidget(self.e_big)
        lo.addWidget(self.e_sub)
        self.rooms = RoomBars(click_hint="Click to show this room on the house")
        self.rooms.room_clicked.connect(self._pick_room)
        lo.addWidget(self.rooms)
        lo.addStretch()
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
        devices = m.devices()
        on = [d for d in devices if d["device"]["on"]]
        out = e.open_outage()
        armed = bool(self.cv.store.config.get("armed"))
        days = e.days_left()
        watching = self.sv.grid_watching() if hasattr(self.sv, "grid_watching") else e.grid_detect
        inv = getattr(self.sv, "inverter", None)
        measured = inv is not None and inv.load_w() is not None

        # ---- header
        hour = datetime.now().hour
        part = "morning" if 5 <= hour < 12 else "afternoon" if hour < 17 else "evening"
        win = self.window()
        who = (getattr(win, "user", None) or {}).get("username", "")
        self.greet.setText(f"Good {part}" + (f", {who}" if who else ""))
        self.date.setText(datetime.now().strftime("%A, %d %B  ·  %H:%M"))
        if out:
            self._chip(self.c_grid, f"● Grid off {_fmt_h((now - out['start']) / 3600)}", CRIT)
        elif watching:
            self._chip(self.c_grid, "● Grid on", GOOD)
        else:
            self._chip(self.c_grid, "Grid not watched", DIM)
        self._chip(self.c_arm, "Armed" if armed else "Disarmed", GOOD if armed else DIM)
        if days is not None:
            self._chip(self.c_meter, f"Meter {_fmt_h(days * 24)}", WARN if days < 2 else ACCENT)
        else:
            self.c_meter.hide()
        self.arm_btn.setText(" Disarm" if armed else " Arm")

        # ---- hero
        load = m.load_w()
        cap = max(1, pw.get("inverter_w", 3000))
        frac = load / cap
        self.g_load.set(f"{load:,.0f} W", f"{frac * 100:.0f}% of inverter" + (" · measured" if measured else ""),
                        "zap", CRIT if frac > 0.9 else WARN if frac > 0.7 else ACCENT)
        pct = pw.get("battery_pct", 100)
        rt = m.runtime_hours()
        self.g_bat.set(f"{pct:.0f}%", f"lasts {_fmt_h(rt)}" if rt else "nothing drawing",
                       "battery", CRIT if pct < 20 else WARN if pct < 40 else GOOD)
        charging = inv.charging_w() if inv is not None else None
        if out:
            self.g_grid.set("Off", f"for {_fmt_h((now - out['start']) / 3600)}", "power", CRIT)
        elif watching:
            self.g_grid.set("On", f"charging ≈ {charging:,.0f} W" if charging else "watching", "power", GOOD)
        else:
            self.g_grid.set("—", "not watched", "power", DIM)
        wsvc = getattr(win, "weather", None)
        w = getattr(wsvc, "now", None)
        if w and w.get("temp") is not None:
            self.g_weather.title.setText(w["place"].split(",")[0].upper())
            self.g_weather.set(f"{w['temp']:.0f}°  {w['desc']}",
                               f"Solar today: {w['solar']}" if w.get("solar") else f"Humidity {w['humidity']}%",
                               w["icon"], ACCENT)
            self.g_weather.show()
        else:
            self.g_weather.hide()
        sig = tuple((d["id"], d["device"]["on"]) for d in devices)
        if sig != self._house_sig:
            self._house_sig = sig
            self.house.view.invalidate()

        # ---- rooms
        self._refresh_rooms(m)

        # ---- power dial
        lc = CRIT if frac > 0.9 else WARN if frac > 0.7 else ACCENT
        self.dial.set(frac, f"{load:,.0f}", "watts" + (" · measured" if measured else ""),
                      f"{frac * 100:.0f}% of the inverter", "0", f"{cap / 1000:.1f} kW".replace(".0 kW", " kW"), lc)
        if frac > 0.9:
            self._chip(self.power_chip, "Overload risk", CRIT)
        else:
            self.power_chip.hide()
        per_hour = load / 1000 * price
        self.p_stats[0].setText(f"{pct:.0f}%")
        self.p_stats[1].setText(_fmt_h(rt) if rt else "—")
        self.p_stats[2].setText(f"{_money(cur, per_hour)}/h")
        src = pw.get("source", "Grid")
        self.power_note.setText(f"Source: {src}" + (f"  ·  {len(on)} of {len(devices)} appliances on"))

        # ---- camera, week, meter, fridge, energy
        self._refresh_camera(armed)
        self._refresh_week(e, now, watching)
        left = e.units_left()
        rate = e.burn_rate()
        if left is None:
            self.m_big.setText("— kWh")
            self.m_sub.setText("No reading yet — tap Reading and type the units left on the meter.")
        else:
            self.m_big.setText(f"{left:,.1f} kWh")
            bits = []
            if days is not None:
                bits.append(f"≈ {_fmt_h(days * 24)} left")
            if rate:
                bits.append(f"{rate:.1f} kWh a day")
            if e.price_per_kwh():
                bits.append(f"{cur}{e.price_per_kwh():,.1f}/kWh paid")
            self.m_sub.setText("  ·  ".join(bits) or "Log a second reading to see how fast it goes.")
        self.spark.set_points([(r["ts"], r["units"]) for r in e.readings if r["ts"] >= now - 14 * 86400])
        self._refresh_fridge(getattr(win, "fridge", None))
        kwh = m.daily_kwh()
        per_day = kwh * price
        self.e_big.setText(f"{_money(cur, per_day)} / day")
        self.e_sub.setText(f"{_money(cur, per_hour)}/h now  ·  {_money(cur, per_day * 30)} a month  ·  "
                           f"{kwh:.1f} kWh a day")
        self.rooms.set_rows([(r["id"], r["name"], m.load_w(r["id"])) for r in m.rooms])

    def _refresh_rooms(self, m):
        names = {r["id"]: r["name"] for r in m.rooms}
        keys = ["all"] + [r["id"] for r in m.rooms]
        if list(self.chip_btns) != keys:
            for b in self.chip_btns.values():
                self.chip_group.removeButton(b)
                b.setParent(None)
            self.chip_btns = {}
            for k in keys:
                b = self._chip_btn(k, "All" if k == "all" else names[k])
                self.chip_btns[k] = b
                self.chips.addWidget(b)
            self.chips.addStretch()
            if self._room not in self.chip_btns:
                self._room = "all"
        self.chip_btns[self._room].setChecked(True)
        devices = sorted(m.devices() if self._room == "all" else m.devices(self._room),
                         key=lambda d: (not d["device"]["on"], d["room"], d["name"]))
        ids = [d["id"] for d in devices]
        if ids != self._row_ids:
            self._row_ids = ids
            while self.rows_lo.count():
                w = self.rows_lo.takeAt(0).widget()
                if w:
                    w.setParent(None)
            keep = {}
            for d in devices:
                row = self.rows.get(d["id"])
                if row is None:
                    row = DeviceRow(d["id"])
                    row.switched.connect(self._switch)
                keep[d["id"]] = row
                self.rows_lo.addWidget(row)
            self.rows.update(keep)
        for d in devices:
            self.rows[d["id"]].set_item(d, names.get(d["room"], "") if self._room == "all" else "",
                                        m.live_w(d["id"]))
        n_on = sum(1 for d in devices if d["device"]["on"])
        self.rooms_count.setText(f"{n_on} of {len(devices)} on")
        room_w = m.load_w(None if self._room == "all" else self._room)
        self.rooms_note.setText(f"{names.get(self._room, 'The house')} is drawing {room_w:,.0f} W."
                                if room_w else "Everything here is off.")

    def _feeds_with_picture(self):
        return [f for f in self.cv.feeds.values() if f.running and f.image is not None and not f.image.isNull()]

    def _refresh_camera(self, armed):
        store = self.cv.store
        self.cam_arm.setIcon(get_icon("shield" if armed else "unlock", GOOD if armed else "#e7e5e4", 16))
        live = self._feeds_with_picture()
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        motions = sum(1 for ev in store.events_since(today) if ev["kind"] == "motion")
        for b in self.cam_nav:
            b.setVisible(len(live) > 1)
        w, h = max(1, self.cam_img.width()), max(1, self.cam_img.height())
        if live:
            feed = live[self._cam_index % len(live)]
            self.cam_name.setText(feed.cam["name"])
            self.cam_badge.setText("●  Live")
            self.cam_badge.setStyleSheet(f"QLabel{{background:{CRIT};color:#fff;border-radius:11px;"
                                         "padding:3px 10px;font-size:11px;font-weight:800;}")
            self.cam_img.setPixmap(rounded_pixmap(QPixmap.fromImage(feed.image), w, h))
            self._snap_key = None
            self.cam_power.setToolTip(f"Stop {feed.cam['name']}")
        else:
            latest = next((ev for ev in reversed(store.events) if ev.get("snapshot")), None)
            key = (latest["snapshot"] if latest else None, w, h)
            if key != self._snap_key:
                self._snap_key = key
                pm = QPixmap(latest["snapshot"]) if latest else QPixmap()
                if pm.isNull():
                    self.cam_img.setPixmap(QPixmap())
                    self.cam_img.setText("No camera picture yet.\nStart a camera on the CCTV page.")
                else:
                    self.cam_img.setPixmap(rounded_pixmap(pm, w, h))
            self.cam_name.setText(latest["camera_name"] if latest else "")
            self.cam_badge.setText(f"{'Motion' if latest and latest['kind'] == 'motion' else 'Snapshot'}  ·  "
                                   f"{datetime.fromtimestamp(latest['ts']):%a %H:%M}" if latest else "Off")
            self.cam_badge.setStyleSheet(f"QLabel{{{glass_style(11)}padding:3px 10px;font-size:11px;"
                                         "font-weight:700;}")
            self.cam_power.setToolTip("Start the cameras")
        cams = len(store.cameras)
        self.cam_line.setText(f"{'Armed' if armed else 'Disarmed'}  ·  {len(live)} of {cams} camera"
                              f"{'s' if cams != 1 else ''} live  ·  {motions} motion today")

    def _refresh_week(self, e, now, watching):
        days = e.daily_outage_hours(7, now)
        total = sum(h for _, h in days)
        longest = e.longest_outage_hours(now - 7 * 86400, now)
        self.week.set_bars([("Today" if i == len(days) - 1 else d.strftime("%a"), h,
                             f"{d:%a %d %b}: {_fmt_h(h)} without grid" if h else f"{d:%a %d %b}: no power cut",
                             i == len(days) - 1) for i, (d, h) in enumerate(days)])
        if not watching and not e.outages:
            self.week_note.setText("Not watching the grid yet: link a smart plug to the inverter input "
                                   "(Smart Devices) or turn on charger detection on the Smart Home page.")
            self._chip(self.week_chip, "Not watched", DIM)
        else:
            self.week_note.setText(f"{_fmt_h(total)} without grid in 7 days" +
                                   (f"  ·  longest cut {_fmt_h(longest)}" if longest else ""))
            avg = total / 7
            self._chip(self.week_chip, f"{avg:.1f} h a day", CRIT if avg >= 6 else WARN if avg >= 1 else GOOD)

    def _refresh_fridge(self, store):
        for w in self._f_labels:
            w.setParent(None)
        self._f_labels = []
        if store is None:
            return
        items = sorted(store.items(), key=lambda v: (not v["low"], v["days_left"] if v["days_left"] is not None
                                                      else 999, v["name"]))
        low = [v for v in items if v["low"]]
        if low:
            self._chip(self.f_chip, f"{len(low)} running low", CRIT)
        else:
            self.f_chip.hide()
        for v in items[:5]:
            row = QWidget()
            row.setStyleSheet("background:transparent;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 3, 0, 3)
            name = _lbl(v["name"], CRIT if v["low"] else TEXT, 13, 600)
            when = _lbl(("runs out today" if v["days_left"] < 1 else f"{v['days_left']:.0f} days left")
                        if v["days_left"] is not None else "", MUTED, 11, 500)
            est = v["estimate"]
            n = f"≈{est:.0f}" if v["rate"] and abs(est - v["count"]) >= 0.5 else str(v["count"])
            num = _lbl(n, CRIT if v["low"] else TEXT, 17, 600)
            rl.addWidget(name)
            rl.addStretch()
            rl.addWidget(when)
            rl.addSpacing(10)
            rl.addWidget(num)
            self.f_rows.addWidget(row)
            self._f_labels.append(row)
        if not items:
            hint = _lbl("Nothing tracked yet. Check a photo of the open fridge.", MUTED, 12, 500)
            hint.setWordWrap(True)
            self.f_rows.addWidget(hint)
            self._f_labels.append(hint)

    @staticmethod
    def _chip(label, text, color):
        label.setText(text)
        label.setStyleSheet(_chip_style(color))
        label.show()

    # --------------------------------------------------------------- actions --

    def _switch(self, item_id, want):
        it = self.sv.model.item(item_id)
        if it and it["device"]["on"] != want:
            self.sv._toggle(item_id)
        self.refresh()

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

    def _pick_room(self, key):
        self._room = key
        if key == "all":
            self.house.view.reset_camera()
        else:
            self.house.view.focus_room(key)
        self.refresh()

    def _cycle_cam(self, step):
        self._cam_index += step
        self.refresh()

    def _snapshot(self):
        live = self._feeds_with_picture()
        if live:
            self.cv.manual_snapshot(live[self._cam_index % len(live)])
        self.refresh()

    def _cam_power(self):
        live = self._feeds_with_picture()
        if live:
            self.cv.stop_camera(live[self._cam_index % len(live)])
        else:
            for f in self.cv.feeds.values():
                self.cv.start_camera(f)
        self.refresh()

    def _go(self, module_id):
        win = self.window()
        if hasattr(win, "navigate_by_id"):
            win.navigate_by_id(module_id)

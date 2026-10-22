"""
Home design system — the look of the Smart Home pages (and the Apps that sit with them).

Warm graphite surfaces with one orange accent, generous rounding and space, and a
few painted controls shared by every page:

  Toggle      the on/off switch used for appliances
  ArcDial     a 240° dial (live load against the inverter, like a thermostat)
  WeekBars    seven rounded bars (e.g. hours without grid per day)

`apply_home_style(widget)` gives a page the warm background and card styling without
touching the Server console, which keeps its own look.
"""
from PySide6.QtCore import Qt, QRectF, QPointF, QVariantAnimation, QEasingCurve, Signal, QSize
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QConicalGradient, QBrush
from PySide6.QtWidgets import QAbstractButton, QWidget, QToolTip, QSizePolicy

# ------------------------------------------------------------------ tokens --
ACCENT = "#ff7a1a"          # warm orange: on, selected, primary
ACCENT_HI = "#ffa25c"
ON_ACCENT = "#1c0d02"       # text / icons on the accent
GOOD = "#34d399"            # healthy: grid on, battery fine
WARN = "#fbbf24"
CRIT = "#f87171"
TEXT = "#fafaf9"
SOFT = "#d6d3d1"
MUTED = "#a8a29e"
DIM = "#78716c"
TRACK = QColor(255, 255, 255, 20)
CARD = "rgba(28, 26, 25, 0.94)"
CARD_LINE = "rgba(255, 255, 255, 0.07)"
PAGE_TOP, PAGE_BOTTOM = "#161412", "#0c0b0a"
GLASS = "rgba(22, 20, 18, 0.78)"   # floating chips over pictures / the 3D house

HOME_QSS = f"""
QFrame#panel {{
    background: {CARD};
    border: 1px solid {CARD_LINE};
    border-radius: 22px;
}}
QFrame#panel:hover {{ border: 1px solid rgba(255, 255, 255, 0.11); }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: rgba(255, 255, 255, 0.14); border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 10px;
    padding: 5px 9px; color: {TEXT};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}
QTableWidget {{ background: transparent; border: none; gridline-color: transparent; }}
QHeaderView::section {{ background: transparent; color: {MUTED}; border: none; padding: 6px; font-weight: 700; }}
QTableWidget::item {{ border-bottom: 1px solid rgba(255, 255, 255, 0.05); }}
QLabel#section-header {{ color: {TEXT}; font-size: 13px; font-weight: 700; letter-spacing: 1px; }}
QPushButton#action-btn-primary {{ background: {ACCENT}; color: {ON_ACCENT}; border: 1px solid {ACCENT}; }}
QPushButton#action-btn-primary:hover {{ background: {ACCENT_HI}; }}
QTextEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QProgressBar {{ background: rgba(255, 255, 255, 0.08); border: none; border-radius: 4px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
"""


def apply_home_style(widget):
    """Warm page background + home card styling for one page (scoped to that page)."""
    if not widget.objectName():
        widget.setObjectName(f"home_{type(widget).__name__}")
    widget.setAttribute(Qt.WA_StyledBackground, True)
    name = widget.objectName()
    widget.setStyleSheet(widget.styleSheet() + HOME_QSS +
                         f"#{name}{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                         f"stop:0 {PAGE_TOP},stop:1 {PAGE_BOTTOM});}}")


def rgba(color, alpha):
    c = QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


def pill_style(color, filled=False):
    """A small rounded label: tinted (status) or filled (selected)."""
    if filled:
        return (f"QLabel{{color:{ON_ACCENT};background:{color};border:none;border-radius:12px;"
                f"padding:4px 11px;font-size:11px;font-weight:800;}}")
    return (f"QLabel{{color:{TEXT};background:{rgba(color, 0.14)};border:1px solid {rgba(color, 0.38)};"
            f"border-radius:12px;padding:4px 11px;font-size:11px;font-weight:700;}}")


def glass_style(radius=16):
    return (f"background:{GLASS};border:1px solid rgba(255,255,255,0.10);border-radius:{radius}px;"
            f"color:{TEXT};")


# ----------------------------------------------------------------- controls --

class Toggle(QAbstractButton):
    """iOS-style switch: orange when on. Emits toggled(bool) like any checkable button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 26)
        self._t = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._step)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(46, 26)

    def set_on(self, on):
        """Set without emitting toggled (for showing state from the model)."""
        if self.isChecked() == bool(on):
            return
        self.blockSignals(True)
        self.setChecked(bool(on))
        self.blockSignals(False)
        self._t = 1.0 if on else 0.0
        self.update()

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _step(self, v):
        self._t = float(v)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        off, on = QColor(255, 255, 255, 34), QColor(ACCENT)
        track = QColor(int(off.red() + (on.red() - off.red()) * self._t),
                       int(off.green() + (on.green() - off.green()) * self._t),
                       int(off.blue() + (on.blue() - off.blue()) * self._t),
                       int(off.alpha() + (255 - off.alpha()) * self._t))
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.x() + 3 + (r.width() - d - 6) * self._t
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, r.y() + 3, d, d))
        p.end()


class ArcDial(QWidget):
    """240° dial with a knob at the value, the reading in the middle and the range under the ends."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 168)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.frac, self.value, self.unit, self.sub = 0.0, "", "", ""
        self.lo, self.hi, self.color = "", "", ACCENT

    def set(self, frac, value, unit="", sub="", lo="", hi="", color=ACCENT):
        self.frac = max(0.0, min(1.0, frac))
        self.value, self.unit, self.sub, self.lo, self.hi, self.color = value, unit, sub, lo, hi, color
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = 13
        side = min(self.width() - 16, (self.height() - 24) * 1.25)
        cx, cy = self.width() / 2, (self.height() - 24) / 2 + side * 0.06 + 6
        r = side / 2 - w
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        start, span = 210, -240                       # degrees, counter-clockwise from 3 o'clock
        p.setPen(QPen(TRACK, w, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, start * 16, span * 16)
        if self.frac > 0:
            g = QConicalGradient(QPointF(cx, cy), start)
            c = QColor(self.color)
            hi = QColor(c)
            hi.setHsl(c.hslHue(), c.hslSaturation(), min(255, c.lightness() + 40))
            g.setColorAt(0.0, hi)
            g.setColorAt(0.67, c)
            g.setColorAt(1.0, hi)
            p.setPen(QPen(QBrush(g), w, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, start * 16, int(span * self.frac * 16))
        # knob at the value
        import math
        ang = math.radians(start + span * self.frac)
        kx, ky = cx + r * math.cos(ang), cy - r * math.sin(ang)
        p.setPen(QPen(QColor(self.color), 3))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(kx, ky), w / 2 + 1, w / 2 + 1)
        # reading
        f = QFont()
        f.setPixelSize(int(max(22, min(40, r * 0.42))))
        f.setWeight(QFont.Light)
        p.setFont(f)
        p.setPen(QColor(TEXT))
        p.drawText(QRectF(cx - r, cy - r * 0.42, 2 * r, r * 0.55), Qt.AlignHCenter | Qt.AlignBottom, self.value)
        f.setPixelSize(12)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(SOFT))
        p.drawText(QRectF(cx - r, cy + r * 0.16, 2 * r, 18), Qt.AlignHCenter | Qt.AlignTop, self.unit)
        if self.sub:
            f.setWeight(QFont.Medium)
            f.setPixelSize(11)
            p.setFont(f)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(cx - r, cy + r * 0.16 + 18, 2 * r, 18), Qt.AlignHCenter | Qt.AlignTop, self.sub)
        # range labels under the two ends
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor(DIM))
        for text, deg, align in ((self.lo, start, Qt.AlignRight), (self.hi, start + span, Qt.AlignLeft)):
            a = math.radians(deg)
            x, y = cx + r * math.cos(a), cy - r * math.sin(a)
            box = QRectF(x - 60, y + w, 120, 16)
            p.drawText(box, Qt.AlignHCenter | Qt.AlignTop, text)
        p.end()


class WeekBars(QWidget):
    """Seven (or any number of) rounded bars with labels; the highlighted one is solid orange."""

    def __init__(self, parent=None, fmt=lambda v: f"{v:g}"):
        super().__init__(parent)
        self.bars = []           # (label, value, tooltip, highlight)
        self.fmt = fmt
        self.top = None          # fixed scale (e.g. 24 h) or None for the largest bar
        self.setMinimumHeight(150)
        self.setMouseTracking(True)
        self._hover = None

    def set_bars(self, bars, top=None):
        self.bars, self.top = bars, top
        self.update()

    def _slots(self):
        n = max(1, len(self.bars))
        area = QRectF(4, 22, self.width() - 8, self.height() - 44)
        slot = area.width() / n
        bw = min(26.0, slot * 0.52)
        return area, slot, bw

    def mouseMoveEvent(self, e):
        area, slot, _ = self._slots()
        i = int((e.position().x() - area.x()) // slot) if slot else -1
        i = i if 0 <= i < len(self.bars) else None
        if i != self._hover:
            self._hover = i
            self.update()
        if i is not None and self.bars[i][2]:
            QToolTip.showText(e.globalPosition().toPoint(), self.bars[i][2], self)

    def leaveEvent(self, _):
        self._hover = None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        area, slot, bw = self._slots()
        top = self.top or max([b[1] for b in self.bars] + [1e-9])
        f = QFont()
        f.setPixelSize(11)
        for i, (label, value, _tip, hi) in enumerate(self.bars):
            x = area.x() + slot * i + (slot - bw) / 2
            track = QRectF(x, area.y(), bw, area.height())
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 12))
            p.drawRoundedRect(track, bw / 2, bw / 2)
            if value > 0:
                h = max(bw, area.height() * min(1.0, value / top))
                bar = QRectF(x, area.bottom() - h, bw, h)
                c = QColor(ACCENT)
                if not hi and i != self._hover:
                    c.setAlpha(120)
                p.setBrush(c)
                p.drawRoundedRect(bar, bw / 2, bw / 2)
                if hi or i == self._hover:
                    f.setWeight(QFont.Bold)
                    p.setFont(f)
                    p.setPen(QColor(TEXT))
                    p.drawText(QRectF(x - 30, bar.y() - 19, bw + 60, 16), Qt.AlignHCenter, self.fmt(value))
            f.setWeight(QFont.DemiBold if hi else QFont.Medium)
            p.setFont(f)
            p.setPen(QColor(TEXT if hi else DIM))
            p.drawText(QRectF(x - 20, area.bottom() + 6, bw + 40, 16), Qt.AlignHCenter, label)
        p.end()


class Clickable(QWidget):
    """Plain container that emits clicked() — for rows and cards."""
    clicked = Signal()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

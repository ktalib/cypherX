"""
Shared building blocks for the Home (Widget Screen) canvas:
glass cards, crisp hi-dpi icons, persisted settings, async HTTP and small labels.
"""
import json

from PySide6.QtCore import Qt, QUrl, QByteArray, QSettings, QSize
from PySide6.QtGui import QPainter, QPixmap, QColor, QIcon
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QSizePolicy

from app.icons import get_svg_string
from app.widgets.home import skins

# Palette shared by every home card
TEXT = "#f8fafc"
TEXT_SOFT = "#cbd5e1"
MUTED = "#94a3b8"
DIM = "#64748b"
ACCENT = "#38bdf8"
WARM = "#f5be4b"
DANGER = "#f87171"

USER_AGENT = b"CypherX/1.0 (desktop widget screen)"


# ---------------------------------------------------------------------------
#  Icons rendered at 3x so they stay sharp when the canvas is scaled up
# ---------------------------------------------------------------------------

_HI_CACHE = {}


def hpix(name: str, color: str = "#ffffff", size: int = 16, stroke: float = 2.0) -> QPixmap:
    pm = render_icon(name, color, size, stroke)
    skins.PIXMAP_SPECS[pm.cacheKey()] = (name, color, size, stroke)
    return pm


def render_icon(name: str, color: str = "#ffffff", size: int = 16, stroke: float = 2.0) -> QPixmap:
    """Cached hi-dpi render; not registered with the skin engine (used for skinned copies)."""
    key = (name, color, size, stroke)
    if key in _HI_CACHE:
        return _HI_CACHE[key]
    ratio = 3
    renderer = QSvgRenderer(QByteArray(get_svg_string(name, color, stroke).encode("utf-8")))
    pm = QPixmap(size * ratio, size * ratio)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(p)
    p.end()
    pm.setDevicePixelRatio(ratio)
    _HI_CACHE[key] = pm
    return pm


def hicon(name: str, color: str = "#ffffff", size: int = 16, stroke: float = 2.0) -> QIcon:
    icon = QIcon(hpix(name, color, size, stroke))
    skins.ICON_SPECS[icon.cacheKey()] = (name, color, size, stroke)
    return icon


# ---------------------------------------------------------------------------
#  Settings persisted as JSON in QSettings (registry on Windows)
# ---------------------------------------------------------------------------

def load_setting(key: str, default):
    raw = QSettings().value(f"home/{key}")
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def save_setting(key: str, value) -> None:
    QSettings().setValue(f"home/{key}", json.dumps(value))


# ---------------------------------------------------------------------------
#  Async HTTP GET (never blocks the GUI thread)
# ---------------------------------------------------------------------------

_NAM = None


def http_get(url: str, callback, timeout_ms: int = 20000):
    """GET `url`; calls callback(data: bytes | None, error: str) on the GUI thread."""
    global _NAM
    if _NAM is None:
        _NAM = QNetworkAccessManager()
    req = QNetworkRequest(QUrl(url))
    req.setRawHeader(b"User-Agent", USER_AGENT)
    req.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                     QNetworkRequest.NoLessSafeRedirectPolicy)
    req.setTransferTimeout(timeout_ms)
    reply = _NAM.get(req)

    def _done():
        ok = reply.error() == QNetworkReply.NoError
        data = bytes(reply.readAll()) if ok else None
        err = "" if ok else reply.errorString()
        reply.deleteLater()
        try:
            callback(data, err)
        except RuntimeError:
            pass  # receiving widget was destroyed

    reply.finished.connect(_done)
    return reply


# ---------------------------------------------------------------------------
#  Widgets
# ---------------------------------------------------------------------------

class GlassCard(QFrame):
    """Semi-transparent liquid-glass card. Style is scoped to the card's objectName."""

    def __init__(self, name: str, bg="rgba(16,22,30,0.62)", border="rgba(255,255,255,0.13)",
                 radius=20, parent=None):
        super().__init__(parent)
        self.setObjectName(name)
        self._bg, self._border, self._radius = bg, border, radius
        self.setProperty("_skn_card", True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.apply_style()

    def set_background(self, bg: str):
        self._bg = bg
        self.apply_style()

    def apply_style(self):
        n = self.objectName()
        bg, border, hover, radius = skins.card_look(self)
        self.setStyleSheet(f"""
            QFrame#{n} {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {radius}px;
            }}
            QFrame#{n}:hover {{ border: 1px solid {hover}; }}
        """)


class ElidedLabel(QLabel):
    """Single-line label that elides with an ellipsis instead of growing its parent."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(10)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, rect.width())
        p.drawText(rect, int(self.alignment()) | Qt.TextSingleLine, text)


def label(text="", color=TEXT, size=12, weight=500, spacing=0.0, elide=False) -> QLabel:
    lbl = ElidedLabel(text) if elide else QLabel(text)
    lbl.setStyleSheet(f"color:{color};font-size:{size}px;font-weight:{weight};"
                      f"letter-spacing:{spacing}px;background:transparent;border:none;")
    return lbl


def card_header(text: str, icon: str, color=MUTED) -> tuple:
    """Small uppercase header row used by every card: returns (icon_label, title_label)."""
    ic = QLabel()
    ic.setPixmap(hpix(icon, color, 13))
    ic.setStyleSheet("background:transparent;border:none;")
    return ic, label(text.upper(), color, 10, 700, 1.0)


def icon_button(icon: str, tip: str = "", size: int = 28, icon_size: int = 15,
                color: str = "#ffffff", round_: bool = True) -> QPushButton:
    btn = QPushButton()
    btn.setIcon(hicon(icon, color, icon_size))
    btn.setIconSize(QSize(icon_size, icon_size))
    btn.setFixedSize(size, size)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setToolTip(tip)
    radius = size // 2 if round_ else 8
    btn.setStyleSheet(f"""
        QPushButton {{ background: transparent; border: none; border-radius: {radius}px; padding: 0; }}
        QPushButton:hover {{ background: rgba(255,255,255,0.14); }}
        QPushButton:pressed {{ background: rgba(255,255,255,0.22); }}
        QPushButton:checked {{ background: rgba(56,189,248,0.22); }}
    """)
    return btn


def pill_button(text: str, icon: str = None, accent: bool = False) -> QPushButton:
    btn = QPushButton(text)
    if icon:
        btn.setIcon(hicon(icon, "#ffffff" if not accent else "#0b1116", 13))
        btn.setIconSize(QSize(13, 13))
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedHeight(26)
    if accent:
        style = """QPushButton{background:#f8fafc;color:#0b1116;border:none;border-radius:13px;
                   font-size:11px;font-weight:700;padding:0 12px;}
                   QPushButton:hover{background:#e2e8f0;}"""
    else:
        style = """QPushButton{background:rgba(255,255,255,0.10);color:#f1f5f9;
                   border:1px solid rgba(255,255,255,0.10);border-radius:13px;
                   font-size:11px;font-weight:600;padding:0 12px;}
                   QPushButton:hover{background:rgba(255,255,255,0.20);}
                   QPushButton:checked{background:rgba(56,189,248,0.28);
                   border:1px solid rgba(56,189,248,0.45);color:#fff;}"""
    btn.setStyleSheet(style)
    return btn


MENU_STYLE = """
QMenu { background: rgba(14,20,27,0.97); border: 1px solid rgba(255,255,255,0.14);
        border-radius: 10px; padding: 6px; color: #f1f5f9; font-size: 12px; }
QMenu::item { padding: 6px 22px 6px 12px; border-radius: 6px; }
QMenu::item:selected { background: rgba(56,189,248,0.25); }
QMenu::item:disabled { color: #64748b; }
QMenu::separator { height: 1px; background: rgba(255,255,255,0.10); margin: 5px 6px; }
QMenu::indicator { width: 12px; height: 12px; margin-left: 4px; }
"""


def make_menu(parent=None):
    from PySide6.QtWidgets import QMenu
    menu = QMenu(parent)
    menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WA_TranslucentBackground, True)
    menu.setStyleSheet(MENU_STYLE)
    return menu


def fmt_ms(ms: int) -> str:
    s = max(0, int(ms) // 1000)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

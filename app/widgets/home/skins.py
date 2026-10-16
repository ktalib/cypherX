"""
Home screen skins — switchable looks for the widget canvas.

Every card is written once in the Liquid Glass palette. A skin re-colours the
whole canvas live, without rebuilding anything (music keeps playing, timers keep
running):

  • GlassCard backgrounds / borders / corner radius come straight from the skin
  • every other style sheet under the canvas is translated colour-by-colour
    (light skins invert neutrals, the sky-blue accent is swapped for the skin's)
  • icons made with hpix / hicon are re-rendered in the translated colour
  • custom-painted widgets call skin_color(self, QColor) in paintEvent

Individual cards can use their own palette (e.g. the pink card in "Pulse", the
dark weather card in "Daylight"), so text and icons inside them stay readable.
"""
import re
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QEvent
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QWidget, QLabel, QAbstractButton


# ---------------------------------------------------------------------------
#  Skin definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Palette:
    mode: str = "dark"            # "light" inverts neutral colours (white text -> dark text)
    card_bg: str = None           # None keeps the card's own background
    border: str = None
    hover: str = None
    accent: str = None            # replaces the sky-blue accent family
    neutral_sat: float = 1.0      # 0 turns slate greys into pure greys
    max_radius: int = None        # caps every border-radius (square HUD look)

    @property
    def identity(self):
        return (self.mode == "dark" and self.accent is None and self.neutral_sat == 1.0
                and self.max_radius is None)


@dataclass(frozen=True)
class Skin:
    key: str
    name: str
    description: str
    cards: Palette
    chrome: Palette                       # island, screen switcher, dock, hero clock
    overrides: dict = field(default_factory=dict)   # card objectName -> Palette
    radius: int = 20
    wallpaper: bool = True                # paint the wallpaper slideshow behind
    tint: tuple = None                    # (r, g, b, a) wash over the wallpaper to suit the skin
    bg: tuple = ("#0f2030", "#03080c")    # solid backdrop when wallpaper is off
    font: str = None
    hero_font: str = None
    hero_weight: int = 200
    hero_upper: bool = False
    swatch: tuple = ("#38bdf8", "#10161e")


KEEP = Palette()

SKINS = {
    "glass": Skin(
        "glass", "Liquid Glass", "Frosted cards over your wallpaper",
        cards=KEEP, chrome=KEEP, swatch=("#38bdf8", "#1e293b"),
    ),
    "midnight": Skin(
        "midnight", "Midnight", "Solid dark bento tiles",
        cards=Palette("dark", "rgba(28,28,31,0.84)", "rgba(255,255,255,0.05)", "rgba(255,255,255,0.14)",
                      "#0a84ff", 0.0),
        chrome=Palette("dark", "rgba(28,28,31,0.84)", "rgba(255,255,255,0.06)", "rgba(255,255,255,0.14)",
                       "#0a84ff", 0.0),
        overrides={"NotesCard": Palette(neutral_sat=0.0)},
        radius=26, tint=(0, 0, 0, 80), bg=("#101012", "#08080a"),
        font="Segoe UI Variable Display", swatch=("#0a84ff", "#1c1c1f"),
    ),
    "daylight": Skin(
        "daylight", "Daylight", "Bright white tiles, iOS style",
        cards=Palette("light", "rgba(255,255,255,0.86)", "rgba(0,0,0,0.05)", "rgba(0,0,0,0.14)",
                      "#0a7aff", 0.0),
        chrome=Palette("light", "rgba(255,255,255,0.92)", "rgba(0,0,0,0.06)",
                       "rgba(0,0,0,0.14)", "#0a7aff", 0.0),
        overrides={"WeatherCard": Palette("dark", "qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                                          "stop:0 #4a4d55, stop:1 #24262b)",
                                          "rgba(0,0,0,0)", "rgba(0,0,0,0.2)", "#4da3ff", 0.0),
                   "NotesCard": Palette(neutral_sat=0.0)},
        radius=26, tint=(243, 243, 246, 110), bg=("#f3f3f6", "#e4e5ea"),
        font="Segoe UI Variable Display", hero_weight=300, swatch=("#0a7aff", "#ffffff"),
    ),
    "pulse": Skin(
        "pulse", "Pulse", "Black tiles, pink highlights, mono digits",
        cards=Palette("dark", "rgba(6,6,6,0.84)", "rgba(255,255,255,0.04)", "rgba(249,184,212,0.45)",
                      "#f9b8d4", 0.0),
        chrome=Palette("dark", "rgba(6,6,6,0.84)", "rgba(255,255,255,0.05)", "rgba(249,184,212,0.45)",
                       "#f9b8d4", 0.0),
        overrides={
            "NotesCard": Palette(neutral_sat=0.0),
            "ActivityCard": Palette("light", "#f9bdd6", "rgba(0,0,0,0)", "rgba(0,0,0,0.25)",
                                    "#b0175a", 0.0),
            "UptimeCard": Palette("light", "#ffffff", "rgba(0,0,0,0)", "rgba(0,0,0,0.25)",
                                  "#d63384", 0.0),
            "TasksCard": Palette("light", "#ffffff", "rgba(0,0,0,0)", "rgba(0,0,0,0.25)",
                                 "#d63384", 0.0),
        },
        radius=22, tint=(24, 16, 22, 90), bg=("#2c2c31", "#1f1f23"),
        font="Cascadia Mono", hero_font="Cascadia Mono", hero_weight=600,
        swatch=("#f9b8d4", "#050505"),
    ),
    "hud": Skin(
        "hud", "Space HUD", "Sci-fi cockpit: radar core, live meters",
        cards=Palette("dark", "rgba(16,34,60,0.62)", "rgba(150,195,255,0.22)",
                      "rgba(170,210,255,0.55)", "#9fd0ff", 0.6, 3),
        chrome=Palette("dark", "rgba(16,34,60,0.66)", "rgba(150,195,255,0.22)",
                       "rgba(170,210,255,0.55)", "#9fd0ff", 0.6, 3),
        overrides={"NotesCard": Palette(max_radius=3)},
        radius=3, wallpaper=True, font="Bahnschrift", hero_font="Bahnschrift",
        hero_weight=300, hero_upper=True, swatch=("#7fd4ff", "#06122a"),
    ),
}

SKIN_ORDER = ["glass", "midnight", "daylight", "pulse", "hud"]
CHROME_CARDS = {"TopIsland", "ScreenControls", "DockCard"}

_active = SKINS["glass"]


def active() -> Skin:
    return _active


def get(key) -> Skin:
    return SKINS.get(key, SKINS["glass"])


# ---------------------------------------------------------------------------
#  Colour translation
# ---------------------------------------------------------------------------

_COLOR_RE = re.compile(
    r"(?<![\w-])#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![\w-])"
    r"|rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+%?)\s*)?\)"
    r"|(?<![\w-])(white|black)(?![\w-])"
)
_RADIUS_RE = re.compile(r"(border(?:-[a-z]+)*-radius\s*:\s*)(\d+)px")
_SKY = (180 / 360, 225 / 360)     # hue band of the glass accent family (#38bdf8, #0284c7 …)
_SKY_L = 0.60                      # lightness of #38bdf8


def map_rgb(r, g, b, pal: Palette):
    if pal.identity:
        return r, g, b
    c = QColor(r, g, b)
    h, s, l = c.hslHueF(), c.hslSaturationF(), c.lightnessF()
    if h < 0:
        h, s = 0.0, 0.0
    neutral = (max(r, g, b) - min(r, g, b)) / 255.0 < 0.18   # whites, blacks, slate greys
    if neutral:
        s *= pal.neutral_sat
        if pal.mode == "light":
            l = 1.0 - l
    elif pal.accent and _SKY[0] <= h <= _SKY[1]:
        a = QColor(pal.accent)
        shift = a.lightnessF() - _SKY_L
        h, s = max(0.0, a.hslHueF()), a.hslSaturationF()
        l = min(0.97, max(0.06, l + shift))
    elif pal.mode == "light" and l > 0.5:
        l = 0.40                                   # bright green / red / amber -> readable on white
    elif pal.mode == "dark" and l < 0.32:
        l = 1.0 - l                                # dark ink -> light ink on dark tiles
    out = QColor.fromHslF(h, min(1.0, s), min(1.0, max(0.0, l)))
    return out.red(), out.green(), out.blue()


def translate(qss: str, pal: Palette) -> str:
    if not qss or pal.identity:
        return qss

    def color(m):
        if m.group(1):
            hx = m.group(1)
            if len(hx) == 3:
                hx = "".join(ch * 2 for ch in hx)
            alpha = ""
            if len(hx) == 8:                       # Qt reads #AARRGGBB
                alpha, hx = hx[:2], hx[2:]
            r, g, b = (int(hx[i:i + 2], 16) for i in (0, 2, 4))
            r, g, b = map_rgb(r, g, b, pal)
            return f"#{alpha}{r:02x}{g:02x}{b:02x}"
        if m.group(6):
            v = 255 if m.group(6) == "white" else 0
            r, g, b = map_rgb(v, v, v, pal)
            return f"#{r:02x}{g:02x}{b:02x}"
        r, g, b = map_rgb(int(m.group(2)), int(m.group(3)), int(m.group(4)), pal)
        if m.group(5) is not None:
            return f"rgba({r},{g},{b},{m.group(5)})"
        return f"rgb({r},{g},{b})"

    out = _COLOR_RE.sub(color, qss)
    if pal.max_radius is not None:
        cap = pal.max_radius
        out = _RADIUS_RE.sub(lambda m: f"{m.group(1)}{min(int(m.group(2)), cap)}px", out)
    return out


def palette_for(widget) -> Palette:
    """Palette of the nearest enclosing card (or the chrome palette outside cards)."""
    skin = _active
    w = widget
    while w is not None:
        if w.property("_skn_card"):
            name = w.objectName()
            if name in skin.overrides:
                return skin.overrides[name]
            return skin.chrome if name in CHROME_CARDS else skin.cards
        if w.property("_skn_root"):
            break
        w = w.parentWidget()
    return skin.chrome


def skin_color(widget, color) -> QColor:
    """For paintEvent code: translate a glass-palette QColor for the active skin."""
    c = QColor(color)
    pal = palette_for(widget)
    if pal.identity:
        return c
    r, g, b = map_rgb(c.red(), c.green(), c.blue(), pal)
    return QColor(r, g, b, c.alpha())


def card_look(card):
    """(background, border, hover border, radius) for a GlassCard under the active skin."""
    skin = _active
    pal = palette_for(card)
    bg = pal.card_bg or translate(card._bg, pal)
    border = pal.border or translate(card._border, pal)
    hover = pal.hover or translate("rgba(255,255,255,0.24)", pal)
    radius = card._radius if skin.key == "glass" else min(card._radius + 6, skin.radius) \
        if card.objectName() in CHROME_CARDS else skin.radius
    if pal.max_radius is not None:
        radius = min(radius, pal.max_radius)
    return bg, border, hover, radius


# ---------------------------------------------------------------------------
#  Icon registry (filled by common.hpix / hicon)
# ---------------------------------------------------------------------------

PIXMAP_SPECS = {}   # QPixmap.cacheKey() -> (name, color, size, stroke)
ICON_SPECS = {}     # QIcon.cacheKey()   -> (name, color, size, stroke)


def _mapped_color(color: str, pal: Palette) -> str:
    return translate(color, pal)


# ---------------------------------------------------------------------------
#  Engine
# ---------------------------------------------------------------------------

class SkinEngine(QObject):
    """Keeps every widget under `root` styled for the active skin, including widgets
    created later and style sheets / icons that cards change on the fly."""

    _WATCH = (QEvent.StyleChange, QEvent.Polish, QEvent.ChildAdded, QEvent.Paint)

    def __init__(self, root: QWidget):
        super().__init__(root)
        self.root = root
        root.setProperty("_skn_root", True)

    def apply(self, key: str):
        global _active
        _active = get(key)
        self._walk(self.root, force=True)
        for w in [self.root] + self.root.findChildren(QWidget):
            w.update()

    # ---------------------------------------------------------------- walk --

    def _walk(self, w, force=False):
        self._process(w, force)
        for ch in w.findChildren(QWidget):
            self._process(ch, force)

    def _process(self, w, force=False):
        if not w.property("_skn_seen"):
            w.setProperty("_skn_seen", True)
            w.installEventFilter(self)
        if w.property("_skn_card"):
            if force:
                w.apply_style()
        else:
            self._restyle(w, force)
        self._reicon(w, force)

    def _restyle(self, w, force):
        cur = w.styleSheet()
        out = w.property("_skn_out")
        if cur == out and not force:
            return
        if cur != out or w.property("_skn_src") is None:
            w.setProperty("_skn_src", cur)          # the card changed its own style sheet
        src = w.property("_skn_src") or ""
        new = translate(src, palette_for(w))
        w.setProperty("_skn_out", new)
        if new != cur:
            w.setStyleSheet(new)

    def _reicon(self, w, force):
        if isinstance(w, QLabel):
            pm = w.pixmap()
            if pm is None or pm.isNull():
                return
            key = pm.cacheKey()
            if key == w.property("_skn_ikey") and not force:
                return
            spec = PIXMAP_SPECS.get(key)
            if spec is None and key != w.property("_skn_ikey"):
                return                                   # a photo / cover art, leave it
            spec = spec or w.property("_skn_ispec")
            if spec is None:
                return
            w.setProperty("_skn_ispec", spec)
            from app.widgets.home.common import render_icon
            name, color, size, stroke = spec
            new = render_icon(name, _mapped_color(color, palette_for(w)), size, stroke)
            w.setProperty("_skn_ikey", new.cacheKey())
            w.setPixmap(new)
        elif isinstance(w, QAbstractButton):
            ic = w.icon()
            if ic.isNull():
                return
            key = ic.cacheKey()
            if key == w.property("_skn_ikey") and not force:
                return
            spec = ICON_SPECS.get(key)
            if spec is None and key != w.property("_skn_ikey"):
                return
            spec = spec or w.property("_skn_ispec")
            if spec is None:
                return
            w.setProperty("_skn_ispec", spec)
            from app.widgets.home.common import render_icon
            name, color, size, stroke = spec
            new = QIcon(render_icon(name, _mapped_color(color, palette_for(w)), size, stroke))
            w.setProperty("_skn_ikey", new.cacheKey())
            w.setIcon(new)

    # -------------------------------------------------------------- events --

    def eventFilter(self, obj, event):
        t = event.type()
        if t not in self._WATCH or not isinstance(obj, QWidget):
            return False
        if t == QEvent.ChildAdded:
            ch = event.child()
            if isinstance(ch, QWidget):
                self._walk(ch)
        elif t == QEvent.Paint:
            if isinstance(obj, (QLabel, QAbstractButton)):
                self._reicon(obj, False)
        elif t == QEvent.StyleChange:
            if not obj.property("_skn_card") and obj.styleSheet() != obj.property("_skn_out"):
                self._restyle(obj, False)
        else:   # Polish
            self._process(obj, False)
        return False

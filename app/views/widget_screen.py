"""
Home — Liquid Glass widget screen (widgetscreen.app / macOS Sonoma inspired).

How it fits without a scroll bar
--------------------------------
All widgets live on one canvas laid out at a fixed *logical* height (BASE_H).
The canvas sits in a QGraphicsView and is scaled uniformly to the window, so the
page always fills the viewport exactly — windowed, maximised or full screen —
and everything stays clickable. The wallpaper slideshow is painted behind it in
real screen pixels, so photos stay sharp.

Features
  • Full screen / immersive mode (button, F11, Esc to leave)
  • Wallpaper slideshow with crossfade: images or folders from the PC, a single
    image URL, or an online feed that auto-loads a fresh photo on every slide
  • Working music player, live weather, calendar, focus timer, tasks, notes,
    system gauges, world clocks and a quick-launch dock
  • Show / hide individual widgets, or Focus mode (clock + wallpaper only)
  • Several named widget screens, each with its own skin. Every skin has its own
    layout and its own widgets (CATALOG): Liquid Glass (clock + cards + dock),
    Midnight / Daylight / Pulse (bento walls) and Space HUD (game pause menu)
"""
import getpass
from datetime import datetime

from PySide6.QtCore import (
    Qt, QTimer, QRectF, QSize, QVariantAnimation, QEasingCurve, Signal
)
from PySide6.QtGui import (
    QPainter, QColor, QPixmap, QIcon, QImage, QLinearGradient,
    QTransform, QKeySequence, QShortcut, QCursor
)
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QSizePolicy, QFileDialog, QInputDialog, QPushButton
)

from app.widgets.home.common import (
    GlassCard, label, icon_button, hicon, make_menu, load_setting, save_setting, MUTED
)
from app.widgets.home import skins
from app.widgets.home.skins import SkinEngine, SKINS, SKIN_ORDER
from app.widgets.home.wallpaper import WallpaperManager, WallpaperDialog
from app.widgets.home.music import MusicPlayerWidget
from app.widgets.home.weather import WeatherWidget
from app.widgets.home.cards import (
    CalendarWidget, NotesCard, TasksWidget, FocusTimerWidget, SystemWidget,
    ClocksWidget, QuickDock
)
from app.widgets.home.bento import (
    WatchCard, ToggleCard, NetSpeedCard, BatteryCard, StorageCard, AgendaCard,
    DayProgressCard, SunCard
)
from app.widgets.home.pulse import PulseCard, ActivityCard, StreakCard, UptimeCard, NetDotCard
from app.widgets.home.hud import (
    HudBar, HudSystems, HudNet, HudMenu, HudReactor, HudBadges, HudFeatured, HudFeed
)

BASE_H = 820          # logical canvas height everything is designed for
MIN_W = 1180          # narrowest logical width before we scale by width instead
CARD_H = 214          # classic (Liquid Glass) tile height
BENTO_ROWS = 3
BENTO_ROW_H = 236     # (BASE_H - margins - top row - gaps) / 3
COLUMNS = 4

# Every skin has its own layout and its own widget catalog: (key, name, colspan, rowspan)
LAYOUT_KIND = {"glass": "classic", "midnight": "bento", "daylight": "bento",
               "pulse": "bento", "hud": "hud"}
CAPACITY = {"classic": COLUMNS * 2, "bento": COLUMNS * BENTO_ROWS}
CATALOG = {
    "glass": [
        ("weather", "Weather", 1, 1), ("music", "Music Player", 1, 1),
        ("calendar", "Calendar", 1, 1), ("focus", "Focus Timer", 1, 1),
        ("notes", "Notes", 1, 1), ("tasks", "Tasks", 1, 1),
        ("system", "System", 1, 1), ("clocks", "World Clocks", 1, 1),
    ],
    "midnight": [
        ("watch", "Watch face", 1, 1), ("weather", "Weather", 1, 1),
        ("music", "Music Player", 1, 1), ("toggles", "Quick toggles", 1, 1),
        ("net", "Network graph", 2, 1), ("system", "System", 1, 1),
        ("battery", "Power", 1, 1), ("focus", "Focus Timer", 1, 1),
        ("notes", "Notes", 1, 1), ("clocks", "World Clocks", 1, 1),
        ("storage", "Device storage", 1, 1), ("tasks", "Tasks", 1, 1),
    ],
    "daylight": [
        ("agenda", "Agenda", 2, 1), ("weather", "Weather", 1, 1),
        ("storage", "Device storage", 1, 1), ("tasks", "Tasks", 1, 1),
        ("music", "Music Player", 1, 1), ("toggles", "Quick toggles", 1, 1),
        ("sun", "Daylight arc", 1, 1), ("notes", "Notes", 1, 1),
        ("progress", "Time left", 1, 1), ("clocks", "World Clocks", 1, 1),
        ("focus", "Focus Timer", 1, 1), ("calendar", "Calendar", 1, 1),
    ],
    "pulse": [
        ("focus", "Focus Timer", 1, 1), ("netdot", "Downloaded", 1, 1),
        ("streak", "Focus streak", 1, 1), ("system", "System", 1, 1),
        ("pulse", "CPU pulse", 1, 1), ("activity", "Activity", 2, 1),
        ("uptime", "Uptime & streak", 1, 1), ("music", "Music Player", 1, 1),
        ("weather", "Weather", 2, 1), ("notes", "Notes", 1, 1),
        ("tasks", "Tasks", 1, 1),
    ],
    "hud": [
        ("hud_bar", "Status strip", 1, 1), ("hud_systems", "Systems meters", 1, 1),
        ("hud_net", "Uplink", 1, 1), ("hud_menu", "Navigation", 1, 1),
        ("hud_reactor", "Radar core", 1, 1), ("hud_badges", "Quick-jump hexes", 1, 1),
        ("hud_featured", "Visual feed (wallpaper)", 1, 1), ("hud_feed", "Mission log", 1, 1),
    ],
}
DEFAULT_LAYOUT = {
    "glass": [k for k, *_ in CATALOG["glass"]],
    "midnight": [k for k, *_ in CATALOG["midnight"] if k != "tasks"],
    "daylight": [k for k, *_ in CATALOG["daylight"] if k != "calendar"],
    "pulse": [k for k, *_ in CATALOG["pulse"] if k != "tasks"],
    "hud": [k for k, *_ in CATALOG["hud"]],
}


def _swatch_icon(skin):
    """Little two-tone tile previewing a skin in menus."""
    pm = QPixmap(36, 36)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QColor(255, 255, 255, 60))
    p.setBrush(QColor(skin.swatch[1]))
    p.drawRoundedRect(QRectF(2, 2, 32, 32), 8, 8)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(skin.swatch[0]))
    p.drawEllipse(QRectF(11, 11, 14, 14))
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


# ---------------------------------------------------------------------------
#  Top control island
# ---------------------------------------------------------------------------

class TopIsland(GlassCard):
    def __init__(self, parent=None):
        super().__init__("TopIsland", bg="rgba(10,14,20,0.70)", radius=20, parent=parent)
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(8, 0, 8, 0)
        lo.setSpacing(2)

        self.prev_btn = icon_button("chevron_left", "Previous wallpaper", 28, 15)
        self.wp_btn = icon_button("images", "Wallpapers", 28, 15)
        self.next_btn = icon_button("chevron_right", "Next wallpaper", 28, 15)
        self.play_btn = icon_button("pause", "Pause slideshow", 28, 13)
        for b in (self.prev_btn, self.wp_btn, self.next_btn, self.play_btn):
            lo.addWidget(b)

        lo.addSpacing(8)
        self.status = label("", MUTED, 11, 600)
        self.status.setMinimumWidth(150)
        self.status.setAlignment(Qt.AlignCenter)
        lo.addWidget(self.status, 1)
        lo.addSpacing(8)

        self.widgets_btn = icon_button("widgets", "Show / hide widgets", 28, 15)
        self.focus_btn = icon_button("eye", "Focus mode — hide all widgets", 28, 15)
        self.fs_btn = icon_button("maximize", "Full screen (F11)", 28, 14)
        for b in (self.widgets_btn, self.focus_btn, self.fs_btn):
            lo.addWidget(b)


# ---------------------------------------------------------------------------
#  Canvas holding every widget (scaled as one unit)
# ---------------------------------------------------------------------------

class HomeCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("HomeCanvas")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("QWidget#HomeCanvas { background: transparent; }")


class Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("""
            QLabel { background: rgba(10,14,20,0.88); color: #f1f5f9; border-radius: 16px;
                     border: 1px solid rgba(255,255,255,0.16); padding: 8px 18px;
                     font-size: 12px; font-weight: 600; }
        """)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def reposition(self):
        par = self.parentWidget()
        self.move(par.width() - self.width() - 22, 18)

    def show_message(self, text: str, ms: int = 2800):
        self.setText(text)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._timer.start(ms)


# ---------------------------------------------------------------------------
#  The view
# ---------------------------------------------------------------------------

class WidgetScreenView(QGraphicsView):
    navigate_to_module = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing
                            | QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setStyleSheet("QGraphicsView { border: none; background: #070b0e; }")
        for sb in (self.horizontalScrollBar(), self.verticalScrollBar()):
            sb.valueChanged.connect(lambda v, sb=sb: v and sb.setValue(sb.minimum()))

        # Background state
        self._src_cur = None       # QImage
        self._src_next = None
        self._bg_cur = None        # QPixmap scaled to the viewport
        self._bg_next = None
        self._fade = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(1100)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.valueChanged.connect(self._on_fade)
        self._anim.finished.connect(self._end_fade)

        self.wallpapers = WallpaperManager(self)
        self.wallpapers.image_ready.connect(self._set_background)
        self.wallpapers.state_changed.connect(self._sync_island)
        self.wallpapers.message.connect(self.toast)

        self._focus_mode = bool(load_setting("focus_mode", False))
        plain = load_setting("plain_bg_skins", [])
        self._plain_bg = set(plain) if isinstance(plain, list) else set()
        self._clock_24h = bool(load_setting("clock_24h", True))
        self._screens = self._load_screens()
        saved_screen = load_setting("current_screen", 0)
        if not isinstance(saved_screen, int) or isinstance(saved_screen, bool):
            saved_screen = 0
        self._current_screen = min(
            max(0, saved_screen), len(self._screens) - 1
        )

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.canvas = HomeCanvas()
        self._build_canvas()
        self._proxy = self._scene.addWidget(self.canvas)
        self.skin_engine = SkinEngine(self.canvas)
        self._rebuild()

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick)
        self._clock_timer.start(1000)
        self._tick()

        for key, slot in [(Qt.Key_MediaTogglePlayPause, self.music.toggle_play),
                          (Qt.Key_MediaPlay, self.music.toggle_play),
                          (Qt.Key_MediaNext, self.music.next),
                          (Qt.Key_MediaPrevious, self.music.previous)]:
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(slot)

        self._sync_island()
        QTimer.singleShot(0, self.wallpapers.start)

    # ------------------------------------------------------------ building --

    def _build_canvas(self):
        self._root = QVBoxLayout(self.canvas)
        self._root.setContentsMargins(22, 14, 22, 16)
        self._root.setSpacing(0)
        self._stage = None
        self._parking = QWidget(self.canvas)       # holds widgets the current skin doesn't use
        self._parking.hide()

        # control island
        self.island = TopIsland()
        self.island.setFixedWidth(520)
        self.island.prev_btn.clicked.connect(self.wallpapers.prev)
        self.island.next_btn.clicked.connect(self.wallpapers.next)
        self.island.play_btn.clicked.connect(
            lambda: self.wallpapers.set_playing(not self.wallpapers.playing))
        self.island.wp_btn.clicked.connect(self._wallpaper_menu)
        self.island.widgets_btn.clicked.connect(self._widgets_menu)
        self.island.focus_btn.clicked.connect(self.toggle_focus_mode)
        self.island.fs_btn.clicked.connect(self.toggle_fullscreen)

        # hero clock
        self.hero = QWidget()
        self.hero.setStyleSheet("background:transparent;")
        hero = QVBoxLayout(self.hero)
        hero.setContentsMargins(0, 0, 0, 0)
        hero.setSpacing(0)
        self._date_lbl = label("", "rgba(255,255,255,0.88)", 19, 600, 0.5)
        self._date_lbl.setAlignment(Qt.AlignCenter)
        self._clock_lbl = label("", "rgba(255,255,255,0.96)", 112, 200, -3)
        self._clock_lbl.setAlignment(Qt.AlignCenter)
        self._clock_lbl.setCursor(Qt.PointingHandCursor)
        self._clock_lbl.setToolTip("Click to switch 12 / 24-hour")
        self._clock_lbl.mousePressEvent = lambda e: self._toggle_clock_format()
        self._greet_lbl = label("", "rgba(255,255,255,0.78)", 14, 500, 0.3)
        self._greet_lbl.setAlignment(Qt.AlignCenter)
        hero.addWidget(self._date_lbl)
        hero.addWidget(self._clock_lbl)
        hero.addWidget(self._greet_lbl)

        # screen switcher
        self.screen_controls = GlassCard("ScreenControls", bg="rgba(10,14,20,0.70)", radius=18)
        self.screen_controls.setFixedHeight(36)
        self.screen_controls.setFixedWidth(316)
        self.screen_controls.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        screen_row = QHBoxLayout(self.screen_controls)
        screen_row.setContentsMargins(6, 2, 6, 2)
        screen_row.setSpacing(4)
        self.screen_prev_btn = icon_button("chevron_left", "Previous widget screen", 28, 14)
        self.screen_name_btn = QPushButton()
        self.screen_name_btn.setCursor(Qt.PointingHandCursor)
        self.screen_name_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;color:#e2e8f0;"
            "font-size:11px;font-weight:700;padding:0 8px;}"
            "QPushButton:hover{color:#7dd3fc;}"
        )
        self.screen_next_btn = icon_button("chevron_right", "Next widget screen", 28, 14)
        self.screen_add_btn = icon_button("plus", "Add a widget screen", 28, 14)
        self.screen_skin_btn = icon_button("palette", "Change this screen's skin", 28, 14)
        self.screen_skin_btn.clicked.connect(self._skins_menu)
        self.screen_prev_btn.clicked.connect(lambda: self._switch_screen(self._current_screen - 1))
        self.screen_next_btn.clicked.connect(lambda: self._switch_screen(self._current_screen + 1))
        self.screen_name_btn.clicked.connect(self._screens_menu)
        self.screen_add_btn.clicked.connect(lambda: self._add_screen(copy_current=False))
        for b in (self.screen_prev_btn, self.screen_name_btn, self.screen_next_btn,
                  self.screen_add_btn, self.screen_skin_btn):
            screen_row.addWidget(b, 1 if b is self.screen_name_btn else 0)

        # every widget any skin can show — created once, moved between layouts
        self.weather = WeatherWidget()
        self.music = MusicPlayerWidget()
        self.calendar = CalendarWidget()
        self.focus = FocusTimerWidget()
        self.notes = NotesCard()
        self.tasks = TasksWidget()
        self.system = SystemWidget()
        self.clocks = ClocksWidget()
        self.toggles = ToggleCard()
        self.storage = StorageCard()
        self.agenda = AgendaCard()
        self.sun = SunCard()
        self.hud_featured = HudFeatured()
        self.hud_reactor = HudReactor()
        self.cards = {
            "weather": self.weather, "music": self.music, "calendar": self.calendar,
            "focus": self.focus, "notes": self.notes, "tasks": self.tasks,
            "system": self.system, "clocks": self.clocks,
            # Midnight
            "watch": WatchCard(), "toggles": self.toggles, "net": NetSpeedCard(),
            "battery": BatteryCard(), "storage": self.storage,
            # Daylight
            "agenda": self.agenda, "sun": self.sun, "progress": DayProgressCard(),
            # Pulse
            "pulse": PulseCard(), "activity": ActivityCard(), "streak": StreakCard(),
            "uptime": UptimeCard(), "netdot": NetDotCard(),
            # Space HUD
            "hud_bar": HudBar(), "hud_systems": HudSystems(), "hud_net": HudNet(),
            "hud_menu": HudMenu(), "hud_reactor": self.hud_reactor, "hud_badges": HudBadges(),
            "hud_featured": self.hud_featured, "hud_feed": HudFeed(),
        }
        self.music.message.connect(self.toast)
        self.focus.finished.connect(lambda m: self.toast(m, 5000))
        self.system.open_monitor.connect(lambda: self.navigate_to_module.emit("system_monitor"))
        for key in ("storage", "agenda", "hud_badges", "hud_menu", "hud_feed"):
            self.cards[key].navigate.connect(self.navigate_to_module.emit)
        self.toggles.theme_toggle.connect(self._flip_day_night)
        self.hud_featured.prev.connect(self.wallpapers.prev)
        self.hud_featured.next.connect(self.wallpapers.next)
        for target in (self.sun, self.hud_reactor):
            self.weather.data_changed.connect(target.set_weather)
            if self.weather._data:
                target.set_weather(self.weather._data)

        self.dock = QuickDock()
        self.dock.navigate.connect(self.navigate_to_module.emit)

        self._persistent = [self.island, self.hero, self.screen_controls, self.dock,
                            *self.cards.values()]
        for w in self._persistent:
            w.setParent(self._parking)

        self.toast_lbl = Toast(self.canvas)
        self._update_screen_controls()

    # -------------------------------------------------------------- layouts --

    def _skin_key(self):
        return self._screens[self._current_screen].get("skin", "glass")

    def _visible_keys(self):
        screen = self._screens[self._current_screen]
        skin = self._skin_key()
        keys = screen.setdefault("layouts", {}).get(skin)
        if keys is None:
            keys = list(DEFAULT_LAYOUT[skin])
        valid = {k for k, *_ in CATALOG[skin]}
        return [k for k, *_ in CATALOG[skin] if k in keys and k in valid]

    def _rebuild(self):
        """Lay the canvas out for the current screen's skin and widget choice."""
        for w in self._persistent:
            w.setParent(self._parking)
            if isinstance(w, GlassCard) and w not in (self.island, self.screen_controls, self.dock):
                w.setMinimumWidth(0)
                w.setMaximumWidth(16777215)
        if self._stage is not None:
            self._root.removeWidget(self._stage)
            self._stage.deleteLater()
        self._stage = QWidget()
        self._stage.setStyleSheet("background:transparent;")
        skin = self._skin_key()
        kind = "focus" if self._focus_mode else LAYOUT_KIND[skin]
        used = getattr(self, f"_layout_{kind}")(self._stage)
        self._root.addWidget(self._stage)
        for w in used:
            w.show()
        self.toast_lbl.raise_()
        self.island.focus_btn.setIcon(hicon("eye_off" if self._focus_mode else "eye", "#ffffff", 15))
        self._apply_skin()

    def _row(self, *widgets, spacing=12):
        row = QHBoxLayout()
        row.setSpacing(spacing)
        row.addStretch(1)
        for w in widgets:
            row.addWidget(w)
        row.addStretch(1)
        return row

    def _layout_focus(self, stage):
        lo = QVBoxLayout(stage)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.addLayout(self._row(self.island))
        lo.addStretch(1)
        lo.addWidget(self.hero)
        lo.addStretch(1)
        lo.addLayout(self._row(self.screen_controls))
        return [self.island, self.hero, self.screen_controls]

    def _layout_classic(self, stage):
        """Liquid Glass: island · big clock · one row of four-wide cards · dock."""
        lo = QVBoxLayout(stage)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)
        lo.addLayout(self._row(self.island))
        lo.addStretch(1)
        lo.addWidget(self.hero)
        lo.addStretch(1)
        lo.addLayout(self._row(self.screen_controls))
        lo.addSpacing(8)
        keys = self._visible_keys()
        grid = self._grid([(k, 1, 1) for k in keys], CARD_H, max_rows=2)
        lo.addLayout(grid)
        lo.addSpacing(14)
        lo.addLayout(self._row(self.dock))
        return [self.island, self.hero, self.screen_controls, self.dock] + \
               [self.cards[k] for k in keys]

    def _layout_bento(self, stage):
        """Midnight / Daylight / Pulse: a wall of tiles, some spanning two columns."""
        lo = QVBoxLayout(stage)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(14)
        lo.addLayout(self._row(self.island, self.screen_controls))
        spans = {k: (cs, rs) for k, _, cs, rs in CATALOG[self._skin_key()]}
        keys = self._visible_keys()
        lo.addLayout(self._grid([(k, *spans[k]) for k in keys], BENTO_ROW_H, max_rows=BENTO_ROWS))
        lo.addStretch(1)
        return [self.island, self.screen_controls] + [self.cards[k] for k in keys]

    def _grid(self, items, row_h, max_rows):
        """Dense-pack (key, colspan, rowspan) tiles into COLUMNS columns."""
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        for c in range(COLUMNS):
            grid.setColumnStretch(c, 1)
        taken = set()
        for key, cs, rs in items:
            placed = False
            for r in range(max_rows):
                for c in range(COLUMNS - cs + 1):
                    cells = {(r + i, c + j) for i in range(rs) for j in range(cs)}
                    if r + rs <= max_rows and not cells & taken:
                        taken |= cells
                        card = self.cards[key]
                        card.setFixedHeight(row_h * rs + 14 * (rs - 1))
                        grid.addWidget(card, r, c, rs, cs)
                        placed = True
                        break
                if placed:
                    break
        return grid

    def _layout_hud(self, stage):
        """Space HUD cockpit: systems + navigation left, radar core centre, feeds right."""
        keys = set(self._visible_keys())
        c = self.cards
        used = [self.island, self.screen_controls]

        def take(key, col, stretch=0, height=None):
            if key in keys:
                if height:
                    c[key].setFixedHeight(height)
                col.addWidget(c[key], stretch)
                used.append(c[key])

        lo = QVBoxLayout(stage)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(12)
        lo.addLayout(self._row(self.island, self.screen_controls))
        take("hud_bar", lo)

        main = QHBoxLayout()
        main.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(12)
        take("hud_systems", left, 0, 230)
        take("hud_net", left, 1)
        take("hud_menu", left, 0, 252)
        center = QVBoxLayout()
        center.setSpacing(4)
        take("hud_reactor", center, 1)
        take("hud_badges", center, 0, 88)
        right = QVBoxLayout()
        right.setSpacing(12)
        take("hud_featured", right, 0, 250)
        take("hud_feed", right, 1)
        for col, width in ((left, 300), (center, None), (right, 330)):
            host = QWidget()
            host.setStyleSheet("background:transparent;")
            host.setLayout(col)
            if width:
                host.setFixedWidth(width)
            col.addStretch(0)
            main.addWidget(host, 0 if width else 1)
        lo.addLayout(main, 1)
        return used

    # ---------------------------------------------------------------- skins --

    def _apply_skin(self):
        skin = SKINS[self._skin_key()]
        font = f"font-family:'{skin.font}';" if skin.font else ""
        self.canvas.setStyleSheet(
            f"QWidget#HomeCanvas {{ background: transparent; }} QWidget {{ {font} }}")
        hero = f"font-family:'{skin.hero_font}';" if skin.hero_font else ""
        self._clock_lbl.setStyleSheet(
            f"color:rgba(255,255,255,0.96);font-size:112px;font-weight:{skin.hero_weight};"
            f"letter-spacing:{0 if skin.hero_font else -3}px;background:transparent;"
            f"border:none;{hero}")
        self._date_lbl.setStyleSheet(
            f"color:rgba(255,255,255,0.88);font-size:19px;font-weight:600;"
            f"letter-spacing:{2.5 if skin.hero_upper else 0.5}px;background:transparent;"
            f"border:none;{hero}")
        self._hero_upper = skin.hero_upper
        self.toggles.set_light(skin.cards.mode == "light")
        self.skin_engine.apply(skin.key)
        self._tick()
        self.viewport().update()

    def set_screen_skin(self, key):
        if key not in SKINS:
            return
        self._screens[self._current_screen]["skin"] = key
        self._save_screens()
        self._rebuild()
        self.toast(f"Skin: {SKINS[key].name}")

    def _flip_day_night(self):
        self.set_screen_skin("midnight" if self._skin_key() == "daylight" else "daylight")

    def _add_skin_actions(self, menu):
        current = self._skin_key()
        for key in SKIN_ORDER:
            skin = SKINS[key]
            a = menu.addAction(_swatch_icon(skin), f"{skin.name}   ·   {skin.description}")
            a.setCheckable(True)
            a.setChecked(key == current)
            a.triggered.connect(lambda _=False, k=key: self.set_screen_skin(k))

    def _skins_menu(self):
        menu = make_menu(self)
        self._add_skin_actions(menu)
        menu.exec(self.screen_skin_btn.mapToGlobal(self.screen_skin_btn.rect().bottomLeft()))

    # -------------------------------------------------------------- screens --

    def _load_screens(self):
        saved = load_setting("widget_screens", None)
        screens = []
        if isinstance(saved, list):
            for screen in saved:
                if not isinstance(screen, dict) or not isinstance(screen.get("name"), str):
                    continue
                skin = screen.get("skin") if screen.get("skin") in SKINS else "glass"
                layouts = {}
                raw = screen.get("layouts")
                if isinstance(raw, dict):
                    for k, v in raw.items():
                        if k in SKINS and isinstance(v, list):
                            layouts[k] = [x for x in v if isinstance(x, str)]
                elif isinstance(screen.get("cards"), list):     # older single-layout format
                    layouts["glass"] = [x for x in screen["cards"] if isinstance(x, str)]
                screens.append({"name": screen["name"].strip() or f"Screen {len(screens) + 1}",
                                "skin": skin, "layouts": layouts})
        return screens or [{"name": "Home", "skin": "glass", "layouts": {}}]

    def _save_screens(self):
        save_setting("widget_screens", self._screens)
        save_setting("current_screen", self._current_screen)

    def _update_screen_controls(self):
        screen = self._screens[self._current_screen]
        self.screen_name_btn.setText(
            f"{screen['name']}  ·  {self._current_screen + 1} / {len(self._screens)}  ▾"
        )
        multiple = len(self._screens) > 1
        self.screen_prev_btn.setEnabled(multiple)
        self.screen_next_btn.setEnabled(multiple)

    def _switch_screen(self, index):
        self._current_screen = index % len(self._screens)
        self._save_screens()
        self._update_screen_controls()
        self._rebuild()

    def _screens_menu(self):
        menu = make_menu(self)
        for index, screen in enumerate(self._screens):
            action = menu.addAction(
                f"{'✓  ' if index == self._current_screen else '    '}{screen['name']}"
                f"   ·   {SKINS[screen.get('skin', 'glass')].name}"
            )
            action.triggered.connect(lambda _=False, i=index: self._switch_screen(i))
        menu.addSeparator()
        style = make_menu(menu)
        style.setTitle("Skin for this screen")
        self._add_skin_actions(style)
        menu.addMenu(style)
        menu.addSeparator()
        menu.addAction("Add blank screen…", lambda: self._add_screen(copy_current=False))
        menu.addAction("Duplicate this screen…", lambda: self._add_screen(copy_current=True))
        menu.addSeparator()
        menu.addAction("Rename this screen…", self._rename_screen)
        remove = menu.addAction("Delete this screen")
        remove.setEnabled(len(self._screens) > 1)
        remove.triggered.connect(self._delete_screen)
        menu.exec(self.screen_name_btn.mapToGlobal(self.screen_name_btn.rect().bottomLeft()))

    def _add_screen(self, copy_current=False):
        default_name = f"Screen {len(self._screens) + 1}"
        name, accepted = QInputDialog.getText(
            self.window(), "Add widget screen", "Name this screen:", text=default_name)
        name = name.strip()
        if not accepted:
            return
        if not name:
            self.toast("A screen name is required.")
            return
        if any(screen["name"].casefold() == name.casefold() for screen in self._screens):
            self.toast("A screen with that name already exists.")
            return
        current = self._screens[self._current_screen]
        layouts = {k: list(v) for k, v in current.get("layouts", {}).items()} if copy_current else {}
        self._screens.append({"name": name, "skin": current.get("skin", "glass"), "layouts": layouts})
        self._current_screen = len(self._screens) - 1
        self._save_screens()
        self._update_screen_controls()
        self._rebuild()
        if not copy_current:
            self.toast("Screen added with the skin's default widgets. Pick a skin with the palette button.")

    def _rename_screen(self):
        current = self._screens[self._current_screen]
        name, accepted = QInputDialog.getText(
            self.window(), "Rename widget screen", "Screen name:", text=current["name"])
        name = name.strip()
        if not accepted:
            return
        if not name:
            self.toast("A screen name is required.")
            return
        if any(screen is not current and screen["name"].casefold() == name.casefold()
               for screen in self._screens):
            self.toast("A screen with that name already exists.")
            return
        current["name"] = name
        self._save_screens()
        self._update_screen_controls()

    def _delete_screen(self):
        if len(self._screens) <= 1:
            return
        del self._screens[self._current_screen]
        self._current_screen = min(self._current_screen, len(self._screens) - 1)
        self._save_screens()
        self._update_screen_controls()
        self._rebuild()

    # --------------------------------------------------------------- menus --

    def _wallpaper_menu(self):
        m = make_menu(self)
        wp = self.wallpapers
        m.addAction(hicon("image", "#e2e8f0", 14), "Add images from PC…", self._add_images)
        m.addAction(hicon("folder", "#e2e8f0", 14), "Use a folder of images…", self._add_folder)
        m.addAction(hicon("link", "#e2e8f0", 14), "Add image from URL…", self._add_url)
        m.addSeparator()
        online = m.addAction(hicon("network_monitor", "#e2e8f0", 14), "Auto-load new wallpapers from the internet")
        online.setCheckable(True)
        online.setChecked(wp.online)
        online.toggled.connect(lambda on: wp.set_online(on))
        save = m.addAction(hicon("save", "#e2e8f0", 14), "Save this wallpaper to library", wp.save_current)
        save.setEnabled(wp.current_is_online())
        speed = make_menu(m)
        speed.setTitle("Change every")
        for secs, text in [(10, "10 seconds"), (30, "30 seconds"), (60, "1 minute"),
                           (300, "5 minutes"), (900, "15 minutes"), (3600, "1 hour")]:
            a = speed.addAction(text)
            a.setCheckable(True)
            a.setChecked(wp.interval == secs)
            a.triggered.connect(lambda _=False, s=secs: (wp.set_interval(s), self._sync_island()))
        m.addMenu(speed)
        shuffle = m.addAction("Shuffle")
        shuffle.setCheckable(True)
        shuffle.setChecked(wp.shuffle)
        shuffle.toggled.connect(wp.set_shuffle)
        m.addSeparator()
        skin = SKINS[self._skin_key()]
        plain = m.addAction(f"Plain background for {skin.name} (hide wallpaper)")
        plain.setCheckable(True)
        plain.setChecked(skin.key in self._plain_bg)
        plain.toggled.connect(lambda on, k=skin.key: self._set_plain_bg(k, on))
        m.addSeparator()
        m.addAction(hicon("automation", "#e2e8f0", 14), "Manage wallpapers & slideshow…", self.open_wallpaper_dialog)
        m.exec(QCursor.pos())

    def _widgets_menu(self):
        m = make_menu(self)
        skin = self._skin_key()
        visible = set(self._visible_keys())
        head = m.addAction(f"{SKINS[skin].name} widgets")
        head.setEnabled(False)
        for key, name, cs, rs in CATALOG[skin]:
            a = m.addAction(name + ("   (wide)" if cs > 1 else ""))
            a.setCheckable(True)
            a.setChecked(key in visible)
            a.toggled.connect(lambda on, k=key: self._set_card_visible(k, on))
        m.addSeparator()
        m.addAction("Reset to this skin's default widgets", self._reset_layout)
        m.exec(QCursor.pos())

    def _set_card_visible(self, key, on):
        skin = self._skin_key()
        keys = self._visible_keys()
        if on and key not in keys:
            capacity = CAPACITY.get(LAYOUT_KIND[skin])
            if capacity:
                spans = {k: cs * rs for k, _, cs, rs in CATALOG[skin]}
                if sum(spans[k] for k in keys) + spans[key] > capacity:
                    self.toast("This screen is full — hide a widget first, or add another screen.")
                    return
            keys.append(key)
        elif not on and key in keys:
            keys.remove(key)
        self._screens[self._current_screen].setdefault("layouts", {})[skin] = keys
        self._save_screens()
        self._rebuild()

    def _reset_layout(self):
        self._screens[self._current_screen].setdefault("layouts", {}).pop(self._skin_key(), None)
        self._focus_mode = False
        save_setting("focus_mode", False)
        self._save_screens()
        self._rebuild()

    def _set_plain_bg(self, key, on):
        self._plain_bg.discard(key)
        if on:
            self._plain_bg.add(key)
        save_setting("plain_bg_skins", sorted(self._plain_bg))
        self.viewport().update()

    def toggle_focus_mode(self):
        self._focus_mode = not self._focus_mode
        save_setting("focus_mode", self._focus_mode)
        self._rebuild()

    def open_wallpaper_dialog(self):
        WallpaperDialog(self.wallpapers, self.window()).exec()

    def _add_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self.window(), "Add Wallpapers", "",
            "Images (*.jpg *.jpeg *.png *.bmp *.webp *.gif *.tif *.tiff)")
        if paths:
            self.wallpapers.add_files(paths)

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self.window(), "Use a Folder of Wallpapers")
        if folder:
            self.wallpapers.add_folder(folder)

    def _add_url(self):
        url, ok = QInputDialog.getText(self.window(), "Wallpaper from URL",
                                       "Paste an image URL (jpg / png / webp):")
        if ok and url.strip():
            self.wallpapers.add_url(url)

    # --------------------------------------------------------- full screen --

    def toggle_fullscreen(self):
        win = self.window()
        if hasattr(win, "toggle_immersive"):
            win.toggle_immersive()
        elif win.isFullScreen():
            win.showNormal()
        else:
            win.showFullScreen()

    def on_immersive_changed(self, on: bool):
        self.island.fs_btn.setIcon(hicon("minimize" if on else "maximize", "#ffffff", 14))
        self.island.fs_btn.setToolTip("Exit full screen (Esc)" if on else "Full screen (F11)")
        if on:
            self.toast("Full screen — press Esc or F11 to exit")

    # ----------------------------------------------------------- clock etc --

    def _toggle_clock_format(self):
        self._clock_24h = not self._clock_24h
        save_setting("clock_24h", self._clock_24h)
        self._tick()

    def _tick(self):
        now = datetime.now()
        self._clock_lbl.setText(now.strftime("%H:%M") if self._clock_24h
                                else now.strftime("%I:%M").lstrip("0"))
        date_text = now.strftime("%A, %d %B")
        self._date_lbl.setText(date_text.upper() if getattr(self, "_hero_upper", False) else date_text)
        h = now.hour
        part = "morning" if 5 <= h < 12 else "afternoon" if h < 17 else "evening" if h < 22 else "night"
        try:
            user = getpass.getuser().split("\\")[-1].capitalize()
        except Exception:
            user = ""
        self._greet_lbl.setText(f"Good {part}{', ' + user if user else ''}")

    def _sync_island(self):
        wp = self.wallpapers
        self.island.play_btn.setIcon(hicon("pause" if wp.playing else "play", "#ffffff", 13))
        self.island.play_btn.setToolTip("Pause slideshow" if wp.playing else "Resume slideshow")
        if wp.fetching:
            text = "Loading wallpaper…"
        else:
            src = "Online" if wp.online else f"{len(wp.images)} wallpapers"
            every = f"{wp.interval // 60} min" if wp.interval >= 60 else f"{wp.interval}s"
            text = f"{src}  ·  {'every ' + every if wp.playing else 'paused'}"
        self.island.status.setText(text)
        n = len(wp.images)
        self.hud_featured.set_caption(
            "Online feed · new photo every slide" if wp.online
            else f"Wallpaper library · {n} image{'s' if n != 1 else ''}")
        self.viewport().update()

    def toast(self, text: str, ms: int = 2800):
        self.toast_lbl.show_message(text, ms)

    # ---------------------------------------------------------- background --

    def _scaled(self, img: QImage):
        if img is None or img.isNull():
            return None
        dpr = self.devicePixelRatioF()
        w, h = max(1, int(self.viewport().width() * dpr)), max(1, int(self.viewport().height() * dpr))
        pm = QPixmap.fromImage(img.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        pm = pm.copy((pm.width() - w) // 2, (pm.height() - h) // 2, w, h)
        pm.setDevicePixelRatio(dpr)
        return pm

    def _set_background(self, img: QImage):
        self.hud_featured.set_image(img)
        if self._anim.state() == QVariantAnimation.Running:
            self._anim.stop()
            self._end_fade()
        if self._src_cur is None:
            self._src_cur, self._bg_cur = img, self._scaled(img)
            self.viewport().update()
            return
        self._src_next, self._bg_next = img, self._scaled(img)
        self._fade = 0.0
        self._anim.start()

    def _on_fade(self, v):
        self._fade = float(v)
        self.viewport().update()

    def _end_fade(self):
        if self._src_next is not None:
            self._src_cur, self._bg_cur = self._src_next, self._bg_next
        self._src_next = self._bg_next = None
        self._fade = 1.0
        self.viewport().update()

    def drawBackground(self, p, rect):
        p.save()
        p.resetTransform()
        vw, vh = self.viewport().width(), self.viewport().height()
        skin = skins.active()
        if not skin.wallpaper or skin.key in self._plain_bg:
            g = QLinearGradient(0, 0, 0, vh)
            g.setColorAt(0, QColor(skin.bg[0]))
            g.setColorAt(1, QColor(skin.bg[1]))
            p.fillRect(0, 0, vw, vh, g)
            p.restore()
            return
        if self._bg_cur is not None:
            p.drawPixmap(0, 0, self._bg_cur)
            if self._bg_next is not None:
                p.setOpacity(self._fade)
                p.drawPixmap(0, 0, self._bg_next)
                p.setOpacity(1.0)
        else:
            g = QLinearGradient(0, 0, vw, vh)
            g.setColorAt(0, QColor(15, 32, 48))
            g.setColorAt(0.55, QColor(8, 20, 26))
            g.setColorAt(1, QColor(3, 8, 12))
            p.fillRect(0, 0, vw, vh, g)

        # Readability: user dim + soft top/bottom vignette
        p.fillRect(0, 0, vw, vh, QColor(0, 0, 0, int(self.wallpapers.dim * 2.55 * 0.8)))
        top = QLinearGradient(0, 0, 0, vh)
        top.setColorAt(0.0, QColor(0, 0, 0, 90))
        top.setColorAt(0.18, QColor(0, 0, 0, 0))
        top.setColorAt(0.62, QColor(0, 0, 0, 0))
        top.setColorAt(1.0, QColor(0, 0, 0, 120))
        p.fillRect(0, 0, vw, vh, top)
        if skin.tint:
            p.fillRect(0, 0, vw, vh, QColor(*skin.tint))
        if skin.key == "hud":
            self._paint_hud_overlay(p, vw, vh)
        p.restore()

    def _paint_hud_overlay(self, p, vw, vh):
        """Cockpit glass: navy wash, faint grid, scanlines and a vignette."""
        p.fillRect(0, 0, vw, vh, QColor(2, 12, 26, 110))
        p.setPen(QColor(127, 212, 255, 14))
        step = 48
        for x in range(0, vw, step):
            p.drawLine(x, 0, x, vh)
        for y in range(0, vh, step):
            p.drawLine(0, y, vw, y)
        for y in range(0, vh, 3):
            p.fillRect(0, y, vw, 1, QColor(0, 0, 0, 28))
        from PySide6.QtGui import QRadialGradient
        g = QRadialGradient(vw / 2, vh / 2, max(vw, vh) * 0.7)
        g.setColorAt(0.55, QColor(0, 0, 0, 0))
        g.setColorAt(1.0, QColor(0, 6, 14, 190))
        p.fillRect(0, 0, vw, vh, g)

    # -------------------------------------------------------------- fitting --

    def _fit(self):
        vw, vh = self.viewport().width(), self.viewport().height()
        if vw < 10 or vh < 10:
            return
        s = vh / BASE_H
        lw, lh = vw / s, BASE_H
        if lw < MIN_W:
            s = vw / MIN_W
            lw, lh = MIN_W, vh / s
        self._proxy.setGeometry(QRectF(0, 0, lw, lh))
        self._scene.setSceneRect(0, 0, lw, lh)
        self.setTransform(QTransform.fromScale(s, s))
        self.toast_lbl.reposition()

        dpr = self.devicePixelRatioF()
        self.wallpapers.target = QSize(int(vw * dpr), int(vh * dpr))
        self._bg_cur = self._scaled(self._src_cur)
        self._bg_next = self._scaled(self._src_next)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()
        self.tasks.refresh()

    def wheelEvent(self, event):
        # Let widgets (sliders etc.) take the wheel, but never scroll the page
        super().wheelEvent(event)
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)

    def shutdown(self):
        self.music.shutdown()

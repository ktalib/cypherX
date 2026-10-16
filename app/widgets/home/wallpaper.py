"""
Wallpaper slideshow engine + manager dialog.

Sources (all mixed into one rotation):
  • images copied into app/assets/wallpapers   (Add Images… / Add from URL…)
  • whole folders on the PC, read in place       (Add Folder…)
  • an online feed URL fetched on every slide     (e.g. https://picsum.photos/{w}/{h})
"""
import random
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QTimer, QSize, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap, QIcon
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QSpinBox, QCheckBox, QSlider, QLineEdit, QComboBox,
    QFileDialog, QInputDialog, QAbstractItemView
)

from app.widgets.home.common import load_setting, save_setting, http_get, hicon

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
WALLPAPERS_DIR = ASSETS_DIR / "wallpapers"
ONLINE_DIR = WALLPAPERS_DIR / "online"
WALLPAPERS_DIR.mkdir(parents=True, exist_ok=True)
ONLINE_DIR.mkdir(parents=True, exist_ok=True)

# Seed default wallpaper from the legacy asset location
_legacy = ASSETS_DIR / "wallpaper_forest.jpg"
if _legacy.exists() and not (WALLPAPERS_DIR / "forest.jpg").exists():
    shutil.copy2(str(_legacy), str(WALLPAPERS_DIR / "forest.jpg"))

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"}
MAX_FOLDER_IMAGES = 3000
MAX_ONLINE_CACHE = 30

ONLINE_PRESETS = [
    ("Picsum — random photo", "https://picsum.photos/{w}/{h}"),
    ("Picsum — grayscale", "https://picsum.photos/{w}/{h}?grayscale"),
    ("Picsum — soft blur", "https://picsum.photos/{w}/{h}?blur=2"),
]


def load_image(path, target: QSize) -> QImage:
    """Decode an image, downscaling during decode so huge photos load fast."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and target.width() > 0 and target.height() > 0:
        f = max(target.width() / size.width(), target.height() / size.height())
        if f < 1.0:
            reader.setScaledSize(QSize(max(1, round(size.width() * f)),
                                       max(1, round(size.height() * f))))
    return reader.read()


class WallpaperManager(QObject):
    """Owns the rotation; emits `image_ready` whenever a new background should fade in."""

    image_ready = Signal(QImage)
    library_changed = Signal()
    state_changed = Signal()
    message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.folders = load_setting("wp_folders", [])
        self.excluded = set(load_setting("wp_excluded", []))
        self.interval = int(load_setting("wp_interval", 30))
        self.shuffle = bool(load_setting("wp_shuffle", True))
        self.online = bool(load_setting("wp_online", False))
        self.online_url = load_setting("wp_online_url", ONLINE_PRESETS[0][1])
        self.dim = int(load_setting("wp_dim", 30))
        self.playing = bool(load_setting("wp_playing", True))

        self.images = []
        self._order = []
        self._pos = -1
        self._history = []
        self.current_path = None
        self.target = QSize(1920, 1080)
        self._fetching = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.next)
        self.rescan()

    # ---- library ----

    def rescan(self):
        found, seen = [], set()

        def add(p: Path):
            key = str(p).lower()
            if key not in seen and str(p) not in self.excluded and p.suffix.lower() in IMG_EXTS:
                seen.add(key)
                found.append(p)

        for p in sorted(WALLPAPERS_DIR.iterdir()):
            if p.is_file():
                add(p)
        for folder in self.folders:
            root = Path(folder)
            if not root.is_dir():
                continue
            count = 0
            for p in sorted(root.rglob("*")):
                if p.is_file() and p.suffix.lower() in IMG_EXTS:
                    add(p)
                    count += 1
                    if count >= MAX_FOLDER_IMAGES:
                        break
        self.images = found
        self._rebuild_order()
        self.library_changed.emit()

    def _rebuild_order(self):
        self._order = list(range(len(self.images)))
        if self.shuffle:
            random.shuffle(self._order)
        self._pos = -1
        if self.current_path in self.images:
            idx = self.images.index(self.current_path)
            self._pos = self._order.index(idx)

    # ---- playback ----

    def start(self):
        last = load_setting("wp_last", None)
        if self.online and not self.images:
            self.next()
        elif last and Path(last) in self.images:
            self.show_path(Path(last))
        elif self.images:
            self.next()
        self._restart_timer()

    def _restart_timer(self):
        self._timer.stop()
        if self.playing:
            self._timer.start(max(5, self.interval) * 1000)

    def next(self):
        if self.online:
            self.fetch_online()
        elif self.images:
            self._pos = (self._pos + 1) % len(self._order)
            if self._pos == 0 and self.shuffle and len(self._order) > 2:
                random.shuffle(self._order)
            self.show_path(self.images[self._order[self._pos]])
        self._restart_timer()

    def prev(self):
        if len(self._history) >= 2:
            self._history.pop()                 # current
            path = self._history.pop()          # previous
            self.show_path(path)
        elif self.images and not self.online:
            self._pos = (self._pos - 1) % len(self._order)
            self.show_path(self.images[self._order[self._pos]])
        self._restart_timer()

    def show_path(self, path: Path):
        img = load_image(path, self.target)
        if img.isNull():
            self.message.emit(f"Could not open {Path(path).name}")
            return
        self.current_path = Path(path)
        self._history.append(self.current_path)
        self._history = self._history[-50:]
        save_setting("wp_last", str(path))
        self.image_ready.emit(img)
        self.state_changed.emit()

    def set_playing(self, on: bool):
        self.playing = on
        save_setting("wp_playing", on)
        self._restart_timer()
        self.state_changed.emit()

    def set_interval(self, seconds: int):
        self.interval = int(seconds)
        save_setting("wp_interval", self.interval)
        self._restart_timer()

    def set_shuffle(self, on: bool):
        self.shuffle = on
        save_setting("wp_shuffle", on)
        self._rebuild_order()

    def set_dim(self, value: int):
        self.dim = int(value)
        save_setting("wp_dim", self.dim)
        self.state_changed.emit()

    def set_online(self, on: bool, url: str = None):
        if url is not None:
            self.online_url = url.strip() or ONLINE_PRESETS[0][1]
            save_setting("wp_online_url", self.online_url)
        changed = on != self.online
        self.online = on
        save_setting("wp_online", on)
        self.state_changed.emit()
        if on and changed:
            self.next()

    # ---- online feed ----

    def _resolve_url(self, url: str) -> str:
        w, h = max(640, self.target.width()), max(360, self.target.height())
        return url.replace("{w}", str(w)).replace("{h}", str(h))

    def fetch_online(self):
        if self._fetching:
            return
        self._fetching = True
        self.state_changed.emit()

        def done(data, err):
            self._fetching = False
            img = QImage.fromData(data) if data else QImage()
            if img.isNull():
                self.message.emit("Online wallpaper failed: " + (err or "URL did not return an image"))
                if self.images:   # fall back to the local rotation for this slide
                    self._pos = (self._pos + 1) % len(self._order)
                    self.show_path(self.images[self._order[self._pos]])
                self.state_changed.emit()
                return
            dest = ONLINE_DIR / f"online_{datetime.now():%Y%m%d_%H%M%S}.jpg"
            img.save(str(dest), "JPG", 92)
            self._prune_online_cache()
            self.current_path = dest
            self._history.append(dest)
            self._history = self._history[-50:]
            self.image_ready.emit(img)
            self.state_changed.emit()

        http_get(self._resolve_url(self.online_url), done, 30000)

    @property
    def fetching(self) -> bool:
        return self._fetching

    def _prune_online_cache(self):
        cached = sorted(ONLINE_DIR.glob("online_*.jpg"))
        for old in cached[:-MAX_ONLINE_CACHE]:
            try:
                old.unlink()
            except OSError:
                pass

    def current_is_online(self) -> bool:
        return bool(self.current_path) and self.current_path.parent == ONLINE_DIR

    def save_current(self):
        """Keep the current online wallpaper in the permanent library."""
        if not self.current_is_online() or not self.current_path.exists():
            return
        dest = WALLPAPERS_DIR / self.current_path.name.replace("online_", "saved_")
        shutil.copy2(str(self.current_path), str(dest))
        self.rescan()
        self.message.emit("Wallpaper saved to your library")

    # ---- adding / removing ----

    @staticmethod
    def _unique_dest(name: str) -> Path:
        dest = WALLPAPERS_DIR / name
        stem, suf, i = dest.stem, dest.suffix, 1
        while dest.exists():
            dest = WALLPAPERS_DIR / f"{stem}_{i}{suf}"
            i += 1
        return dest

    def add_files(self, paths):
        added = []
        for p in paths:
            p = Path(p)
            if p.suffix.lower() not in IMG_EXTS:
                continue
            dest = self._unique_dest(p.name)
            shutil.copy2(str(p), str(dest))
            self.excluded.discard(str(dest))
            added.append(dest)
        if added:
            save_setting("wp_excluded", sorted(self.excluded))
            self.rescan()
            self.show_path(added[0])
            self.message.emit(f"Added {len(added)} wallpaper{'s' if len(added) > 1 else ''}")
        return len(added)

    def add_folder(self, folder: str):
        if folder and folder not in self.folders:
            self.folders.append(folder)
            save_setting("wp_folders", self.folders)
        before = len(self.images)
        self.rescan()
        self.message.emit(f"Folder added — {len(self.images) - before} images in rotation")
        if before == 0 and self.images:
            self.next()

    def remove_folder(self, folder: str):
        if folder in self.folders:
            self.folders.remove(folder)
            save_setting("wp_folders", self.folders)
            self.rescan()

    def add_url(self, url: str, on_done=None):
        url = url.strip()
        if not url:
            return
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url

        def done(data, err):
            img = QImage.fromData(data) if data else QImage()
            if img.isNull():
                self.message.emit("That URL did not return an image" + (f" ({err})" if err else ""))
                if on_done:
                    on_done(False)
                return
            dest = self._unique_dest(f"url_{datetime.now():%Y%m%d_%H%M%S}.jpg")
            img.save(str(dest), "JPG", 94)
            self.rescan()
            self.show_path(dest)
            self.message.emit("Wallpaper downloaded")
            if on_done:
                on_done(True)

        self.message.emit("Downloading wallpaper…")
        http_get(self._resolve_url(url), done, 45000)

    def remove(self, path: Path):
        path = Path(path)
        if path.parent == WALLPAPERS_DIR:
            try:
                path.unlink()
            except OSError:
                pass
        else:
            self.excluded.add(str(path))
            save_setting("wp_excluded", sorted(self.excluded))
        self.rescan()


# ---------------------------------------------------------------------------
#  Manager dialog
# ---------------------------------------------------------------------------

DIALOG_STYLE = """
QDialog { background: #0e151c; }
QLabel { color: #e2e8f0; background: transparent; }
QLabel[role="h"] { color: #94a3b8; font-size: 10px; font-weight: 800; letter-spacing: 1.2px; }
QListWidget { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.10);
              border-radius: 12px; padding: 6px; }
QListWidget::item { border-radius: 8px; padding: 4px; color: #cbd5e1; }
QListWidget::item:selected { background: rgba(56,189,248,0.25); }
QCheckBox { color: #e2e8f0; spacing: 8px; }
QSpinBox, QComboBox { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.14);
                      border-radius: 8px; padding: 4px 8px; color: #fff; min-height: 22px; }
QComboBox QAbstractItemView { background: #111a22; color: #fff; selection-background-color: #0369a1; }
QSlider::groove:horizontal { height: 4px; background: rgba(255,255,255,0.15); border-radius: 2px; }
QSlider::sub-page:horizontal { background: #38bdf8; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; border-radius: 7px; background: #fff; }
"""


class WallpaperDialog(QDialog):
    def __init__(self, manager: WallpaperManager, parent=None):
        super().__init__(parent)
        self.mgr = manager
        self.setWindowTitle("Wallpapers & Slideshow")
        self.resize(860, 620)
        self.setStyleSheet(DIALOG_STYLE)
        self._thumb_queue = []
        self._thumb_timer = QTimer(self)
        self._thumb_timer.timeout.connect(self._load_thumb_batch)

        lo = QVBoxLayout(self)
        lo.setContentsMargins(18, 16, 18, 16)
        lo.setSpacing(12)

        # Library ------------------------------------------------------------
        head = QHBoxLayout()
        self._count = QLabel()
        self._count.setProperty("role", "h")
        head.addWidget(self._count)
        head.addStretch()
        for text, icon, slot in [("Add Images", "image", self._add_images),
                                 ("Add Folder", "folder", self._add_folder),
                                 ("Add from URL", "link", self._add_url),
                                 ("Remove", "trash", self._remove)]:
            b = QPushButton(" " + text)
            b.setIcon(hicon(icon, "#e2e8f0", 14))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(slot)
            head.addWidget(b)
        lo.addLayout(head)

        self._grid = QListWidget()
        self._grid.setViewMode(QListWidget.IconMode)
        self._grid.setIconSize(QSize(176, 99))
        self._grid.setGridSize(QSize(192, 132))
        self._grid.setResizeMode(QListWidget.Adjust)
        self._grid.setMovement(QListWidget.Static)
        self._grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._grid.setUniformItemSizes(True)
        self._grid.itemDoubleClicked.connect(self._show_item)
        self._grid.setToolTip("Double-click to show now")
        lo.addWidget(self._grid, 1)

        # Folders --------------------------------------------------------------
        fh = QLabel("FOLDERS IN ROTATION")
        fh.setProperty("role", "h")
        lo.addWidget(fh)
        frow = QHBoxLayout()
        self._folders = QListWidget()
        self._folders.setFixedHeight(64)
        frow.addWidget(self._folders, 1)
        rmf = QPushButton("Remove Folder")
        rmf.clicked.connect(self._remove_folder)
        frow.addWidget(rmf, 0, Qt.AlignTop)
        lo.addLayout(frow)

        # Settings -------------------------------------------------------------
        sh = QLabel("SLIDESHOW")
        sh.setProperty("role", "h")
        lo.addWidget(sh)
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(8)

        g.addWidget(QLabel("Change every"), 0, 0)
        self._interval = QSpinBox()
        self._interval.setRange(5, 3600)
        self._interval.setSuffix(" s")
        self._interval.setValue(self.mgr.interval)
        self._interval.valueChanged.connect(self.mgr.set_interval)
        g.addWidget(self._interval, 0, 1)

        self._shuffle = QCheckBox("Shuffle order")
        self._shuffle.setChecked(self.mgr.shuffle)
        self._shuffle.toggled.connect(self.mgr.set_shuffle)
        g.addWidget(self._shuffle, 0, 2)

        self._playing = QCheckBox("Slideshow running")
        self._playing.setChecked(self.mgr.playing)
        self._playing.toggled.connect(self.mgr.set_playing)
        g.addWidget(self._playing, 0, 3)

        g.addWidget(QLabel("Darken"), 1, 0)
        self._dim = QSlider(Qt.Horizontal)
        self._dim.setRange(0, 80)
        self._dim.setValue(self.mgr.dim)
        self._dim.valueChanged.connect(self.mgr.set_dim)
        g.addWidget(self._dim, 1, 1, 1, 3)

        self._online = QCheckBox("Auto-load a new wallpaper from the internet on every slide")
        self._online.setChecked(self.mgr.online)
        g.addWidget(self._online, 2, 0, 1, 4)

        g.addWidget(QLabel("Feed"), 3, 0)
        self._preset = QComboBox()
        for name, url in ONLINE_PRESETS:
            self._preset.addItem(name, url)
        self._preset.addItem("Custom URL…", "")
        g.addWidget(self._preset, 3, 1)
        self._url = QLineEdit(self.mgr.online_url)
        self._url.setPlaceholderText("Any URL that returns an image; {w} and {h} = screen size")
        g.addWidget(self._url, 3, 2, 1, 2)
        lo.addLayout(g)

        idx = next((i for i, (_, u) in enumerate(ONLINE_PRESETS) if u == self.mgr.online_url), -1)
        self._preset.setCurrentIndex(idx if idx >= 0 else len(ONLINE_PRESETS))
        self._preset.currentIndexChanged.connect(self._preset_changed)
        self._online.toggled.connect(self._apply_online)
        self._url.editingFinished.connect(self._apply_online)

        # Footer ---------------------------------------------------------------
        foot = QHBoxLayout()
        self._save_btn = QPushButton(" Save Current to Library")
        self._save_btn.setIcon(hicon("save", "#e2e8f0", 14))
        self._save_btn.clicked.connect(self.mgr.save_current)
        foot.addWidget(self._save_btn)
        foot.addStretch()
        close = QPushButton("Done")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        lo.addLayout(foot)

        self.mgr.library_changed.connect(self._populate)
        self.mgr.state_changed.connect(self._sync_state)
        self._populate()
        self._sync_state()

    # ---- population ----

    def _populate(self):
        self._grid.clear()
        self._thumb_queue = []
        placeholder = QIcon(hicon("image", "#475569", 40))
        for p in self.mgr.images:
            it = QListWidgetItem(placeholder, p.name if len(p.name) < 26 else p.name[:23] + "…")
            it.setData(Qt.UserRole, str(p))
            it.setToolTip(str(p))
            self._grid.addItem(it)
            self._thumb_queue.append(it)
        self._thumb_timer.start(0)
        self._folders.clear()
        for f in self.mgr.folders:
            self._folders.addItem(f)
        self._count.setText(f"LIBRARY — {len(self.mgr.images)} IMAGES")

    def _load_thumb_batch(self):
        for _ in range(8):
            if not self._thumb_queue:
                self._thumb_timer.stop()
                return
            it = self._thumb_queue.pop(0)
            img = load_image(it.data(Qt.UserRole), QSize(176, 99))
            if not img.isNull():
                pm = QPixmap.fromImage(img).scaled(176, 99, Qt.KeepAspectRatioByExpanding,
                                                   Qt.SmoothTransformation)
                x, y = (pm.width() - 176) // 2, (pm.height() - 99) // 2
                it.setIcon(QIcon(pm.copy(x, y, 176, 99)))

    def _sync_state(self):
        self._save_btn.setEnabled(self.mgr.current_is_online())

    # ---- actions ----

    def _add_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Wallpaper Images", str(Path.home() / "Pictures"),
            "Images (*.jpg *.jpeg *.png *.bmp *.webp *.gif *.tif *.tiff)")
        if paths:
            self.mgr.add_files(paths)

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Use a Folder of Wallpapers",
                                                  str(Path.home() / "Pictures"))
        if folder:
            self.mgr.add_folder(folder)

    def _add_url(self):
        url, ok = QInputDialog.getText(self, "Add Wallpaper from URL", "Image URL:")
        if ok and url.strip():
            self.mgr.add_url(url)

    def _remove(self):
        for it in self._grid.selectedItems():
            self.mgr.remove(Path(it.data(Qt.UserRole)))

    def _remove_folder(self):
        it = self._folders.currentItem()
        if it:
            self.mgr.remove_folder(it.text())

    def _show_item(self, it):
        self.mgr.show_path(Path(it.data(Qt.UserRole)))

    def _preset_changed(self, i):
        url = self._preset.itemData(i)
        if url:
            self._url.setText(url)
        else:
            self._url.setFocus()
            self._url.selectAll()
        self._apply_online()

    def _apply_online(self):
        self.mgr.set_online(self._online.isChecked(), self._url.text())

    def done(self, r):
        self._thumb_timer.stop()
        try:
            self.mgr.library_changed.disconnect(self._populate)
            self.mgr.state_changed.disconnect(self._sync_state)
        except (RuntimeError, TypeError):
            pass
        super().done(r)

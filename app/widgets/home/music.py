"""
Music player card — real playback through QtMultimedia (FFmpeg backend).

Features: playlist from files / folders / drag-and-drop / stream URLs, shuffle,
repeat (off / all / one), volume + mute, click-to-seek scrubber, embedded cover art
and tags, a live spectrum visualizer fed by the decoded audio, and a remembered queue.
"""
import math
import random
from array import array
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QTimer, QRectF, Signal
from PySide6.QtGui import QPainter, QColor, QPixmap, QPainterPath, QImage, QLinearGradient, QCursor
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QSlider, QWidget, QStyle, QStyleOptionSlider,
    QFileDialog, QInputDialog, QSizePolicy
)

from app.widgets.home.skins import skin_color
from app.widgets.home.common import (
    GlassCard, label, icon_button, hicon, hpix, make_menu, fmt_ms,
    load_setting, save_setting, TEXT, MUTED, DIM
)

try:
    from PySide6.QtMultimedia import (
        QMediaPlayer, QAudioOutput, QMediaMetaData, QAudioFormat
    )
    HAS_MULTIMEDIA = True
except ImportError:  # pragma: no cover
    HAS_MULTIMEDIA = False

try:
    from PySide6.QtMultimedia import QAudioBufferOutput
    HAS_BUFFER_OUTPUT = True
except ImportError:  # Qt < 6.8
    HAS_BUFFER_OUTPUT = False

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
DEFAULT_COVER = ASSETS_DIR / "album_cover.jpg"
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".oga", ".opus", ".aac", ".wma", ".aiff", ".alac", ".mp4", ".webm"}
COVER_NAMES = ("cover.jpg", "folder.jpg", "front.jpg", "album.jpg", "cover.png", "folder.png")
MAX_PLAYLIST = 2000
BANDS = 18


def is_url(src: str) -> bool:
    return src.lower().startswith(("http://", "https://"))


def rounded_cover(src, size: int, radius: int) -> QPixmap:
    ratio = 3
    pm = QPixmap.fromImage(src) if isinstance(src, QImage) else QPixmap(str(src))
    pm = pm.scaled(size * ratio, size * ratio, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(size * ratio, size * ratio)
    out.fill(QColor(0, 0, 0, 0))
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size * ratio, size * ratio, radius * ratio, radius * ratio)
    p.setClipPath(path)
    p.drawPixmap((size * ratio - pm.width()) // 2, (size * ratio - pm.height()) // 2, pm)
    p.end()
    out.setDevicePixelRatio(ratio)
    return out


class SeekSlider(QSlider):
    """Slider that jumps straight to the clicked position."""

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            groove = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
            handle = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
            x = event.position().x() - groove.x() - handle.width() / 2
            span = max(1, groove.width() - handle.width())
            val = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), int(x), span)
            self.setValue(val)
            self.sliderMoved.emit(val)
        super().mousePressEvent(event)


class SpectrumBars(QWidget):
    """Rounded spectrum bars; real levels when audio buffers arrive, gentle idle motion otherwise."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._target = [0.0] * BANDS
        self._shown = [0.0] * BANDS
        self._phase = 0.0
        self.playing = False
        self.live = False          # set True while real buffers are flowing
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_levels(self, levels):
        self._target = levels

    def _tick(self):
        if not self.isVisible():
            return
        self._phase += 0.18
        changed = False
        for i in range(BANDS):
            if self.playing and not self.live:
                t = 0.35 + 0.3 * math.sin(self._phase + i * 0.7) * math.sin(self._phase * 0.37 + i)
                t += random.random() * 0.15
            elif self.playing:
                t = self._target[i]
            else:
                t = 0.06
            cur = self._shown[i]
            nxt = t if t > cur else cur * 0.82 + t * 0.18      # fast attack, slow decay
            if abs(nxt - cur) > 0.003:
                changed = True
            self._shown[i] = nxt
        if changed:
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        gap = 3
        bw = max(2.0, (w - gap * (BANDS - 1)) / BANDS)
        grad = QLinearGradient(0, h, 0, 0)
        grad.setColorAt(0, skin_color(self, QColor(56, 189, 248, 230)))
        grad.setColorAt(1, skin_color(self, QColor(255, 255, 255, 240)))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        for i, v in enumerate(self._shown):
            bh = max(3.0, min(1.0, v) * h)
            x = i * (bw + gap)
            p.drawRoundedRect(QRectF(x, h - bh, bw, bh), bw / 2, bw / 2)


class MusicPlayerWidget(GlassCard):
    message = Signal(str)

    def __init__(self, parent=None):
        super().__init__("MusicCard", bg="rgba(20,24,32,0.66)", parent=parent)
        self.setAcceptDrops(True)

        self.playlist = [s for s in load_setting("music_playlist", []) if is_url(s) or Path(s).exists()]
        self.index = int(load_setting("music_index", 0))
        self.shuffle = bool(load_setting("music_shuffle", False))
        self.repeat = load_setting("music_repeat", "all")      # off | all | one
        self.volume = int(load_setting("music_volume", 70))
        self.muted = False
        self._duration = 0
        self._errors_in_row = 0
        self._last_buffer = 0
        self._coeffs_key = None
        self._coeffs = []
        self._buf_tick = 0

        self.player = None
        if HAS_MULTIMEDIA:
            self.audio = QAudioOutput(self)
            self.player = QMediaPlayer(self)
            self.player.setAudioOutput(self.audio)
            self.audio.setVolume(self.volume / 100)
            self.player.positionChanged.connect(self._on_position)
            self.player.durationChanged.connect(self._on_duration)
            self.player.playbackStateChanged.connect(self._on_state)
            self.player.mediaStatusChanged.connect(self._on_status)
            self.player.metaDataChanged.connect(self._on_metadata)
            self.player.errorOccurred.connect(self._on_error)
            if HAS_BUFFER_OUTPUT:
                fmt = QAudioFormat()
                fmt.setSampleRate(22050)
                fmt.setChannelCount(1)
                fmt.setSampleFormat(QAudioFormat.Int16)
                self.buffer_out = QAudioBufferOutput(fmt, self)
                self.buffer_out.audioBufferReceived.connect(self._on_buffer)
                self.player.setAudioBufferOutput(self.buffer_out)

        self._build_ui()
        self._sync_mode_buttons()

        if self.playlist:
            self.index = min(max(0, self.index), len(self.playlist) - 1)
            self._load(self.index, autoplay=False)
        elif not HAS_MULTIMEDIA:
            self._artist.setText("QtMultimedia is not available")

    # ------------------------------------------------------------------ UI --

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(14, 12, 14, 10)
        lo.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(12)
        self._cover = QLabel()
        self._cover.setFixedSize(64, 64)
        self._cover.setCursor(Qt.PointingHandCursor)
        self._cover.setToolTip("Open music files")
        self._cover.setStyleSheet("background:transparent;border:none;")
        self._cover.mousePressEvent = lambda e: self.open_files()
        self._set_cover(None)
        top.addWidget(self._cover, 0, Qt.AlignTop)

        meta = QVBoxLayout()
        meta.setSpacing(1)
        trow = QHBoxLayout()
        trow.setSpacing(4)
        self._title = label("Nothing playing", TEXT, 14, 700, elide=True)
        trow.addWidget(self._title, 1)
        self._menu_btn = icon_button("list_music", "Queue & sources", 24, 14, "#e2e8f0")
        self._menu_btn.clicked.connect(self._show_menu)
        trow.addWidget(self._menu_btn)
        meta.addLayout(trow)
        self._artist = label("Click the cover or drop files here", MUTED, 11, 600, elide=True)
        meta.addWidget(self._artist)
        meta.addStretch()
        self._bars = SpectrumBars()
        meta.addWidget(self._bars)
        top.addLayout(meta, 1)
        lo.addLayout(top)
        lo.addSpacing(4)

        self._scrubber = SeekSlider(Qt.Horizontal)
        self._scrubber.setRange(0, 1000)
        self._scrubber.setCursor(Qt.PointingHandCursor)
        self._scrubber.setFixedHeight(14)
        self._scrubber.sliderMoved.connect(self._on_scrub_move)
        self._scrubber.sliderReleased.connect(self._on_scrub_release)
        self._scrubber.setStyleSheet("""
            QSlider { background: transparent; }
            QSlider::groove:horizontal { height: 4px; background: rgba(255,255,255,0.18); border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #ffffff; border-radius: 2px; }
            QSlider::handle:horizontal { width: 10px; margin: -3px 0; border-radius: 5px; background: #fff; }
        """)
        lo.addWidget(self._scrubber)

        times = QHBoxLayout()
        self._pos_lbl = label("0:00", MUTED, 10, 600)
        self._dur_lbl = label("0:00", MUTED, 10, 600)
        self._queue_lbl = label("", DIM, 10, 600)
        self._queue_lbl.setAlignment(Qt.AlignCenter)
        times.addWidget(self._pos_lbl)
        times.addStretch()
        times.addWidget(self._queue_lbl)
        times.addStretch()
        times.addWidget(self._dur_lbl)
        lo.addLayout(times)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(4)
        self._shuffle_btn = icon_button("shuffle", "Shuffle", 28, 14)
        self._shuffle_btn.setCheckable(True)
        self._shuffle_btn.clicked.connect(self._toggle_shuffle)
        prev = icon_button("skip_back", "Previous", 32, 16)
        prev.clicked.connect(self.previous)
        self._play_btn = icon_button("play", "Play / Pause", 40, 16, "#0b1116")
        self._play_btn.setStyleSheet("""
            QPushButton { background: #ffffff; border: none; border-radius: 20px; }
            QPushButton:hover { background: #e2e8f0; }
        """)
        self._play_btn.clicked.connect(self.toggle_play)
        nxt = icon_button("skip_forward", "Next", 32, 16)
        nxt.clicked.connect(self.next)
        self._repeat_btn = icon_button("repeat", "Repeat", 28, 14)
        self._repeat_btn.setCheckable(True)
        self._repeat_btn.clicked.connect(self._cycle_repeat)

        ctrl.addWidget(self._shuffle_btn)
        ctrl.addStretch()
        ctrl.addWidget(prev)
        ctrl.addWidget(self._play_btn)
        ctrl.addWidget(nxt)
        ctrl.addStretch()
        ctrl.addWidget(self._repeat_btn)
        lo.addLayout(ctrl)

        vol = QHBoxLayout()
        vol.setSpacing(6)
        self._vol_btn = icon_button("volume", "Mute", 22, 13, MUTED)
        self._vol_btn.clicked.connect(self._toggle_mute)
        self._vol = QSlider(Qt.Horizontal)
        self._vol.setRange(0, 100)
        self._vol.setValue(self.volume)
        self._vol.setFixedHeight(14)
        self._vol.setCursor(Qt.PointingHandCursor)
        self._vol.valueChanged.connect(self._on_volume)
        self._vol.setStyleSheet("""
            QSlider { background: transparent; }
            QSlider::groove:horizontal { height: 3px; background: rgba(255,255,255,0.15); border-radius: 1px; }
            QSlider::sub-page:horizontal { background: rgba(255,255,255,0.75); border-radius: 1px; }
            QSlider::handle:horizontal { width: 9px; margin: -3px 0; border-radius: 4px; background: #fff; }
        """)
        vol.addWidget(self._vol_btn)
        vol.addWidget(self._vol, 1)
        lo.addLayout(vol)
        self._update_vol_icon()

    def _set_cover(self, src):
        if src is None:
            src = DEFAULT_COVER if DEFAULT_COVER.exists() else None
        if src is None or (isinstance(src, QImage) and src.isNull()):
            self._cover.setPixmap(hpix("music", "#64748b", 34))
            self._cover.setAlignment(Qt.AlignCenter)
            self._cover.setStyleSheet("background:rgba(255,255,255,0.07);border-radius:12px;border:none;")
            return
        self._cover.setStyleSheet("background:transparent;border:none;")
        self._cover.setPixmap(rounded_cover(src, 64, 12))

    def _sync_mode_buttons(self):
        self._shuffle_btn.setChecked(self.shuffle)
        self._repeat_btn.setChecked(self.repeat != "off")
        self._repeat_btn.setIcon(hicon("repeat_one" if self.repeat == "one" else "repeat",
                                       "#ffffff" if self.repeat != "off" else MUTED, 14))
        self._shuffle_btn.setIcon(hicon("shuffle", "#ffffff" if self.shuffle else MUTED, 14))
        self._repeat_btn.setToolTip({"off": "Repeat: off", "all": "Repeat: all", "one": "Repeat: one"}[self.repeat])
        n = len(self.playlist)
        self._queue_lbl.setText(f"{self.index + 1} / {n}" if n else "")

    # ------------------------------------------------------------ sources --

    def open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open Music", str(Path.home() / "Music"),
            "Audio (*.mp3 *.wav *.flac *.m4a *.ogg *.opus *.aac *.wma *.aiff);;All files (*)")
        if paths:
            self.add_sources(paths, play=True)

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Music Folder", str(Path.home() / "Music"))
        if folder:
            self.add_sources([folder], play=True)

    def open_url(self):
        url, ok = QInputDialog.getText(self, "Play Stream",
                                       "Audio or internet-radio stream URL (mp3 / aac / m3u8):")
        if ok and url.strip():
            self.add_sources([url.strip()], play=True)

    def add_sources(self, sources, play=True):
        new = []
        for s in sources:
            if is_url(s):
                new.append(s)
                continue
            p = Path(s)
            if p.is_dir():
                files = sorted(f for f in p.rglob("*") if f.suffix.lower() in AUDIO_EXTS)
                new.extend(str(f) for f in files)
            elif p.suffix.lower() in AUDIO_EXTS:
                new.append(str(p))
        if not new:
            self.message.emit("No playable audio found")
            return
        self.playlist.extend(new)
        self.playlist = self.playlist[-MAX_PLAYLIST:]
        first = max(0, len(self.playlist) - len(new))
        self._save_queue()
        self.message.emit(f"Added {len(new)} track{'s' if len(new) != 1 else ''} to the queue")
        if play:
            self._load(first, autoplay=True)
        else:
            self._sync_mode_buttons()

    def clear_queue(self):
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())
        self.playlist = []
        self.index = 0
        self._save_queue()
        self._title.setText("Nothing playing")
        self._artist.setText("Click the cover or drop files here")
        self._set_cover(None)
        self._pos_lbl.setText("0:00")
        self._dur_lbl.setText("0:00")
        self._scrubber.setValue(0)
        self._sync_mode_buttons()

    def _save_queue(self):
        save_setting("music_playlist", self.playlist)
        save_setting("music_index", self.index)

    def _show_menu(self):
        menu = make_menu(self)
        menu.addAction(hicon("music", "#e2e8f0", 14), "Open files…", self.open_files)
        menu.addAction(hicon("folder", "#e2e8f0", 14), "Open folder…", self.open_folder)
        menu.addAction(hicon("link", "#e2e8f0", 14), "Play stream URL…", self.open_url)
        if self.playlist:
            menu.addSeparator()
            start = max(0, min(self.index - 5, len(self.playlist) - 15))
            for i in range(start, min(len(self.playlist), start + 15)):
                src = self.playlist[i]
                name = src if is_url(src) else Path(src).stem
                act = menu.addAction(f"{i + 1}.  {name[:48]}")
                act.setCheckable(True)
                act.setChecked(i == self.index)
                act.triggered.connect(lambda _=False, j=i: self._load(j, autoplay=True))
            if len(self.playlist) > 15:
                more = menu.addAction(f"… {len(self.playlist)} tracks in queue")
                more.setEnabled(False)
            menu.addSeparator()
            menu.addAction(hicon("trash", "#f87171", 14), "Clear queue", self.clear_queue)
        menu.exec(QCursor.pos())

    # ---- drag & drop ----

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        srcs = [u.toLocalFile() if u.isLocalFile() else u.toString() for u in e.mimeData().urls()]
        self.add_sources(srcs, play=True)
        e.acceptProposedAction()

    # ----------------------------------------------------------- transport --

    def _load(self, i: int, autoplay=True):
        if not self.player or not self.playlist:
            return
        self.index = i % len(self.playlist)
        src = self.playlist[self.index]
        self._duration = 0
        self._title.setText(src.rsplit("/", 1)[-1] if is_url(src) else Path(src).stem.replace("_", " "))
        self._artist.setText("Stream" if is_url(src) else Path(src).parent.name)
        self._set_cover(self._folder_cover(src))
        self.player.setSource(QUrl(src) if is_url(src) else QUrl.fromLocalFile(src))
        if autoplay:
            self.player.play()
        save_setting("music_index", self.index)
        self._sync_mode_buttons()

    @staticmethod
    def _folder_cover(src):
        if is_url(src):
            return None
        d = Path(src).parent
        for name in COVER_NAMES:
            if (d / name).exists():
                return d / name
        return None

    def toggle_play(self):
        if not self.player:
            return
        if not self.playlist:
            self.open_files()
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            if self.player.source().isEmpty():
                self._load(self.index, autoplay=True)
            else:
                self.player.play()

    def next(self, auto=False):
        if not self.player or not self.playlist:
            return
        if self.shuffle and len(self.playlist) > 1:
            i = random.choice([j for j in range(len(self.playlist)) if j != self.index])
        else:
            i = self.index + 1
            if i >= len(self.playlist):
                if auto and self.repeat == "off":
                    self.player.stop()
                    return
                i = 0
        self._load(i, autoplay=True)

    def previous(self):
        if not self.player or not self.playlist:
            return
        if self.player.position() > 3000:
            self.player.setPosition(0)
            return
        self._load(self.index - 1, autoplay=True)

    def _toggle_shuffle(self):
        self.shuffle = not self.shuffle
        save_setting("music_shuffle", self.shuffle)
        self._sync_mode_buttons()

    def _cycle_repeat(self):
        self.repeat = {"off": "all", "all": "one", "one": "off"}[self.repeat]
        save_setting("music_repeat", self.repeat)
        self._sync_mode_buttons()

    def _on_volume(self, v):
        self.volume = v
        if self.player:
            self.audio.setVolume(v / 100)
            if self.muted and v > 0:
                self._toggle_mute()
        save_setting("music_volume", v)
        self._update_vol_icon()

    def _toggle_mute(self):
        if not self.player:
            return
        self.muted = not self.muted
        self.audio.setMuted(self.muted)
        self._update_vol_icon()

    def _update_vol_icon(self):
        name = "volume_x" if self.muted or self.volume == 0 else ("volume_1" if self.volume < 50 else "volume")
        self._vol_btn.setIcon(hicon(name, "#cbd5e1", 13))

    # ---- scrubbing ----

    def _on_scrub_move(self, v):
        if self._duration > 0:
            self._pos_lbl.setText(fmt_ms(v * self._duration / 1000))

    def _on_scrub_release(self):
        if self.player and self._duration > 0:
            self.player.setPosition(int(self._scrubber.value() * self._duration / 1000))

    # ------------------------------------------------------ player signals --

    def _on_position(self, ms):
        if not self._scrubber.isSliderDown():
            if self._duration > 0:
                self._scrubber.setValue(int(ms * 1000 / self._duration))
            self._pos_lbl.setText(fmt_ms(ms))

    def _on_duration(self, ms):
        self._duration = ms
        self._dur_lbl.setText(fmt_ms(ms) if ms > 0 else "LIVE")

    def _on_state(self, state):
        playing = state == QMediaPlayer.PlayingState
        self._play_btn.setIcon(hicon("pause" if playing else "play", "#0b1116", 16))
        self._bars.playing = playing
        if not playing:
            self._bars.live = False

    def _on_status(self, status):
        if status == QMediaPlayer.EndOfMedia:
            if self.repeat == "one":
                self.player.setPosition(0)
                self.player.play()
            else:
                self.next(auto=True)
        elif status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            self._errors_in_row = 0

    def _on_metadata(self):
        md = self.player.metaData()
        title = md.stringValue(QMediaMetaData.Title)
        artist = (md.stringValue(QMediaMetaData.ContributingArtist)
                  or md.stringValue(QMediaMetaData.AlbumArtist)
                  or md.stringValue(QMediaMetaData.Author))
        album = md.stringValue(QMediaMetaData.AlbumTitle)
        if title:
            self._title.setText(title)
        if artist or album:
            self._artist.setText(" — ".join(x for x in (artist, album) if x))
        for key in (QMediaMetaData.ThumbnailImage, QMediaMetaData.CoverArtImage):
            img = md.value(key)
            if isinstance(img, QImage) and not img.isNull():
                self._set_cover(img)
                break

    def _on_error(self, error, text):
        if error == QMediaPlayer.NoError:
            return
        self._errors_in_row += 1
        self._artist.setText(f"Can't play: {text or 'unsupported file'}")
        self.message.emit("Playback error — skipping track")
        if len(self.playlist) > 1 and self._errors_in_row < len(self.playlist):
            QTimer.singleShot(1200, lambda: self.next(auto=True))

    # ----------------------------------------------------- spectrum (live) --

    def _band_coeffs(self, sr: int, n: int):
        key = (sr, n)
        if key != self._coeffs_key:
            lo, hi = 60.0, min(9000.0, sr * 0.45)
            freqs = [lo * (hi / lo) ** (i / (BANDS - 1)) for i in range(BANDS)]
            self._coeffs = [2.0 * math.cos(2.0 * math.pi * max(1, round(n * f / sr)) / n) for f in freqs]
            self._coeffs_key = key
        return self._coeffs

    def _on_buffer(self, buf):
        self._buf_tick += 1
        if self._buf_tick % 2 or not self._bars.isVisible():
            return
        try:
            fmt = buf.format()
            ch = max(1, fmt.channelCount())
            sf = fmt.sampleFormat()
            raw = bytes(buf.constData())
            if sf == QAudioFormat.Int16:
                arr, scale = array("h"), 32768.0
            elif sf == QAudioFormat.Float:
                arr, scale = array("f"), 1.0
            elif sf == QAudioFormat.Int32:
                arr, scale = array("i"), 2147483648.0
            else:
                return
            arr.frombytes(raw[: len(raw) - len(raw) % arr.itemsize])
            samples = arr[::ch][:512]
            n = len(samples)
            if n < 128:
                return
            levels = []
            for coeff in self._band_coeffs(fmt.sampleRate() or 22050, n):
                s1 = s2 = 0.0
                for x in samples:
                    s0 = x + coeff * s1 - s2
                    s2, s1 = s1, s0
                power = max(0.0, s1 * s1 + s2 * s2 - coeff * s1 * s2)
                mag = math.sqrt(power) / (n / 2) / scale
                db = 20 * math.log10(mag + 1e-9)
                levels.append(max(0.0, min(1.0, (db + 58) / 52)))
            self._bars.live = True
            self._bars.set_levels(levels)
        except Exception:
            self._bars.live = False

    def shutdown(self):
        if self.player:
            save_setting("music_index", self.index)
            self.player.stop()

"""
CCTV — live camera wall with motion detection.

  • cameras: the PC webcam / USB cameras, or network CCTV streams (rtsp:// or
    http:// URL from an IP / Wi-Fi camera)
  • live grid of feeds; double-click a feed to watch it alone
  • motion detection per camera with adjustable sensitivity; every motion
    event saves a snapshot and lands in the event list
  • Arm: while armed, motion also pops a Windows notification
  • manual recording and optional record-on-motion (local cameras), snapshots
  • snapshots and clips older than the retention period are deleted

Cameras only switch on when you press Start (or when "Start with CypherX" is
ticked for that camera). They keep running while you use other pages.
"""
import math
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QTimer, Signal, QUrl, QRectF, QSize
from PySide6.QtGui import (
    QPainter, QColor, QPen, QFont, QImage, QPixmap, QIcon, QCursor, QDesktopServices
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QListWidget, QListWidgetItem, QInputDialog, QMessageBox, QSpinBox, QApplication, QSizePolicy
)

from app.icons import get_icon
from app.database import Database
from app.services.cctv_service import CctvStore, MotionDetector
from app.widgets.home.common import make_menu, hicon

try:
    from PySide6.QtMultimedia import (
        QMediaDevices, QCamera, QMediaCaptureSession, QVideoSink, QMediaRecorder, QMediaPlayer
    )
    HAS_MULTIMEDIA = True
except ImportError:  # PySide6-Essentials only
    HAS_MULTIMEDIA = False

MOTION_SAMPLE_S = 0.25        # motion check 4x a second
THUMB_W, THUMB_H = 64, 48
EVENT_COOLDOWN_S = 10         # at most one motion event / snapshot per camera per 10 s
NOTIFY_COOLDOWN_S = 60        # at most one notification per camera per minute
STREAM_RETRY_MS = 5000
MAX_LISTED_EVENTS = 200

_SUB = "color:#94a3b8;font-size:11px;background:transparent;"


def _mask_url(url):
    """rtsp://user:secret@host → rtsp://user:•••@host for display."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        cred, host = rest.split("@", 1)
        if ":" in cred:
            cred = cred.split(":", 1)[0] + ":•••"
        return f"{scheme}://{cred}@{host}"
    return url


def _device_key(dev):
    return bytes(dev.id()).decode("utf-8", "replace")


def video_inputs():
    return list(QMediaDevices.videoInputs()) if HAS_MULTIMEDIA else []


def gray_thumb(img):
    """Small grayscale copy of a frame as raw bytes for the motion detector."""
    small = img.scaled(THUMB_W, THUMB_H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    small = small.convertToFormat(QImage.Format_Grayscale8)
    raw = bytes(small.constBits())
    bpl = small.bytesPerLine()
    if bpl == THUMB_W:
        return raw[:THUMB_W * THUMB_H]
    return b"".join(raw[r * bpl:r * bpl + THUMB_W] for r in range(THUMB_H))


class CameraFeed(QObject):
    """One camera: capture (device) or playback (stream URL) into a video sink,
    with motion sampling and recording."""

    frame_ready = Signal()
    motion = Signal(float)
    state_changed = Signal()

    def __init__(self, cam, parent=None):
        super().__init__(parent)
        self.cam = cam
        self.image = None
        self.running = False
        self.recording = False
        self.status = "Off"
        self.score = 0.0
        self.detector = MotionDetector(cam.get("sensitivity", 6))
        self._last_sample = 0.0
        self._camera = self._session = self._recorder = self._player = None
        self.sink = QVideoSink(self)
        self.sink.videoFrameChanged.connect(self._on_frame)
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._play_stream)

    @property
    def can_record(self):
        return self.cam["source"] == "device"

    # -------------------------------------------------------------- control --

    def start(self):
        if self.running:
            return
        self.running = True
        self.detector.reset()
        if self.cam["source"] == "url":
            self._player = QMediaPlayer(self)
            self._player.setVideoSink(self.sink)
            self._player.errorOccurred.connect(self._on_stream_error)
            self._player.mediaStatusChanged.connect(self._on_stream_status)
            self._play_stream()
        else:
            dev = self._find_device()
            if dev is None:
                self.running = False
                self._set_status("Camera not found")
                return
            self._camera = QCamera(dev, self)
            self._camera.errorOccurred.connect(lambda _e, msg: self._set_status(f"Error: {msg}"))
            self._session = QMediaCaptureSession(self)
            self._session.setCamera(self._camera)
            self._session.setVideoSink(self.sink)
            self._recorder = QMediaRecorder(self)
            self._recorder.errorOccurred.connect(lambda _e, msg: self._set_status(f"Recording error: {msg}"))
            self._recorder.recorderStateChanged.connect(self._on_recorder_state)
            self._session.setRecorder(self._recorder)
            self._camera.start()
            self._set_status("Live")

    def stop(self):
        self._retry.stop()
        self.stop_recording()
        if self._camera is not None:
            self._camera.stop()
            self._camera.deleteLater()
        if self._player is not None:
            self._player.stop()
            self._player.deleteLater()
        for obj in (self._session, self._recorder):
            if obj is not None:
                obj.deleteLater()
        self._camera = self._session = self._recorder = self._player = None
        self.running = False
        self.image = None
        self._set_status("Off")
        self.frame_ready.emit()

    def start_recording(self, path):
        if not (self.running and self.can_record and self._recorder) or self.recording:
            return False
        self._recorder.setOutputLocation(QUrl.fromLocalFile(str(path)))
        self._recorder.record()
        self.recording = True
        self.state_changed.emit()
        return True

    def stop_recording(self):
        if self._recorder is not None and self.recording:
            self._recorder.stop()
        if self.recording:
            self.recording = False
            self.state_changed.emit()

    def snapshot(self, path):
        if self.image is None or self.image.isNull():
            return False
        return self.image.save(str(path), "JPG", 85)

    # ------------------------------------------------------------ internals --

    def _find_device(self):
        devices = video_inputs()
        want = self.cam.get("device_id")
        for d in devices:
            if want and _device_key(d) == want:
                return d
        if not want and devices:
            return QMediaDevices.defaultVideoInput()
        return None

    def _set_status(self, text):
        self.status = text
        self.state_changed.emit()

    def _play_stream(self):
        if not self.running or self._player is None:
            return
        self._set_status("Connecting…")
        self._player.setSource(QUrl(self.cam["url"]))
        self._player.play()

    def _on_stream_status(self, status):
        if status in (QMediaPlayer.BufferedMedia, QMediaPlayer.LoadedMedia, QMediaPlayer.BufferingMedia):
            if self.status != "Live":
                self._set_status("Live")
        elif status in (QMediaPlayer.EndOfMedia, QMediaPlayer.InvalidMedia) and self.running:
            self._set_status("Stream lost — retrying…")
            self._retry.start(STREAM_RETRY_MS)

    def _on_stream_error(self, _err, msg):
        if self.running:
            self._set_status(f"Stream error — retrying… ({msg})" if msg else "Stream error — retrying…")
            self._retry.start(STREAM_RETRY_MS)

    def _on_recorder_state(self, state):
        if state == QMediaRecorder.StoppedState and self.recording:
            self.recording = False
            self.state_changed.emit()

    def _on_frame(self, frame):
        if not self.running or not frame.isValid():
            return
        img = frame.toImage()
        if img.isNull():
            return
        self.image = img
        self.frame_ready.emit()
        now = time.monotonic()
        if self.cam.get("motion", True) and now - self._last_sample >= MOTION_SAMPLE_S:
            self._last_sample = now
            self.detector.sensitivity = self.cam.get("sensitivity", 6)
            self.score, moving = self.detector.feed(gray_thumb(img))
            if moving:
                self.motion.emit(self.score)


class VideoCanvas(QWidget):
    """Paints the latest frame (fit, letterboxed) with the CCTV overlay."""

    double_clicked = Signal()

    def __init__(self, feed, parent=None):
        super().__init__(parent)
        self.feed = feed
        self.motion_until = 0.0
        self.setMinimumSize(240, 135)

    def mouseDoubleClickEvent(self, e):
        self.double_clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.fillRect(r, QColor("#05080d"))
        img = self.feed.image
        f = QFont()
        if img is not None and not img.isNull():
            s = img.size().scaled(r.size(), Qt.KeepAspectRatio)
            target = QRectF((r.width() - s.width()) / 2, (r.height() - s.height()) / 2, s.width(), s.height())
            p.drawImage(target, img)
            f.setPixelSize(12)
            f.setBold(True)
            p.setFont(f)
            stamp = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
            p.setPen(QColor(0, 0, 0, 160))
            p.drawText(r.adjusted(11, 0, 0, -9), Qt.AlignLeft | Qt.AlignBottom, stamp)
            p.setPen(QColor("#f8fafc"))
            p.drawText(r.adjusted(10, 0, 0, -10), Qt.AlignLeft | Qt.AlignBottom, stamp)
        else:
            f.setPixelSize(13)
            p.setFont(f)
            p.setPen(QColor("#64748b"))
            p.drawText(r, Qt.AlignCenter, "Camera off — press Start" if not self.feed.running
                       else self.feed.status)
        if self.feed.recording and int(time.time() * 2) % 2 == 0:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ef4444"))
            p.drawEllipse(r.right() - 58, 12, 10, 10)
            f.setPixelSize(11)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#fecaca"))
            p.drawText(r.right() - 44, 22, "REC")
        if time.time() < self.motion_until:
            p.setPen(QPen(QColor("#f43f5e"), 3))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r.adjusted(1, 1, -2, -2))
            f.setPixelSize(11)
            f.setBold(True)
            p.setFont(f)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#f43f5e"))
            p.drawRoundedRect(QRectF(10, 10, 66, 20), 4, 4)
            p.setPen(QColor("#ffffff"))
            p.drawText(QRectF(10, 10, 66, 20), Qt.AlignCenter, "MOTION")
        p.end()


class CameraTile(QFrame):
    def __init__(self, view, feed, parent=None):
        super().__init__(parent)
        self.view = view
        self.feed = feed
        self.setObjectName("panel")
        lo = QVBoxLayout(self)
        lo.setContentsMargins(8, 6, 8, 8)
        lo.setSpacing(6)
        head = QHBoxLayout()
        self.dot = QLabel()
        self.dot.setFixedSize(9, 9)
        self.name = QLabel()
        self.name.setStyleSheet("color:#f8fafc;font-size:12px;font-weight:700;background:transparent;")
        self.status = QLabel()
        self.status.setStyleSheet(_SUB)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)   # shrinks before the name
        head.addWidget(self.dot)
        head.addWidget(self.name)
        head.addWidget(self.status, 1)
        self.power_btn = self._button("power", "Start / stop this camera", self._toggle_power)
        self.snap_btn = self._button("camera", "Take a snapshot", lambda: self.view.manual_snapshot(self.feed))
        self.rec_btn = self._button("video", "Start / stop recording", lambda: self.view.toggle_recording(self.feed))
        self.menu_btn = self._button("more", "Camera settings", lambda: self.view.camera_menu(self.feed))
        for b in (self.power_btn, self.snap_btn, self.rec_btn, self.menu_btn):
            head.addWidget(b)
        lo.addLayout(head)
        self.canvas = VideoCanvas(feed)
        self.canvas.double_clicked.connect(lambda: self.view.toggle_focus(self.feed))
        lo.addWidget(self.canvas, 1)
        feed.frame_ready.connect(self.canvas.update)
        feed.state_changed.connect(self.sync)
        self.sync()

    def _button(self, icon, tip, slot):
        b = QPushButton()
        b.setFixedSize(28, 26)
        b.setToolTip(tip)
        b.setIcon(get_icon(icon, "#e2e8f0", 14))
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def _toggle_power(self):
        if self.feed.running:
            self.view.stop_camera(self.feed)
        else:
            self.view.start_camera(self.feed)

    def sync(self):
        cam, feed = self.feed.cam, self.feed
        self.name.setText(cam["name"])
        bits = [feed.status]
        if cam["source"] == "url":
            bits.append(_mask_url(cam["url"]))
        if not cam.get("motion", True):
            bits.append("motion off")
        self.status.setText("  ·  ".join(bits))
        live = feed.running and feed.status == "Live"
        color = "#10b981" if live else "#f59e0b" if feed.running else "#475569"
        self.dot.setStyleSheet(f"background:{color};border-radius:4px;")
        self.power_btn.setIcon(get_icon("power", "#f87171" if feed.running else "#e2e8f0", 14))
        self.power_btn.setToolTip("Stop camera" if feed.running else "Start camera")
        self.snap_btn.setEnabled(feed.running)
        self.rec_btn.setEnabled(feed.running and feed.can_record)
        self.rec_btn.setIcon(get_icon("square" if feed.recording else "video",
                                      "#ef4444" if feed.recording else "#e2e8f0", 14))
        self.rec_btn.setToolTip("Stop recording" if feed.recording else
                                "Start recording" if feed.can_record else
                                "Recording is available for local cameras only")
        self.canvas.update()


class CctvView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = CctvStore()
        self.db = Database.get_instance()
        self.feeds = {}
        self.tiles = {}
        self.focused = None
        self._last_event = {}
        self._last_notify = {}
        self._stop_rec_timers = {}
        self._setup_ui()
        if HAS_MULTIMEDIA:
            self._first_run_camera()
            for cam in self.store.cameras:
                self._new_feed(cam)
        self._rebuild_grid()
        self._fill_events()
        self.store.prune()
        self._overlay_timer = QTimer(self)        # keeps clock / REC blink / motion border moving
        self._overlay_timer.timeout.connect(self._tick)
        self._overlay_timer.start(500)
        self._prune_timer = QTimer(self)
        self._prune_timer.timeout.connect(self.store.prune)
        self._prune_timer.start(6 * 3600 * 1000)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)
        QTimer.singleShot(500, self._auto_start)

    # ------------------------------------------------------------------ UI --

    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(12)

        bar = QFrame()
        bar.setObjectName("panel")
        tb = QHBoxLayout(bar)
        tb.setContentsMargins(14, 8, 10, 8)
        title = QLabel("CCTV // SECURITY CAMERAS")
        title.setObjectName("section-header")
        tb.addWidget(title)
        tb.addSpacing(12)
        self.arm_btn = QPushButton()
        self.arm_btn.setCheckable(True)
        self.arm_btn.setChecked(bool(self.store.config.get("armed")))
        self.arm_btn.setToolTip("While armed, motion on any camera pops a Windows notification")
        self.arm_btn.toggled.connect(self._arm_toggled)
        tb.addWidget(self.arm_btn)
        self.all_btn = QPushButton(" Start all")
        self.all_btn.setIcon(get_icon("play", "#e2e8f0", 13))
        self.all_btn.clicked.connect(self._start_stop_all)
        tb.addWidget(self.all_btn)
        tb.addStretch()
        add = QPushButton(" Add camera")
        add.setIcon(get_icon("plus", "#e2e8f0", 13))
        add.clicked.connect(self._add_menu)
        tb.addWidget(add)
        folder = QPushButton(" Saved files")
        folder.setIcon(get_icon("folder", "#e2e8f0", 13))
        folder.setToolTip("Open the folder with snapshots and recordings")
        folder.clicked.connect(lambda: self._open_path(self.store.root))
        tb.addWidget(folder)
        main.addWidget(bar)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.grid_host = QWidget()
        self.grid_host.setStyleSheet("background:transparent;")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(10)
        body.addWidget(self.grid_host, 1)

        side = QFrame()
        side.setObjectName("panel")
        side.setFixedWidth(300)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(12, 10, 12, 12)
        sl.setSpacing(8)
        head = QLabel("MOTION EVENTS")
        head.setObjectName("section-header")
        sl.addWidget(head)
        self.events_sub = QLabel()
        self.events_sub.setStyleSheet(_SUB)
        sl.addWidget(self.events_sub)
        self.events = QListWidget()
        self.events.setIconSize(QSize(96, 54))
        self.events.setSpacing(2)
        self.events.setToolTip("Double-click to open the snapshot")
        self.events.itemDoubleClicked.connect(self._open_event)
        self.events.setContextMenuPolicy(Qt.CustomContextMenu)
        self.events.customContextMenuRequested.connect(self._event_menu)
        sl.addWidget(self.events, 1)
        row = QHBoxLayout()
        keep = QLabel("Keep files")
        keep.setStyleSheet(_SUB)
        self.keep = QSpinBox()
        self.keep.setRange(1, 365)
        self.keep.setSuffix(" days")
        self.keep.setValue(int(self.store.config.get("retention_days", 14)))
        self.keep.valueChanged.connect(self._retention_changed)
        clear = QPushButton(" Clear")
        clear.setIcon(get_icon("trash", "#f87171", 13))
        clear.setToolTip("Clear the event list (saved snapshots stay on disk)")
        clear.clicked.connect(self._clear_events)
        row.addWidget(keep)
        row.addWidget(self.keep)
        row.addStretch()
        row.addWidget(clear)
        sl.addLayout(row)
        body.addWidget(side)
        main.addLayout(body, 1)
        self._sync_bar()

    def _rebuild_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        if not HAS_MULTIMEDIA:
            self._empty("QtMultimedia is not installed, so cameras can't be opened.\n"
                        "Install the full PySide6 package:  pip install PySide6")
            return
        if not self.feeds:
            self._empty("No cameras yet. Use Add camera to add the PC camera\n"
                        "or a network CCTV camera (RTSP / HTTP stream).")
            return
        shown = [self.focused] if self.focused in self.feeds else list(self.feeds)
        cols = max(1, math.ceil(math.sqrt(len(shown))))
        for i, cid in enumerate(shown):
            tile = self.tiles.get(cid)
            if tile is None:
                tile = self.tiles[cid] = CameraTile(self, self.feeds[cid])
            self.grid.addWidget(tile, i // cols, i % cols)
            tile.show()
        for r in range(self.grid.rowCount()):
            self.grid.setRowStretch(r, 1)
        for c in range(self.grid.columnCount()):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)

    def _empty(self, text):
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color:#94a3b8;font-size:13px;background:transparent;")
        self.grid.addWidget(lbl, 0, 0)

    def _sync_bar(self):
        armed = self.arm_btn.isChecked()
        self.arm_btn.setText(" Armed" if armed else " Disarmed")
        self.arm_btn.setIcon(get_icon("shield" if armed else "unlock", "#10b981" if armed else "#94a3b8", 13))
        any_on = any(f.running for f in self.feeds.values())
        self.all_btn.setText(" Stop all" if any_on else " Start all")
        self.all_btn.setIcon(get_icon("pause" if any_on else "play", "#e2e8f0", 13))
        self.all_btn.setEnabled(bool(self.feeds))

    def _tick(self):
        for tile in self.tiles.values():
            if tile.feed.running:
                tile.canvas.update()

    # ------------------------------------------------------------ cameras --

    def _first_run_camera(self):
        """Seed the PC camera once, so the demo works straight away (it stays off)."""
        if self.store.config.get("seeded"):
            return
        self.store.config["seeded"] = True
        devs = video_inputs()
        if devs and not self.store.cameras:
            d = QMediaDevices.defaultVideoInput()
            self.store.add_camera("PC Camera", device_id=_device_key(d))
        self.store.save()

    def _new_feed(self, cam):
        feed = CameraFeed(cam, self)
        feed.motion.connect(lambda s, cid=cam["id"]: self._on_motion(cid, s))
        feed.state_changed.connect(self._sync_bar)
        self.feeds[cam["id"]] = feed
        return feed

    def _add_feed(self, cam):
        feed = self._new_feed(cam)
        self._rebuild_grid()
        self._sync_bar()
        return feed

    def _auto_start(self):
        for feed in self.feeds.values():
            if feed.cam.get("auto_start"):
                self.start_camera(feed, log=False)

    def start_camera(self, feed, log=True):
        feed.start()
        if log and feed.running:
            self._log(f"{feed.cam['name']} started")
        self._sync_bar()

    def stop_camera(self, feed):
        timer = self._stop_rec_timers.pop(feed.cam["id"], None)
        if timer:
            timer.stop()
        feed.stop()
        self._log(f"{feed.cam['name']} stopped")
        self._sync_bar()

    def _start_stop_all(self):
        if any(f.running for f in self.feeds.values()):
            for f in self.feeds.values():
                if f.running:
                    self.stop_camera(f)
        else:
            for f in self.feeds.values():
                self.start_camera(f)

    def toggle_focus(self, feed):
        self.focused = None if self.focused == feed.cam["id"] else feed.cam["id"]
        self._rebuild_grid()

    def _add_menu(self):
        if not HAS_MULTIMEDIA:
            QMessageBox.information(self, "CCTV", "Install the full PySide6 package to use cameras:\n"
                                                  "pip install PySide6")
            return
        m = make_menu(self)
        used = {c.get("device_id") for c in self.store.cameras if c["source"] == "device"}
        devs = video_inputs()
        for d in devs:
            key = _device_key(d)
            act = m.addAction(hicon("camera", "#e2e8f0", 14), d.description(),
                              lambda d=d, key=key: self._add_device(d.description(), key))
            act.setEnabled(key not in used)
        if not devs:
            act = m.addAction("No local camera found")
            act.setEnabled(False)
        m.addSeparator()
        m.addAction(hicon("wifi", "#e2e8f0", 14), "Network camera (RTSP / HTTP URL)…", self._add_url)
        m.exec(QCursor.pos())

    def _add_device(self, name, key):
        cam = self.store.add_camera(name, device_id=key)
        self._log(f"Camera added: {name}")
        self._add_feed(cam)

    def _add_url(self):
        name, ok = QInputDialog.getText(self, "Network camera", "Name (e.g. Gate, Front door):")
        if not ok or not name.strip():
            return
        url, ok = QInputDialog.getText(
            self, "Network camera",
            "Stream URL from the camera's manual or app, e.g.\n"
            "rtsp://admin:password@192.168.1.50:554/stream1\n"
            "The URL is saved on this PC only.")
        url = url.strip()
        if not ok or not url:
            return
        if "://" not in url:
            url = "rtsp://" + url
        cam = self.store.add_camera(name.strip(), url=url)
        self._log(f"Network camera added: {name.strip()} ({_mask_url(url)})")
        self.start_camera(self._add_feed(cam))

    def camera_menu(self, feed):
        cam = feed.cam
        m = make_menu(self)
        m.addAction(hicon("file_text", "#e2e8f0", 14), "Rename…", lambda: self._rename(feed))
        a = m.addAction(hicon("activity", "#e2e8f0", 14), "Motion detection")
        a.setCheckable(True)
        a.setChecked(cam.get("motion", True))
        a.toggled.connect(lambda on: self._set(feed, motion=on))
        m.addAction(hicon("eye", "#e2e8f0", 14),
                    f"Motion sensitivity ({cam.get('sensitivity', 6)}/10)…", lambda: self._sensitivity(feed))
        a = m.addAction(hicon("video", "#e2e8f0", 14), "Record when motion is detected")
        a.setCheckable(True)
        a.setChecked(cam.get("record_on_motion", False))
        a.setEnabled(feed.can_record)
        a.toggled.connect(lambda on: self._set(feed, record_on_motion=on))
        a = m.addAction(hicon("power", "#e2e8f0", 14), "Start with CypherX")
        a.setCheckable(True)
        a.setChecked(cam.get("auto_start", False))
        a.toggled.connect(lambda on: self._set(feed, auto_start=on))
        m.addSeparator()
        m.addAction(hicon("trash", "#f87171", 14), "Remove camera", lambda: self._remove(feed))
        m.exec(QCursor.pos())

    def _set(self, feed, **fields):
        self.store.update_camera(feed.cam["id"], **fields)
        if "motion" in fields:
            feed.detector.reset()
        feed.state_changed.emit()

    def _rename(self, feed):
        name, ok = QInputDialog.getText(self, "Rename camera", "Name:", text=feed.cam["name"])
        if ok and name.strip():
            self._set(feed, name=name.strip())

    def _sensitivity(self, feed):
        val, ok = QInputDialog.getInt(self, "Motion sensitivity",
                                      "1 = only big movement close up, 10 = the smallest change.\n"
                                      "Lower it if leaves, shadows or the TV keep triggering it.",
                                      feed.cam.get("sensitivity", 6), 1, 10)
        if ok:
            self._set(feed, sensitivity=val)

    def _remove(self, feed):
        cam = feed.cam
        if QMessageBox.question(self, "Remove camera", f"Remove {cam['name']}? Saved snapshots and "
                                                       "recordings stay on disk.") != QMessageBox.Yes:
            return
        if feed.running:
            self.stop_camera(feed)
        self.store.remove_camera(cam["id"])
        self.feeds.pop(cam["id"], None)
        tile = self.tiles.pop(cam["id"], None)
        if tile:
            tile.setParent(None)
            tile.deleteLater()
        if self.focused == cam["id"]:
            self.focused = None
        feed.deleteLater()
        self._log(f"Camera removed: {cam['name']}")
        self._rebuild_grid()
        self._sync_bar()

    # ---------------------------------------------------- snapshots / video --

    def manual_snapshot(self, feed):
        path = self.store.snapshot_path(feed.cam["id"], tag="manual")
        if feed.snapshot(path):
            self.store.add_event(feed.cam["id"], "snapshot", snapshot=path)
            self._fill_events()

    def toggle_recording(self, feed):
        cid = feed.cam["id"]
        if feed.recording:
            timer = self._stop_rec_timers.pop(cid, None)
            if timer:
                timer.stop()
            feed.stop_recording()
            self._log(f"{feed.cam['name']}: recording stopped")
        else:
            path = self.store.recording_path(cid)
            if feed.start_recording(path):
                self.store.add_event(cid, "recording", snapshot=None)
                self._log(f"{feed.cam['name']}: recording to {path.name}")
                self._fill_events()

    def _record_on_motion(self, feed):
        cid = feed.cam["id"]
        timer = self._stop_rec_timers.get(cid)
        if not feed.recording:
            if not feed.start_recording(self.store.recording_path(cid)):
                return
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda f=feed, c=cid: (self._stop_rec_timers.pop(c, None),
                                                          f.stop_recording()))
            self._stop_rec_timers[cid] = timer
        if timer is not None:      # extend while motion continues; manual recordings have no timer
            timer.start(int(self.store.config.get("record_seconds", 20)) * 1000)

    # -------------------------------------------------------------- motion --

    def _on_motion(self, cid, score):
        feed = self.feeds.get(cid)
        if feed is None:
            return
        tile = self.tiles.get(cid)
        if tile:
            tile.canvas.motion_until = time.time() + 2.0
        if feed.cam.get("record_on_motion") and feed.can_record:
            self._record_on_motion(feed)
        now = time.time()
        if now - self._last_event.get(cid, 0) < EVENT_COOLDOWN_S:
            return
        self._last_event[cid] = now
        path = self.store.snapshot_path(cid, ts=now)
        snap = path if feed.snapshot(path) else None
        self.store.add_event(cid, "motion", score=score, snapshot=snap, ts=now)
        self._fill_events()
        if self.arm_btn.isChecked() and now - self._last_notify.get(cid, 0) >= NOTIFY_COOLDOWN_S:
            self._last_notify[cid] = now
            self._log(f"Motion on {feed.cam['name']} ({score * 100:.1f}% of the picture changed)")
            win = self.window()
            if hasattr(win, "notify"):
                win.notify("Motion detected", f"{feed.cam['name']} — {datetime.now():%H:%M:%S}")

    def _arm_toggled(self, on):
        self.store.config["armed"] = on
        self.store.save()
        self._log("CCTV armed" if on else "CCTV disarmed")
        self._sync_bar()

    # -------------------------------------------------------------- events --

    def _fill_events(self):
        self.events.clear()
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        n_today = sum(1 for e in self.store.events_since(today) if e["kind"] == "motion")
        self.events_sub.setText(f"{n_today} motion event{'s' if n_today != 1 else ''} today")
        labels = {"motion": "Motion", "snapshot": "Snapshot", "recording": "Recording started"}
        for ev in reversed(self.store.events[-MAX_LISTED_EVENTS:]):
            dt = datetime.fromtimestamp(ev["ts"])
            when = dt.strftime("%H:%M:%S") if ev["ts"] >= today else dt.strftime("%d %b %H:%M")
            text = f"{ev['camera_name']}\n{labels.get(ev['kind'], ev['kind'])} · {when}"
            if ev["kind"] == "motion":
                text += f" · {ev['score'] * 100:.1f}%"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, ev)
            if ev.get("snapshot"):
                pm = QPixmap(ev["snapshot"])
                if not pm.isNull():
                    item.setIcon(QIcon(pm.scaled(96, 54, Qt.KeepAspectRatioByExpanding,
                                                 Qt.SmoothTransformation).copy(0, 0, 96, 54)))
            self.events.addItem(item)

    def _open_event(self, item):
        ev = item.data(Qt.UserRole)
        if ev and ev.get("snapshot"):
            self._open_path(ev["snapshot"])

    def _event_menu(self, pos):
        item = self.events.itemAt(pos)
        if item is None:
            return
        ev = item.data(Qt.UserRole)
        m = make_menu(self)
        if ev.get("snapshot"):
            snap = Path(ev["snapshot"])
            m.addAction(hicon("image", "#e2e8f0", 14), "Open snapshot", lambda: self._open_path(snap))
            m.addAction(hicon("folder", "#e2e8f0", 14), "Open folder", lambda: self._open_path(snap.parent))
        else:
            m.addAction(hicon("folder", "#e2e8f0", 14), "Open recordings folder",
                        lambda: self._open_path(self.store.root / "recordings" / ev["camera"]))
        m.exec(self.events.viewport().mapToGlobal(pos))

    def _clear_events(self):
        if QMessageBox.question(self, "Clear events", "Clear the event list? Saved snapshots and "
                                                      "recordings stay on disk.") == QMessageBox.Yes:
            self.store.clear_events()
            self._fill_events()

    def _retention_changed(self, days):
        self.store.config["retention_days"] = days
        self.store.save()

    # --------------------------------------------------------------- misc --

    @staticmethod
    def _open_path(path):
        path = Path(path)
        if not path.suffix:
            path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _log(self, action):
        try:
            self.db.log_operation("CCTV", action, "Success")
        except Exception:
            pass

    def shutdown(self):
        """Stop every camera so recordings are finalised before the app exits."""
        for feed in self.feeds.values():
            if feed.running:
                feed.stop()

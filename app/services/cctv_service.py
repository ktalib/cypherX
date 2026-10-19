"""
CCTV — camera list, motion detection, motion events and the snapshot /
recording folders. No Qt here, so it can be unit tested on its own.

Cameras are a local video device (the PC webcam, a USB camera), a network
stream URL (rtsp:// or http:// from an IP / Wi-Fi CCTV camera or a phone camera
app), or a phone browser that sends pictures to the web dashboard ("phone").

Motion detection works on small grayscale thumbnails (e.g. 64 x 48) sampled a
few times a second: a pixel counts as changed when it differs from the previous
thumbnail by more than PIXEL_DELTA after removing the frame's overall brightness
shift (so auto-exposure and clouds don't trigger it). Motion is reported when
the changed fraction passes the camera's sensitivity threshold on two samples in
a row.

Everything lives under USER_DATA_DIR/cctv:
  cctv.json                    cameras + settings
  events.json                  motion events (newest last)
  snapshots/<cam>/<date>/...   motion and manual snapshots (JPEG)
  recordings/<cam>/...         video clips (MP4)
"""
import json
import os
import time
import uuid
from datetime import datetime

from app.config import USER_DATA_DIR

CCTV_DIR = USER_DATA_DIR / "cctv"
CONFIG_FILE = CCTV_DIR / "cctv.json"
EVENTS_FILE = CCTV_DIR / "events.json"

PIXEL_DELTA = 25            # grey-level change that counts a pixel as changed
CONFIRM_SAMPLES = 2         # consecutive samples over threshold before motion
MAX_EVENTS = 1000


def threshold_for(sensitivity):
    """Changed-pixel fraction needed for motion. Sensitivity 1 (least) → 20 %,
    10 (most) → 0.8 %."""
    s = min(10, max(1, int(sensitivity)))
    return 0.20 * (0.04 ** ((s - 1) / 9.0))


class MotionDetector:
    def __init__(self, sensitivity=6):
        self.sensitivity = sensitivity
        self._prev = None
        self._hits = 0

    def reset(self):
        self._prev = None
        self._hits = 0

    def feed(self, gray):
        """gray: bytes of one grayscale thumbnail (same size every call).
        Returns (score, motion): score = fraction of changed pixels."""
        prev, self._prev = self._prev, gray
        if prev is None or len(prev) != len(gray) or not gray:
            self._hits = 0
            return 0.0, False
        n = len(gray)
        shift = (sum(gray) - sum(prev)) / n
        changed = sum(1 for a, b in zip(gray, prev) if abs(a - b - shift) > PIXEL_DELTA)
        score = changed / n
        if score >= threshold_for(self.sensitivity):
            self._hits += 1
        else:
            self._hits = 0
        return score, self._hits >= CONFIRM_SAMPLES


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, type(default)):
            return data
    except (OSError, ValueError):
        pass
    return default


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def _default_config():
    return {"cameras": [], "armed": False, "retention_days": 14, "record_seconds": 20}


class CctvStore:
    def __init__(self, root=CCTV_DIR):
        self.root = root
        self.config_file = root / "cctv.json"
        self.events_file = root / "events.json"
        self.config = _default_config()
        self.config.update(_read_json(self.config_file, {}))
        self.events = _read_json(self.events_file, [])

    def save(self):
        _write_json(self.config_file, self.config)

    # ------------------------------------------------------------ cameras --

    @property
    def cameras(self):
        return self.config["cameras"]

    def camera(self, cam_id):
        return next((c for c in self.cameras if c["id"] == cam_id), None)

    def add_camera(self, name, device_id=None, url=None, source=None):
        cam = {"id": "cam_" + uuid.uuid4().hex[:6], "name": name,
               "source": source or ("url" if url else "device"), "device_id": device_id or "", "url": url or "",
               "motion": True, "sensitivity": 6, "record_on_motion": False, "auto_start": False}
        self.cameras.append(cam)
        self.save()
        return cam

    def update_camera(self, cam_id, **fields):
        cam = self.camera(cam_id)
        if cam:
            cam.update(fields)
            self.save()

    def remove_camera(self, cam_id):
        self.config["cameras"] = [c for c in self.cameras if c["id"] != cam_id]
        self.save()

    # ------------------------------------------------------------- events --

    def add_event(self, cam_id, kind, score=0.0, snapshot=None, ts=None):
        cam = self.camera(cam_id)
        ev = {"ts": ts or time.time(), "camera": cam_id, "camera_name": cam["name"] if cam else cam_id,
              "kind": kind, "score": round(score, 4), "snapshot": str(snapshot) if snapshot else None}
        self.events.append(ev)
        self.events = self.events[-MAX_EVENTS:]
        _write_json(self.events_file, self.events)
        return ev

    def clear_events(self):
        self.events = []
        _write_json(self.events_file, self.events)

    def events_since(self, since):
        return [e for e in self.events if e["ts"] >= since]

    # -------------------------------------------------------------- files --

    def snapshot_path(self, cam_id, ts=None, tag="motion"):
        dt = datetime.fromtimestamp(ts or time.time())
        folder = self.root / "snapshots" / cam_id / dt.strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{dt.strftime('%H%M%S')}_{dt.microsecond // 1000:03d}_{tag}.jpg"

    def recording_path(self, cam_id, ts=None):
        dt = datetime.fromtimestamp(ts or time.time())
        folder = self.root / "recordings" / cam_id
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{dt.strftime('%Y-%m-%d_%H%M%S')}.mp4"

    def prune(self, days=None, now=None):
        """Delete snapshots / recordings older than the retention period, and
        their events. Returns the number of files removed."""
        days = self.config.get("retention_days", 14) if days is None else days
        if not days or days <= 0:
            return 0
        cutoff = (now or time.time()) - days * 86400
        removed = 0
        for sub in ("snapshots", "recordings"):
            base = self.root / sub
            if not base.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(base, topdown=False):
                for fn in filenames:
                    p = os.path.join(dirpath, fn)
                    try:
                        if os.path.getmtime(p) < cutoff:
                            os.remove(p)
                            removed += 1
                    except OSError:
                        pass
                if dirpath != str(base):
                    try:
                        os.rmdir(dirpath)       # only succeeds when empty
                    except OSError:
                        pass
        before = len(self.events)
        self.events = [e for e in self.events if e["ts"] >= cutoff]
        if len(self.events) != before:
            _write_json(self.events_file, self.events)
        return removed

"""
Fridge camera — an ESP32-S3 camera board inside the fridge (firmware in
firmware/fridge_cam). With the door shut the fridge is dark; when the door
opens the light comes on. So the service asks the board for a picture every
couple of seconds and watches how bright it is:

  dark → bright        the door opened: wait a moment for the camera to adjust,
                       then count the shelves with the fridge AI (at most every
                       N minutes, since each count is one AI request)
  bright for too long  the door was left open → alert

Nothing here needs the GUI thread; the AI runs on this service's thread.
"""
import threading
import time
import urllib.request

from app.server.services import ThreadService

POLL_S = 2.0
SETTLE_S = 2.0         # after the light comes on, let the camera's exposure settle
DARK, BRIGHT = 40, 70  # mean grey level 0–255 (a gap between them so flicker doesn't count as opening)
GIVE_UP_AFTER = 15     # failed pictures in a row before the service reports a failure


def fetch_jpeg(url, timeout=6):
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("the camera didn't send a JPEG picture")
    return data


def brightness(jpeg):
    """Mean grey level of the picture, 0 (black) to 255 (white)."""
    from PySide6.QtGui import QImage
    img = QImage.fromData(jpeg, "JPG")
    if img.isNull():
        raise ValueError("unreadable picture")
    small = img.scaled(32, 24).convertToFormat(QImage.Format_Grayscale8)
    bpl = small.bytesPerLine()
    raw = bytes(small.constBits())
    px = b"".join(raw[r * bpl:r * bpl + 32] for r in range(24))
    return sum(px) / len(px)


class FridgeCamService(ThreadService):
    id = "fridge_cam"
    title = "Fridge camera"
    description = "An ESP32-S3 camera inside the fridge: counts what's inside each time the door opens."
    icon = "camera"
    default_enabled = False
    settings_schema = [
        ("url", "Camera picture address", "str", "",
         "Shown on the board's serial monitor, e.g. http://192.168.1.40/capture"),
        ("gap_min", "Count at most every (minutes)", "int", 10, "Each count is one AI request"),
        ("open_alert_s", "Door-open alert after (seconds)", "int", 120, "0 = no alert"),
    ]

    def __init__(self, store, settings_loader, bus, fetch=fetch_jpeg, measure=brightness, check=None,
                 clock=time.time):
        super().__init__()
        self.store = store
        self.settings_loader = settings_loader          # → the fridge AI settings (vision_ai)
        self.bus = bus
        self.fetch = fetch
        self.measure = measure
        self.clock = clock
        if check is None:
            from app.services.fridge_service import run_photo_check
            check = run_photo_check
        self.check = check
        self.state = "unknown"          # "open" | "closed"
        self.level = None
        self.opens = 0
        self.counts = 0
        self.last_count = 0.0
        self.last_result = ""

    def can_start(self):
        if not (self.setting("url") or "").strip():
            return False, "Enter the camera's picture address (e.g. http://192.168.1.40/capture) in Settings."
        return True, ""

    def run(self, stop):
        url = self.setting("url").strip()
        gap = max(1, int(self.setting("gap_min") or 10)) * 60
        open_alert = int(self.setting("open_alert_s") or 0)
        fails, opened_at, alerted = 0, None, False
        self.mark_running()
        self.log(f"Watching {url}")
        while not stop.is_set():
            try:
                jpeg = self.fetch(url)
                level = self.measure(jpeg)
                fails = 0
            except Exception as e:
                fails += 1
                if fails == 1:
                    self.log(f"No picture from the camera: {e}", "warn")
                if fails >= GIVE_UP_AFTER:
                    raise RuntimeError(f"The fridge camera isn't answering ({e})")
                stop.wait(POLL_S)
                continue
            self.level = level
            now = self.clock()
            if level >= BRIGHT and self.state != "open":
                self.state, opened_at, alerted = "open", now, False
                self.opens += 1
                if now - self.last_count >= gap:
                    if stop.wait(SETTLE_S):
                        break
                    try:
                        jpeg = self.fetch(url)
                    except Exception:
                        pass
                    self._count(jpeg)
            elif level <= DARK and self.state != "closed":
                if self.state == "open" and opened_at is not None:
                    self.log(f"Door closed after {now - opened_at:.0f} s")
                self.state = "closed"
            if (self.state == "open" and open_alert and not alerted and opened_at is not None
                    and now - opened_at >= open_alert):
                alerted = True
                self.bus.publish("fridge", "Fridge door open",
                                 f"The fridge has been open for {(now - opened_at) / 60:.0f} min — close it?")
            stop.wait(POLL_S)

    def _count(self, jpeg):
        from app.services.fridge_service import changes_text
        self.last_count = self.clock()
        try:
            res = self.check(self.store, jpeg, self.settings_loader(), "camera")
        except Exception as e:
            self.last_result = f"not counted: {e}"
            self.log(f"Couldn't count the shelves: {e}", "warn")
            return
        self.counts += 1
        self.last_result = "photo saved (no AI set up)" if res["manual"] else \
            changes_text(res["changes"]).replace("\n", ", ")
        self.log(f"Door opened — {self.last_result}")

    def info(self):
        url = (self.setting("url") or "").strip() or "not set"
        door = {"open": "door open", "closed": "door shut"}.get(self.state, "no picture yet")
        lines = [f"Camera: {url}",
                 f"Now: {door}" + (f" (brightness {self.level:.0f}/255)" if self.level is not None else ""),
                 f"Door opened {self.opens}× · counted {self.counts}× since start"]
        if self.last_count:
            lines.append(f"Last count {time.strftime('%H:%M', time.localtime(self.last_count))}: {self.last_result}")
        return lines

    def actions(self):
        def test():
            url = (self.setting("url") or "").strip()
            if not url:
                raise RuntimeError("Enter the camera address first")
            jpeg = self.fetch(url, timeout=4)
            return f"Picture OK: {len(jpeg) // 1024} KB, brightness {self.measure(jpeg):.0f}/255 " \
                   f"(dark below {DARK}, light above {BRIGHT})."

        def count_now():
            url = (self.setting("url") or "").strip()
            if not url:
                raise RuntimeError("Enter the camera address first")
            threading.Thread(target=lambda: self._count(self.fetch(url)), daemon=True,
                             name="fridge-cam-count").start()
            return "Counting in the background — see the Fridge page in a minute."
        return [("Test the camera", test), ("Count now", count_now)]

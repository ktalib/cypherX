"""
Fridge stock — what's in a fridge that isn't smart, and how fast it goes.

Counts come from four places, and each change is kept in the item's history:
  bought   ticking an item as bought in Groceries adds it (× pack size, e.g. a crate = 30 eggs)
  photo    an AI counts a fridge photo (see app/services/vision_ai.py): the true count
  manual   −1 / +1 taps in the app, the phone dashboard or Telegram (/took 2 eggs)
  camera   the fridge camera (ESP32-S3) took the photo when the door opened

From the history it learns how fast each item is used (drops over the last
weeks, ignoring purchases), so between photos it can estimate what's left and
when it runs out. Items at or below their "low" level are reported once (until
they're restocked) so the app can alert and add them to the shopping list.

No Qt here; safe to call from any thread. Lives in USER_DATA_DIR/fridge:
  fridge.json         items + recent checks
  photos/*.jpg        the last fridge photos
"""
import json
import os
import re
import threading
import time
import uuid

from app.config import USER_DATA_DIR

FRIDGE_DIR = USER_DATA_DIR / "fridge"
MAX_HISTORY = 500
MAX_CHECKS = 50
RATE_WINDOW_DAYS = 21
MIN_RATE_SPAN_DAYS = 0.5     # need at least half a day of history before guessing a rate

# Seeded once so the first photo has names to match; edit or remove freely.
DEFAULT_ITEMS = [
    {"name": "Eggs", "low_at": 6, "per_pack": 30, "match": "egg"},
    {"name": "Beer", "low_at": 2, "per_pack": 1,
     "match": "beer, lager, star, gulder, heineken, trophy, hero, goldberg, budweiser, guinness"},
]


def norm(name):
    """'Eggs (crate)' → 'egg crate'; drops plurals so 'beers' matches 'beer'."""
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    out = []
    for w in words:
        if len(w) > 3 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and (w.endswith("oes") or (w.endswith("es") and w[-3] in "sxz")):
            w = w[:-2]
        elif len(w) > 2 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return " ".join(out)


def _keywords(item):
    return [norm(k) for k in (item.get("match") or "").split(",") if norm(k)]


class FridgeStore:
    def __init__(self, root=None):
        self.root = root or FRIDGE_DIR
        os.makedirs(os.path.join(self.root, "photos"), exist_ok=True)
        self.path = os.path.join(self.root, "fridge.json")
        self._lock = threading.RLock()
        self.version = 0
        self.data = {"items": [], "checks": [], "seeded": False}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass
        if not self.data.get("seeded"):
            self.data["seeded"] = True
            for d in DEFAULT_ITEMS:
                if not self.find(d["name"]):
                    self._new(d["name"], 0, d["low_at"], d["per_pack"], d["match"], record=False)
            self._save()

    # ------------------------------------------------------------- storage --

    def _save(self):
        tmp = f"{self.path}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.path)
        self.version += 1

    def _raw(self, item_id):
        return next((i for i in self.data["items"] if i["id"] == item_id), None)

    # --------------------------------------------------------------- items --

    def items(self, now=None):
        """Copies with the live estimate, usage rate, days left and low flag."""
        with self._lock:
            return [self._view(i, now) for i in sorted(self.data["items"], key=lambda i: i["name"].lower())]

    def item(self, item_id, now=None):
        with self._lock:
            raw = self._raw(item_id)
            return self._view(raw, now) if raw else None

    def _view(self, raw, now=None):
        now = now or time.time()
        v = {k: raw[k] for k in ("id", "name", "count", "low_at", "per_pack", "match", "updated")}
        v["source"] = raw["history"][-1][2] if raw["history"] else ""
        rate = self.rate_per_day(raw, now)
        est = raw["count"]
        if rate and raw["history"]:
            est = max(0.0, raw["count"] - rate * (now - raw["history"][-1][0]) / 86400)
        v["rate"] = rate
        v["estimate"] = est
        v["days_left"] = (est / rate) if rate else None
        v["low"] = est <= raw["low_at"]
        return v

    def find(self, name):
        """Best match for a name from a photo, a grocery list or a chat command."""
        want = norm(name)
        if not want:
            return None
        with self._lock:
            items = self.data["items"]
            for i in items:                                   # same name
                if norm(i["name"]) == want:
                    return i
            words = set(want.split())
            for i in items:                                   # one of its keywords
                if any(k == want or k in words for k in _keywords(i)):
                    return i
            for i in items:                                   # "eggs" in "fresh eggs (crate)"
                if set(norm(i["name"]).split()) <= words:
                    return i
            return None

    def _new(self, name, count, low_at, per_pack, match, record=True, source="manual"):
        raw = {"id": "f_" + uuid.uuid4().hex[:8], "name": name.strip()[:40], "count": max(0, int(count)),
               "low_at": max(0, int(low_at)), "per_pack": max(1, int(per_pack)), "match": (match or "").strip(),
               "updated": time.time(), "history": [], "alerted": False}
        if record:
            raw["history"].append([raw["updated"], raw["count"], source])
        self.data["items"].append(raw)
        return raw

    def add_item(self, name, count=0, low_at=1, per_pack=1, match=""):
        with self._lock:
            if not (name or "").strip():
                raise ValueError("Give the item a name")
            same = self.find(name)
            if same and norm(same["name"]) == norm(name):
                raise ValueError(f"'{name}' is already in the fridge list")
            raw = self._new(name, count, low_at, per_pack, match)
            self._save()
            return self._view(raw)

    def update_item(self, item_id, **fields):
        with self._lock:
            raw = self._raw(item_id)
            if raw is None:
                raise LookupError("No such item")
            for k in ("name", "match"):
                if k in fields:
                    raw[k] = str(fields[k]).strip()[:200 if k == "match" else 40] or raw[k]
            for k, lo in (("low_at", 0), ("per_pack", 1)):
                if k in fields:
                    raw[k] = max(lo, int(fields[k]))
            if raw["count"] > raw["low_at"]:
                raw["alerted"] = False
            self._save()

    def remove_item(self, item_id):
        with self._lock:
            self.data["items"] = [i for i in self.data["items"] if i["id"] != item_id]
            self._save()

    # -------------------------------------------------------------- counts --

    def _record(self, raw, count, source, ts=None):
        ts = ts or time.time()
        raw["count"] = max(0, int(round(count)))
        raw["updated"] = ts
        raw["history"].append([ts, raw["count"], source])
        raw["history"] = raw["history"][-MAX_HISTORY:]
        if raw["count"] > raw["low_at"]:
            raw["alerted"] = False

    def set_count(self, item_id, count, source="manual", ts=None):
        with self._lock:
            raw = self._raw(item_id)
            if raw is None:
                raise LookupError("No such item")
            before = raw["count"]
            self._record(raw, count, source, ts)
            self._save()
            return {"id": item_id, "name": raw["name"], "before": before, "after": raw["count"]}

    def adjust(self, item_id, delta, source="manual", ts=None):
        """+delta / −delta from the *estimate* — what's really there now."""
        with self._lock:
            raw = self._raw(item_id)
            if raw is None:
                raise LookupError("No such item")
            base = round(self._view(raw, ts)["estimate"])
            return self.set_count(item_id, base + int(delta), source, ts)

    def apply_check(self, counts, photo=None, provider="", note="", source="photo", add_new=True, ts=None):
        """counts: [(name, count)] from a photo. Returns the changes, new items included."""
        ts = ts or time.time()
        changes = []
        with self._lock:
            for name, count in counts:
                raw = self.find(name)
                if raw is None:
                    if not add_new or count <= 0:
                        continue
                    raw = self._new(name.strip().capitalize(), 0, 1, 1, "", record=False)
                    changes.append({"id": raw["id"], "name": raw["name"], "before": None, "after": int(count),
                                    "new": True})
                else:
                    changes.append({"id": raw["id"], "name": raw["name"], "before": raw["count"],
                                    "after": int(count), "new": False})
                self._record(raw, count, source, ts)
            self.data["checks"].append({"ts": ts, "photo": str(photo) if photo else None, "provider": provider,
                                        "note": note, "source": source,
                                        "counts": [[c["name"], c["after"]] for c in changes]})
            self.data["checks"] = self.data["checks"][-MAX_CHECKS:]
            self._save()
        return changes

    def on_bought(self, grocery_name, qty, ts=None):
        """A grocery item was ticked as bought (qty < 0: un-ticked). Returns the change or None."""
        with self._lock:
            want = set(norm(grocery_name).split())
            raw = next((i for i in self.data["items"]
                        if any(set(k.split()) <= want for k in _keywords(i))), None) or self.find(grocery_name)
            if raw is None:
                return None
            delta = int(round(qty)) * raw["per_pack"]
        return self.adjust(raw["id"], delta, source="bought", ts=ts)

    @property
    def checks(self):
        with self._lock:
            return list(self.data["checks"])

    def last_check(self):
        with self._lock:
            return dict(self.data["checks"][-1]) if self.data["checks"] else None

    # ---------------------------------------------------- learning / alerts --

    @staticmethod
    def rate_per_day(raw, now=None):
        """Units used per day over the last weeks (purchases don't count as negative use)."""
        now = now or time.time()
        since = now - RATE_WINDOW_DAYS * 86400
        hist = [h for h in raw["history"] if h[0] >= since]
        if len(hist) < 2:
            return None
        span = (hist[-1][0] - hist[0][0]) / 86400      # between observations, not up to now
        if span < MIN_RATE_SPAN_DAYS:
            return None
        used = sum(max(0, a[1] - b[1]) for a, b in zip(hist, hist[1:]))
        return used / span if used else None

    def newly_low(self, now=None):
        """Items that just reached their low level (each reported once until restocked)."""
        out = []
        with self._lock:
            for raw in self.data["items"]:
                v = self._view(raw, now)
                if v["low"] and not raw["alerted"] and raw["history"]:
                    raw["alerted"] = True
                    out.append(v)
            if out:
                self._save()
        return out

    # -------------------------------------------------------------- photos --

    def save_photo(self, jpeg, ts=None):
        ts = ts or time.time()
        folder = os.path.join(self.root, "photos")
        path = os.path.join(folder, time.strftime("%Y-%m-%d_%H%M%S", time.localtime(ts))
                            + f"_{int(ts * 1000) % 1000:03d}.jpg")
        with open(path, "wb") as f:
            f.write(jpeg)
        photos = sorted(os.listdir(folder))
        for old in photos[:-MAX_CHECKS]:
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass
        return path


def summary_text(items, limit=None):
    """'Eggs ≈7 (2 days) · Beer 4' for Telegram and notifications."""
    parts = []
    for v in items[:limit] if limit else items:
        est = v["estimate"]
        n = f"≈{est:.0f}" if v["rate"] and abs(est - v["count"]) >= 0.5 else f"{v['count']}"
        extra = f" ({v['days_left']:.0f} d)" if v["days_left"] is not None and v["days_left"] < 14 else ""
        parts.append(f"{'⚠️ ' if v['low'] else ''}{v['name']} {n}{extra}")
    return " · ".join(parts)


def changes_text(changes):
    if not changes:
        return "Nothing I recognised in the photo."
    bits = []
    for c in changes:
        if c["new"]:
            bits.append(f"{c['name']}: {c['after']} (new)")
        elif c["before"] == c["after"]:
            bits.append(f"{c['name']}: {c['after']}")
        else:
            d = c["after"] - c["before"]
            bits.append(f"{c['name']}: {c['after']} ({'+' if d > 0 else '−'}{abs(d)})")
    return "\n".join(bits)


def run_photo_check(store, image_bytes, settings, source="photo"):
    """Save the photo, count it with the chosen AI (and backup), update the stock.
    Blocks for as long as the AI takes — call it off the GUI thread.
    Raises vision_ai.VisionError when no AI could read it (the photo is still kept)."""
    from app.services import vision_ai
    jpeg = vision_ai.prepare_jpeg(image_bytes)
    photo = store.save_photo(jpeg)
    if (settings.get("provider") or "none") == "none":
        store.apply_check([], photo=photo, provider="none", note="Saved to count by hand", source=source)
        return {"manual": True, "photo": photo, "changes": [], "provider": "none", "note": "", "errors": []}
    try:
        res = vision_ai.count_items(settings, jpeg, [i["name"] for i in store.items()])
    except vision_ai.VisionError as e:
        store.apply_check([], photo=photo, provider="", note=f"Not counted: {e}", source=source)
        raise
    changes = store.apply_check(res["items"], photo=photo, provider=res["provider"], note=res["note"],
                                source=source)
    return {"manual": False, "photo": photo, "changes": changes, "provider": res["provider"],
            "note": res["note"], "errors": res["errors"]}

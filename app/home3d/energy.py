"""
Energy log — what the home power system is actually doing, from data the user
can see today without smart hardware:

  • prepaid meter: tokens bought (amount + units) and readings typed in from the
    meter's display. From these come the real burn rate (kWh / day), the units
    left right now, the days until the meter runs out and the real price per kWh.
  • battery: readings typed in from the inverter / charge controller display
    (charge % and / or battery volts).
  • grid: power cuts, detected through the laptop charger. When the laptop is
    plugged into a grid-only socket, "charger lost power" means the grid is off.

Everything lives in USER_DATA_DIR/smart_home_energy.json, kept apart from the
layout file so resetting the 3D layout never wipes the history.
Times are POSIX timestamps (seconds).
"""
import json
import time

from app.config import USER_DATA_DIR

ENERGY_FILE = USER_DATA_DIR / "smart_home_energy.json"

RATE_WINDOW_DAYS = 14        # burn rate looks at readings from the last two weeks
MIN_RATE_SPAN_H = 6          # ... spanning at least this long
MAX_EVENTS = 500             # cap on each log so the file stays small


def _empty():
    return {"tokens": [], "readings": [], "battery": [], "outages": [],
            "grid_detect": False}


class EnergyLog:
    def __init__(self, path=ENERGY_FILE):
        self.path = path
        self.data = self._load()

    # ------------------------------------------------------------ storage --

    def _load(self):
        data = _empty()
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                for k, v in stored.items():
                    if k in data and isinstance(v, type(data[k])):
                        data[k] = v
        except (OSError, ValueError):
            pass
        return data

    def save(self):
        for k in ("tokens", "readings", "battery", "outages"):
            self.data[k] = sorted(self.data[k], key=lambda e: e.get("ts", e.get("start", 0)))[-MAX_EVENTS:]
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        tmp.replace(self.path)

    # ------------------------------------------------------------ entries --

    @property
    def tokens(self):
        return self.data["tokens"]

    @property
    def readings(self):
        return self.data["readings"]

    @property
    def battery(self):
        return self.data["battery"]

    @property
    def outages(self):
        return self.data["outages"]

    def add_token(self, amount, units, ts=None):
        self.tokens.append({"ts": ts or time.time(), "amount": float(amount), "units": float(units)})
        self.save()

    def add_reading(self, units, ts=None):
        self.readings.append({"ts": ts or time.time(), "units": float(units)})
        self.save()

    def add_battery(self, pct=None, volts=None, ts=None):
        entry = {"ts": ts or time.time()}
        if pct is not None:
            entry["pct"] = float(pct)
        if volts is not None:
            entry["volts"] = float(volts)
        self.battery.append(entry)
        self.save()

    def remove(self, kind, entry):
        self.data[kind] = [e for e in self.data[kind] if e is not entry]
        self.save()

    # ------------------------------------------------------- prepaid meter --

    def price_per_kwh(self):
        """Average price actually paid, from the tokens bought (None without tokens)."""
        units = sum(t["units"] for t in self.tokens)
        if units <= 0:
            return None
        return sum(t["amount"] for t in self.tokens) / units

    def _tokens_between(self, t0, t1):
        return sum(t["units"] for t in self.tokens if t0 < t["ts"] <= t1)

    def burn_rate(self, now=None):
        """kWh per day from consecutive meter readings, tokens loaded in between
        counted as added units. None until there is enough history."""
        now = now or time.time()
        recent = sorted((r for r in self.readings if r["ts"] >= now - RATE_WINDOW_DAYS * 86400),
                        key=lambda r: r["ts"])
        if len(recent) < 2:
            return None
        used = 0.0
        for a, b in zip(recent, recent[1:]):
            used += a["units"] + self._tokens_between(a["ts"], b["ts"]) - b["units"]
        span_h = (recent[-1]["ts"] - recent[0]["ts"]) / 3600.0
        if span_h < MIN_RATE_SPAN_H or used < 0:
            return None
        return used / span_h * 24.0

    def units_left(self, now=None):
        """Estimated units on the meter now: last reading, plus tokens loaded
        since, minus what the burn rate says was used since."""
        now = now or time.time()
        if not self.readings:
            return None
        last = max(self.readings, key=lambda r: r["ts"])
        units = last["units"] + self._tokens_between(last["ts"], now)
        rate = self.burn_rate(now)
        if rate:
            units -= rate * (now - last["ts"]) / 86400.0
        return max(0.0, units)

    def days_left(self, now=None):
        rate = self.burn_rate(now)
        left = self.units_left(now)
        if not rate or left is None:
            return None
        return left / rate

    def last_reading(self):
        return max(self.readings, key=lambda r: r["ts"]) if self.readings else None

    # ------------------------------------------------------------- battery --

    def last_battery(self):
        return max(self.battery, key=lambda r: r["ts"]) if self.battery else None

    # ---------------------------------------------------------------- grid --

    @property
    def grid_detect(self):
        return bool(self.data.get("grid_detect"))

    @grid_detect.setter
    def grid_detect(self, on):
        self.data["grid_detect"] = bool(on)
        self.save()

    def open_outage(self):
        return next((o for o in reversed(self.outages) if o.get("end") is None), None)

    def grid_changed(self, grid_on, now=None):
        """Feed the latest grid state. Opens an outage when the grid goes off and
        closes it when it comes back. Returns "off", "on" or None (no change)."""
        now = now or time.time()
        current = self.open_outage()
        if not grid_on and current is None:
            self.outages.append({"start": now, "end": None})
            self.save()
            return "off"
        if grid_on and current is not None:
            current["end"] = now
            self.save()
            return "on"
        return None

    def outage_hours(self, since, now=None):
        """Hours without grid since the given time (open outage counts up to now)."""
        now = now or time.time()
        total = 0.0
        for o in self.outages:
            start, end = o["start"], o.get("end") or now
            if end > since:
                total += end - max(start, since)
        return total / 3600.0


def read_grid_from_charger():
    """True / False when the laptop charger has / has lost power, None when it
    can't be told (desktop PC, no battery sensor)."""
    try:
        import psutil
        bat = psutil.sensors_battery()
    except Exception:
        return None
    if bat is None or bat.power_plugged is None:
        return None
    return bool(bat.power_plugged)

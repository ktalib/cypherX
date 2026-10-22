"""
The inverter, measured with two ordinary smart energy plugs (no data port needed):

    wall socket ──[ plug "IN" ]──► inverter ──[ plug "OUT" ]──► extension board → appliances
                   (grid side)                 (house side)

  IN  answers and sees mains voltage  → the grid is on; its watts are what the
                                        inverter takes from the grid (load + battery charging)
  IN  goes silent / 0 V while OUT     → the grid is off (the IN plug lost its power with the
      still answers                     grid; OUT keeps running on the battery)
  OUT watts                           → the real load on the inverter, live
  IN − OUT (grid on)                  → roughly what goes into charging the battery

Plugs are linked to these roles on the Smart Devices page ("Plugged in" → Inverter input /
Inverter output). CYPHER-X only reads them — it never switches them.

No Qt here (unit-tested on its own).
"""
import time

INVERTER_IN = "@inverter_in"
INVERTER_OUT = "@inverter_out"
ROLES = {INVERTER_IN: "Inverter input (grid → inverter)", INVERTER_OUT: "Inverter output (house load)"}

FRESH_S = 30          # readings older than this are ignored
MAINS_MIN_V = 100     # below this the grid side is counted as off (Nigeria is 230 V; low-voltage nights still pass)


def is_role(item_id):
    return bool(item_id) and item_id in ROLES


class InverterMeter:
    def __init__(self, linked=None):
        """linked: callable → the roles that have a plug linked (read from the smart device book)."""
        # role -> {"reading": dict|None, "ok_ts": last good answer, "err_ts": last failure, "error": str|None}
        self.state = {INVERTER_IN: {}, INVERTER_OUT: {}}
        self._linked = linked or (lambda: ())

    @property
    def linked(self):
        return set(self._linked()) & set(ROLES)

    def update(self, role, reading=None, error=None, now=None):
        now = now or time.time()
        s = self.state.setdefault(role, {})
        if error is None and reading is not None:
            s.update(reading=reading, ok_ts=now, error=None)
        else:
            s.update(err_ts=now, error=error or "no answer")

    def _fresh(self, role, now):
        s = self.state.get(role) or {}
        if s.get("error") or not s.get("ok_ts") or now - s["ok_ts"] > FRESH_S:
            return None
        return s["reading"]

    def _silent(self, role, now):
        """The plug stopped answering recently (as a plug on the grid side does in a power cut)."""
        s = self.state.get(role) or {}
        return bool(s.get("error")) and now - s.get("err_ts", 0) <= FRESH_S

    @property
    def configured(self):
        return INVERTER_IN in self.linked

    def grid_on(self, now=None):
        """True / False, or None when it can't be told (no IN plug, or both plugs silent)."""
        now = now or time.time()
        if INVERTER_IN not in self.linked:
            return None
        rin = self._fresh(INVERTER_IN, now)
        if rin is not None:
            v = rin.get("voltage")
            if v is None or v >= MAINS_MIN_V:
                return True
            return False
        if self._silent(INVERTER_IN, now):
            # With an OUT plug: OUT still answering (it runs on the battery) while IN went quiet is a power
            # cut, and both quiet is a Wi-Fi problem. Without one, assume a cut — the router is usually
            # on the inverter, so Wi-Fi stays up when the grid goes.
            if INVERTER_OUT not in self.linked or self._fresh(INVERTER_OUT, now) is not None:
                return False
        return None

    def load_w(self, now=None):
        """Watts the inverter is supplying to the house right now (None when not measured)."""
        r = self._fresh(INVERTER_OUT, now or time.time()) if INVERTER_OUT in self.linked else None
        if r is None:
            return None
        if r.get("power_w") is not None:
            return float(r["power_w"])
        return 0.0 if r.get("on") is False else None

    def input_w(self, now=None):
        r = self._fresh(INVERTER_IN, now or time.time()) if INVERTER_IN in self.linked else None
        return float(r["power_w"]) if r and r.get("power_w") is not None else None

    def charging_w(self, now=None):
        """Roughly what goes into the battery from the grid (None when it can't be measured)."""
        now = now or time.time()
        if self.grid_on(now) is not True:
            return None
        pin, pout = self.input_w(now), self.load_w(now)
        if pin is None or pout is None:
            return None
        return max(0.0, pin - pout)

    def summary(self, now=None):
        """Short lines for the Smart Home page and the Services page."""
        now = now or time.time()
        if not self.linked:
            return []
        lines = []
        g = self.grid_on(now)
        lines.append({True: "Grid on (inverter input plug)", False: "Grid OFF (inverter input plug lost power)",
                      None: "Grid: no answer from the inverter input plug"}[g] if INVERTER_IN in self.linked
                     else "No plug on the inverter input — grid not watched by plug")
        load = self.load_w(now)
        if INVERTER_OUT in self.linked:
            lines.append(f"House load {load:,.0f} W (measured)" if load is not None else
                         "House load: no answer from the inverter output plug")
        ch = self.charging_w(now)
        if ch is not None:
            lines.append(f"Charging the battery ≈ {ch:,.0f} W")
        return lines

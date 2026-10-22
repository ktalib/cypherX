"""
Smart Home model — rooms, furniture and powered devices of the flat, plus the
power-system settings (inverter, battery, tariff).

Everything lives in one JSON file (USER_DATA_DIR/smart_home.json) so new rooms
and devices can be added later without code changes. The first run seeds it
with the living room, bedroom and kitchen measured from the photos.

Units: metres. x runs left → right, z runs back (north, kitchen) → front,
y is up. A room is an axis-aligned rectangle (x, z, w, d).
"""
import copy
import time
import json
import uuid

from app.config import USER_DATA_DIR

HOME_FILE = USER_DATA_DIR / "smart_home.json"
WALL_H = 2.7

LAYOUT_VERSION = 2

# One-bedroom flat. Plan, left to right:  Living room | Kitchen (walk-through) | Bedroom.
# The curtained door beside the photo in the living room opens into the kitchen;
# straight across the kitchen is the bedroom door.
DEFAULT_HOME = {
    "version": LAYOUT_VERSION,
    "rooms": [
        {"id": "living", "name": "Living Room", "x": 0.0, "z": 0.0, "w": 4.4, "d": 3.8,
         "floor": "living_floor", "floor_tile": 0.9, "dado": "living_marble", "dado_h": 1.25,
         "paint": "living_paint"},
        {"id": "kitchen", "name": "Kitchen", "x": 4.4, "z": 0.0, "w": 1.7, "d": 3.8,
         "floor": "kitchen_floor", "floor_tile": 0.6, "dado": "kitchen_wall", "dado_h": 1.9,
         "paint": "living_paint"},
        {"id": "bedroom", "name": "Bedroom", "x": 6.1, "z": 0.0, "w": 3.4, "d": 3.6,
         "floor": "bed_floor", "floor_tile": 1.1, "dado": "bed_wall_tile", "dado_h": 1.05,
         "paint": "bed_paint"},
    ],
    # kind decides the 3D shape; device != None makes it a powered device
    "items": [
        # ---- living room
        {"id": "tv", "kind": "tv_wall", "name": "Television", "room": "living",
         "x": 1.4, "z": 0.0, "w": 1.5, "d": 0.08, "h": 0.95, "y": 1.0,
         "device": {"watts": 100, "hours": 5, "on": False}},
        {"id": "tv_stand", "kind": "cabinet", "name": "TV stand", "room": "living",
         "x": 1.5, "z": 0.06, "w": 1.3, "d": 0.42, "h": 0.5, "color": "#e8e6ee"},
        {"id": "decoder", "kind": "small_box", "name": "Decoder", "room": "living",
         "x": 1.95, "z": 0.12, "w": 0.32, "d": 0.22, "h": 0.07, "y": 0.5, "color": "#16181d",
         "device": {"watts": 25, "hours": 5, "on": False}},
        {"id": "sofa", "kind": "sofa_l", "name": "Sofa", "room": "living",
         "x": 0.9, "z": 2.95, "w": 2.7, "d": 0.8, "h": 0.8, "color": "#2a2b33"},
        {"id": "coffee", "kind": "coffee_table", "name": "Coffee table", "room": "living",
         "x": 1.75, "z": 1.5, "w": 0.65, "d": 0.65, "h": 0.45, "color": "#eceaf0"},
        {"id": "fan", "kind": "fan", "name": "Standing fan", "room": "living",
         "x": 0.3, "z": 0.5, "w": 0.45, "d": 0.45, "h": 1.3,
         "device": {"watts": 55, "hours": 8, "on": False}},
        {"id": "light_living", "kind": "ceiling_light", "name": "Living room light", "room": "living",
         "x": 2.1, "z": 1.8, "w": 0.3, "d": 0.3, "h": 0.05,
         "device": {"watts": 15, "hours": 6, "on": False}},
        {"id": "charger_living", "kind": "small_box", "name": "Phone charger", "room": "living",
         "x": 2.55, "z": 0.15, "w": 0.1, "d": 0.08, "h": 0.04, "y": 0.5, "color": "#f4f4f4",
         "device": {"watts": 10, "hours": 3, "on": False}},
        {"id": "frame", "kind": "decal", "name": "Photo", "room": "living", "wall": "east",
         "x": 4.4, "z": 1.45, "w": 0.6, "h": 0.8, "y": 1.45, "tex": "photo_frame"},
        {"id": "curtain_k", "kind": "decal", "name": "Door to kitchen", "room": "living", "wall": "east",
         "x": 4.4, "z": 2.4, "w": 0.9, "h": 2.15, "y": 0.0, "tex": "curtain_living", "door": True},
        {"id": "hub", "kind": "power_hub", "name": "Power hub", "room": "living",
         "x": 0.12, "z": 3.25, "w": 0.45, "d": 0.32, "h": 0.65},
        # ---- kitchen (walk-through between living room and bedroom)
        {"id": "counter", "kind": "counter", "name": "Counter", "room": "kitchen",
         "x": 4.45, "z": 0.05, "w": 0.62, "d": 1.55, "h": 0.9},
        {"id": "stove", "kind": "small_box", "name": "Gas cooker", "room": "kitchen",
         "x": 4.5, "z": 0.3, "w": 0.5, "d": 0.6, "h": 0.12, "y": 0.9, "color": "#1d1e22"},
        {"id": "fridge", "kind": "fridge", "name": "Fridge", "room": "kitchen",
         "x": 4.47, "z": 1.65, "w": 0.6, "d": 0.62, "h": 1.45,
         "device": {"watts": 150, "hours": 10, "on": True}},
        {"id": "gas", "kind": "small_box", "name": "Gas cylinder", "room": "kitchen",
         "x": 5.65, "z": 0.15, "w": 0.32, "d": 0.32, "h": 0.55, "color": "#2347a8"},
        {"id": "bin", "kind": "small_box", "name": "Drum", "room": "kitchen",
         "x": 5.55, "z": 0.6, "w": 0.42, "d": 0.42, "h": 0.75, "color": "#121316"},
        {"id": "door_kl", "kind": "decal", "name": "Door to living room", "room": "kitchen", "wall": "west",
         "x": 4.4, "z": 2.4, "w": 0.9, "h": 2.15, "y": 0.0, "tex": "curtain_living", "door": True},
        {"id": "door_kb", "kind": "decal", "name": "Door to bedroom", "room": "kitchen", "wall": "east",
         "x": 6.1, "z": 2.4, "w": 0.9, "h": 2.15, "y": 0.0, "tex": "curtain_bed", "door": True},
        {"id": "window_k", "kind": "decal", "name": "Kitchen window", "room": "kitchen", "wall": "north",
         "x": 4.75, "z": 0.0, "w": 1.0, "h": 0.75, "y": 1.2, "tex": "kitchen_window"},
        {"id": "light_kitchen", "kind": "ceiling_light", "name": "Kitchen light", "room": "kitchen",
         "x": 5.25, "z": 1.6, "w": 0.3, "d": 0.3, "h": 0.05,
         "device": {"watts": 15, "hours": 4, "on": False}},
        # ---- bedroom
        {"id": "curtain_b", "kind": "decal", "name": "Door to kitchen", "room": "bedroom", "wall": "west",
         "x": 6.1, "z": 2.4, "w": 0.9, "h": 2.15, "y": 0.0, "tex": "curtain_bed", "door": True},
        {"id": "bed", "kind": "bed", "name": "Bed", "room": "bedroom",
         "x": 7.05, "z": 0.12, "w": 2.2, "d": 2.1, "h": 0.55},
        {"id": "wardrobe", "kind": "wardrobe", "name": "Wardrobe", "room": "bedroom",
         "x": 7.9, "z": 3.0, "w": 1.3, "d": 0.55, "h": 2.0},
        {"id": "nightstand", "kind": "cabinet", "name": "Bedside table", "room": "bedroom",
         "x": 6.4, "z": 0.15, "w": 0.5, "d": 0.42, "h": 0.55, "color": "#17171b"},
        {"id": "light_bed", "kind": "ceiling_light", "name": "Bedroom light", "room": "bedroom",
         "x": 7.8, "z": 1.8, "w": 0.3, "d": 0.3, "h": 0.05,
         "device": {"watts": 15, "hours": 6, "on": False}},
        {"id": "charger_bed", "kind": "small_box", "name": "Bedside charger", "room": "bedroom",
         "x": 6.6, "z": 0.25, "w": 0.1, "d": 0.08, "h": 0.04, "y": 0.55, "color": "#f4f4f4",
         "device": {"watts": 10, "hours": 6, "on": False}},
    ],
    "power": {"source": "Grid", "inverter_w": 3000, "battery_wh": 2400, "battery_pct": 100,
              "tariff": 225.0, "currency": "₦"},
}


LIVE_FRESH_S = 30          # a plug reading older than this falls back to the rated watts


class HomeModel:
    def __init__(self):
        self.data = self._load()
        # called with (item_id, on) whenever an appliance is switched here, so a linked smart
        # plug can follow (set by the main window)
        self.switch_hook = None
        self.live = {}             # item_id -> (watts measured by its smart plug, timestamp)
        # optional callable → the whole house's watts measured at the inverter (None when not measured)
        self.measured_load = None

    # ------------------------------------------------------------ storage --

    def _load(self):
        try:
            with open(HOME_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if (isinstance(data, dict) and data.get("rooms") and isinstance(data.get("items"), list)
                    and data.get("version", 1) >= LAYOUT_VERSION):
                data.setdefault("power", copy.deepcopy(DEFAULT_HOME["power"]))
                return data
        except (OSError, ValueError):
            pass
        data = copy.deepcopy(DEFAULT_HOME)
        self._write(data)
        return data

    def _write(self, data):
        tmp = HOME_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(HOME_FILE)

    def save(self):
        self._write(self.data)

    def reset(self):
        self.data = copy.deepcopy(DEFAULT_HOME)
        self.save()

    # ------------------------------------------------------------ queries --

    @property
    def rooms(self):
        return self.data["rooms"]

    @property
    def items(self):
        return self.data["items"]

    @property
    def power(self):
        return self.data["power"]

    def room(self, room_id):
        return next((r for r in self.rooms if r["id"] == room_id), None)

    def devices(self, room_id=None):
        return [i for i in self.items if i.get("device")
                and (room_id is None or i.get("room") == room_id)]

    def item(self, item_id):
        return next((i for i in self.items if i["id"] == item_id), None)

    def live_w(self, item_id, now=None):
        """Measured watts from the appliance's smart plug, or None when there's no fresh reading."""
        r = self.live.get(item_id)
        if r is None or (now or time.time()) - r[1] > LIVE_FRESH_S:
            return None
        return r[0]

    def device_w(self, d):
        live = self.live_w(d["id"])
        if live is not None:
            return live
        return d["device"]["watts"] if d["device"]["on"] else 0

    def load_w(self, room_id=None):
        if room_id is None and self.measured_load is not None:
            m = self.measured_load()             # the whole house, measured at the inverter output
            if m is not None:
                return m
        return sum(self.device_w(d) for d in self.devices(room_id))

    def daily_kwh(self):
        return sum(d["device"]["watts"] * d["device"]["hours"] for d in self.devices()) / 1000.0

    def runtime_hours(self):
        """Battery runtime at the current load (None when nothing is on)."""
        load = self.load_w()
        if load <= 0:
            return None
        usable = self.power["battery_wh"] * self.power["battery_pct"] / 100.0 * 0.9  # ~90 % inverter eff.
        return usable / load

    # ---------------------------------------------------------- mutations --

    def set_on(self, item_id, on):
        it = self.item(item_id)
        if it and it.get("device"):
            changed = it["device"]["on"] != bool(on)
            it["device"]["on"] = bool(on)
            self.save()
            if changed and self.switch_hook:
                self.switch_hook(item_id, bool(on))

    def apply_reading(self, item_id, on=None, watts=None):
        """A smart plug reported its real state: update without calling the switch hook back."""
        it = self.item(item_id)
        if not it or not it.get("device"):
            return False
        changed = False
        if on is not None and it["device"]["on"] != bool(on):
            it["device"]["on"] = bool(on)
            changed = True
            self.save()
        if watts is not None:
            self.live[item_id] = (float(watts), time.time())
        return changed

    def toggle(self, item_id):
        it = self.item(item_id)
        if it and it.get("device"):
            self.set_on(item_id, not it["device"]["on"])

    def all_off(self, keep=("fridge",)):
        switched = []
        for d in self.devices():
            if d["id"] not in keep and d["device"]["on"]:
                d["device"]["on"] = False
                switched.append(d["id"])
        self.save()
        if self.switch_hook:
            for item_id in switched:
                self.switch_hook(item_id, False)

    def update_device(self, item_id, **fields):
        it = self.item(item_id)
        if it and it.get("device"):
            it["device"].update(fields)
            self.save()

    def add_device(self, name, room_id, watts, hours):
        """New appliance shown as a small labelled box in the middle of the room."""
        r = self.room(room_id)
        if r is None:
            return None
        n = len(self.devices(room_id))
        item = {"id": "dev_" + uuid.uuid4().hex[:8], "kind": "appliance", "name": name,
                "room": room_id, "x": r["x"] + 0.4 + (n % 4) * 0.5, "z": r["z"] + r["d"] - 0.7,
                "w": 0.36, "d": 0.3, "h": 0.4, "color": "#3b4252",
                "device": {"watts": float(watts), "hours": float(hours), "on": False}}
        self.items.append(item)
        self.save()
        return item

    def remove_item(self, item_id):
        self.data["items"] = [i for i in self.items if i["id"] != item_id]
        self.save()

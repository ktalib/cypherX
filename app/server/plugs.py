"""
Smart plug control: switch linked plugs for real and read their live power.

Drivers (all local, over the home Wi-Fi):
  Tuya / Smart Life   tinytuya (optional package) + the device's local key
                      DPS 1 = switch, 19 = power (0.1 W), 20 = voltage (0.1 V), 18 = current (mA)
  Shelly              HTTP: gen 1 /relay/0 + /status, gen 2+ /rpc/Switch.*
  Tasmota             HTTP: /cm?cmnd=Power ... and Status 10 (energy)
  TP-Link Kasa        TCP 9999, length-prefixed XOR "autokey" JSON; emeter on HS110 / KP115

The PlugService polls every linked plug every few seconds and hands readings to
the app (`apply(item_id, on, watts)`), and switches a plug when its appliance is
switched anywhere in the app (`request(item_id, on)`).
"""
import json
import queue
import socket
import struct
import time
import urllib.parse
import urllib.request

from app.server.services import ThreadService
from app.server.discovery import kasa_encrypt, kasa_decrypt

try:
    import tinytuya
    HAS_TINYTUYA = True
except ImportError:  # pragma: no cover
    tinytuya = None
    HAS_TINYTUYA = False

POLL_S = 5


class PlugError(Exception):
    pass


def _http_json(url, timeout=3.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read(65536).decode("utf-8", "replace"))
    except (OSError, ValueError) as e:
        raise PlugError(f"no answer from {urllib.parse.urlsplit(url).hostname}: {getattr(e, 'reason', e)}")


def reading(on=None, power_w=None, voltage=None, current_a=None, energy_kwh=None):
    return {"on": on, "power_w": power_w, "voltage": voltage, "current_a": current_a, "energy_kwh": energy_kwh}


# ---------------------------------------------------------------- drivers --

class TuyaDriver:
    def __init__(self, dev, factory=None):
        key = dev.get("local_key")
        if not key:
            raise PlugError("no local key yet")
        extra = dev.get("extra") or {}
        dev_id = extra.get("device_id") or dev["id"].split(":", 1)[1]
        version = float(extra.get("version") or 3.3)
        if factory is None:
            if not HAS_TINYTUYA:
                raise PlugError("install the 'tinytuya' package to control Tuya plugs")
            factory = tinytuya.OutletDevice
        self.d = factory(dev_id, dev["ip"], key)
        self.d.set_version(version)
        self.d.set_socketTimeout(3)

    def status(self):
        res = self.d.status()
        if not isinstance(res, dict) or "dps" not in res:
            msg = res.get("Error") if isinstance(res, dict) else "no answer"
            raise PlugError(f"Tuya: {msg}")
        dps = {str(k): v for k, v in res["dps"].items()}

        def num(key, scale):
            v = dps.get(key)
            return round(v * scale, 2) if isinstance(v, (int, float)) else None
        return reading(on=dps.get("1") if isinstance(dps.get("1"), bool) else None,
                       power_w=num("19", 0.1), voltage=num("20", 0.1), current_a=num("18", 0.001))

    def set_on(self, on):
        res = self.d.set_status(bool(on), 1)
        if isinstance(res, dict) and res.get("Error"):
            raise PlugError(f"Tuya: {res['Error']}")


class ShellyDriver:
    def __init__(self, dev, get=_http_json):
        self.ip = dev["ip"]
        self.gen = int((dev.get("extra") or {}).get("gen") or 1)
        self.get = get

    def status(self):
        if self.gen >= 2:
            s = self.get(f"http://{self.ip}/rpc/Switch.GetStatus?id=0")
            total = (s.get("aenergy") or {}).get("total")
            return reading(on=s.get("output"), power_w=s.get("apower"), voltage=s.get("voltage"),
                           current_a=s.get("current"), energy_kwh=total / 1000 if total is not None else None)
        s = self.get(f"http://{self.ip}/status")
        relay = (s.get("relays") or [{}])[0]
        meter = (s.get("meters") or [{}])[0]
        return reading(on=relay.get("ison"), power_w=meter.get("power"))

    def set_on(self, on):
        if self.gen >= 2:
            self.get(f"http://{self.ip}/rpc/Switch.Set?id=0&on={'true' if on else 'false'}")
        else:
            self.get(f"http://{self.ip}/relay/0?turn={'on' if on else 'off'}")


class TasmotaDriver:
    def __init__(self, dev, get=_http_json):
        self.ip = dev["ip"]
        self.get = get

    def _cmd(self, cmd):
        return self.get(f"http://{self.ip}/cm?cmnd={urllib.parse.quote(cmd)}")

    def status(self):
        p = self._cmd("Power")
        state = p.get("POWER", p.get("POWER1"))
        energy = {}
        try:
            energy = (self._cmd("Status 10").get("StatusSNS") or {}).get("ENERGY") or {}
        except PlugError:
            pass
        return reading(on=None if state is None else state == "ON", power_w=energy.get("Power"),
                       voltage=energy.get("Voltage"), current_a=energy.get("Current"), energy_kwh=energy.get("Total"))

    def set_on(self, on):
        self._cmd(f"Power {'On' if on else 'Off'}")


def kasa_request(ip, payload, port=9999, timeout=3.0):
    data = kasa_encrypt(json.dumps(payload))
    try:
        with socket.create_connection((ip, port), timeout=timeout) as s:
            s.sendall(struct.pack(">I", len(data)) + data)
            head = b""
            while len(head) < 4:
                chunk = s.recv(4 - len(head))
                if not chunk:
                    raise PlugError("Kasa closed the connection")
                head += chunk
            n = struct.unpack(">I", head)[0]
            body = b""
            while len(body) < n:
                chunk = s.recv(n - len(body))
                if not chunk:
                    break
                body += chunk
    except OSError as e:
        raise PlugError(f"no answer from {ip}: {e}")
    return json.loads(kasa_decrypt(body))


class KasaDriver:
    def __init__(self, dev, request=kasa_request):
        self.ip = dev["ip"]
        self.request = request

    def status(self):
        info = self.request(self.ip, {"system": {"get_sysinfo": {}}})["system"]["get_sysinfo"]
        r = reading(on=bool(info.get("relay_state")) if "relay_state" in info else None)
        if "ENE" in str(info.get("feature", "")):
            try:
                rt = self.request(self.ip, {"emeter": {"get_realtime": {}}})["emeter"]["get_realtime"]
                r["power_w"] = rt.get("power", rt.get("power_mw", 0) / 1000 if "power_mw" in rt else None)
                r["voltage"] = rt.get("voltage", rt.get("voltage_mv", 0) / 1000 if "voltage_mv" in rt else None)
            except (PlugError, KeyError):
                pass
        return r

    def set_on(self, on):
        self.request(self.ip, {"system": {"set_relay_state": {"state": 1 if on else 0}}})


DRIVERS = {"tuya": TuyaDriver, "shelly": ShellyDriver, "tasmota": TasmotaDriver, "kasa": KasaDriver}


def make_driver(dev):
    cls = DRIVERS.get(dev.get("protocol"))
    if cls is None:
        raise PlugError(f"{dev.get('brand', 'This device')} can't be controlled yet")
    return cls(dev)


def can_control(dev):
    proto = dev.get("protocol")
    if proto == "tuya":
        return bool(dev.get("local_key")), ("needs its local key" if not dev.get("local_key") else
                                            "needs the 'tinytuya' package" if not HAS_TINYTUYA else "")
    return proto in DRIVERS, "" if proto in DRIVERS else "not supported for control"


# ------------------------------------------------------------- Tuya keys --

def fetch_tuya_keys(region, api_key, api_secret, cloud_factory=None):
    """Ask the Tuya IoT cloud (once) for the local keys of the devices on your account.
    Returns {device_id: {"key": ..., "name": ..., "product": ...}}."""
    if cloud_factory is None:
        if not HAS_TINYTUYA:
            raise PlugError("install the 'tinytuya' package first")
        cloud_factory = tinytuya.Cloud
    cloud = cloud_factory(apiRegion=region, apiKey=api_key, apiSecret=api_secret)
    if getattr(cloud, "error", None):
        raise PlugError(f"Tuya cloud: {cloud.error.get('Payload', cloud.error) if isinstance(cloud.error, dict) else cloud.error}")
    devices = cloud.getdevices(verbose=False)
    if isinstance(devices, dict) and devices.get("Error"):
        raise PlugError(f"Tuya cloud: {devices.get('Payload') or devices['Error']}")
    out = {}
    for d in devices or []:
        if d.get("id") and d.get("key"):
            out[d["id"]] = {"key": d["key"], "name": d.get("name", ""), "product": d.get("product_name", "")}
    return out


# --------------------------------------------------------------- service --

class PlugService(ThreadService):
    id = "plugs"
    title = "Smart plug control"
    description = "Switches linked smart plugs for real and reads their live power every few seconds."
    icon = "zap"
    default_enabled = True
    settings_schema = [("poll_s", "Read plugs every (seconds)", "int", POLL_S, "")]

    def __init__(self, book, apply, driver_factory=make_driver):
        """book: SmartDeviceBook. apply(item_id, on, watts) runs on any thread and must hand
        the reading to the GUI thread itself."""
        super().__init__()
        self.book = book
        self.apply = apply
        self.driver_factory = driver_factory
        self.readings = {}         # dev_id -> {"reading": dict, "ts": t, "error": str|None}
        self.commands = queue.Queue()
        self._drivers = {}

    def linked(self):
        return {k: d for k, d in dict(self.book.devices).items() if d.get("linked_item")}

    def driver(self, dev_id, dev):
        sig = (dev.get("ip"), dev.get("local_key"), (dev.get("extra") or {}).get("version"))
        cached = self._drivers.get(dev_id)
        if cached and cached[0] == sig:
            return cached[1]
        drv = self.driver_factory(dev)
        self._drivers[dev_id] = (sig, drv)
        return drv

    def request(self, item_id, on):
        """An appliance was switched in the app: switch its plug (if it has a controllable one)."""
        dev_id = self.book.by_item(item_id)
        if dev_id and can_control(self.book.devices[dev_id])[0]:
            self.commands.put((dev_id, bool(on)))
            return True
        return False

    def run(self, stop):
        self.mark_running()
        next_poll = 0
        while not stop.is_set():
            try:
                dev_id, on = self.commands.get(timeout=0.25)
                self._switch(dev_id, on)
                next_poll = 0                     # read back straight away
                continue
            except queue.Empty:
                pass
            if time.time() >= next_poll:
                self.poll_all()
                next_poll = time.time() + max(2, int(self.setting("poll_s") or POLL_S))

    def _switch(self, dev_id, on):
        dev = self.book.devices.get(dev_id)
        if not dev:
            return
        try:
            self.driver(dev_id, dev).set_on(on)
            self.log(f"{self.book.label(dev_id)} switched {'ON' if on else 'OFF'}")
        except Exception as e:
            self.log(f"Couldn't switch {self.book.label(dev_id)}: {e}", "error")
            self.readings.setdefault(dev_id, {})["error"] = str(e)

    def poll_all(self):
        for dev_id, dev in self.linked().items():
            if not can_control(dev)[0]:
                continue
            self.poll(dev_id, dev)

    def poll(self, dev_id, dev):
        prev = self.readings.get(dev_id, {})
        try:
            r = self.driver(dev_id, dev).status()
        except Exception as e:
            if not prev.get("error"):
                self.log(f"{self.book.label(dev_id)} not answering: {e}", "warn")
            self.readings[dev_id] = {**prev, "error": str(e)}
            self._drivers.pop(dev_id, None)
            return None
        if prev.get("error"):
            self.log(f"{self.book.label(dev_id)} answering again")
        self.readings[dev_id] = {"reading": r, "ts": time.time(), "error": None}
        watts = r["power_w"]
        if watts is None and r["on"] is False:
            watts = 0.0
        try:
            self.apply(dev["linked_item"], r["on"], watts)
        except Exception as e:
            self.log(f"Couldn't update the appliance: {e}", "warn")
        return r

    def info(self):
        linked = self.linked()
        if not linked:
            return ["No plug is linked to an appliance yet (Smart Devices → Plugged in)."]
        lines = []
        for dev_id, dev in linked.items():
            ok, why = can_control(dev)
            r = self.readings.get(dev_id, {})
            if not ok:
                state = f"can't control — {why}"
            elif r.get("error"):
                state = f"not answering ({r['error']})"
            elif r.get("reading"):
                rd = r["reading"]
                state = ("ON" if rd["on"] else "OFF" if rd["on"] is False else "?") + \
                        (f" · {rd['power_w']:.0f} W" if rd["power_w"] is not None else "")
            else:
                state = "waiting for first reading"
            lines.append(f"{self.book.label(dev_id)}: {state}")
        if not HAS_TINYTUYA:
            lines.append("Tuya control needs:  pip install tinytuya")
        return lines

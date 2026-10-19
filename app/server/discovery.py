"""
Smart device discovery: finds smart plugs, sockets, bulbs and switches on the
home Wi-Fi by the way each brand announces itself.

  Tuya / Smart Life   every device broadcasts "I'm here" on UDP 6666 (v3.1, plain JSON)
                      or 6667 (v3.3: AES-ECB with Tuya's public UDP key; v3.4/3.5:
                      AES-GCM). We only listen. Gives device id, IP, version, product key.
  TP-Link Kasa        we broadcast a "get_sysinfo" request on UDP 9999; plugs and bulbs
                      answer with name, model and relay state (XOR "autokey" cipher)
  mDNS / Bonjour      Shelly, ESPHome, Sonoff DIY (eWeLink), HomeKit, Google Cast, Hue,
                      WLED — needs the optional `zeroconf` package
  HTTP fingerprint    devices from the Wi-Fi scan that answer like a Shelly (/shelly)
                      or a Tasmota plug (/cm?cmnd=Status)

Found devices are kept in USER_DATA_DIR/smart_devices.json. Controlling them is
the next step (Tuya needs each device's local key, fetched once).
"""
import concurrent.futures as cf
import hashlib
import json
import socket
import struct
import threading
import time
import urllib.request

from app.config import USER_DATA_DIR
from app.server.services import ThreadService

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    HAS_CRYPTO = False

try:
    from zeroconf import Zeroconf, ServiceBrowser
    HAS_ZEROCONF = True
except ImportError:  # pragma: no cover
    HAS_ZEROCONF = False

SMART_FILE = USER_DATA_DIR / "smart_devices.json"
TUYA_PORTS = (6666, 6667)
TUYA_UDP_KEY = hashlib.md5(b"yGAdlopoPVldABfn").digest()
KASA_PORT = 9999
ONLINE_WINDOW_S = 180            # Tuya devices broadcast every few seconds

MDNS_TYPES = {
    "_shelly._tcp.local.": ("Shelly", "plug / relay"),
    "_esphomelib._tcp.local.": ("ESPHome", "device"),
    "_ewelink._tcp.local.": ("Sonoff (eWeLink DIY)", "switch"),
    "_hap._tcp.local.": ("HomeKit accessory", "device"),
    "_googlecast._tcp.local.": ("Google Cast", "TV / speaker"),
    "_hue._tcp.local.": ("Philips Hue bridge", "hub"),
    "_wled._tcp.local.": ("WLED", "light"),
}


# ---------------------------------------------------------------- Tuya --

def _unpad(data):
    n = data[-1] if data else 0
    if 1 <= n <= 16 and data.endswith(bytes([n]) * n):
        return data[:-n]
    raise ValueError("bad padding")


def _try_json(raw):
    raw = raw.strip(b"\x00")
    start = raw.find(b"{")
    if start < 0:
        return None
    try:
        obj = json.loads(raw[start:].decode("utf-8", "replace"))
        return obj if isinstance(obj, dict) else None
    except ValueError:
        return None


def _aes_ecb_decrypt(data, key=TUYA_UDP_KEY):
    if not HAS_CRYPTO or not data or len(data) % 16:
        raise ValueError("can't decrypt")
    d = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    return _unpad(d.update(data) + d.finalize())


def parse_tuya_packet(data):
    """A Tuya discovery broadcast → dict (gwId, ip, version, productKey, ...), or None.
    Tries every framing Tuya uses; unknown encrypted packets return {"encrypted": True}."""
    if len(data) < 24:
        return None
    prefix = struct.unpack(">I", data[:4])[0]
    if prefix == 0x000055AA and data[-4:] == b"\x00\x00\xaa\x55":
        body = data[16:-8]
        candidates = [body, body[4:]]
        for c in candidates:
            obj = _try_json(c) if c[:1] == b"{" else None
            if obj:
                return obj
        for c in candidates:
            try:
                obj = _try_json(_aes_ecb_decrypt(c))
                if obj:
                    return obj
            except ValueError:
                continue
        return {"encrypted": True}
    if prefix == 0x00006699 and data[-4:] == b"\x00\x00\x99\x66" and HAS_CRYPTO:
        iv, ct_tag, aad = data[18:30], data[30:-4], data[4:18]
        for ad in (aad, None):
            try:
                plain = AESGCM(TUYA_UDP_KEY).decrypt(iv, ct_tag, ad)
            except Exception:
                continue
            obj = _try_json(plain) or _try_json(plain[4:])
            if obj:
                return obj
        return {"encrypted": True}
    obj = _try_json(data)          # some very old firmware sends bare JSON
    return obj


# ---------------------------------------------------------------- Kasa --

def kasa_encrypt(text):
    key, out = 171, bytearray()
    for c in text.encode("utf-8"):
        key ^= c
        out.append(key)
    return bytes(out)


def kasa_decrypt(data):
    key, out = 171, bytearray()
    for c in data:
        out.append(key ^ c)
        key = c
    return out.decode("utf-8", "replace")


KASA_QUERY = kasa_encrypt(json.dumps({"system": {"get_sysinfo": {}}}))


def parse_kasa_reply(data, ip):
    try:
        info = json.loads(kasa_decrypt(data))["system"]["get_sysinfo"]
    except (ValueError, KeyError, TypeError):
        return None
    dev_type = (info.get("type") or info.get("mic_type") or "").upper()
    model = info.get("model", "")
    kind = "bulb" if "BULB" in dev_type else "switch" if model.upper().startswith("HS2") else "plug"
    mac = (info.get("mac") or info.get("mic_mac") or "").upper().replace("-", ":")
    return {"id": f"kasa:{info.get('deviceId') or mac or ip}", "protocol": "kasa", "brand": "TP-Link Kasa",
            "kind": kind, "model": model, "name": info.get("alias", ""), "ip": ip, "mac": mac,
            "extra": {"on": bool(info.get("relay_state")) if "relay_state" in info else None},
            "control": "Local control possible (no key needed)"}


# ---------------------------------------------------------------- HTTP --

def _get_json(url, timeout=1.5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        if r.status != 200:
            return None
        return json.loads(r.read(65536).decode("utf-8", "replace"))


def probe_http(ip, get=_get_json):
    """Is this IP a Shelly or a Tasmota device? → device dict or None."""
    try:
        info = get(f"http://{ip}/shelly")
        if isinstance(info, dict) and ("type" in info or "gen" in info or "model" in info):
            model = str(info.get("type") or info.get("model") or "")
            up = model.upper()
            kind = ("plug" if "PLG" in up or "PLUG" in up else "bulb" if "BULB" in up or "DUO" in up
                    else "relay switch")
            mac = str(info.get("mac", "")).upper()
            mac = ":".join(mac[i:i + 2] for i in range(0, 12, 2)) if len(mac) == 12 else mac
            return {"id": f"shelly:{mac or ip}", "protocol": "shelly", "brand": "Shelly", "kind": kind,
                    "model": model, "name": str(info.get("name") or ""), "ip": ip, "mac": mac,
                    "extra": {"gen": info.get("gen", 1)}, "control": "Local control possible (no key needed)"}
    except Exception:
        pass
    try:
        info = get(f"http://{ip}/cm?cmnd=Status")
        if isinstance(info, dict) and "Status" in info:
            st = info["Status"]
            names = st.get("FriendlyName") or [st.get("DeviceName", "")]
            return {"id": f"tasmota:{ip}", "protocol": "tasmota", "brand": "Tasmota", "kind": "plug / switch",
                    "model": str(st.get("DeviceName", "")), "name": names[0] if names else "", "ip": ip,
                    "mac": "", "extra": {"power": st.get("Power")},
                    "control": "Local control possible (no key needed)"}
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- book --

def tuya_device(info, ip):
    gw = info.get("gwId") or info.get("devId") or ""
    version = str(info.get("version", ""))
    if info.get("encrypted"):
        return {"id": f"tuya:{ip}", "protocol": "tuya", "brand": "Tuya / Smart Life", "kind": "plug, bulb or switch",
                "model": "", "name": "", "ip": ip, "mac": "", "extra": {"encrypted": True},
                "control": "Needs the device's local key (Tuya wizard)"}
    return {"id": f"tuya:{gw or ip}", "protocol": "tuya", "brand": "Tuya / Smart Life",
            "kind": "plug, bulb or switch", "model": "", "name": "",
            "ip": info.get("ip") or ip, "mac": "", "extra": {"version": version, "device_id": gw,
                                                             "product_key": info.get("productKey", "")},
            "control": "Needs the device's local key (Tuya wizard)"}


class SmartDeviceBook:
    def __init__(self, path=SMART_FILE):
        self.path = path
        self.devices = {}
        self.pending_keys = {}     # Tuya device id -> local key, imported before the device was seen
        self._lock = threading.Lock()
        self._file_lock = threading.Lock()
        try:
            with open(path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            self.devices = stored.get("devices", {})
            self.pending_keys = stored.get("pending_keys", {})
        except (OSError, ValueError):
            pass

    def save(self):
        # several listener threads may record sightings at once: one writer at a time,
        # each through its own temp file
        with self._file_lock:
            with self._lock:
                data = json.dumps({"devices": self.devices, "pending_keys": self.pending_keys}, indent=2)
            tmp = self.path.with_name(f"{self.path.stem}.{threading.get_ident()}.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(data)
            tmp.replace(self.path)

    def seen(self, dev, now=None):
        """Record a sighting. Returns True when the device is new."""
        now = now or time.time()
        with self._lock:
            # an encrypted Tuya sighting (keyed by IP) folds into a known device at that IP
            if dev["id"].startswith("tuya:") and dev.get("extra", {}).get("encrypted"):
                for k, d in self.devices.items():
                    if d.get("protocol") == "tuya" and d.get("ip") == dev["ip"]:
                        d["last_seen"] = now
                        return False
            known = self.devices.get(dev["id"])
            new = known is None
            if new:
                known = {"first_seen": now, "label": "", "linked_item": None}
                self.devices[dev["id"]] = known
            for k, v in dev.items():
                if v not in ("", None) or k not in known:
                    known[k] = v
            known["last_seen"] = now
            tuya_id = (known.get("extra") or {}).get("device_id")
            if tuya_id and tuya_id in self.pending_keys and not known.get("local_key"):
                known["local_key"] = self.pending_keys.pop(tuya_id)
        self.save()
        return new

    def online(self, dev_id, now=None, window=ONLINE_WINDOW_S):
        d = self.devices.get(dev_id)
        return bool(d) and (now or time.time()) - d.get("last_seen", 0) <= window

    def label(self, dev_id):
        d = self.devices.get(dev_id, {})
        return d.get("label") or d.get("name") or f"{d.get('brand', 'Device')} {d.get('kind', '')}".strip()

    def rename(self, dev_id, label):
        if dev_id in self.devices:
            self.devices[dev_id]["label"] = label.strip()
            self.save()

    def link(self, dev_id, item_id):
        if dev_id in self.devices:
            with self._lock:
                for d in self.devices.values():          # one plug per appliance
                    if item_id and d.get("linked_item") == item_id:
                        d["linked_item"] = None
                self.devices[dev_id]["linked_item"] = item_id or None
            self.save()

    def forget(self, dev_id):
        with self._lock:
            self.devices.pop(dev_id, None)
        self.save()

    def set_key(self, dev_id, key):
        if dev_id in self.devices:
            self.devices[dev_id]["local_key"] = key.strip()
            self.save()

    def import_tuya_keys(self, keys):
        """keys: {tuya_device_id: {"key", "name"}} from the Tuya cloud. Applies them to known
        devices and keeps the rest for when those devices show up. Returns (applied, pending)."""
        applied, pending = [], []
        with self._lock:
            for tid, info in keys.items():
                dev_id = next((k for k, d in self.devices.items()
                               if (d.get("extra") or {}).get("device_id") == tid), None)
                if dev_id:
                    self.devices[dev_id]["local_key"] = info["key"]
                    if info.get("name") and not self.devices[dev_id].get("label"):
                        self.devices[dev_id]["label"] = info["name"]
                    applied.append(info.get("name") or tid)
                else:
                    self.pending_keys[tid] = info["key"]
                    pending.append(info.get("name") or tid)
        self.save()
        return applied, pending

    def by_item(self, item_id):
        return next((k for k, d in self.devices.items() if d.get("linked_item") == item_id), None)


# ------------------------------------------------------------- service --

class DiscoveryService(ThreadService):
    id = "discovery"
    title = "Smart device discovery"
    description = "Finds smart plugs, sockets, bulbs and switches on your Wi-Fi (Tuya / Smart Life, Kasa, Shelly, " \
                  "Tasmota, ESPHome, Sonoff, HomeKit…)."
    icon = "plug"
    default_enabled = False
    settings_schema = [
        ("tuya", "Listen for Tuya / Smart Life", "bool", True, "UDP 6666 / 6667 broadcasts"),
        ("kasa", "Look for TP-Link Kasa", "bool", True, "UDP 9999 broadcast every minute"),
        ("mdns", "Look for mDNS devices", "bool", True, "Shelly, ESPHome, Sonoff, HomeKit, Cast, Hue, WLED"),
        ("http_probe", "Check Wi-Fi devices for Shelly / Tasmota", "bool", True, "Every 15 min"),
    ]

    def __init__(self, bus, book=None, ip_source=None, tuya_ports=TUYA_PORTS, kasa_port=KASA_PORT,
                 on_found=None):
        super().__init__()
        self.bus = bus
        self.book = book or SmartDeviceBook()
        self.ip_source = ip_source or (lambda: [])      # IPs seen by Network watch
        self.tuya_ports = tuya_ports
        self.kasa_port = kasa_port
        self.on_found = on_found
        self._socks = []
        self._zc = None
        self.packets = 0
        self.listen_errors = []
        self._probe_now = False

    # -- results --
    def found(self, dev):
        if self.book.seen(dev):
            label = dev.get("name") or f"{dev['brand']} {dev['kind']}"
            self.log(f"Found {label} at {dev['ip']}")
            self.bus.publish("smart", "Smart device found", f"{label} · {dev['ip']}", device=dev["id"])
        if self.on_found:
            try:
                self.on_found(dev)
            except Exception:
                pass

    # -- listeners --
    def _listen_tuya(self, port, stop):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("", port))
        except OSError as e:
            self.listen_errors.append(f"UDP {port}: {e.strerror or e}")
            self.log(f"Can't listen on UDP {port} ({e.strerror or e}) — is another Tuya app running?", "warn")
            s.close()
            return
        s.settimeout(1.0)
        self._socks.append(s)
        while not stop.is_set():
            try:
                data, (ip, _p) = s.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            self.packets += 1
            try:
                info = parse_tuya_packet(data)
                if info is not None:
                    self.found(tuya_device(info, ip))
            except Exception as e:              # one odd packet must not stop the listener
                self.log(f"Couldn't read a packet from {ip}: {e}", "warn")

    def kasa_scan(self, wait=2.5):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.5)
        found = []
        try:
            sent = 0
            for target in ("255.255.255.255",) + tuple(self._extra_kasa_targets):
                try:
                    s.sendto(KASA_QUERY, (target, self.kasa_port))
                    sent += 1
                except OSError:
                    continue            # e.g. broadcast not allowed on this network
            if not sent:
                return found
            end = time.time() + wait
            while time.time() < end:
                try:
                    data, (ip, _p) = s.recvfrom(8192)
                except socket.timeout:
                    continue
                dev = parse_kasa_reply(data, ip)
                if dev:
                    found.append(dev)
                    self.found(dev)
        except OSError as e:
            self.log(f"Kasa scan failed: {e}", "warn")
        finally:
            s.close()
        return found

    _extra_kasa_targets = ()

    def http_probe(self):
        ips = list(self.ip_source())
        if not ips:
            return []
        out = []
        with cf.ThreadPoolExecutor(max_workers=16) as pool:
            for dev in pool.map(probe_http, ips):
                if dev:
                    out.append(dev)
                    self.found(dev)
        return out

    def _start_mdns(self):
        if not HAS_ZEROCONF:
            self.log("mDNS skipped: install the 'zeroconf' package to find Shelly / ESPHome / Sonoff", "warn")
            return
        svc = self

        class Handler:
            def add_service(self, zc, type_, name):
                threading.Thread(target=svc._mdns_resolve, args=(zc, type_, name), daemon=True).start()

            update_service = add_service

            def remove_service(self, zc, type_, name):
                pass

        try:
            self._zc = Zeroconf()
            self._browser = ServiceBrowser(self._zc, list(MDNS_TYPES), Handler())
        except Exception as e:
            self.log(f"mDNS unavailable: {e}", "warn")
            self._zc = None

    def _mdns_resolve(self, zc, type_, name):
        try:
            info = zc.get_service_info(type_, name, timeout=2000)
        except Exception:
            return
        if not info:
            return
        ips = info.parsed_addresses() if hasattr(info, "parsed_addresses") else []
        ip = next((a for a in ips if ":" not in a), ips[0] if ips else "")
        brand, kind = MDNS_TYPES.get(type_, ("mDNS device", "device"))
        props = {}
        for k, v in (info.properties or {}).items():
            try:
                props[k.decode()] = v.decode() if isinstance(v, bytes) else v
            except Exception:
                pass
        short = name.replace("." + type_, "")
        self.found({"id": f"mdns:{type_.split('.')[0]}:{short}", "protocol": "mdns", "brand": brand, "kind": kind,
                    "model": props.get("md") or props.get("model") or props.get("app", ""), "name": short,
                    "ip": ip, "mac": props.get("mac", ""), "extra": {"service": type_},
                    "control": "Local control possible" if brand in ("Shelly", "ESPHome", "Sonoff (eWeLink DIY)", "WLED")
                    else "Shown for information"})

    # -- main loop --
    def run(self, stop):
        self.listen_errors = []
        threads = []
        if self.setting("tuya") is not False:
            for port in self.tuya_ports:
                t = threading.Thread(target=self._listen_tuya, args=(port, stop), daemon=True)
                t.start()
                threads.append(t)
        if self.setting("mdns") is not False:
            self._start_mdns()
        self.mark_running()
        self.log("Listening for smart devices")
        next_kasa = next_probe = 0
        while not stop.is_set():
            now = time.time()
            if self.setting("kasa") is not False and now >= next_kasa:
                self.kasa_scan()
                next_kasa = now + 60
            if self.setting("http_probe") is not False and (now >= next_probe or self._probe_now):
                self._probe_now = False
                self.http_probe()
                next_probe = now + 900
            stop.wait(1)

    def on_stop(self):
        for s in self._socks:
            try:
                s.close()
            except OSError:
                pass
        self._socks = []
        if self._zc is not None:
            try:
                self._zc.close()
            except Exception:
                pass
            self._zc = None

    # -- Services page --
    def info(self):
        n = len(self.book.devices)
        online = sum(1 for k in self.book.devices if self.book.online(k))
        lines = [f"{n} smart device(s) known · {online} seen in the last 3 min · {self.packets} Tuya packets heard"]
        if self.listen_errors:
            lines.append("Listening problems: " + "; ".join(self.listen_errors))
        if not HAS_ZEROCONF:
            lines.append("mDNS off: 'pip install zeroconf' to find Shelly / ESPHome / Sonoff.")
        lines.append("Windows Firewall may ask once — allow Private networks so broadcasts can reach CYPHER-X.")
        return lines

    def actions(self):
        def scan():
            if self.status != "running":
                raise RuntimeError("Start Smart device discovery first.")
            self._probe_now = True
            found = self.kasa_scan()
            return f"Looking… Kasa answered: {len(found)}. Tuya devices appear within ~10 s; Shelly / Tasmota " \
                   "checks run in the background."
        return [("Scan now", scan)]

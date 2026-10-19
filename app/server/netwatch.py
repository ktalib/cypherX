"""
Network watch: which devices are on the home Wi-Fi, and an alert when a new
one joins.

How a scan works (no extra software, no admin rights):
  1. ping every address in this PC's /24 range, 64 at a time, so every device
     answers and lands in the PC's ARP table
  2. read the ARP table (Windows `arp -a`, Linux `ip neigh`) → IP + MAC
  3. look up a name for each IP (reverse DNS / NetBIOS name, when the router
     provides one)

Devices are remembered in USER_DATA_DIR/network_devices.json by MAC address,
with a name you can set, first / last seen and whether you trust them.
"""
import concurrent.futures as cf
import ipaddress
import json
import os
import platform
import re
import socket
import subprocess
import time

from app.config import USER_DATA_DIR
from app.server.services import ThreadService

DEVICES_FILE = USER_DATA_DIR / "network_devices.json"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0          # don't flash a console per ping

# Only makers we are sure about; everything else shows as unknown rather than guessed.
OUI = {
    **{p: "Espressif (smart plug / IoT)" for p in (
        "18:FE:34", "24:0A:C4", "24:62:AB", "24:6F:28", "30:AE:A4", "5C:CF:7F", "60:01:94",
        "84:CC:A8", "A4:CF:12", "BC:DD:C2", "DC:4F:22", "EC:FA:BC")},
    **{p: "Raspberry Pi" for p in ("B8:27:EB", "DC:A6:32", "E4:5F:01")},
    **{p: "VMware (virtual machine)" for p in ("00:50:56", "00:0C:29")},
    "08:00:27": "VirtualBox (virtual machine)",
}

_MAC = r"([0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5})"


def norm_mac(mac):
    return mac.replace("-", ":").upper()


def vendor_of(mac):
    mac = norm_mac(mac)
    if mac[:8] in OUI:
        return OUI[mac[:8]]
    try:
        if int(mac[:2], 16) & 0x02:
            return "Private address (phone / laptop privacy mode)"
    except ValueError:
        pass
    return "Unknown maker"


def parse_arp_windows(text):
    """`arp -a` output → [(ip, mac)] for dynamic entries."""
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*(\d+\.\d+\.\d+\.\d+)\s+" + _MAC + r"\s+(\w+)", line)
        if m and m.group(3).lower() in ("dynamic", "dynamique", "dynamisch"):
            out.append((m.group(1), norm_mac(m.group(2))))
    return out


def parse_ip_neigh(text):
    """`ip neigh` output → [(ip, mac)] for reachable / stale entries."""
    out = []
    for line in text.splitlines():
        m = re.match(r"(\d+\.\d+\.\d+\.\d+)\s+dev\s+\S+\s+lladdr\s+" + _MAC + r"\s+(\w+)", line)
        if m and m.group(3).upper() != "FAILED":
            out.append((m.group(1), norm_mac(m.group(2))))
    return out


def is_unicast_device(ip, mac):
    if mac in ("FF:FF:FF:FF:FF:FF", "00:00:00:00:00:00") or mac.startswith("01:00:5E"):
        return False
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_multicast or a.is_loopback or str(a).endswith(".255"))


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def subnet_hosts(ip):
    net = ipaddress.ip_network(f"{ip}/24", strict=False)
    return [str(h) for h in net.hosts()]


def ping(ip, timeout_ms=400):
    if platform.system() == "Windows":
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", "1", ip]
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=3, creationflags=NO_WINDOW).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def read_arp_table():
    try:
        if platform.system() == "Windows":
            text = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10,
                                  creationflags=NO_WINDOW).stdout
            return parse_arp_windows(text)
        text = subprocess.run(["ip", "neigh"], capture_output=True, text=True, timeout=10).stdout
        return parse_ip_neigh(text)
    except (OSError, subprocess.TimeoutExpired):
        return []


def hostname_of(ip):
    try:
        name = socket.gethostbyaddr(ip)[0]
        return "" if name == ip else name.split(".")[0]
    except OSError:
        return ""


def scan(stop=None, ping_fn=ping, arp_fn=read_arp_table, name_fn=hostname_of, ip=None):
    """Returns {"ip": this PC's IP, "devices": [{ip, mac, hostname, vendor}], "answered": n}."""
    ip = ip or local_ip()
    if not ip or ip.startswith("127."):
        raise RuntimeError("This PC isn't connected to a network")
    hosts = subnet_hosts(ip)
    answered = 0
    with cf.ThreadPoolExecutor(max_workers=64) as pool:
        for ok in pool.map(ping_fn, hosts):
            answered += 1 if ok else 0
            if stop is not None and stop.is_set():
                return None
    prefix = ip.rsplit(".", 1)[0] + "."
    entries = [(i, m) for i, m in arp_fn() if i.startswith(prefix) and is_unicast_device(i, m)]
    with cf.ThreadPoolExecutor(max_workers=16) as pool:
        names = list(pool.map(name_fn, [i for i, _ in entries]))
    devices = [{"ip": i, "mac": m, "hostname": n, "vendor": vendor_of(m)} for (i, m), n in zip(entries, names)]
    return {"ip": ip, "devices": devices, "answered": answered}


class DeviceBook:
    """Known devices by MAC, saved as JSON."""

    def __init__(self, path=DEVICES_FILE):
        self.path = path
        self.devices = {}
        self.last_scan = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.devices = data.get("devices", {})
            self.last_scan = data.get("last_scan")
        except (OSError, ValueError):
            pass

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"devices": self.devices, "last_scan": self.last_scan}, f, indent=2)
        tmp.replace(self.path)

    def merge(self, result, now=None):
        """Record a scan. Returns the devices seen for the first time (empty on the very first scan,
        which only builds the baseline)."""
        now = now or time.time()
        baseline = bool(self.devices)
        new = []
        gateway = result["ip"].rsplit(".", 1)[0] + ".1"
        for d in result["devices"]:
            known = self.devices.get(d["mac"])
            if known is None:
                known = {"name": "", "first_seen": now, "trusted": not baseline}
                self.devices[d["mac"]] = known
                if baseline:
                    new.append(d)
            known.update({"ip": d["ip"], "hostname": d["hostname"] or known.get("hostname", ""),
                          "vendor": d["vendor"], "last_seen": now})
            if d["ip"] == gateway and not known.get("name"):
                known["name"] = "Router (likely)"
        self.last_scan = {"ts": now, "online": [d["mac"] for d in result["devices"]], "ip": result["ip"]}
        self.save()
        return new

    def online(self, mac):
        return bool(self.last_scan) and mac in self.last_scan.get("online", [])

    def label(self, mac):
        d = self.devices.get(mac, {})
        return d.get("name") or d.get("hostname") or d.get("vendor") or mac

    def rename(self, mac, name):
        if mac in self.devices:
            self.devices[mac]["name"] = name.strip()
            self.save()

    def trust(self, mac, on=True):
        if mac in self.devices:
            self.devices[mac]["trusted"] = bool(on)
            self.save()

    def forget(self, mac):
        self.devices.pop(mac, None)
        self.save()


class NetWatchService(ThreadService):
    id = "netwatch"
    title = "Network watch"
    description = "Finds every device on your Wi-Fi and alerts you when an unknown one joins."
    icon = "wifi"
    default_enabled = False
    settings_schema = [
        ("interval_min", "Scan every (minutes)", "int", 10, "How often to look for devices"),
        ("alert_new", "Alert on new devices", "bool", True, "Tray notification and Telegram"),
    ]

    def __init__(self, bus, book=None, scan_fn=scan):
        super().__init__()
        self.bus = bus
        self.book = book or DeviceBook()
        self.scan_fn = scan_fn
        self.scanning = False
        self._now = None

    def run(self, stop):
        self.mark_running()
        while not stop.is_set():
            self.scan_once(stop)
            self._now = None
            minutes = max(1, int(self.setting("interval_min") or 10))
            end = time.time() + minutes * 60
            while not stop.is_set() and time.time() < end and self._now is None:
                stop.wait(1)

    def scan_once(self, stop=None):
        self.scanning = True
        t0 = time.time()
        try:
            result = self.scan_fn(stop)
            if result is None:
                return []
            new = self.book.merge(result)
        except RuntimeError as e:
            self.log(str(e), "warn")
            return []
        finally:
            self.scanning = False
        self.log(f"Scan: {len(result['devices'])} devices online ({time.time() - t0:.0f} s)")
        for d in new:
            label = d["hostname"] or d["vendor"]
            self.log(f"New device: {label} {d['ip']} {d['mac']}", "warn")
            if self.setting("alert_new") is not False:
                self.bus.publish("network", "New device on your Wi-Fi",
                                 f"{label} · {d['ip']} · {d['mac']}", mac=d["mac"])
        return new

    def scan_now(self):
        self._now = True
        return "Scanning — results appear in a few seconds."

    def info(self):
        b = self.book
        if not b.last_scan:
            return ["No scan yet."]
        online = len(b.last_scan.get("online", []))
        untrusted = sum(1 for m, d in b.devices.items() if not d.get("trusted"))
        when = time.strftime("%H:%M", time.localtime(b.last_scan["ts"]))
        return [f"{online} online now · {len(b.devices)} known · {untrusted} not trusted",
                f"Last scan {when} on {b.last_scan.get('ip', '?')}/24" + (" · scanning…" if self.scanning else "")]

    def actions(self):
        def now():
            if self.status != "running":
                raise RuntimeError("Start Network watch first.")
            return self.scan_now()
        return [("Scan now", now)]

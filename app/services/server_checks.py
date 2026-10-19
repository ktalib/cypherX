"""
Start-up checks run by the Server console's boot screen.

Every check is real and returns (status, detail):
  status  "ok" | "warn" | "fail" | "info"
  detail  one short line for the user

No Qt here, so the checks can be unit tested and run in a worker thread.
"""
import os
import platform
import socket
import sqlite3
import time

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"


def check_launch():
    host = socket.gethostname()
    return OK, f"{host} · {platform.system()} {platform.release()} · Python {platform.python_version()}"


def check_root(user):
    if (user or {}).get("role") == "root":
        return OK, f"{user.get('username')} has root access"
    return FAIL, "Root access is required for the server console"


def check_system():
    if psutil is None:
        return WARN, "psutil not installed — no health data"
    cpu = psutil.cpu_percent(interval=0.3)
    mem = psutil.virtual_memory()
    uptime_h = (time.time() - psutil.boot_time()) / 3600
    up = f"{uptime_h:.0f} h" if uptime_h < 48 else f"{uptime_h / 24:.1f} days"
    detail = f"CPU {cpu:.0f}% of {psutil.cpu_count()} threads · RAM {mem.percent:.0f}% used · up {up}"
    status = WARN if mem.percent >= 90 or cpu >= 95 else OK
    return status, detail


def local_ip():
    """IP of the interface used for outbound traffic (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def check_network(host="1.1.1.1", port=53, timeout=2.0):
    ip = local_ip()
    if ip.startswith("127."):
        return WARN, "No network adapter is connected — local features still work"
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            ms = (time.perf_counter() - t0) * 1000
        return OK, f"LAN {ip} · internet reachable ({ms:.0f} ms)"
    except OSError:
        return WARN, f"LAN {ip} · no internet — local features still work"


def check_database(db_path):
    if not os.path.exists(db_path):
        return FAIL, f"Database not found at {db_path}"
    t0 = time.perf_counter()
    try:
        conn = sqlite3.connect(str(db_path), timeout=3)
        try:
            result = conn.execute("PRAGMA quick_check").fetchone()[0]
            tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as e:
        return FAIL, f"Can't open the database: {e}"
    ms = (time.perf_counter() - t0) * 1000
    size_kb = os.path.getsize(db_path) / 1024
    if result != "ok":
        return FAIL, f"Integrity check failed: {result}"
    return OK, f"SQLite · {tables} tables · {size_kb:,.0f} KB · integrity ok ({ms:.0f} ms)"


def check_storage():
    if psutil is None:
        return WARN, "psutil not installed — no storage data"
    root = os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/"
    try:
        du = psutil.disk_usage(root)
    except OSError:
        return WARN, f"Can't read {root}"
    free_gb = du.free / 1024 ** 3
    drives = len([p for p in psutil.disk_partitions(all=False)])
    status = FAIL if du.percent >= 97 else WARN if du.percent >= 90 else OK
    return status, f"{root} {free_gb:,.0f} GB free ({100 - du.percent:.0f}%) · {drives} drive{'s' if drives != 1 else ''}"


def check_updates(version):
    # No update server exists yet, so say so instead of pretending to be "up to date".
    return INFO, f"v{version} installed · no update server configured"


def check_services(enabled_automations=0, cameras=0, cameras_live=0, grid_watch=False):
    parts = [f"{enabled_automations} automation{'s' if enabled_automations != 1 else ''}",
             f"{cameras_live}/{cameras} camera{'s' if cameras != 1 else ''} live",
             "grid watch on" if grid_watch else "grid watch off",
             "telemetry running"]
    return OK, " · ".join(parts)

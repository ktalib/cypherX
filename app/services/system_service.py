import os
import platform
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

try:
    import psutil
except ImportError:
    psutil = None

class SystemService:
    """Provides real-time Windows hardware, OS, and resource metrics."""

    @staticmethod
    def get_os_info() -> Dict[str, str]:
        try:
            return {
                "os": f"Windows {platform.release()}",
                "version": platform.version(),
                "arch": platform.machine(),
                "hostname": platform.node(),
                "processor": platform.processor() or "x86_64 Compatible",
            }
        except Exception as e:
            return {
                "os": "Windows",
                "version": "N/A",
                "arch": "N/A",
                "hostname": "LOCALHOST",
                "processor": "N/A",
            }

    @staticmethod
    def get_uptime_seconds() -> float:
        if not psutil:
            return 0.0
        try:
            boot_time = psutil.boot_time()
            return time.time() - boot_time
        except Exception:
            return 0.0

    @staticmethod
    def format_uptime(seconds: float) -> str:
        d = int(seconds // 86400)
        h = int((seconds % 86400) // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        if d > 0:
            return f"{d}d {h:02d}h {m:02d}m"
        return f"{h:02d}h {m:02d}m {s:02d}s"

    @staticmethod
    def get_cpu_metrics() -> Dict[str, Any]:
        if not psutil:
            return {"percent": 0.0, "count_logical": 1, "count_physical": 1, "per_cpu": [0.0], "freq_mhz": 0}
        try:
            percent = psutil.cpu_percent(interval=None)
            per_cpu = psutil.cpu_percent(interval=None, percpu=True)
            freq = psutil.cpu_freq()
            freq_mhz = int(freq.current) if freq else 0
            return {
                "percent": percent,
                "count_logical": psutil.cpu_count(logical=True) or 1,
                "count_physical": psutil.cpu_count(logical=False) or 1,
                "per_cpu": per_cpu,
                "freq_mhz": freq_mhz,
            }
        except Exception:
            return {"percent": 0.0, "count_logical": 1, "count_physical": 1, "per_cpu": [0.0], "freq_mhz": 0}

    @staticmethod
    def get_memory_metrics() -> Dict[str, Any]:
        if not psutil:
            return {"total": 0, "used": 0, "available": 0, "percent": 0.0}
        try:
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            return {
                "total": mem.total,
                "used": mem.used,
                "available": mem.available,
                "percent": mem.percent,
                "swap_total": swap.total,
                "swap_used": swap.used,
                "swap_percent": swap.percent,
            }
        except Exception:
            return {"total": 0, "used": 0, "available": 0, "percent": 0.0, "swap_total": 0, "swap_used": 0, "swap_percent": 0.0}

    @staticmethod
    def get_disks_summary() -> List[Dict[str, Any]]:
        disks = []
        if not psutil:
            return disks
        try:
            partitions = psutil.disk_partitions(all=False)
            for p in partitions:
                # Filter out CD-ROMs or empty drives
                if "cdrom" in p.opts or p.fstype == "":
                    continue
                try:
                    usage = psutil.disk_usage(p.mountpoint)
                    disks.append({
                        "device": p.device,
                        "mountpoint": p.mountpoint,
                        "fstype": p.fstype,
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                        "percent": usage.percent,
                    })
                except (PermissionError, OSError):
                    continue
        except Exception:
            pass
        return disks

    @staticmethod
    def get_process_count() -> int:
        if not psutil:
            return 0
        try:
            return len(psutil.pids())
        except Exception:
            return 0

    @staticmethod
    def format_bytes(num_bytes: float) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if abs(num_bytes) < 1024.0:
                return f"{num_bytes:3.1f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.1f} PB"

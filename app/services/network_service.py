import time
import socket
from typing import Dict, List, Any, Optional

try:
    import psutil
except ImportError:
    psutil = None

class NetworkService:
    """Monitors real local network interfaces, IP configurations, and bandwidth speeds."""

    def __init__(self):
        self._last_time = time.time()
        self._last_io = None
        self._rates = {"up_bps": 0.0, "down_bps": 0.0}
        if psutil:
            try:
                self._last_io = psutil.net_io_counters()
            except Exception:
                self._last_io = None

    def sample_bandwidth(self) -> Dict[str, float]:
        """Calculates current upload and download rates in bytes/sec."""
        if not psutil:
            return {"up_bps": 0.0, "down_bps": 0.0}

        now = time.time()
        dt = now - self._last_time
        if dt <= 0:
            return self._rates

        try:
            current_io = psutil.net_io_counters()
            if self._last_io:
                bytes_sent = current_io.bytes_sent - self._last_io.bytes_sent
                bytes_recv = current_io.bytes_recv - self._last_io.bytes_recv
                
                # Protect against interface counter resets
                up_bps = max(0.0, bytes_sent / dt)
                down_bps = max(0.0, bytes_recv / dt)
                self._rates = {"up_bps": up_bps, "down_bps": down_bps}
            
            self._last_io = current_io
            self._last_time = now
        except Exception:
            pass

        return self._rates

    @staticmethod
    def get_totals() -> Dict[str, int]:
        if not psutil:
            return {"bytes_sent": 0, "bytes_recv": 0, "packets_sent": 0, "packets_recv": 0}
        try:
            io = psutil.net_io_counters()
            return {
                "bytes_sent": io.bytes_sent,
                "bytes_recv": io.bytes_recv,
                "packets_sent": io.packets_sent,
                "packets_recv": io.packets_recv,
            }
        except Exception:
            return {"bytes_sent": 0, "bytes_recv": 0, "packets_sent": 0, "packets_recv": 0}

    @staticmethod
    def get_interfaces() -> List[Dict[str, Any]]:
        interfaces = []
        if not psutil:
            return interfaces
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            
            for nic_name, nic_addrs in addrs.items():
                is_up = stats[nic_name].isup if nic_name in stats else False
                speed_mbps = stats[nic_name].speed if nic_name in stats else 0
                
                ipv4 = "N/A"
                netmask = "N/A"
                mac = "N/A"
                
                for addr in nic_addrs:
                    if addr.family == socket.AF_INET:
                        ipv4 = addr.address
                        netmask = addr.netmask or "N/A"
                    elif hasattr(psutil, "AF_LINK") and addr.family == psutil.AF_LINK:
                        mac = addr.address

                # Skip virtual loopbacks if unwanted or mark them
                interfaces.append({
                    "name": nic_name,
                    "is_up": is_up,
                    "speed_mbps": speed_mbps,
                    "ipv4": ipv4,
                    "netmask": netmask,
                    "mac": mac,
                })
        except Exception:
            pass
        return interfaces

    @staticmethod
    def format_speed(bps: float) -> str:
        if bps < 1024:
            return f"{bps:3.0f} B/s"
        elif bps < 1024 * 1024:
            return f"{bps / 1024:3.1f} KB/s"
        else:
            return f"{bps / (1024 * 1024):3.1f} MB/s"

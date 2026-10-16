import os
from typing import List, Dict, Any, Optional
from app.config import PROTECTED_PROCESSES

try:
    import psutil
except ImportError:
    psutil = None

class ProcessService:
    """Manages Windows process inspection, status filtering, and safe termination."""

    @staticmethod
    def is_protected_process(proc_name: str, pid: int) -> bool:
        if pid in (0, 4):  # System Idle and System
            return True
        name_lower = proc_name.lower().strip()
        return name_lower in PROTECTED_PROCESSES

    @staticmethod
    def get_process_list(sort_by: str = "cpu", reverse: bool = True) -> List[Dict[str, Any]]:
        processes = []
        if not psutil:
            return processes

        for proc in psutil.process_iter(['pid', 'name', 'status', 'cpu_percent', 'memory_info', 'exe', 'create_time']):
            try:
                info = proc.info
                name = info.get('name') or f"PID-{info['pid']}"
                pid = info['pid']
                cpu = info.get('cpu_percent') or 0.0
                mem_bytes = info['memory_info'].rss if info.get('memory_info') else 0
                exe_path = info.get('exe') or "System / Inaccessible"
                status = info.get('status') or "running"

                is_protected = ProcessService.is_protected_process(name, pid)

                processes.append({
                    "pid": pid,
                    "name": name,
                    "cpu_percent": cpu,
                    "memory_bytes": mem_bytes,
                    "memory_mb": round(mem_bytes / (1024 * 1024), 1),
                    "status": status,
                    "exe": exe_path,
                    "is_protected": is_protected,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue

        # Sort
        if sort_by == "cpu":
            processes.sort(key=lambda p: p["cpu_percent"], reverse=reverse)
        elif sort_by == "memory":
            processes.sort(key=lambda p: p["memory_bytes"], reverse=reverse)
        elif sort_by == "name":
            processes.sort(key=lambda p: p["name"].lower(), reverse=not reverse)
        elif sort_by == "pid":
            processes.sort(key=lambda p: p["pid"], reverse=reverse)

        return processes

    @staticmethod
    def terminate_process(pid: int) -> Dict[str, Any]:
        """Safely terminates a non-protected process with guardrails."""
        if not psutil:
            return {"success": False, "error": "psutil not available"}

        try:
            proc = psutil.Process(pid)
            name = proc.name()

            if ProcessService.is_protected_process(name, pid):
                return {
                    "success": False,
                    "error": f"Process '{name}' (PID {pid}) is a critical Windows system component and cannot be terminated."
                }

            proc.terminate()
            proc.wait(timeout=3)
            return {"success": True, "name": name, "pid": pid}
        except psutil.NoSuchProcess:
            return {"success": False, "error": f"Process with PID {pid} no longer exists."}
        except psutil.AccessDenied:
            return {"success": False, "error": f"Access denied. Elevated privileges required to terminate PID {pid}."}
        except psutil.TimeoutExpired:
            # Fallback to kill if terminate timed out
            try:
                proc.kill()
                return {"success": True, "name": name, "pid": pid, "forced": True}
            except Exception as e:
                return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}

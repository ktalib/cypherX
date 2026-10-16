import os
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from app.config import PROTECTED_DIRS

try:
    import send2trash
except ImportError:
    send2trash = None

class CleanupService:
    """Safe disk cleaning utility with dry-run analysis and Recycle Bin integration."""

    SAFE_TEMP_EXTENSIONS = {".tmp", ".temp", ".log", ".bak", ".old", ".dmp", ".chk", ".wer"}

    @classmethod
    def get_cleanup_targets(cls) -> List[Dict[str, Any]]:
        """Identifies eligible temporary locations safely."""
        targets = []
        user_temp = os.environ.get("TEMP") or os.environ.get("TMP")
        if user_temp and os.path.exists(user_temp):
            targets.append({
                "id": "user_temp",
                "name": "User Temporary Files",
                "path": user_temp,
                "description": "Transient application files and scratch data in %TEMP%",
                "type": "temp"
            })

        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            thumb_cache = os.path.join(local_app_data, "Microsoft", "Windows", "Explorer")
            if os.path.exists(thumb_cache):
                targets.append({
                    "id": "thumb_cache",
                    "name": "Windows Thumbnail Cache",
                    "path": thumb_cache,
                    "description": "Cached image and icon previews",
                    "type": "cache"
                })

            crash_dumps = os.path.join(local_app_data, "CrashDumps")
            if os.path.exists(crash_dumps):
                targets.append({
                    "id": "crash_dumps",
                    "name": "Windows Crash Dumps",
                    "path": crash_dumps,
                    "description": "Saved application crash minidumps",
                    "type": "dumps"
                })

        return targets

    @classmethod
    def analyze_target(cls, target_path: str,
                       min_age_hours: float = 24.0,
                       progress_callback: Optional[Callable[[int, str], None]] = None,
                       is_cancelled: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
        """
        Pure read-only analysis. Never deletes anything.
        Finds candidate files older than min_age_hours or safe temp extensions.
        """
        candidates = []
        total_reclaimable_bytes = 0
        now = time.time()
        min_age_seconds = min_age_hours * 3600
        scanned = 0

        # Safety check: Prevent scanning protected directories directly
        norm_target = os.path.abspath(target_path).lower()
        if norm_target in PROTECTED_DIRS:
            return {"candidates": [], "total_bytes": 0, "scanned": 0, "error": "Protected directory"}

        try:
            for root, dirs, files in os.walk(target_path):
                if is_cancelled and is_cancelled():
                    break
                for f in files:
                    if is_cancelled and is_cancelled():
                        break
                    scanned += 1
                    fp = os.path.join(root, f)
                    try:
                        stat = os.stat(fp)
                        age = now - stat.st_mtime
                        ext = os.path.splitext(f)[1].lower()

                        # Candidate if older than threshold or explicitly recognized temp format
                        is_candidate = (age >= min_age_seconds) or (ext in cls.SAFE_TEMP_EXTENSIONS)
                        if is_candidate and stat.st_size > 0:
                            candidates.append({
                                "name": f,
                                "path": fp,
                                "size": stat.st_size,
                                "modified": stat.st_mtime,
                                "age_hours": age / 3600.0,
                                "selected": True
                            })
                            total_reclaimable_bytes += stat.st_size
                    except (PermissionError, OSError):
                        pass

                    if progress_callback and scanned % 100 == 0:
                        progress_callback(scanned, f)
        except (PermissionError, OSError) as e:
            pass

        return {
            "candidates": candidates,
            "total_bytes": total_reclaimable_bytes,
            "scanned": scanned,
        }

    @classmethod
    def execute_cleanup(cls, files: List[str],
                        use_recycle_bin: bool = True,
                        progress_callback: Optional[Callable[[int, str], None]] = None,
                        is_cancelled: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
        """
        Executes removal on user-confirmed files.
        Prefers send2trash for safety.
        """
        processed = 0
        removed = 0
        skipped = 0
        bytes_freed = 0
        errors = []

        for fp in files:
            if is_cancelled and is_cancelled():
                break
            processed += 1
            if progress_callback:
                progress_callback(processed, os.path.basename(fp))

            if not os.path.exists(fp):
                skipped += 1
                continue

            try:
                size = os.path.getsize(fp)
                if use_recycle_bin and send2trash:
                    send2trash.send2trash(os.path.normpath(fp))
                else:
                    # Deletion only if explicitly permitted
                    os.remove(fp)
                
                removed += 1
                bytes_freed += size
            except PermissionError:
                skipped += 1
                errors.append(f"Locked / In use: {os.path.basename(fp)}")
            except Exception as e:
                skipped += 1
                errors.append(f"{os.path.basename(fp)}: {str(e)}")

        return {
            "processed": processed,
            "removed": removed,
            "skipped": skipped,
            "bytes_freed": bytes_freed,
            "errors": errors,
        }

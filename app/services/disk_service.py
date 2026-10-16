import os
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
import heapq
from app.config import PROTECTED_DIRS, CATEGORY_EXTENSIONS

try:
    import psutil
except ImportError:
    psutil = None

class DiskService:
    """Provides drive discovery, recursive folder sizing, and large file analysis."""

    @staticmethod
    def get_drives() -> List[Dict[str, Any]]:
        drives = []
        if not psutil:
            return drives
        try:
            for part in psutil.disk_partitions(all=False):
                if "cdrom" in part.opts or part.fstype == "":
                    continue
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    drives.append({
                        "device": part.device,
                        "mountpoint": part.mountpoint,
                        "fstype": part.fstype,
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                        "percent": usage.percent,
                    })
                except Exception:
                    continue
        except Exception:
            pass
        return drives

    @staticmethod
    def is_protected_path(path_str: str) -> bool:
        normalized = os.path.abspath(path_str).lower()
        for p in PROTECTED_DIRS:
            if normalized == p or normalized.startswith(p + "\\"):
                return True
        return False

    @staticmethod
    def scan_folder(folder_path: str,
                    progress_callback: Optional[Callable[[int, str], None]] = None,
                    is_cancelled: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
        """
        Full recursive scan of a directory tree. Returns total size, file/folder counts,
        size per immediate subfolder, extension + category distribution across ALL files,
        and the 50 largest files anywhere in the tree.
        """
        root_path = Path(folder_path)
        if not root_path.exists() or not root_path.is_dir():
            raise ValueError(f"Directory does not exist: {folder_path}")

        ext_to_cat = {e: cat for cat, exts in CATEGORY_EXTENSIONS.items() for e in exts}
        total_size = file_count = folder_count = 0
        extension_map: Dict[str, Dict[str, Any]] = {}
        categories: Dict[str, int] = {}
        subfolders: Dict[str, int] = {}
        subfolder_files: Dict[str, int] = {}
        loose_size = 0
        heap: List[tuple] = []
        skipped = 0

        # Stack of (path, top-level child name or None for the root itself)
        stack = [(folder_path, None)]
        while stack:
            if is_cancelled and is_cancelled():
                break
            current, top = stack.pop()
            try:
                it = os.scandir(current)
            except (PermissionError, OSError):
                skipped += 1
                continue
            with it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            folder_count += 1
                            child_top = top if top is not None else entry.name
                            if top is None:
                                subfolders.setdefault(entry.name, 0)
                                subfolder_files.setdefault(entry.name, 0)
                            stack.append((entry.path, child_top))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        st = entry.stat(follow_symlinks=False)
                    except (PermissionError, OSError):
                        skipped += 1
                        continue
                    size = st.st_size
                    file_count += 1
                    total_size += size
                    if top is None:
                        loose_size += size
                    else:
                        subfolders[top] += size
                        subfolder_files[top] += 1
                    ext = os.path.splitext(entry.name)[1].lower() or "[no ext]"
                    em = extension_map.setdefault(ext, {"count": 0, "size": 0})
                    em["count"] += 1
                    em["size"] += size
                    cat = ext_to_cat.get(ext, "Other")
                    categories[cat] = categories.get(cat, 0) + size
                    item = (size, entry.path, entry.name, st.st_mtime)
                    if len(heap) < 50:
                        heapq.heappush(heap, item)
                    elif size > heap[0][0]:
                        heapq.heapreplace(heap, item)
                    if progress_callback and file_count % 500 == 0:
                        progress_callback(file_count, entry.name)

        largest = [{"name": n, "path": p, "size": sz, "modified": mt}
                   for sz, p, n, mt in sorted(heap, reverse=True)]
        return {
            "root": folder_path,
            "total_size": total_size,
            "file_count": file_count,
            "folder_count": folder_count,
            "subfolders": subfolders,
            "subfolder_files": subfolder_files,
            "loose_size": loose_size,
            "extensions": extension_map,
            "categories": categories,
            "largest_files": largest,
            "skipped": skipped,
        }

    @staticmethod
    def _measure_folder_shallow(dir_path: str, is_cancelled: Optional[Callable[[], bool]] = None) -> tuple[int, int]:
        total_size = 0
        total_files = 0
        try:
            for root, dirs, files in os.walk(dir_path):
                if is_cancelled and is_cancelled():
                    break
                for f in files:
                    total_files += 1
                    try:
                        fp = os.path.join(root, f)
                        total_size += os.path.getsize(fp)
                    except (PermissionError, OSError):
                        pass
        except (PermissionError, OSError):
            pass
        return total_size, total_files

    @staticmethod
    def find_large_files(folder_path: str,
                         min_size_bytes: int = 100 * 1024 * 1024,
                         progress_callback: Optional[Callable[[int, str], None]] = None,
                         is_cancelled: Optional[Callable[[], bool]] = None) -> List[Dict[str, Any]]:
        """Finds all files in a folder and subfolders greater than min_size_bytes."""
        results = []
        scanned_count = 0
        
        try:
            for root, dirs, files in os.walk(folder_path):
                if is_cancelled and is_cancelled():
                    break
                for f in files:
                    if is_cancelled and is_cancelled():
                        break
                    scanned_count += 1
                    try:
                        filepath = os.path.join(root, f)
                        stat = os.stat(filepath)
                        if stat.st_size >= min_size_bytes:
                            results.append({
                                "name": f,
                                "path": filepath,
                                "size": stat.st_size,
                                "modified": stat.st_mtime,
                                "extension": os.path.splitext(f)[1].lower() or "[no ext]"
                            })
                    except (PermissionError, OSError):
                        pass
                    
                    if progress_callback and scanned_count % 100 == 0:
                        progress_callback(scanned_count, f)
        except (PermissionError, OSError):
            pass

        results.sort(key=lambda x: x["size"], reverse=True)
        return results

    @staticmethod
    def compute_sha256(filepath: str, max_bytes: Optional[int] = None) -> Optional[str]:
        """Computes SHA-256 hash of a file for duplicate verification."""
        hasher = hashlib.sha256()
        try:
            bytes_read = 0
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    hasher.update(chunk)
                    bytes_read += len(chunk)
                    if max_bytes and bytes_read >= max_bytes:
                        break
            return hasher.hexdigest()
        except (PermissionError, OSError):
            return None

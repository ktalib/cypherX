import os
from collections import defaultdict
from typing import Dict, List, Any
from PySide6.QtCore import QThread, Signal
from app.services.disk_service import DiskService

class DuplicateFinderWorker(QThread):
    """
    Two-pass duplicate file finder:
    1. Size-based grouping (fast filter)
    2. SHA-256 cryptographic verification of matching sizes
    """

    progress = Signal(int, str)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, root_path: str, parent=None):
        super().__init__(parent)
        self.root_path = root_path
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            # Pass 1: Size grouping
            size_map = defaultdict(list)
            scanned_files = 0

            for root, dirs, files in os.walk(self.root_path):
                if self._is_cancelled:
                    return
                for f in files:
                    if self._is_cancelled:
                        return
                    scanned_files += 1
                    fp = os.path.join(root, f)
                    try:
                        sz = os.path.getsize(fp)
                        if sz > 0:  # Skip 0-byte files
                            size_map[sz].append(fp)
                    except (PermissionError, OSError):
                        pass

                    if scanned_files % 100 == 0:
                        self.progress.emit(scanned_files, f"Phase 1: Size check ({f[:25]})")

            # Filter out unique sizes
            candidate_sizes = {sz: paths for sz, paths in size_map.items() if len(paths) > 1}
            total_candidate_files = sum(len(paths) for paths in candidate_sizes.values())

            # Pass 2: SHA-256 hashing
            hash_groups = defaultdict(list)
            hashed_count = 0

            for sz, paths in candidate_sizes.items():
                if self._is_cancelled:
                    return
                for fp in paths:
                    if self._is_cancelled:
                        return
                    hashed_count += 1
                    file_hash = DiskService.compute_sha256(fp)
                    if file_hash:
                        hash_groups[file_hash].append({
                            "path": fp,
                            "name": os.path.basename(fp),
                            "size": sz,
                            "modified": os.path.getmtime(fp)
                        })

                    if hashed_count % 10 == 0:
                        self.progress.emit(hashed_count, f"Phase 2: SHA-256 verify ({os.path.basename(fp)[:25]})")

            # Only keep groups with > 1 file
            duplicate_groups = [files for files in hash_groups.values() if len(files) > 1]
            total_wasted_bytes = sum(group[0]["size"] * (len(group) - 1) for group in duplicate_groups)

            self.finished.emit({
                "duplicate_groups": duplicate_groups,
                "total_groups": len(duplicate_groups),
                "total_duplicates": sum(len(g) - 1 for g in duplicate_groups),
                "wasted_bytes": total_wasted_bytes,
                "scanned_count": scanned_files,
            })

        except Exception as e:
            self.error.emit(str(e))

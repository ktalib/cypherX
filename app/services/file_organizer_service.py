import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from app.config import CATEGORY_EXTENSIONS

class FileOrganizerService:
    """Intelligent, rule-based file organization engine with dry-run previews and undo support."""

    @classmethod
    def get_category_for_extension(cls, ext: str) -> str:
        ext = ext.lower()
        for cat, extensions in CATEGORY_EXTENSIONS.items():
            if ext in extensions:
                return cat
        return "Other"

    @classmethod
    def preview_organization(cls, folder_path: str,
                             strategy: str = "category", # "category", "extension", "date_ym", "date_y"
                             custom_rules: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Simulates file moves without modifying the disk.
        Returns proposed actions, conflict detections, and stats.
        """
        root = Path(folder_path)
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Invalid directory: {folder_path}")

        planned_moves = []
        conflicts = 0
        total_files = 0
        total_bytes = 0

        # Scan top-level files only to avoid organizing existing organized subfolders recursively
        for entry in os.scandir(folder_path):
            if not entry.is_file(follow_symlinks=False):
                continue

            total_files += 1
            filename = entry.name
            filepath = entry.path
            ext = os.path.splitext(filename)[1].lower()
            try:
                stat = entry.stat()
                file_size = stat.st_size
                mtime = stat.st_mtime
            except (PermissionError, OSError):
                file_size = 0
                mtime = 0

            total_bytes += file_size

            # Determine destination subfolder
            subfolder_name = "Other"
            if custom_rules and ext in custom_rules:
                subfolder_name = custom_rules[ext]
            elif strategy == "category":
                subfolder_name = cls.get_category_for_extension(ext)
            elif strategy == "extension":
                subfolder_name = ext.lstrip(".").upper() if ext else "NO_EXT"
            elif strategy == "date_ym":
                dt = datetime.fromtimestamp(mtime)
                subfolder_name = dt.strftime("%Y-%m")
            elif strategy == "date_y":
                dt = datetime.fromtimestamp(mtime)
                subfolder_name = dt.strftime("%Y")

            dest_folder = root / subfolder_name
            dest_file = dest_folder / filename

            # Check conflict
            has_conflict = dest_file.exists()
            if has_conflict:
                conflicts += 1

            planned_moves.append({
                "filename": filename,
                "source_path": str(filepath),
                "dest_folder": str(dest_folder),
                "dest_path": str(dest_file),
                "size": file_size,
                "subfolder": subfolder_name,
                "has_conflict": has_conflict,
                "conflict_resolution": "rename" if has_conflict else "none"
            })

        return {
            "root_path": folder_path,
            "strategy": strategy,
            "total_files": total_files,
            "total_bytes": total_bytes,
            "conflicts": conflicts,
            "planned_moves": planned_moves,
        }

    @classmethod
    def execute_moves(cls, planned_moves: List[Dict[str, Any]],
                      conflict_mode: str = "rename", # "rename", "skip", "overwrite"
                      progress_callback = None,
                      is_cancelled = None) -> Dict[str, Any]:
        """
        Executes moves based on previewed plan.
        Returns completed operations log with reverse instructions for undo.
        """
        executed = []
        skipped = []
        errors = []

        for idx, item in enumerate(planned_moves):
            if is_cancelled and is_cancelled():
                break

            if progress_callback:
                progress_callback(idx + 1, item["filename"])

            src = Path(item["source_path"])
            dest_folder = Path(item["dest_folder"])
            dest = Path(item["dest_path"])

            if not src.exists():
                skipped.append(f"{src.name} (Source file missing)")
                continue

            try:
                dest_folder.mkdir(parents=True, exist_ok=True)

                final_dest = dest
                if final_dest.exists() and final_dest.resolve() != src.resolve():
                    if conflict_mode == "skip":
                        skipped.append(f"{src.name} (Destination exists)")
                        continue
                    elif conflict_mode == "rename":
                        stem = final_dest.stem
                        suffix = final_dest.suffix
                        counter = 1
                        while final_dest.exists():
                            final_dest = dest_folder / f"{stem}_{counter}{suffix}"
                            counter += 1

                # Execute atomic or safe move
                shutil.move(str(src), str(final_dest))

                executed.append({
                    "original_path": str(src),
                    "new_path": str(final_dest),
                    "filename": item["filename"]
                })
            except Exception as e:
                errors.append(f"{item['filename']}: {str(e)}")

        return {
            "executed_count": len(executed),
            "skipped_count": len(skipped),
            "errors": errors,
            "executed_moves": executed,
        }

    @classmethod
    def undo_moves(cls, executed_moves: List[Dict[str, str]]) -> Dict[str, Any]:
        """Restores moved files back to their original positions."""
        restored = 0
        failed = []

        for item in reversed(executed_moves):
            current_path = Path(item["new_path"])
            orig_path = Path(item["original_path"])

            if not current_path.exists():
                failed.append(f"{current_path.name} (File not found at destination)")
                continue

            try:
                orig_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(current_path), str(orig_path))
                restored += 1
            except Exception as e:
                failed.append(f"{current_path.name}: {str(e)}")

        return {
            "restored_count": restored,
            "failed": failed
        }

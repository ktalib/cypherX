"""
Backups: one zip a night with everything CYPHER-X knows — the database
(accounts, tasks, notes, bills, groceries, history), the 3D home layout,
energy log, camera settings and events, known Wi-Fi devices — optionally the
camera snapshots too. Old backups beyond "keep" are deleted.

The database is copied with SQLite's online backup API, so a backup is
consistent even while the app is writing to it.

Restore puts the files back and needs a restart of CYPHER-X; before
restoring, the current state is saved as a "pre-restore" backup.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

from app.config import USER_DATA_DIR, DB_PATH, APP_VERSION
from app.server.services import ThreadService

DATA_FILES = ["smart_home.json", "smart_home_energy.json", "network_devices.json",
              "cctv/cctv.json", "cctv/events.json"]
PREFIX = "cypherx-backup-"


class BackupManager:
    def __init__(self, data_dir=USER_DATA_DIR, db_path=DB_PATH):
        self.data_dir = Path(data_dir)
        self.db_path = Path(db_path)

    def default_folder(self):
        return self.data_dir / "backups"

    def create(self, dest, include_snapshots=False, tag=""):
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = dest / f"{PREFIX}{stamp}{('-' + tag) if tag else ''}.zip"
        files = []
        with tempfile.TemporaryDirectory() as tmp:
            db_copy = Path(tmp) / self.db_path.name
            if self.db_path.exists():
                src = sqlite3.connect(str(self.db_path))
                dst = sqlite3.connect(str(db_copy))
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()
            partial = target.with_suffix(".part")
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as z:
                if db_copy.exists():
                    z.write(db_copy, self.db_path.name)
                    files.append(self.db_path.name)
                for rel in DATA_FILES:
                    p = self.data_dir / rel
                    if p.exists():
                        z.write(p, rel)
                        files.append(rel)
                if include_snapshots:
                    snaps = self.data_dir / "cctv" / "snapshots"
                    for root, _dirs, names in os.walk(snaps):
                        for n in names:
                            p = Path(root) / n
                            rel = p.relative_to(self.data_dir).as_posix()
                            z.write(p, rel)
                            files.append(rel)
                z.writestr("manifest.json", json.dumps({
                    "app": "CYPHER-X", "version": APP_VERSION, "created": time.time(),
                    "files": files, "snapshots": include_snapshots}, indent=2))
            partial.replace(target)
        return target

    @staticmethod
    def list(dest):
        dest = Path(dest)
        if not dest.exists():
            return []
        out = []
        for p in dest.glob(f"{PREFIX}*.zip"):
            try:
                st = p.stat()
                out.append({"path": p, "size": st.st_size, "mtime": st.st_mtime})
            except OSError:
                pass
        return sorted(out, key=lambda b: b["mtime"], reverse=True)

    def prune(self, dest, keep):
        """Delete nightly backups beyond the newest `keep` (pre-restore backups are kept)."""
        nightly = [b for b in self.list(dest) if "-pre-restore" not in b["path"].name]
        removed = 0
        for b in nightly[max(1, int(keep)):]:
            try:
                b["path"].unlink()
                removed += 1
            except OSError:
                pass
        return removed

    @staticmethod
    def read_manifest(path):
        with zipfile.ZipFile(path) as z:
            manifest = json.loads(z.read("manifest.json"))
        if manifest.get("app") != "CYPHER-X":
            raise ValueError("Not a CYPHER-X backup")
        return manifest

    def restore(self, path):
        """Put the backup's files back. The caller must restart the app afterwards."""
        manifest = self.read_manifest(path)
        with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory() as tmp:
            for name in manifest["files"]:
                target = (self.data_dir / name).resolve()
                if self.data_dir.resolve() not in target.parents and target != self.data_dir.resolve():
                    raise ValueError(f"Unsafe path in backup: {name}")
            z.extractall(tmp, members=[n for n in z.namelist() if n in manifest["files"]])
            for name in manifest["files"]:
                src = Path(tmp) / name
                if name == self.db_path.name:
                    # copy into the live database through SQLite (safe while it's open elsewhere)
                    s = sqlite3.connect(str(src))
                    d = sqlite3.connect(str(self.db_path))
                    try:
                        s.backup(d)
                    finally:
                        d.close()
                        s.close()
                else:
                    target = self.data_dir / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, target)
        return manifest


def open_folder(path):
    path = str(path)
    if os.name == "nt":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class BackupService(ThreadService):
    id = "backups"
    title = "Backups"
    description = "Backs up the database and settings every night, keeps the last copies, restores in one click."
    icon = "save"
    default_enabled = True
    settings_schema = [
        ("folder", "Backup folder", "str", "", "Leave empty for the app's data folder. An external drive or "
                                                "a synced folder (Google Drive / OneDrive) is safer."),
        ("time", "Back up at (HH:MM)", "str", "02:30", "If the PC is off then, it backs up as soon as it's on"),
        ("keep", "Keep this many", "int", 7, "Older backups are deleted"),
        ("include_snapshots", "Include camera snapshots", "bool", False, "Makes backups much bigger"),
    ]

    def __init__(self, bus, manager_cls=BackupManager, extra_actions=None):
        super().__init__()
        self.bus = bus
        self.bm = manager_cls()
        self.extra_actions = extra_actions or []
        self._now = False
        self.last_result = None

    def folder(self):
        return Path(self.setting("folder") or self.bm.default_folder())

    def last_backup(self):
        b = self.bm.list(self.folder())
        return b[0] if b else None

    def due(self, now=None):
        now = now or time.time()
        last = self.last_backup()
        try:
            hh, mm = [int(x) for x in str(self.setting("time") or "02:30").split(":")]
        except ValueError:
            hh, mm = 2, 30
        today_at = datetime.fromtimestamp(now).replace(hour=hh % 24, minute=mm % 60, second=0).timestamp()
        slot = today_at if now >= today_at else today_at - 86400        # the most recent scheduled time
        return last is None or last["mtime"] < slot

    def run(self, stop):
        self.mark_running()
        while not stop.is_set():
            if self._now or self.due():
                self._now = False
                self.backup_now()
            stop.wait(30)

    def backup_now(self, tag=""):
        try:
            path = self.bm.create(self.folder(), include_snapshots=bool(self.setting("include_snapshots")), tag=tag)
            removed = self.bm.prune(self.folder(), int(self.setting("keep") or 7))
            size = path.stat().st_size / 1024
            self.last_result = ("ok", f"{path.name} ({size:,.0f} KB)")
            self.log(f"Backed up to {path} ({size:,.0f} KB)" + (f", removed {removed} old" if removed else ""))
            return path
        except Exception as e:
            self.last_result = ("fail", str(e))
            self.log(f"Backup failed: {e}", "error")
            self.bus.publish("backup", "Backup failed", str(e))
            raise

    def info(self):
        last = self.last_backup()
        lines = [f"Folder: {self.folder()}"]
        if last:
            age_h = (time.time() - last["mtime"]) / 3600
            lines.append(f"Last backup: {datetime.fromtimestamp(last['mtime']):%a %d %b %H:%M} "
                         f"({age_h:.0f} h ago) · {last['size'] / 1024:,.0f} KB · "
                         f"{len(self.bm.list(self.folder()))} kept")
        else:
            lines.append("No backup yet.")
        lines.append(f"Next: daily at {self.setting('time') or '02:30'}")
        if self.last_result and self.last_result[0] == "fail":
            lines.append(f"Last attempt failed: {self.last_result[1]}")
        return lines

    def actions(self):
        def now():
            path = self.backup_now()
            return f"Backup saved:\n{path}"

        def folder():
            self.folder().mkdir(parents=True, exist_ok=True)
            open_folder(self.folder())
            return None
        return [("Back up now", now), ("Open backup folder", folder)] + list(self.extra_actions)


def backup_check(service):
    """Boot-screen check: how old is the newest backup?"""
    last = service.last_backup()
    if last is None:
        return "warn", "No backup yet — it runs tonight, or press Back up now in Services"
    age_h = (time.time() - last["mtime"]) / 3600
    detail = f"Last backup {age_h:.0f} h ago · {len(service.bm.list(service.folder()))} kept"
    return ("warn" if age_h > 48 else "ok"), detail

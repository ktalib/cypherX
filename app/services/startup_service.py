import os
import struct
import time
import winreg
from pathlib import Path
from typing import List, Dict, Any, Optional


class StartupService:
    """Manages Windows Startup applications via Registry Run keys and the Startup folder."""

    REG_LOCATIONS = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "Registry: HKCU Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "Registry: HKLM Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
         "Registry: HKLM Run (32-bit)"),
    ]

    # The same on/off switch Windows Task Manager uses — reversible, nothing is deleted
    APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"

    # ------------------------------------------------------------------ list --

    @classmethod
    def get_startup_entries(cls) -> List[Dict[str, Any]]:
        entries = []

        for root_key, subkey, source_label in cls.REG_LOCATIONS:
            try:
                with winreg.OpenKey(root_key, subkey, 0, winreg.KEY_READ) as key:
                    num_values = winreg.QueryInfoKey(key)[1]
                    for i in range(num_values):
                        try:
                            name, val, _val_type = winreg.EnumValue(key, i)
                        except OSError:
                            continue
                        entry = {
                            "name": name,
                            "command": val,
                            "source": source_label,
                            "type": "registry",
                            "root_key": "HKCU" if root_key == winreg.HKEY_CURRENT_USER else "HKLM",
                            "subkey": subkey,
                        }
                        entry["enabled"] = cls.is_enabled(entry)
                        entries.append(entry)
            except (OSError, PermissionError):
                continue

        app_data = os.environ.get("APPDATA")
        if app_data:
            startup_folder = Path(app_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            if startup_folder.exists():
                try:
                    for item in startup_folder.iterdir():
                        if (item.is_file() and item.name.lower() != "desktop.ini"
                                and not item.name.endswith(".disabled")):
                            entry = {
                                "name": item.stem,
                                "command": str(item),
                                "source": "User Startup Folder",
                                "type": "shortcut",
                                "path": str(item),
                            }
                            entry["enabled"] = cls.is_enabled(entry)
                            entries.append(entry)
                except OSError:
                    pass

        return entries

    @staticmethod
    def program_path(command: str):
        """(path, exists) for the program a Run command launches."""
        import shutil
        cmd = os.path.expandvars((command or "").strip())
        if cmd.startswith('"'):
            path = cmd[1:].split('"', 1)[0]
        else:
            idx = cmd.lower().find(".exe")
            path = cmd[: idx + 4] if idx >= 0 else cmd.split(" ")[0]
        if path and not os.path.isabs(path):
            path = shutil.which(path) or path
        return path, bool(path) and os.path.exists(path)

    @classmethod
    def executable_of(cls, command: str) -> Optional[str]:
        path, exists = cls.program_path(command)
        return path if exists else None

    # ------------------------------------------------------- enable / disable --

    @classmethod
    def _approved_location(cls, entry):
        if entry.get("type") == "shortcut":
            return winreg.HKEY_CURRENT_USER, cls.APPROVED + r"\StartupFolder"
        root = winreg.HKEY_CURRENT_USER if entry.get("root_key") == "HKCU" else winreg.HKEY_LOCAL_MACHINE
        sub = "Run32" if "WOW6432Node" in entry.get("subkey", "") else "Run"
        return root, cls.APPROVED + "\\" + sub

    @staticmethod
    def _approved_name(entry):
        return Path(entry["path"]).name if entry.get("type") == "shortcut" else entry["name"]

    @classmethod
    def is_enabled(cls, entry) -> bool:
        root, sub = cls._approved_location(entry)
        try:
            with winreg.OpenKey(root, sub, 0, winreg.KEY_READ) as k:
                data, _ = winreg.QueryValueEx(k, cls._approved_name(entry))
                return not (data and data[0] & 0x01)      # 0x03 = disabled, 0x02/0x06 = enabled
        except OSError:
            return True

    @classmethod
    def set_enabled(cls, entry, enabled: bool) -> Dict[str, Any]:
        root, sub = cls._approved_location(entry)
        if enabled:
            data = bytes([2]) + bytes(11)
        else:
            filetime = int((time.time() + 11644473600) * 10_000_000)
            data = bytes([3, 0, 0, 0]) + struct.pack("<Q", filetime)
        try:
            with winreg.CreateKeyEx(root, sub, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, cls._approved_name(entry), 0, winreg.REG_BINARY, data)
            return {"success": True}
        except PermissionError:
            return {"success": False,
                    "error": "Windows needs administrator rights to change this machine-wide entry.\n"
                             "Run CYPHER-X as administrator, or use Task Manager > Startup."}
        except OSError as e:
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------- remove / restore --

    @classmethod
    def remove_startup_entry(cls, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Removes a startup item entirely. Returns backup data for undo/restore."""
        entry_type = entry.get("type")
        if entry_type == "registry":
            root_key = winreg.HKEY_CURRENT_USER if entry["root_key"] == "HKCU" else winreg.HKEY_LOCAL_MACHINE
            try:
                with winreg.OpenKey(root_key, entry["subkey"], 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, entry["name"])
                return {"success": True, "backup": entry}
            except PermissionError:
                return {"success": False, "error": "Administrator privileges required to modify HKLM startup items."}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif entry_type == "shortcut":
            filepath = Path(entry["path"])
            try:
                disabled_path = filepath.with_suffix(filepath.suffix + ".disabled")
                filepath.rename(disabled_path)
                return {"success": True, "backup": {**entry, "disabled_path": str(disabled_path)}}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "Unknown entry type"}

    @classmethod
    def restore_startup_entry(cls, backup: Dict[str, Any]) -> Dict[str, Any]:
        """Restores a previously removed startup entry."""
        entry_type = backup.get("type")
        if entry_type == "registry":
            root_key = winreg.HKEY_CURRENT_USER if backup["root_key"] == "HKCU" else winreg.HKEY_LOCAL_MACHINE
            try:
                with winreg.OpenKey(root_key, backup["subkey"], 0, winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, backup["name"], 0, winreg.REG_SZ, backup["command"])
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif entry_type == "shortcut":
            disabled_path = Path(backup.get("disabled_path", ""))
            orig_path = Path(backup.get("path", ""))
            try:
                if disabled_path.exists():
                    disabled_path.rename(orig_path)
                    return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "Invalid backup data"}

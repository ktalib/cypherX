import os
from pathlib import Path

# Application Meta
APP_NAME = "CYBEROPS"
APP_SUBTITLE = "COMMAND CENTER"
APP_VERSION = "1.0.0"
ORG_NAME = "CyberOps Command"

# Storage Paths
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
USER_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cyberops")) / "CyberOps"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = USER_DATA_DIR / "cyberops.db"

# Theme & Palette Tokens (Sci-Fi / Cyberpunk Console)
COLOR_BG_DARK = "#080c0e"          # Main window canvas
COLOR_PANEL_BG = "#0d1717"         # Card / panel background
COLOR_PANEL_ALT = "#122020"        # Elevated headers, hover states
COLOR_PANEL_HOVER = "#162828"      # Hover highlight
COLOR_BORDER_MUTED = "#16302b"     # Thin futuristic border
COLOR_BORDER_FOCUS = "#00f0ff"     # Neon cyan active border
COLOR_BORDER_ACCENT = "#00ff66"    # Terminal green secondary border

COLOR_CYAN = "#00f0ff"             # Primary Neon Cyan
COLOR_CYAN_DIM = "#009ea8"         # Muted cyan
COLOR_CYAN_BG = "rgba(0, 240, 255, 0.08)"

COLOR_GREEN = "#00ff66"            # Secondary Neon Green
COLOR_GREEN_DIM = "#00b347"        # Muted green
COLOR_GREEN_BG = "rgba(0, 255, 102, 0.08)"

COLOR_YELLOW = "#ffd000"           # Warning gold/yellow
COLOR_RED = "#ff3355"              # Critical alert red
COLOR_ORANGE = "#ff8800"

COLOR_TEXT_PRIMARY = "#e2f5f1"     # Bright cyber cyan-white
COLOR_TEXT_SECONDARY = "#789890"   # Muted teal-gray
COLOR_TEXT_MUTED = "#44635b"       # Low contrast labels

FONT_FAMILY_DISPLAY = "'SF Pro Display', 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Inter', 'Helvetica Neue', sans-serif"
FONT_FAMILY_MONO = "'SF Mono', 'Segoe UI Mono', Consolas, 'Cascadia Mono', monospace"

# Refresh & Telemetry Intervals (Milliseconds)
DEFAULT_METRICS_INTERVAL_MS = 1500
FAST_METRICS_INTERVAL_MS = 1000
SLOW_METRICS_INTERVAL_MS = 3000

# Critical Windows System Directories (Protected from destructive operations)
PROTECTED_DIRS = {
    os.environ.get("WINDIR", "C:\\Windows").lower(),
    os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "System32").lower(),
    os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "SysWOW64").lower(),
    os.environ.get("ProgramFiles", "C:\\Program Files").lower(),
    os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)").lower(),
    os.environ.get("ProgramData", "C:\\ProgramData").lower(),
    "c:\\windows",
    "c:\\system volume information",
    "c:\\recovery",
    "c:\\boot",
    "c:\\$recycle.bin",
}

# Critical Windows System Processes (Must not be terminated)
PROTECTED_PROCESSES = {
    "system",
    "system idle process",
    "registry",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "winlogon.exe",
    "dwm.exe",
    "svchost.exe",
    "explorer.exe",
    "fontdrvhost.exe",
    "sihost.exe",
    "taskhostw.exe",
    "ctfmon.exe",
    "spoolsv.exe",
    "runtimebroker.exe",
}

# File Categories for Folder Organizer
CATEGORY_EXTENSIONS = {
    "Documents": [".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".tex", ".wpd", ".pages", ".epub"],
    "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".tiff", ".ico", ".raw", ".psd"],
    "Videos": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".3gp"],
    "Audio": [".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".aiff", ".mid"],
    "Archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".tgz"],
    "Installers": [".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".dmg", ".pkg"],
    "Spreadsheets": [".xls", ".xlsx", ".csv", ".tsv", ".ods", ".xlsm"],
    "Presentations": [".ppt", ".pptx", ".key", ".odp"],
    "Code": [".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".yaml", ".yml", ".c", ".cpp", ".h", ".cs", ".java", ".go", ".rs", ".sql", ".sh", ".md"],
}

# Large File Finder Presets (Bytes)
LARGE_FILE_PRESETS = [
    ("50 MB", 50 * 1024 * 1024),
    ("100 MB", 100 * 1024 * 1024),
    ("500 MB", 500 * 1024 * 1024),
    ("1 GB", 1024 * 1024 * 1024),
    ("5 GB", 5 * 1024 * 1024 * 1024),
]

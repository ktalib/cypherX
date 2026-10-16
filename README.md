# CYPHER-X — Liquid Glass Desktop Operations & Widget Center

CYPHER-X is a modern, macOS / iOS Sonoma-inspired desktop operations hub and widget dashboard built with **Python 3.12+** and **PySide6**. It features a translucent **Liquid Glass** aesthetic (inspired by [WidgetScreen](https://widgetscreen.app/)), pure vector SVG icons (Lucide / Apple SF Symbols style, zero emojis), deep aerial wallpaper integration, and practical Windows system administration utilities.

---

## Key Features & Modules

1. **Widget Screen (Home)**: Full-viewport liquid-glass home that always fits the window (no scroll bar), with immersive full screen (F11 / Esc). Background slideshow with crossfade from images or folders on your PC, an image URL, or an online feed that loads a new photo on every slide (default: picsum.photos). Widgets: working music player (files, folders, drag-and-drop, stream URLs, shuffle/repeat, live spectrum), live weather (Open-Meteo, no API key), calendar, focus timer, tasks (shared with Notes & Tasks), auto-saved notes, system gauges, world clocks and a quick-launch dock. Widgets can be shown/hidden individually, or hidden all at once with Focus mode.
2. **Command Center (Dashboard)**: Real-time CPU & RAM performance graphs, active task previews, volume meters, quick actions, and a live operations terminal.
3. **My Computer**: Hardware profile, CPU architecture, memory allocation, and storage partitions.
4. **Disk Analyzer**: Recursive folder size calculation, extension distribution metrics, top consuming files, and CSV export.
5. **Disk Cleaner**: Non-destructive analysis of transient files (`%TEMP%`, thumbnail cache, crash dumps) with Recycle Bin protection and explicit confirmation modals.
6. **Folder Organizer**: Heuristic rule-based categorization (Documents, Media, Code, Archives), dry-run previews, conflict resolution (`_1` suffix), and 1-click **Undo Revert**.
7. **File Explorer**: Clean modern file browser with breadcrumbs, vector icons, drive navigation, and launch integration.
8. **Duplicate Finder**: Two-pass size filtering + cryptographic **SHA-256** hash verification, reference copy preservation, and safe pruning.
9. **Large File Finder**: Instant heavy storage discovery with presets (50MB, 100MB, 500MB, 1GB, 5GB) and CSV export.
10. **Process Manager**: Real-time Windows task inspector with PID search, CPU/RAM sorting, and protected system process shields (blocking accidental termination of critical Windows kernel processes).
11. **Startup Manager**: Inspection and management of Windows Registry (`HKCU`/`HKLM` Run keys) and Startup folder programs with backup recovery.
12. **System Monitor**: Real-time multi-core CPU matrix, memory usage breakdown, and historical trend lines with selectable sampling rates (1s, 1.5s, 3s).
13. **Network Monitor**: Active NIC adapter states, IPv4 addresses, and real-time upload/download throughput meters.
14. **Clock & Calendar**: Modern digital clock, calendar, stopwatch, and countdown timers.
15. **Notes & Tasks**: Persistent local SQLite task manager with priority tags and memo scratchpad.
16. **Application Launcher**: Searchable shortcut matrix for Windows utilities and custom executables.
17. **Automation Center**: Rule-based scheduled tasks, low disk alerts, and maintenance watchdogs.
18. **Operation History**: Full audit trail of every scanned, moved, or cleaned item with CSV export.
19. **Settings**: Theme presets, accent customization, refresh frequency, and safety safeguards.

---

## App-wide Experience

- Every tool page sits on a blurred, darkened copy of the current Home wallpaper (liquid-glass look); darkness is adjustable in Settings.
- System tray icon with Windows notifications (automations, alarms); optional "keep running in the tray" mode.
- Settings apply instantly: telemetry rate, side panel, sidebar, Home full screen on launch, slideshow options, launch at Windows sign-in.
- Automation Center rules really run (low disk, high RAM, low battery, Downloads tidiness, temp space, hardware snapshot) and only measure + notify.
- Clock & Calendar: world clocks, stopwatch with laps, countdown with presets, alarms with snooze.

## Safety & Reliability Built-in

- **Non-Destructive Dry Runs**: Analysis and preview passes never delete or modify files without explicit user action.
- **Recycle Bin Preference**: Deletions prefer `send2trash` so files can be restored via Windows Recycle Bin.
- **Protected System Paths**: Scanning and destructive tools block Windows system directories (`C:\Windows`, `System32`, `Program Files`, etc.).
- **Protected Process Shields**: Critical kernel processes (`csrss.exe`, `svchost.exe`, `explorer.exe`, etc.) are protected against termination.
- **Non-Blocking GUI**: All heavy filesystem operations and SHA-256 computations execute in background `QThread` workers.

---

## 🚀 Installation & Quick Start

### 1. Requirements
- Windows 10 or Windows 11
- Python 3.10+ (tested on Python 3.12, 3.14)

### 2. Setup Virtual Environment (Optional but recommended)
```cmd
python -m venv venv
venv\Scripts\activate
```

### 3. Install Dependencies
```cmd
pip install -r requirements.txt
```

### 4. Launch CYBEROPS
Double-click `run.bat` or run:
```cmd
python main.py
```

---

## 🧪 Running Unit Tests

The test suite covers folder reorganization, dry-run simulation, undo restore, cryptographic duplicate matching, and safety shields:

```cmd
python -m unittest discover tests
```

---

## 📦 Packaging as an Executable (PyInstaller)

To build a standalone `.exe` without requiring Python to be installed on target machines:

```cmd
pip install pyinstaller
pyinstaller --noconsole --name "CyberOps" --add-data "app;app" main.py
```
The resulting executable will be generated in `dist/CyberOps/`.

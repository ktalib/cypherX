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

## Smart Home & Power

- 3D model of the flat with live load per room, inverter capacity, battery runtime and daily cost at your tariff. Click an appliance to switch it.
- **Prepaid meter tracker**: log each token you buy and type in the meter's "units left" now and then. CypherX works out your real kWh per day, the units left now, how many days until the meter runs out, and the average price you pay per kWh.
- **Battery readings**: log the charge % and / or voltage shown on the inverter or charge controller; the % updates the runtime estimate.
- **Power-cut logging**: plug the laptop charger into a socket that is *not* on the inverter and tick "Detect power cuts". When the charger loses power CypherX logs an outage, notifies you and switches the power source to the inverter; hours without grid are totalled per day and week.
- All entries are in the Energy log (with delete for typos) and stored in `smart_home_energy.json`, separate from the 3D layout.

## Sign-in, roles and the sidebar

- CYPHER-X opens with a sign-in screen. First run: **admin / admin** with **root** access. Change it in **Settings → Accounts** (the app keeps reminding until you do). Passwords are stored as salted PBKDF2 hashes; five wrong tries lock the sign-in for 30 seconds.
- **Lock** with the padlock at the bottom of the sidebar, **Ctrl+L**, or the tray menu. Any account can unlock; the app follows whoever signs in.
- The sidebar has three collapsible groups:
  - **Smart Home** — Home Dashboard, Smart Home (3D), CCTV, Widget Screen
  - **Apps** — Notes & Tasks, Bills, Groceries, Clock & Calendar, App Launcher
  - **Server** — the PC the smart home runs on: Command Center, My Computer, monitors, process / startup managers, disk and file tools, automation, operation history. Collapsed by default and **root only**.
- Roles: **root** sees everything and manages users (add, reset password, remove — the last root can't be removed); **user** sees Smart Home and Apps.

## Bills

- Household bills with amount, frequency (monthly, weekly, quarterly, yearly, one-off), due day and category.
- Tiles: monthly total (yearly / quarterly / weekly bills converted to a monthly amount), split per person, paid this period with what's still to pay this month, and the next bill due. Overdue bills are flagged red; due within 3 days in amber.
- "Mark paid" applies to the current period, so a monthly bill is unpaid again next month. Monthly cost by category.

## Groceries

- Shopping lists with quantity × unit price, category, a budget (with % used and over-budget warning), and ticks for items in the basket.
- Prices are remembered: type an item you've bought before and its last price is filled in. Copy a list to start next week's shop with the same items.
- Spend by category; "Clear bought" removes ticked items.

## Home Dashboard

- One page for the whole smart home: a greeting with the home's status and quick actions (All off, Arm / Disarm, Bought token, 3D map).
- Tiles for live load against the inverter, battery charge and runtime, prepaid meter days left, and energy cost (now vs a usual hour, per day and month).
- Tap an appliance tile to switch it (same model as the 3D Smart Home page), load by room (click a room to fly the 3D map there), the last 24 h of grid supply with power cuts, meter units over two weeks, and a security card with the latest motion snapshot.
- The layout adapts to the window width: four columns, two columns or one.

## CCTV

- Live camera wall in the **CCTV** page: the PC webcam / USB cameras, or network CCTV cameras via their RTSP or HTTP stream URL (e.g. `rtsp://admin:password@192.168.1.50:554/stream1`). Double-click a feed to watch it alone.
- Motion detection per camera with a 1–10 sensitivity; every motion event saves a snapshot and appears in the event list (double-click to open).
- **Arm** to get a Windows notification on motion. Manual snapshots, manual recording and optional record-on-motion (local cameras), saved as MP4.
- Cameras only turn on when you press Start, or at launch when "Start with CypherX" is ticked. Snapshots and clips older than the retention period (default 14 days) are deleted automatically. Files are under `%LOCALAPPDATA%\CyberOps\cctv`.
- Needs QtMultimedia, which comes with the full `PySide6` package (not `PySide6-Essentials`).

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

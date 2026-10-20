# CYPHER-X — Liquid Glass Desktop Operations & Widget Center

CYPHER-X is a modern, macOS / iOS Sonoma-inspired desktop operations hub and widget dashboard built with **Python 3.12+** and **PySide6**. It features a translucent **Liquid Glass** aesthetic (inspired by [WidgetScreen](https://widgetscreen.app/)), pure vector SVG icons (Lucide / Apple SF Symbols style, zero emojis), deep aerial wallpaper integration, and practical Windows system administration utilities.

---

> Project status, delivered work, hardware notes and the roadmap: see [`Doc/PROGRESS.md`](Doc/PROGRESS.md).

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
- The home network sidebar has two collapsible groups:
  - **Smart Home** — Home Dashboard, Smart Home (3D), CCTV, Widget Screen
  - **Apps** — Notes & Tasks, Bills, Groceries, Clock & Calendar, App Launcher
- **Server** (root only) opens the **server console** for the PC the smart home runs on. It starts with a boot screen that runs real checks one by one — launching the server, verifying root access, system health (CPU / RAM / uptime), network connection (LAN address, internet reachability and latency), database (SQLite integrity check), storage (free space), updates (shows the installed version; no update server exists yet) and services (automations, cameras, grid watch). Warnings don't stop the boot; a failed root check does. Then the console opens with its own green sidebar — **Overview** (Command Center, My Computer, System / Network Monitor), **Processes & automation**, **Storage & files**, **Logs** — and a **Return to Home** button in the sidebar and in the "Server console" banner.
- Links between the two worlds just work: a server tool opened from the home network goes through the boot screen; a home page opened from the server switches back home.
- Roles: **root** sees everything and manages users (add, reset password, remove — the last root can't be removed); **user** sees Smart Home and Apps.

## Bills

- Household bills with amount, frequency (monthly, weekly, quarterly, yearly, one-off), due day and category.
- Tiles: monthly total (yearly / quarterly / weekly bills converted to a monthly amount), split per person, paid this period with what's still to pay this month, and the next bill due. Overdue bills are flagged red; due within 3 days in amber.
- "Mark paid" applies to the current period, so a monthly bill is unpaid again next month. Monthly cost by category.

## Groceries

- Shopping lists with quantity × unit price, category, a budget (with % used and over-budget warning), and ticks for items in the basket.
- Prices are remembered: type an item you've bought before and its last price is filled in. Copy a list to start next week's shop with the same items.
- Spend by category; "Clear bought" removes ticked items.

## Server features (Server → Services)

All background jobs run as services with status, uptime, restarts, logs, settings and a watchdog that restarts
anything that crashes (5 s, 15 s, 60 s, then every 5 min).

- **Web dashboard** — turn it on, then open `http://<this PC's IP>:8080` on a phone on the same Wi-Fi and sign in
  with your CYPHER-X account: live load, battery, grid, meter (add readings / tokens), tap-to-switch appliances,
  arm / disarm, the latest camera picture, bills and the shopping list; root also sees server stats and services.
  It is built like a phone app (bottom tabs, device tiles, light / dark theme) and can be added to the home screen
  (browser menu → *Add to Home screen*); on a tablet or PC the tabs move to a side rail.
  It won't start while admin still has the default password. Windows Firewall asks once — allow Private networks.
  Don't forward the port on your router.
- **Telegram bot** — create a bot with @BotFather, paste the token, Start, press *Pair a chat* and send the code to
  the bot. Alerts: motion with the photo (when armed), power cut / back, meter running low, service restarts,
  new Wi-Fi devices, failed backups. Commands: `/status /devices /on <name> /off <name> /alloff /units /arm
  /disarm /snapshot`.
- **Network watch** — the **Wi-Fi Devices** page lists every device on the network (IP, MAC, name, maker where
  certain), lets you name and trust them, and alerts when an unknown device joins.
- **Backups** — every night (default 02:30, or as soon as the PC is on), keeps the last 7, optional camera
  snapshots, any folder (an external drive or a synced folder is safest). *Restore from a backup…* saves the
  current state first and restarts CYPHER-X.

## Smart Devices (auto-discovery)

The **Smart Devices** page (Smart Home group) finds smart plugs, sockets, bulbs and switches on the Wi-Fi by
themselves — press **Start discovery**:

- **Tuya / Smart Life** (most plugs sold locally, including the Tuya 20A plugs): listens for the broadcasts every
  Tuya device sends on UDP 6666 / 6667 (protocol 3.1, 3.3 and 3.4/3.5). Found within ~10 s, no cloud needed.
- **TP-Link Kasa**: UDP 9999 discovery. **Shelly, ESPHome, Sonoff DIY, HomeKit, Google Cast, Hue, WLED**: mDNS.
  **Shelly / Tasmota**: checked on devices from the Wi-Fi scan.
- Name each device and pick the appliance plugged into it (one plug per appliance); the Smart Home list shows
  "smart plug linked". New devices raise an alert (tray + Telegram) and are labelled on the Wi-Fi Devices page.
- Requirements: pair the device in its own app first, keep it on the same 2.4 GHz Wi-Fi as the PC (not a guest
  network), allow CYPHER-X through Windows Firewall on Private networks. `cryptography` and `zeroconf` (in
  requirements.txt) enable Tuya 3.3+ and mDNS.
- **Control + live power**: a linked plug is switched for real whenever its appliance is switched — in the app,
  the 3D view, the web dashboard or Telegram — and the *Smart plug control* service reads it every 5 s. Measured
  watts replace the rated watts in the live load, battery runtime and cost (shown as "146 W live").
  - Shelly, Tasmota and TP-Link Kasa work straight away (no key).
  - Tuya / Smart Life needs each plug's **local key**: press **Import Tuya keys…** (one-time, free Tuya IoT
    developer account linked to your Smart Life app — the dialog walks you through it), or paste a key with
    *Set local key…*. Keys for plugs not seen yet are kept and applied when they show up. Needs `tinytuya`.

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
- **A phone as a camera**, two ways:
  - *With a camera app* — run **IP Webcam** (Android) or **DroidCam** on the phone, then **Add camera → Phone camera app** and type the phone's IP. Best for a spare phone left in place: full video, keeps running with the screen off.
  - *With no app* — open the dashboard's secure address (`https://<this PC's IP>:8443`, shown under Server → Services → Web dashboard) on the phone, accept the one-time certificate warning, then **Security → Use this phone as a camera**. The phone sends about 2–3 pictures a second; motion detection, snapshots and alerts work as for any camera (no recording). Keep the page open.

## Fridge (a fridge that isn't smart)

- **Smart Home → Fridge** keeps count of what's inside: eggs, drinks, anything you track.
- **Counts come from:** ticking items as bought in Groceries (a crate = 30 eggs; set pack sizes and
  grocery names per item), a **photo checked by AI**, −/+ taps (desktop, phone dashboard) and Telegram
  (`/took 2 eggs`, `/add 6 beer`, `/fridge`).
- It learns how fast each item goes, shows an estimate between photos and "runs out in N days".
  When something runs low you get a notification and a Telegram alert, and it goes on the shopping list.
- **Photo check:** phone dashboard → Fridge → *Check with a photo*, send the photo to the Telegram bot,
  pick a file on the PC, or use a live CCTV camera.
- **Fridge → AI settings** — pick who counts the photo, with an optional backup if the first fails:
  - Free: **Google Gemini** (free key from aistudio.google.com), **OpenRouter** (free models),
    **Groq** (free tier), **Ollama** on this PC (offline, no key; `ollama pull qwen2.5vl:7b`).
  - Paid: **Claude** (most accurate; `pip install anthropic`), **OpenAI**.
  - Any OpenAI-compatible server (LM Studio, vLLM…), or **no AI**: photos are kept and you correct by hand.
  - Keys stay on this PC. **Test** checks the connection.
- **Optional fridge camera:** an ESP32-S3 camera board inside the fridge counts by itself each time the door opens
  (and warns if the door is left open). Firmware and fitting tips in [`firmware/fridge_cam`](firmware/fridge_cam/README.md);
  turn it on in Server → Services → Fridge camera.

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

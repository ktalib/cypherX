# CYPHER-X — Progress Report

_Last updated: 19 October 2026_

CYPHER-X started as a Windows "command center" desktop app (see [`initial.md`](initial.md)) and is becoming a
**smart home system with its own server console**. It runs on a Windows laptop at home and talks to the
home's power system, cameras and (soon) smart plugs.

---

## 1. Where we are

| Area | Status |
|---|---|
| Home network UI (Smart Home + Apps) | Built and merged |
| Sign-in, roles, lock | Built and merged |
| Server console with boot checks | Built and merged ([#5](https://github.com/ktalib/cypherX/pull/5)) |
| Server features: services + watchdog, web dashboard, Telegram bot, network watch, backups | Built, pushed — **pull request not opened yet** |
| Smart device discovery (Tuya, Kasa, Shelly, Tasmota, mDNS) + Smart Devices page | Built, pushed — pull request not opened yet |
| Smart plug control + live watts (Tuya, Shelly, Tasmota, Kasa) | Built, pushed — tested with simulated plugs; needs the real plugs |
| Inverter data | Waiting — check the back panel for a data port |
| Tested on the Windows laptop | **Not yet** — everything so far was tested on a Linux cloud machine |

**Codebase:** about 27,900 lines (Python / PySide6 + one HTML page for phones), 74 unit tests (73 pass — see §5).

---

## 2. Delivered

| # | Date | Pull request | What it added |
|---|---|---|---|
| 1 | 17 Oct | [#1](https://github.com/ktalib/cypherX/pull/1) | **Smart Home energy tracking** — prepaid meter tracker (tokens + readings → kWh/day, units left, days left, real ₦/kWh), battery readings from the inverter / charge controller display, power-cut logging through the laptop charger |
| 2 | 17 Oct | [#2](https://github.com/ktalib/cypherX/pull/2) | **CCTV** — live camera grid (PC webcam, USB, RTSP/HTTP network cameras), motion detection with sensitivity, snapshots, recording, arm/disarm alerts, auto-cleanup of old files |
| 3 | 17 Oct | [#3](https://github.com/ktalib/cypherX/pull/3) | **Home Dashboard** — one-page overview: live load, battery, meter, energy cost, tap-to-switch appliances, load by room, 24 h grid timeline, meter trend, security card; adapts to window width |
| 4 | 18 Oct | [#4](https://github.com/ktalib/cypherX/pull/4) | **Sign-in and roles** (admin/admin first run, root vs user, lock, account management), **sidebar regrouped** into Smart Home / Apps / Server, new **Bills** and **Groceries** apps |
| 5 | 19 Oct | [#5](https://github.com/ktalib/cypherX/pull/5) | **Server console** — Server button opens a boot screen with 8 real checks (launch, root access, system health, network, database, storage, updates, services), then a separate green server sidebar with a "Return to Home" button; this progress report |
| 6 | 19 Oct | _not opened yet_ (branch `claude/wizardly-turing-ahgl2u`) | **Server features (roadmap 1–5)** — service manager with watchdog and a Services page; **web dashboard** for phones on the Wi-Fi; **Telegram bot** (alerts + commands); **network watch** with a Wi-Fi Devices page and new-device alerts; **nightly backups** with restore |
| 7 | 19 Oct | _same branch, not opened yet_ | **Smart device discovery** — finds Tuya / Smart Life plugs, sockets, bulbs and switches from their broadcasts (protocol 3.1 / 3.3 / 3.5), TP-Link Kasa, Shelly / ESPHome / Sonoff / HomeKit via mDNS, Shelly / Tasmota via HTTP; **Smart Devices** page to name devices and link each to its appliance |
| 8 | 19 Oct | _same branch, not opened yet_ | **Smart plug control** — linked plugs switch for real from the app, 3D view, web dashboard and Telegram; live watts / volts read every 5 s replace the estimates; Tuya local keys by paste or **Import Tuya keys** from the Tuya cloud (once); drivers for Tuya (tinytuya), Shelly gen 1/2, Tasmota, TP-Link Kasa |

---

## 3. What the app does today

### Home network (everyone)
- **Home Dashboard** — the whole home at a glance; actions: All off, Arm/Disarm, Bought token, 3D map.
- **Smart Home** — 3D model of the flat (living room, kitchen, bedroom) built from room photos; click an appliance
  to switch it; live load per room vs inverter capacity; battery runtime; daily and monthly cost; prepaid meter,
  battery and grid cards.
- **CCTV** — live feeds, motion events with snapshots, recording, notifications when armed.
- **Widget Screen** — the liquid-glass home screen (music, weather, calendar, notes, clocks, wallpapers).
- **Apps** — Notes & Tasks, **Bills** (monthly total, split per person, paid per period, overdue/due-soon),
  **Groceries** (lists, budget, basket ticks, remembered prices), Clock & Calendar, App Launcher.

### Server console (root only)
- Boot screen with real checks (now 9, including backups) and a terminal log; warnings don't block, a failed
  root check does.
- Overview (Command Center, **Services**, My Computer, System Monitor, Network Monitor, **Wi-Fi Devices**),
  Processes & automation, Storage & files, Logs.

### Server features (services)
Every background job runs as a service on the **Services** page: status, uptime, restarts, Start / Stop / Restart,
start automatically, settings, actions and its own log. A **watchdog** restarts a crashed service after 5 s,
15 s, 60 s, then every 5 min.

| Service | What it does | On by default |
|---|---|---|
| Telemetry | CPU / RAM / disk / network samples for the monitors | Yes |
| Grid watch | Power-cut detection through the laptop charger | If it was on before |
| Camera monitoring | Runs every CCTV camera with motion detection | No |
| Automation scheduler | Automation Center rules | Yes |
| **Web dashboard** | `http://<server-ip>:8080` on any phone on the Wi-Fi — Home (load, battery, grid, meter, tap-to-switch, meter readings / tokens), Security (arm, camera picture), Money (bills, groceries), Server (root) | No — and it **won't start while admin has the default password** |
| **Telegram bot** | Alerts: motion with photo, power cut / back, meter low, service restarts, new Wi-Fi devices, backup failures. Commands: `/status /devices /on /off /alloff /units /arm /disarm /snapshot`. Pair with a one-time code | No — needs a bot token from @BotFather |
| **Network watch** | Finds every device on the Wi-Fi (IP, MAC, name, maker where certain), remembers them, alerts on new ones | No |
| **Backups** | Nightly zip of the database and settings (optionally snapshots), keeps 7, restore in one click | Yes |

### Accounts and safety
- Sign-in screen; passwords stored as salted PBKDF2 hashes; 5 wrong tries → 30 s lockout.
- Lock with the sidebar padlock, **Ctrl+L** or the tray menu.
- Root manages users; the last root account can't be removed; clearing the audit log is root-only.

---

## 4. Hardware status

| Device | Can the app read it? | Plan |
|---|---|---|
| Tuya 20A smart plugs (being bought) | **Discovery + control built** — found from their Wi-Fi broadcasts; switched and read locally once each plug's key is imported | When they arrive: pair in Smart Life → Start discovery → Import Tuya keys → link to appliances → check real watts |
| Ikeja Electric prepaid meter (split meter) | No data port | Manual tracker built (tokens + readings). Optional: Tuya clamp meter fitted by an electrician after the meter |
| Solar charge controller (PWM) | Probably no data port | Manual battery readings built. Optional: Bluetooth battery monitor (shunt) |
| Invertek Mega+ inverter | Unknown | **Open question:** check the back panel for a USB / RS232 / RJ45 "COM" port |
| Laptop charger | Yes — used for power-cut detection | Needs testing on the laptop (charger in a grid-only socket) |
| PC webcam | Yes | Used for the CCTV demo; real cameras should support RTSP/ONVIF |

---

## 5. Testing

- **Unit tests:** 74 (energy log 9, smart device discovery 9, plug control 8, CCTV 7, network watch + backups 7,
  accounts/bills/groceries 6, service manager 6, Telegram 6, server checks 5, web dashboard 5, original 6). 73 pass. The one failure, `test_protected_directory_detection`, predates this work and only fails when the
  tests run on Linux (`C:\Windows` isn't an absolute path there).
- **App checks:** each feature was run headless on a Linux cloud machine with sample data and screenshotted —
  layouts, navigation between Home and Server, sign-in, roles, lock, motion detection with synthetic frames.
  The web dashboard was driven in a real browser (Chromium, phone size): sign-in, switching an appliance (the
  desktop updated), a meter reading, all four tabs. Telegram was tested against a fake Telegram server
  (this cloud machine can't reach the real one). Smart device discovery was tested with hand-built Tuya
  broadcasts (all three formats) sent to the real UDP ports, and a fake Kasa plug answering on UDP. Plug control
  was tested end to end with a simulated Tuya plug: switching from the Smart Devices card, the web API and a
  Telegram command each switched the plug, and its measured watts replaced the rated watts in the load.
- **Not tested yet (needs the Windows laptop):** real webcam, recording, RTSP streams, charger-based power-cut
  detection, Windows notifications, the registry-based Startup Manager, everything at real screen sizes, the web
  dashboard from a real phone (Windows Firewall will ask once — allow Private networks), the real Telegram bot,
  a network scan of the real Wi-Fi.

Run the tests:

```cmd
python -m unittest discover tests
```

---

## 6. Known issues and to-dos

- **Change the default admin password** after the first sign-in (the app shows a reminder until you do).
- **No password recovery** — if the only root password is lost, restore a backup from before the change
  (Backups → Restore), or delete `cyberops.db` (loses tasks, notes, bills and groceries).
- The web dashboard is plain HTTP on the home network (fine at home; don't forward port 8080 on the router).
- The "Checking for updates" step only reports the installed version — there is no update server yet (roadmap #12).
- The Command Center page is wider than the space at the default window size (pre-existing).
- The repo still tracks downloaded wallpapers, old `__pycache__` files, `battery-report.html` and `qtawesome.whl`.
- Name mix: README says CYPHER-X, `config.py` / `run.bat` / window title say CYBEROPS.

---

## 7. Roadmap — real server features

Proposed on 19 October. **1–5 are built** (§3, "Server features"); the rest are next, in this order.

### Done
1. ~~Web dashboard on the home Wi-Fi~~ 2. ~~Telegram bot~~ 3. ~~Service manager + watchdog~~
4. ~~Network scanner + new-device alerts~~ 5. ~~Automatic backups~~

### Power-aware and local
6. Power-saving mode on battery (slower telemetry, pause non-essential recording, delay backups).
7. Internet uptime log + data-bundle tracker (MTN / Airtel / Glo) + occasional speed test.
8. Status page with uptime history for internet, router, cameras and plugs.

### Security
9. Sign-in history and active sessions. 10. Two-step login (2FA) for root. 11. API keys with an audit log.

### Admin tools
12. Real update checks from GitHub releases. 13. Live system log viewer. 14. 7-day health history with alerts.
15. Wake-on-LAN. 16. Shared folder for phones on the Wi-Fi.

---

## 8. Next steps

1. Open and merge the pull request for the server features (item 6 in §2).
2. On the Windows laptop: change the admin password, then turn on the Web dashboard and open it on a phone;
   create a Telegram bot with @BotFather and pair it; run a network scan; check webcam / CCTV, power-cut
   detection and notifications.
3. Check the inverter's back panel for a data port.
4. When the Tuya plugs arrive: pair them in Smart Life, `pip install -r requirements.txt`, Start discovery on
   Smart Devices, Import Tuya keys, link each plug to its appliance, then check switching and real watts.
5. Continue the roadmap: 6 (power-saving on battery), 7 (internet uptime + data bundle), 8 (status page).

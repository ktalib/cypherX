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
| Server console with boot checks | Built — in review as [#5](https://github.com/ktalib/cypherX/pull/5) |
| Real hardware (smart plugs, inverter data) | Not started — waiting on hardware |
| Tested on the Windows laptop | **Not yet** — everything so far was tested on a Linux cloud machine |

**Codebase:** about 22,000 lines of Python (PySide6 / Qt), 33 unit tests (32 pass — see §5).

---

## 2. Delivered

| # | Date | Pull request | What it added |
|---|---|---|---|
| 1 | 17 Oct | [#1](https://github.com/ktalib/cypherX/pull/1) | **Smart Home energy tracking** — prepaid meter tracker (tokens + readings → kWh/day, units left, days left, real ₦/kWh), battery readings from the inverter / charge controller display, power-cut logging through the laptop charger |
| 2 | 17 Oct | [#2](https://github.com/ktalib/cypherX/pull/2) | **CCTV** — live camera grid (PC webcam, USB, RTSP/HTTP network cameras), motion detection with sensitivity, snapshots, recording, arm/disarm alerts, auto-cleanup of old files |
| 3 | 17 Oct | [#3](https://github.com/ktalib/cypherX/pull/3) | **Home Dashboard** — one-page overview: live load, battery, meter, energy cost, tap-to-switch appliances, load by room, 24 h grid timeline, meter trend, security card; adapts to window width |
| 4 | 18 Oct | [#4](https://github.com/ktalib/cypherX/pull/4) | **Sign-in and roles** (admin/admin first run, root vs user, lock, account management), **sidebar regrouped** into Smart Home / Apps / Server, new **Bills** and **Groceries** apps |
| 5 | 19 Oct | [#5](https://github.com/ktalib/cypherX/pull/5) (open) | **Server console** — Server button opens a boot screen with 8 real checks (launch, root access, system health, network, database, storage, updates, services), then a separate green server sidebar with a "Return to Home" button |

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
- Boot screen with real checks and a terminal log; warnings don't block, a failed root check does.
- Overview (Command Center, My Computer, System Monitor, Network Monitor), Processes & automation,
  Storage & files, Logs — the original PC tools, now separated from the home screens.

### Accounts and safety
- Sign-in screen; passwords stored as salted PBKDF2 hashes; 5 wrong tries → 30 s lockout.
- Lock with the sidebar padlock, **Ctrl+L** or the tray menu.
- Root manages users; the last root account can't be removed; clearing the audit log is root-only.

---

## 4. Hardware status

| Device | Can the app read it? | Plan |
|---|---|---|
| Tuya 20A smart plugs (being bought) | **Yes** — local Wi-Fi control + live watts via `tinytuya` | Next hardware step: link each plug to its appliance in the 3D view |
| Ikeja Electric prepaid meter (split meter) | No data port | Manual tracker built (tokens + readings). Optional: Tuya clamp meter fitted by an electrician after the meter |
| Solar charge controller (PWM) | Probably no data port | Manual battery readings built. Optional: Bluetooth battery monitor (shunt) |
| Invertek Mega+ inverter | Unknown | **Open question:** check the back panel for a USB / RS232 / RJ45 "COM" port |
| Laptop charger | Yes — used for power-cut detection | Needs testing on the laptop (charger in a grid-only socket) |
| PC webcam | Yes | Used for the CCTV demo; real cameras should support RTSP/ONVIF |

---

## 5. Testing

- **Unit tests:** 33 (energy log 9, CCTV 7, accounts/bills/groceries 6, server checks 5, original 6).
  32 pass. The one failure, `test_protected_directory_detection`, predates this work and only fails when the
  tests run on Linux (`C:\Windows` isn't an absolute path there).
- **App checks:** each feature was run headless on a Linux cloud machine with sample data and screenshotted —
  layouts, navigation between Home and Server, sign-in, roles, lock, motion detection with synthetic frames.
- **Not tested yet (needs the Windows laptop):** real webcam, recording, RTSP streams, charger-based power-cut
  detection, Windows notifications, the registry-based Startup Manager, everything at real screen sizes.

Run the tests:

```cmd
python -m unittest discover tests
```

---

## 6. Known issues and to-dos

- **Change the default admin password** after the first sign-in (the app shows a reminder until you do).
- **No password recovery** — if the only root password is lost, accounts can only be reset by deleting
  `cyberops.db`, which also deletes tasks, notes, bills and groceries. Automatic backups (roadmap #5) will fix this.
- The "Checking for updates" step only reports the installed version — there is no update server yet (roadmap #12).
- The Command Center page is wider than the space at the default window size (pre-existing).
- The repo still tracks downloaded wallpapers, old `__pycache__` files, `battery-report.html` and `qtawesome.whl`.
- Name mix: README says CYPHER-X, `config.py` / `run.bat` / window title say CYBEROPS.

---

## 7. Roadmap — real server features

Proposed on 19 October; **waiting for a pick** of which to build first.

### Top 5 (recommended order: 1 → 2 → 3)
1. **Web dashboard on the home Wi-Fi** — open `http://<laptop-ip>:8080` on a phone, same accounts; dashboard,
   switches, CCTV snapshots, meter tokens.
2. **Telegram bot** — alerts (motion with snapshot, power cut / back, meter low, battery low, server down) and
   commands (`/status`, `/snapshot`, `/alloff`, `/units`).
3. **Service manager + watchdog** — web, CCTV, grid watch, scheduler, telemetry, backups; status, uptime,
   start / stop / restart, auto-restart, per-service logs.
4. **Network scanner + new-device alerts** — every device on the Wi-Fi (name, IP, MAC, maker); Tuya plug discovery.
5. **Automatic backups** — nightly database / settings / snapshots, keep N copies, one-click restore.

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

1. Merge [#5](https://github.com/ktalib/cypherX/pull/5) (server console + this report).
2. Run the app on the Windows laptop and check: webcam / CCTV, power-cut detection, notifications, layouts.
3. Check the inverter's back panel for a data port.
4. Pick roadmap features to build (suggested: 1, 2, 3).
5. When the Tuya plugs arrive: pair them in the Smart Life app, get the local keys, then add plug support.

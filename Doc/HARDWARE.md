# CYPHER-X — Hardware guide

What to buy, what you already have, and how each device connects to CYPHER-X.
Last updated 22 Oct 2026.

---

## 1. What you already have

| Device | What CYPHER-X can do with it | Notes |
|---|---|---|
| **Invertek Mega+ 1500VA / 12V** (pure sine wave UPS) | No data port seen on the front, so it can't be read directly. **Measured with two smart plugs** (section 3) | Set **Inverter = 1200 W** in Smart Home → Power source (1500VA × 0.8) |
| **60A PWM solar charge controller** (12/24/36/48V, LCD, 2× USB) | No data port. Its USB sockets give **5V power only**, which is handy for the ESP32 boards | Battery % is still typed in by hand from its screen (Smart Home → Battery readings) |
| **Laptop charger** | Power-cut detection, as a fallback when there's no inverter input plug | Plug it into a socket that is *not* on the inverter |
| **Ikeja Electric prepaid meter** | No data port | Tokens and "units left" readings are typed in; CYPHER-X works out the rest |
| **PC webcam / phones** | CCTV cameras | Phones work through IP Webcam / DroidCam, or the phone dashboard's secure page |

Still to check (send photos): the **back and sides of the inverter** (any port marked COM, RS232,
USB, RJ45 or "Remote"?), the **battery label** (Ah, lead-acid/tubular or lithium), whether **solar panels**
are connected and their total watts, and whether the inverter feeds an **extension board** or the house wiring.

---

## 2. Shopping list

### Buy now

| # | Item | Qty | Search for | What it does |
|---|---|---|---|---|
| 1 | Wi-Fi smart plug **with energy monitoring** | 4 | "Tuya smart plug UK 13A energy monitoring" | Switch and measure the TV, decoder, fan and PC desk |
| 2 | Same plug, **16A** | 1 | "Tuya smart plug UK 16A energy monitoring" | The fridge: real power use, never switched off by "All off" |
| 3 | Same plug, **16A** | **2** | as above | **The inverter**: one on its grid input, one on its output (section 3) |
| 4 | ESP32-S3 N16R8 CAM (OV3660) | 1 | "ESP32-S3 N16R8 CAM OV3660" (about ₦20,000) | Fridge camera: counts the shelves when the door opens |
| 5 | Flat USB-C cable, 1 m | 1 | "flat USB-C cable 1m" | Powers the fridge camera through the door seal |
| 6 | 5V 2A USB charger | 1 | any phone charger | Fridge camera power (or use the charge controller's USB socket) |

**Total smart plugs: 7** (4 × 13A, 3 × 16A).

### Nice to have

| # | Item | Qty | Search for | Why |
|---|---|---|---|---|
| 7 | Wi-Fi camera with RTSP | 1–2 | "TP-Link Tapo C200" (indoor), "Tapo C320WS" (outdoor) | Proper 24/7 CCTV (CCTV → Add camera → Network camera) |
| 8 | Smart switch module for lights | 1 per light | "Tuya Wi-Fi mini smart switch **1 gang**" | Switch a light from the app; fits behind the wall switch |
| 9 | Wi-Fi repeater | 1 | "TP-Link RE200" | Only if the fridge camera's signal is weak |

### Don't buy yet

- **A battery monitor (shunt)** for true battery % and solar charging. Send the listing first so its data
  output (RS485 / UART / Wi-Fi) can be confirmed.
- **Anything to read the inverter** until the port question above is answered.
- **Smart bulbs, 2- or 3-gang wall switches.** CYPHER-X finds them but can't switch them yet.

### Before you pay

- **2.4 GHz Wi-Fi**, set up with the **Smart Life / Tuya Smart** app.
- **"Energy monitoring" / "power metering"** must be in the plug's description (otherwise no watts or volts).
- **UK 3-pin (Type G)** plug.
- **Not** Zigbee, Bluetooth-only or "needs hub".
- **Never** put an air conditioner or pumping machine on a 13A plug.

---

## 3. Measuring the inverter with two smart plugs

```
 wall socket (grid) ──[ plug IN ]──► inverter's mains input
                                      Invertek Mega+
 inverter's output socket ──[ plug OUT ]──► extension board ──► TV, fan, fridge…
```

| What CYPHER-X sees | What it means |
|---|---|
| **IN** answers and shows mains voltage (≥ 100 V) | Grid is **on** |
| **IN** stops answering (it lost power with the grid) while **OUT** still answers | **Power cut**. Logged, notified, Telegram alert with battery time left, power source switched to the inverter |
| Both stop answering | Wi-Fi problem, not a power cut (nothing is logged) |
| **OUT** watts | The **real load** on the inverter. Replaces the appliance estimate for the live load, battery runtime and "% of inverter" |
| **IN − OUT** watts (grid on) | Roughly what goes into **charging the battery** (shown on the Smart Home page and as a chip on the phone) |

CYPHER-X **only reads** these two plugs. It never switches them, and they get no on/off button, so it can
never cut your inverter.

### Set it up

1. Set both 16A plugs up in **Smart Life** on the 2.4 GHz Wi-Fi.
2. CYPHER-X → **Smart Devices** → **Start discovery**. Both appear. Click **Import Tuya keys** once so CYPHER-X
   can talk to them, and rename them "Inverter IN" and "Inverter OUT" (⋯ → Rename).
3. Plug **IN** into a **wall socket on the grid** (not on the inverter!) and plug the **inverter's mains cable into it**.
   On its card, **Plugged in → ⚡ Inverter input (grid → inverter)**.
4. Plug **OUT** into the **inverter's output socket** and the **extension board into it**.
   On its card, **Plugged in → ⚡ Inverter output (house load)**.
5. **Smart Home → Power source**: Inverter **1200 W**; Battery Wh = **battery Ah × 12**. For lead-acid / tubular
   batteries enter **half** of that, since they shouldn't be run below about 50%.
6. Check: the Smart Home page says "Measured at the inverter" under the live load, and the grid card says
   "Watching the inverter input plug". Switch the grid off at the breaker for a minute to see a power cut logged.

**Safety:** the Mega+ gives at most about 1200 W, and grid input (load + charging) stays well under 16A at 230V. Still:
use 16A plugs for these two, push them fully in, and don't chain extension boards. If the inverter is **wired into
the house** (no output socket), plug OUT can't be used. Use only plug IN (grid and charging), and the load stays an
estimate from the appliance plugs.

### Limits

- **Battery %** isn't measured by the plugs. It still comes from the readings you type in (and the estimate from
  them). A battery monitor (section 4) would fix that.
- **Solar charging** goes straight from the charge controller to the battery, so the plugs don't see it.
- "Charging" includes the inverter's own losses, so it reads a little high.

---

## 4. Later options

| Option | Gives | Effort |
|---|---|---|
| **Battery monitor with a shunt** on the battery cable | True battery %, solar + grid charging, exact hours left | Heavy DC wiring, best done by the inverter installer. Confirm the data output before buying |
| **Camera reading the inverter's screen** (spare phone or a 2nd ESP32-S3 CAM) | Whatever the LCD shows (battery %, load), read by the fridge AI every few minutes | No wiring; uses AI requests |
| **Inverter data port** (if the photos show one) | Everything the inverter knows | The right cable plus a small driver |

---

## 5. Device → CYPHER-X page

| Device | Where it shows up |
|---|---|
| Smart plugs (appliances) | Smart Devices → link to an appliance; Smart Home, phone dashboard, Telegram `/on` `/off` |
| Smart plugs (inverter IN / OUT) | Smart Devices → ⚡ roles; Smart Home grid and live load; phone chips; power-cut alerts |
| Tapo / RTSP cameras, phones | CCTV → Add camera |
| ESP32-S3 fridge camera | Server → Services → Fridge camera; results on the Fridge page ([firmware](../firmware/fridge_cam/README.md)) |
| Light switch modules (1-gang) | Smart Devices → link to the light |

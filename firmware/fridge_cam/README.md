# Fridge camera (ESP32-S3)

Optional. A small camera board inside the fridge lets CYPHER-X count the shelves
by itself every time the door opens. Without it, use a phone photo (phone dashboard → Fridge,
or send the photo to the Telegram bot).

**Board:** "ESP32-S3 N16R8 CAM" with an OV3660 (or OV2640) camera, about ₦20,000.

## Flash it

1. Arduino IDE → Boards Manager → install **esp32** by Espressif.
2. Open `fridge_cam.ino` and put your Wi-Fi name and password at the top.
3. Tools: Board **ESP32S3 Dev Module**, PSRAM **OPI PSRAM**, Flash Size **16MB**,
   USB CDC On Boot **Enabled**.
4. Upload, open the Serial Monitor at 115200. It prints the address to use, e.g.
   `http://192.168.1.40/capture`. Open that in a browser: you should see a picture.
   If the camera doesn't start, check the pin list at the top of the sketch against your board's pin sheet.

## Fit it

- **Power by cable, not battery.** Run a thin flat USB-C cable through the door seal to a
  phone charger outside. The seal closes over a flat cable without letting warm air in.
- **Where:** high on the inside wall or ceiling, looking down at the shelves. A bit of
  double-sided tape or a small 3D-printed bracket is enough.
- **Wi-Fi:** the fridge is a metal box. Check the "Wi-Fi signal (RSSI)" line in the serial
  monitor with the door shut: better than −75 is fine. If it's weaker, move the router or
  add a cheap repeater near the kitchen.
- **Fogging:** a camera that stays inside settles at fridge temperature and rarely fogs.
  If it does, a dab of anti-fog spray (as used for glasses) on the lens helps.
- The fridge's own light is the flash: the board only needs to see while the door is open.

## Connect it

CYPHER-X → **Server → Services → Fridge camera** → Settings: paste the address, Save, Start.
**Test the camera** shows the picture size and brightness. Then open the fridge: about
2 seconds later the shelves are counted (by the AI chosen in Fridge → AI settings) and the
Fridge page updates. To save AI requests it counts at most every 10 minutes (adjustable),
and it alerts you if the door stays open too long.

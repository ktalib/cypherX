// CYPHER-X fridge camera — ESP32-S3 (N16R8) camera board with an OV3660 / OV2640.
//
// Serves one picture at http://<board-ip>/capture. CYPHER-X (Server → Services →
// Fridge camera) asks for a picture every couple of seconds; when the fridge light
// comes on (door opened) it counts what's on the shelves with the fridge AI.
//
// Arduino IDE: install "esp32" by Espressif (Boards Manager), then
//   Board: "ESP32S3 Dev Module" · PSRAM: "OPI PSRAM" · Flash Size: "16MB"
//   USB CDC On Boot: "Enabled" (so the serial monitor works over USB-C)
// Fill in your Wi-Fi below, upload, open the serial monitor (115200) and copy
// the address it prints into CYPHER-X.
//
// NOT TESTED ON HARDWARE YET. The pins below are the common "ESP32-S3 WROOM CAM"
// layout (same as Espressif's CAMERA_MODEL_ESP32S3_EYE). If the camera doesn't
// start, compare them with your board's pin sheet.

#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>

const char *WIFI_SSID = "your-wifi-name";
const char *WIFI_PASS = "your-wifi-password";

#define PWDN_GPIO_NUM  -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM  15
#define SIOD_GPIO_NUM  4
#define SIOC_GPIO_NUM  5
#define Y9_GPIO_NUM    16
#define Y8_GPIO_NUM    17
#define Y7_GPIO_NUM    18
#define Y6_GPIO_NUM    12
#define Y5_GPIO_NUM    10
#define Y4_GPIO_NUM    8
#define Y3_GPIO_NUM    9
#define Y2_GPIO_NUM    11
#define VSYNC_GPIO_NUM 6
#define HREF_GPIO_NUM  7
#define PCLK_GPIO_NUM  13

WebServer server(80);

bool startCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM;
  c.pin_d1 = Y3_GPIO_NUM;
  c.pin_d2 = Y4_GPIO_NUM;
  c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM;
  c.pin_d5 = Y7_GPIO_NUM;
  c.pin_d6 = Y8_GPIO_NUM;
  c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM;
  c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM;
  c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM;
  c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM;
  c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_UXGA;       // 1600x1200: enough detail to count eggs
  c.jpeg_quality = 12;                 // 0–63, lower is better
  c.fb_count = 2;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;
  if (esp_camera_init(&c) != ESP_OK) return false;
  sensor_t *s = esp_camera_sensor_get();
  if (s && s->id.PID == OV3660_PID) {
    s->set_vflip(s, 1);                // OV3660 modules are usually mounted upside down
  }
  return true;
}

void handleCapture() {
  camera_fb_t *fb = esp_camera_fb_get();   // drop one frame: it may be from before the light came on
  if (fb) esp_camera_fb_return(fb);
  fb = esp_camera_fb_get();
  if (!fb) {
    server.send(503, "text/plain", "camera busy");
    return;
  }
  server.sendHeader("Cache-Control", "no-store");
  server.setContentLength(fb->len);
  server.send(200, "image/jpeg", "");
  server.client().write(fb->buf, fb->len);
  esp_camera_fb_return(fb);
}

void handleStatus() {
  String j = "{\"ok\":true,\"rssi\":" + String(WiFi.RSSI()) + ",\"uptime_s\":" + String(millis() / 1000) +
             ",\"free_psram\":" + String(ESP.getFreePsram()) + "}";
  server.send(200, "application/json", j);
}

void setup() {
  Serial.begin(115200);
  delay(500);
  if (!startCamera()) {
    Serial.println("Camera failed to start — check the pins at the top of this file.");
    delay(5000);
    ESP.restart();
  }
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting to Wi-Fi");
  for (int i = 0; WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
    Serial.print(".");
    if (i > 60) ESP.restart();             // 30 s without Wi-Fi: start over
  }
  Serial.println();
  server.on("/capture", handleCapture);
  server.on("/status", handleStatus);
  server.on("/", [] { server.send(200, "text/plain", "CYPHER-X fridge camera. Picture: /capture"); });
  server.begin();
  Serial.print("Ready. In CYPHER-X use:  http://");
  Serial.print(WiFi.localIP());
  Serial.println("/capture");
  Serial.print("Wi-Fi signal (RSSI): ");
  Serial.println(WiFi.RSSI());
}

void loop() {
  server.handleClient();
  if (WiFi.status() != WL_CONNECTED) {     // the fridge door is metal: Wi-Fi can drop, so reconnect
    WiFi.reconnect();
    delay(1000);
  }
}

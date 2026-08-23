/*
  F.R.I.D.A.Y. ESP32 Firmware
  ---------------------------
  Lets the FRIDAY backend dynamically configure pins at runtime, e.g.:
    "Hey FRIDAY, I just connected a gas sensor to pin 34"
  ...which FRIDAY turns into a POST /configure call to this board - no
  reflashing needed to add a new sensor/actuator.

  HTTP API (JSON):
    GET  /status                 -> { "34": {"name":"gas","type":"gas","mode":"analog","value":812}, ... }
    POST /configure  {pin, mode, type, name}   mode: "input"|"output"|"analog"|"pwm"
    POST /set        {pin, value}              drive an output/pwm pin

  OTA:
    Once connected to WiFi, this board accepts OTA firmware pushes via
    ArduinoOTA (Arduino IDE: Tools > Port > select the network port,
    or `platformio run -t upload --upload-port <esp32-ip>`).

  REQUIRED LIBRARIES (Arduino Library Manager):
    - ArduinoJson (by Benoit Blanchon)
    - ArduinoOTA (bundled with ESP32 board package)
    - Preferences (bundled with ESP32 board package)

  BOARD: "ESP32 Dev Module" (or your specific ESP32 board) in Arduino IDE.
*/

#include <WiFi.h>
#include <WebServer.h>
#include <ArduinoOTA.h>
#include <ArduinoJson.h>
#include <Preferences.h>

// ---------------------- USER CONFIG ----------------------
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* OTA_HOSTNAME  = "friday-esp32";
const char* OTA_PASSWORD  = "friday123";   // change this
const int   HTTP_PORT     = 80;
// -----------------------------------------------------------

WebServer server(HTTP_PORT);
Preferences prefs;

#define MAX_PINS 20

struct PinConfig {
  bool used = false;
  int pin = -1;
  String mode;   // input, output, analog, pwm
  String type;   // e.g. "gas", "temperature", "led", "relay"
  String name;   // friendly label
  int lastValue = 0;
  int pwmChannel = -1;
};

PinConfig pins[MAX_PINS];
int nextPwmChannel = 0;

// ---------------------- helpers ----------------------
int findPinConfig(int pin) {
  for (int i = 0; i < MAX_PINS; i++) {
    if (pins[i].used && pins[i].pin == pin) return i;
  }
  return -1;
}

int findFreeSlot() {
  for (int i = 0; i < MAX_PINS; i++) {
    if (!pins[i].used) return i;
  }
  return -1;
}

void applyPinMode(PinConfig &cfg) {
  if (cfg.mode == "input") {
    pinMode(cfg.pin, INPUT);
  } else if (cfg.mode == "output") {
    pinMode(cfg.pin, OUTPUT);
  } else if (cfg.mode == "analog") {
    // analog pins need no pinMode() on ESP32, analogRead() handles it
  } else if (cfg.mode == "pwm") {
    if (cfg.pwmChannel < 0) {
      cfg.pwmChannel = nextPwmChannel++;
    }
    ledcSetup(cfg.pwmChannel, 5000, 8); // 5kHz, 8-bit resolution
    ledcAttachPin(cfg.pin, cfg.pwmChannel);
  }
}

void saveConfigToFlash() {
  prefs.begin("friday", false);
  prefs.putInt("count", MAX_PINS);
  for (int i = 0; i < MAX_PINS; i++) {
    String key = String("p") + i;
    if (pins[i].used) {
      String packed = String(pins[i].pin) + "|" + pins[i].mode + "|" + pins[i].type + "|" + pins[i].name;
      prefs.putString(key.c_str(), packed);
    } else {
      prefs.putString(key.c_str(), "");
    }
  }
  prefs.end();
}

void loadConfigFromFlash() {
  prefs.begin("friday", true);
  for (int i = 0; i < MAX_PINS; i++) {
    String key = String("p") + i;
    String packed = prefs.getString(key.c_str(), "");
    if (packed.length() > 0) {
      int p1 = packed.indexOf('|');
      int p2 = packed.indexOf('|', p1 + 1);
      int p3 = packed.indexOf('|', p2 + 1);
      if (p1 > 0 && p2 > 0 && p3 > 0) {
        pins[i].used = true;
        pins[i].pin = packed.substring(0, p1).toInt();
        pins[i].mode = packed.substring(p1 + 1, p2);
        pins[i].type = packed.substring(p2 + 1, p3);
        pins[i].name = packed.substring(p3 + 1);
        applyPinMode(pins[i]);
      }
    }
  }
  prefs.end();
}

// ---------------------- HTTP handlers ----------------------
void handleStatus() {
  // Refresh readings first
  for (int i = 0; i < MAX_PINS; i++) {
    if (!pins[i].used) continue;
    if (pins[i].mode == "input") {
      pins[i].lastValue = digitalRead(pins[i].pin);
    } else if (pins[i].mode == "analog") {
      pins[i].lastValue = analogRead(pins[i].pin);
    }
    // output/pwm values reflect the last value we set, not re-read here
  }

  StaticJsonDocument<2048> doc;
  for (int i = 0; i < MAX_PINS; i++) {
    if (!pins[i].used) continue;
    JsonObject obj = doc.createNestedObject(String(pins[i].pin));
    obj["name"] = pins[i].name;
    obj["type"] = pins[i].type;
    obj["mode"] = pins[i].mode;
    obj["value"] = pins[i].lastValue;
  }
  String out;
  serializeJson(doc, out);
  server.send(200, "application/json", out);
}

void handleConfigure() {
  if (server.method() != HTTP_POST) { server.send(405, "text/plain", "POST only"); return; }
  StaticJsonDocument<512> doc;
  DeserializationError err = deserializeJson(doc, server.arg("plain"));
  if (err) { server.send(400, "text/plain", "bad json"); return; }

  int pin = doc["pin"] | -1;
  String mode = doc["mode"] | "input";
  String type = doc["type"] | "generic";
  String name = doc["name"] | ("pin" + String(pin));
  if (pin < 0) { server.send(400, "text/plain", "pin required"); return; }

  int slot = findPinConfig(pin);
  if (slot < 0) slot = findFreeSlot();
  if (slot < 0) { server.send(507, "text/plain", "no free pin slots"); return; }

  pins[slot].used = true;
  pins[slot].pin = pin;
  pins[slot].mode = mode;
  pins[slot].type = type;
  pins[slot].name = name;
  applyPinMode(pins[slot]);
  saveConfigToFlash();

  server.send(200, "application/json", "{\"ok\":true}");
}

void handleSet() {
  if (server.method() != HTTP_POST) { server.send(405, "text/plain", "POST only"); return; }
  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, server.arg("plain"));
  if (err) { server.send(400, "text/plain", "bad json"); return; }

  int pin = doc["pin"] | -1;
  int value = doc["value"] | 0;
  int slot = findPinConfig(pin);
  if (slot < 0) { server.send(404, "text/plain", "pin not configured"); return; }

  if (pins[slot].mode == "output") {
    digitalWrite(pin, value ? HIGH : LOW);
  } else if (pins[slot].mode == "pwm") {
    ledcWrite(pins[slot].pwmChannel, constrain(value, 0, 255));
  } else {
    server.send(400, "text/plain", "pin is not an output/pwm pin");
    return;
  }
  pins[slot].lastValue = value;
  server.send(200, "application/json", "{\"ok\":true}");
}

void handleRoot() {
  server.send(200, "text/plain", "F.R.I.D.A.Y. ESP32 node online. See /status");
}

// ---------------------- setup / loop ----------------------
void setup() {
  Serial.begin(115200);
  loadConfigFromFlash();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Connected. IP address: ");
  Serial.println(WiFi.localIP());

  // ---- OTA ----
  ArduinoOTA.setHostname(OTA_HOSTNAME);
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.onStart([]() { Serial.println("OTA update starting..."); });
  ArduinoOTA.onEnd([]() { Serial.println("OTA update complete."); });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    Serial.printf("OTA progress: %u%%\r", (progress / (total / 100)));
  });
  ArduinoOTA.onError([](ota_error_t error) {
    Serial.printf("OTA error[%u]\n", error);
  });
  ArduinoOTA.begin();

  // ---- HTTP routes ----
  server.on("/", handleRoot);
  server.on("/status", HTTP_GET, handleStatus);
  server.on("/configure", HTTP_POST, handleConfigure);
  server.on("/set", HTTP_POST, handleSet);
  server.begin();
  Serial.println("HTTP server started on port 80.");
  Serial.println("Set ESP32_IP in FRIDAY's .env to this board's IP above.");
}

void loop() {
  ArduinoOTA.handle();
  server.handleClient();
}

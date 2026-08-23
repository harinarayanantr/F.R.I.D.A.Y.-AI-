"""
Talks to the FRIDAY ESP32 firmware over HTTP on the local network.
The ESP32 runs a small webserver exposing:
    GET  /status              -> JSON of all configured pins/sensors
    POST /configure  {pin, mode, type, name}  -> define/relabel a pin
    POST /set        {pin, value}             -> drive an output pin
    (OTA updates handled on-device via ArduinoOTA, see esp32_firmware/)
"""
import threading
import time

import requests

from backend.config import settings
from backend.logger import log, push_event

_last_status: dict = {}
_lock = threading.Lock()


def base_url() -> str:
    return f"http://{settings.ESP32_IP}"


def get_status() -> dict:
    with _lock:
        return dict(_last_status)


def configure_pin(pin: int, mode: str, sensor_type: str, name: str) -> str:
    """mode: 'input' | 'output' | 'analog' | 'pwm'. sensor_type: free text label e.g. 'gas'."""
    try:
        r = requests.post(
            f"{base_url()}/configure",
            json={"pin": pin, "mode": mode, "type": sensor_type, "name": name},
            timeout=4,
        )
        r.raise_for_status()
        log(f"ESP32: configured pin {pin} as {mode} ({name}/{sensor_type})", channel="esp32")
        return f"Pin {pin} configured as {mode} for '{name}'. It will now appear on the dashboard."
    except Exception as e:
        log(f"ESP32 configure failed: {e}", level="error", channel="esp32")
        return f"Couldn't reach the ESP32 to configure the pin: {e}"


def set_pin(pin: int, value):
    try:
        r = requests.post(f"{base_url()}/set", json={"pin": pin, "value": value}, timeout=4)
        r.raise_for_status()
        return f"Set pin {pin} to {value}."
    except Exception as e:
        return f"Couldn't set pin {pin}: {e}"


def _poll_loop():
    while True:
        if settings.ESP32_ENABLED:
            try:
                r = requests.get(f"{base_url()}/status", timeout=3)
                if r.ok:
                    data = r.json()
                    with _lock:
                        _last_status.clear()
                        _last_status.update(data)
                    push_event("esp32_status", {"data": data})
            except Exception:
                pass  # ESP32 offline/unreachable - stay quiet, retry next cycle
        time.sleep(settings.ESP32_POLL_SECONDS)


def start_esp32_poller():
    if not settings.ESP32_ENABLED:
        log("ESP32 integration disabled (ESP32_ENABLED=false in .env).", channel="esp32")
        return
    log(f"Polling ESP32 at {settings.ESP32_IP} every {settings.ESP32_POLL_SECONDS}s", channel="esp32")
    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()

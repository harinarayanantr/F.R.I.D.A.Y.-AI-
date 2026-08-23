# F.R.I.D.A.Y. 🤖

> A personal AI assistant inspired by Tony Stark's FRIDAY — voice, vision, hardware, and a Groq-powered brain.

F.R.I.D.A.Y. is a fully-featured AI assistant that runs on your machine:

- 🧠 **Groq LLM brain** with tool-calling — controls your computer via natural language
- 🎙️ **Voice pipeline** — offline wake word ("Hey FRIDAY"), Whisper STT, natural TTS
- 👋 **Computer vision** — MediaPipe hand-gesture control and webcam face tracking
- 🔌 **ESP32 bridge** — talk to sensors/relays over WiFi, with OTA firmware updates
- 🖥️ **Arc-reactor HUD** — a web-based dashboard you can talk or type into

## Project Structure

```
friday-ai/
├── setup.sh                  # Run once — installs everything
├── start.sh                  # Run every time — brings FRIDAY up
├── .env.example              # Copy to .env and add your Groq key
├── requirements.txt
├── backend/
│   ├── main.py               # FastAPI server + orchestrator
│   ├── brain.py              # Groq LLM + tool-calling ("the brain")
│   ├── system_control.py     # Open apps, run shell cmds, files, browser
│   ├── voice/                # Wake word (Vosk) · STT (Groq Whisper) · TTS (edge-tts)
│   ├── vision/               # MediaPipe hand gestures + face tracking
│   ├── esp32/                # HTTP client for your ESP32 boards
│   └── hud/                  # Web-based Tony Stark style HUD (HTML/CSS/JS)
└── esp32_firmware/
    └── friday_esp32.ino      # Flash this to your ESP32
```

## Quick Start

### 1. Install

```bash
chmod +x setup.sh start.sh
./setup.sh
```

Installs system packages (portaudio, ffmpeg, cmake), creates a Python virtual
environment, installs all dependencies, and downloads the offline wake-word model.
It also creates `.env` from `.env.example`.

> **Windows:** run inside WSL2 (Ubuntu). For native Windows, install Python 3.11+,
> ffmpeg, and Build Tools for Visual Studio manually, then `pip install -r requirements.txt`.

### 2. Add your Groq API key

1. Get a free key at [console.groq.com/keys](https://console.groq.com/keys)
2. Set it in `.env`:

```env
GROQ_API_KEY=gsk_your_real_key_here
```

That's the only required key — voice, vision, and wake word all run locally.

### 3. Run

```bash
./start.sh
```

Opens the HUD at **http://localhost:8000**, starts listening for **"Hey FRIDAY"**,
and launches the webcam gesture/face tracker. Talk to her, or type into the HUD's
command box — both go through the same brain.

## Gestures

Default mapping (edit `GESTURE_*_ACTION` in `.env`):

| Gesture | Action |
|---|---|
| ☝️ 1 finger | Opens claude.ai |
| ✌️ 2 fingers | Opens the FRIDAY admin dashboard |
| 🤟 3 fingers | Opens YouTube |

Supported action formats: `open_url:<url>`, `open_app:<name>`, `run_command:<shell command>`.

## Face Recognition (optional)

By default FRIDAY *detects and tracks* faces. To recognize *named* people:

1. Uncomment `face_recognition==1.3.0` in `requirements.txt` and re-run `./setup.sh`
   (needs `cmake`/`dlib`, so it's off by default).
2. Drop a clear reference photo of each person into `friday_workspace/known_faces/`,
   named `their_name.jpg`.
3. Set `ENABLE_FACE_RECOGNITION=true` in `.env` and restart.

## ESP32 Integration

1. Open `esp32_firmware/friday_esp32/friday_esp32.ino` in the Arduino IDE.
2. Install the **ArduinoJson** library (Library Manager).
3. Set `WIFI_SSID` / `WIFI_PASSWORD` (and change `OTA_PASSWORD`) in the sketch.
4. Flash it — the Serial Monitor (115200 baud) shows the board's IP.
5. In `.env`: set `ESP32_ENABLED=true` and `ESP32_IP=<that IP>`, then restart.

Now just say:

> "Hey FRIDAY, I just connected a gas sensor to pin 34, show it on the dashboard."

FRIDAY configures the pin over HTTP — no reflashing needed. The reading appears as a
live card on the HUD.

**OTA updates:** after the first flash, push new firmware wirelessly via the Arduino
IDE (Tools → Port → `friday-esp32`) or PlatformIO — no USB cable needed.

## Shell Command Safety

FRIDAY asks for a `y/N` confirmation in the terminal before running any shell command.
Set `AUTO_CONFIRM_SHELL=true` in `.env` to skip confirmation (**not recommended** on
machines with sensitive data).

File writes/deletes through conversation are scoped to `friday_workspace/` unless an
explicit absolute path is given.

## Troubleshooting

| Problem | Fix |
|---|---|
| No sound / mic errors | Ensure `portaudio19-dev` installed; check OS mic permissions for terminal/Python |
| Wake word never triggers | Verify `backend/voice/model/vosk-model-small-en-us` exists; speak closer; say "hey friday" naturally |
| Camera feed blank in HUD | Try different `CAMERA_INDEX` values in `.env`; close apps holding the webcam |
| ESP32 cards never appear | Check `ESP32_ENABLED=true`, correct IP, and both devices on the same subnet |

## License

MIT — see [LICENSE](LICENSE).

---

*Yes, she'll call you "boss" occasionally.* 😎

F.R.I.D.A.Y.

An asynchronous, local AI assistant integrating real-time voice processing, computer vision, local automation, and Groq-powered LLM tool execution.

F.R.I.D.A.Y. operates as a distributed system designed for minimal latency and fully local execution of multi-modal streams:

    Groq LLM Engine: Executes structured tool-calling pipelines to interact directly with the host operating system via high-throughput function schemas.

    Audio Pipeline: Combines local wake-word activation (Vosk engine), speech recognition (Groq Whisper API), and real-time audio synthesis (Edge-TTS).

    Computer Vision Module: Implements MediaPipe pipelines for concurrent real-time hand-gesture classification and facial tracking via OpenCV.

    Hardware Telemetry (ESP32): Asynchronous HTTP client interface communicating with microcontrollers over local network protocols with OTA support.

    Web HUD Dashboard: FastAPI-driven web dashboard utilizing WebSockets for real-time telemetry rendering and dynamic system interaction.

Architecture Directory

friday-ai/
├── setup.sh                 # Environment setup and dependency bootstrapper
├── start.sh                 # System orchestrator startup script
├── .env.example             # Configuration settings template
├── requirements.txt         # Dependencies list
├── backend/
│   ├── main.py              # FastAPI server & asynchronous event loop
│   ├── brain.py             # Tool execution engine and Groq client interface
│   ├── system_control.py    # OS-level execution handlers (shell, FS, URL)
│   ├── voice/               # Vosk wake-word, Whisper STT, and Edge-TTS modules
│   ├── vision/              # MediaPipe gesture detection and face processing
│   ├── esp32/               # Microcontroller REST interface client
│   └── hud/                 # Static HUD web assets (HTML/CSS/JS)
└── esp32_firmware/
    └── friday_esp32.ino     # C++ microcontroller firmware

Setup & Deployment
1. Installation

Execute the bootstrapper script to install system dependencies (portaudio, ffmpeg, cmake), configure the Python virtual environment, download the Vosk acoustic model, and initialize configuration files:
Bash

chmod +x setup.sh start.sh
./setup.sh

2. Configuration & Safety Settings

Obtain an API key from console.groq.com and configure your .env file:
Code snippet

GROQ_API_KEY=gsk_your_actual_key_here
AUTO_CONFIRM_SHELL=true

Important Deployment Note regarding Command Approvals:
The WebSocket-based interactive permission modal within the HUD is currently undergoing optimization and may cause execution delays during headless autostart. For consistent operation, set AUTO_CONFIRM_SHELL=true in your .env file to bypass manual terminal prompts.

3. System Launch

Start the system stack:
Bash

./start.sh

Access the HUD interface at http://localhost:8000. The system concurrently initializes audio capture streams and webcam gesture processing loops.
Input Systems
Gesture Mappings

Configure mappings via .env settings:
Gesture	Default Command
1 Finger	open_url:[https://claude.ai](https://claude.ai)
2 Fingers	Opens Admin Dashboard
3 Fingers	open_url:[https://youtube.com](https://youtube.com)

Action structure syntax: open_url:<url>, open_app:<name>, run_command:<cmd>.
Face Recognition Pipeline

    Uncomment face_recognition==1.3.0 in requirements.txt and execute ./setup.sh.

    Save reference images (person_name.jpg) into friday_workspace/known_faces/.

    Set ENABLE_FACE_RECOGNITION=true in .env.

ESP32 Hardware Integration

    Flash esp32_firmware/friday_esp32/friday_esp32.ino via Arduino IDE (requires ArduinoJson).

    Retrieve the board IP from the Serial Monitor (115200 baud).

    Update .env with ESP32_ENABLED=true and ESP32_IP=<BOARD_IP>.

Pins can be configured dynamically through natural language tool calls without reflashing. OTA updates are supported on the local network subnet.
Troubleshooting
Issue	Resolution
Audio Input Error	Verify portaudio19-dev installation and system ALSA/PulseAudio input access
Wake Word Inactive	Verify path backend/voice/model/vosk-model-small-en-us
Camera Frame Failure	Check index assignment via CAMERA_INDEX in .env
Hardware Timeout	Ensure host and ESP32 board share identical network subnets
License

Distributed under the MIT License. See LICENSE for details.
*Coded using AI. May contain errors. Use with caution.

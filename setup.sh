#!/usr/bin/env bash
# ============================================================
# F.R.I.D.A.Y. setup script
# Installs system packages, creates a Python venv, installs
# Python deps, and downloads the offline wake-word model.
# ============================================================
set -e

BOLD='\033[1m'; ORANGE='\033[38;5;208m'; GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
say() { echo -e "${ORANGE}${BOLD}[FRIDAY SETUP]${NC} $1"; }
ok()  { echo -e "${GREEN}✓${NC} $1"; }
err() { echo -e "${RED}✗${NC} $1"; }

say "Booting setup sequence for F.R.I.D.A.Y. ..."
cd "$(dirname "$0")"

OS="$(uname -s)"

# ---------------------------------------------------------------- system deps
say "Installing system dependencies (audio, video, build tools)..."
if [ "$OS" = "Linux" ]; then
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y \
      python3 python3-venv python3-pip \
      portaudio19-dev libasound2-dev \
      ffmpeg \
      libatlas-base-dev \
      cmake build-essential \
      libgl1 \
      unzip curl git
  else
    err "Non-apt Linux detected. Please manually install: python3, portaudio dev headers, ffmpeg, cmake, build tools."
  fi
elif [ "$OS" = "Darwin" ]; then
  if command -v brew >/dev/null 2>&1; then
    brew install python portaudio ffmpeg cmake
  else
    err "Homebrew not found. Install it from https://brew.sh then re-run this script."
    exit 1
  fi
else
  err "Unsupported OS: $OS. On Windows, use WSL2 (Ubuntu) and re-run this script there."
  exit 1
fi
ok "System dependencies installed."

# ---------------------------------------------------------------- python venv
say "Creating Python virtual environment (.venv)..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel setuptools
ok "Virtual environment ready."

say "Installing Python packages from requirements.txt (this can take a few minutes)..."
pip install -r requirements.txt
ok "Python packages installed."

# ---------------------------------------------------------------- wake word model
WAKE_DIR="backend/voice/model"
WAKE_MODEL="vosk-model-small-en-us"
if [ ! -d "$WAKE_DIR/$WAKE_MODEL" ]; then
  say "Downloading offline wake-word model (Vosk, ~40MB)..."
  mkdir -p "$WAKE_DIR"
  curl -L -o /tmp/vosk-model.zip "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip" || {
    err "Download failed - you can grab it manually from https://alphacephei.com/vosk/models"
    err "and unzip it into $WAKE_DIR/$WAKE_MODEL"
  }
  if [ -f /tmp/vosk-model.zip ]; then
    unzip -q -o /tmp/vosk-model.zip -d /tmp/vosk-extract
    mv /tmp/vosk-extract/vosk-model-small-en-us-0.15 "$WAKE_DIR/$WAKE_MODEL"
    rm -rf /tmp/vosk-model.zip /tmp/vosk-extract
    ok "Wake-word model installed."
  fi
else
  ok "Wake-word model already present."
fi

# ---------------------------------------------------------------- .env
if [ ! -f ".env" ]; then
  cp .env.example .env
  say "Created .env from .env.example - EDIT IT NOW and add your GROQ_API_KEY."
else
  ok ".env already exists, leaving it untouched."
fi

mkdir -p friday_workspace
chmod +x start.sh 2>/dev/null || true

echo ""
echo -e "${GREEN}${BOLD}============================================================${NC}"
echo -e "${GREEN}${BOLD} F.R.I.D.A.Y. setup complete.${NC}"
echo -e "${GREEN}${BOLD}============================================================${NC}"
echo ""
echo "NEXT STEPS:"
echo "  1. Get a free Groq API key:  https://console.groq.com/keys"
echo "  2. Open .env and set GROQ_API_KEY=..."
echo "  3. (Optional) Flash esp32_firmware/friday_esp32/friday_esp32.ino to your"
echo "     ESP32 with the Arduino IDE, set its WiFi creds in the sketch, then"
echo "     put its IP into .env as ESP32_IP and set ESP32_ENABLED=true."
echo "  4. Run:  ./start.sh"
echo ""

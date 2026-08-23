#!/usr/bin/env bash
# ============================================================
# Launches F.R.I.D.A.Y. Run ./setup.sh once before using this.
# ============================================================
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "No .venv found - run ./setup.sh first."
  exit 1
fi

if [ ! -f ".env" ]; then
  echo "No .env found - run ./setup.sh first, then edit .env with your GROQ_API_KEY."
  exit 1
fi

source .venv/bin/activate

echo ""
echo "  _____ ____  ___ ____    _ __   __"
echo " |  ___|  _ \\|_ _|  _ \\  / \\\\ \\ / /"
echo " | |_  | |_) || || | | |/ _ \\\\ V / "
echo " |  _| |  _ < | || |_| / ___ \\| |  "
echo " |_|   |_| \\_\\___|____/_/   \\_\\_|  "
echo ""
echo " Booting up... HUD will open at http://localhost:8000"
echo " Say \"Hey FRIDAY\" once she's listening, or type in the HUD."
echo " Press Ctrl+C to shut down."
echo ""

export PYTHONUNBUFFERED=1
python -m backend.main

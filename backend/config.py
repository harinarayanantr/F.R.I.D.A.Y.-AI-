"""
Central configuration for FRIDAY. Loads .env and exposes typed settings.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _str(name: str, default: str = "") -> str:
    """Raw string env value: strips whitespace/surrounding quotes and rejects
    values that mistakenly contain 'name=' (protects against .env typos)."""
    val = os.getenv(name)
    if val is None:
        return default
    val = val.strip().strip("'\"").strip()
    prefix = name.lower() + "="
    if val.lower().startswith(prefix):
        # e.g. GROQ_LLM_MODEL="groq_llm_model=llama..." -> keep only the real value
        val = val[len(prefix):].strip()
    return val or default


class Settings:
    # Groq
    # NOTE: llama-3.3-70b-specdec / llama-3.3-70b-versatile were decommissioned by
    # Groq (400 "model_decommissioned"). Active defaults verified against the live
    # /models endpoint: openai/gpt-oss-120b (reasoning), openai/gpt-oss-20b, qwen/qwen3.6-27b.
    GROQ_API_KEY = _str("GROQ_API_KEY", "")
    GROQ_LLM_MODEL = _str("GROQ_LLM_MODEL", "openai/gpt-oss-120b")
    GROQ_STT_MODEL = _str("GROQ_STT_MODEL", "whisper-large-v3-turbo")

    # Wake word / voice
    WAKE_WORD = os.getenv("WAKE_WORD", "hey friday").lower()
    WAKE_MODEL_PATH = str(ROOT_DIR / os.getenv("WAKE_MODEL_PATH", "backend/voice/model/vosk-model-small-en-us"))
    TTS_VOICE = os.getenv("TTS_VOICE", "en-IE-EmilyNeural")
    TTS_RATE = os.getenv("TTS_RATE", "+8%")

    # HUD
    HUD_HOST = os.getenv("HUD_HOST", "0.0.0.0")
    HUD_PORT = int(os.getenv("HUD_PORT", "8000"))
    OPEN_BROWSER_ON_START = _bool("OPEN_BROWSER_ON_START", True)

    # Vision
    ENABLE_VISION = _bool("ENABLE_VISION", True)
    CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
    ENABLE_FACE_RECOGNITION = _bool("ENABLE_FACE_RECOGNITION", False)
    GESTURE_DEBOUNCE_SECONDS = float(os.getenv("GESTURE_DEBOUNCE_SECONDS", "2.5"))
    GESTURE_ACTIONS = {
        1: os.getenv("GESTURE_1_ACTION", "open_url:https://claude.ai"),
        2: os.getenv("GESTURE_2_ACTION", "open_url:http://localhost:8000/dashboard"),
        3: os.getenv("GESTURE_3_ACTION", "open_url:https://youtube.com"),
        4: os.getenv("GESTURE_4_ACTION", "open_url:https://google.com"),
        5: os.getenv("GESTURE_5_ACTION", "open_url:https://instagram.com"),
    }

    # ESP32
    ESP32_ENABLED = _bool("ESP32_ENABLED", False)
    ESP32_IP = os.getenv("ESP32_IP", "192.168.1.50")
    ESP32_POLL_SECONDS = float(os.getenv("ESP32_POLL_SECONDS", "3"))

    # Safety
    FRIDAY_WORKSPACE = Path(os.getenv("FRIDAY_WORKSPACE", "./friday_workspace")).resolve()
    AUTO_CONFIRM_SHELL = _bool("AUTO_CONFIRM_SHELL", False)
    # How long to wait for a command approval (HUD response) before auto-rejecting.
    APPROVAL_TIMEOUT_SECONDS = float(os.getenv("APPROVAL_TIMEOUT_SECONDS", "60"))
    # TEMPORARY (testing): when true, every command approval auto-passes with a
    # warning log instead of waiting for HUD/terminal confirmation.
    COMMAND_APPROVAL_BYPASS = _bool("COMMAND_APPROVAL_BYPASS", False)


settings = Settings()
settings.FRIDAY_WORKSPACE.mkdir(parents=True, exist_ok=True)

if not settings.GROQ_API_KEY or settings.GROQ_API_KEY == "your_groq_api_key_here":
    print("[WARN] GROQ_API_KEY is not set. Add it to your .env file before starting FRIDAY.")

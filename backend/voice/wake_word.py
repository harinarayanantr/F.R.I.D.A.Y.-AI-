"""
Offline "Hey FRIDAY" wake word detection using Vosk (no cloud calls, so it
can run continuously without burning API quota). Once triggered, the voice
loop switches to recording a real command which gets sent to Groq Whisper.

Robustness guarantees:
 - Explicit default-input-device selection + sample-rate verification
   (16 kHz preferred; falls back to the device's native rate).
 - Audio blocks are fed from a bounded, non-blocking queue - overflow drops
   old audio instead of stalling the PortAudio callback.
 - Every failure is logged and retried; the thread never dies silently and
   stop_event is honored within ~0.25s.
"""
import json
import os
import queue

import sounddevice as sd
from vosk import KaldiRecognizer, Model

from backend.config import settings
from backend.logger import log
from backend.voice.audio_device import open_input_stream, make_drop_oldest_callback

SAMPLE_RATE = 16000
_audio_q: "queue.Queue[bytes]" = queue.Queue(maxsize=64)
_model: Model | None = None


def _load_model() -> Model:
    global _model
    if _model is not None:
        return _model
    if not os.path.isdir(settings.WAKE_MODEL_PATH):
        raise FileNotFoundError(
            f"Vosk model not found at {settings.WAKE_MODEL_PATH}. "
            "Run setup.sh again, or download from https://alphacephei.com/vosk/models "
            "and unzip it there."
        )
    _model = Model(settings.WAKE_MODEL_PATH)
    return _model


def listen_for_wake_word(stop_event=None):
    """Blocks until the wake word is heard, then returns True.
    Returns False when asked to stop. Never raises for audio-device issues."""
    try:
        model = _load_model()
    except FileNotFoundError as e:
        log(str(e), level="error")
        raise  # voice_loop treats this as fatal config error

    wake_phrase = settings.WAKE_WORD
    recognizer = KaldiRecognizer(model, SAMPLE_RATE)
    callback = make_drop_oldest_callback(_audio_q)

    while True:
        if stop_event is not None and stop_event.is_set():
            return False

        # Drain any stale audio left over from a previous stream session.
        while not _audio_q.empty():
            _audio_q.get_nowait()

        try:
            stream, rate = open_input_stream(
                lambda samplerate: sd.RawInputStream(
                    samplerate=samplerate,
                    blocksize=8000,
                    dtype="int16",
                    channels=1,
                    callback=callback,
                ),
                preferred=SAMPLE_RATE,
            )
        except Exception as e:
            log(f"Microphone unavailable ({type(e).__name__}: {e}); retrying in 3s.", level="error")
            if stop_event is not None:
                stop_event.wait(3.0)
                if stop_event.is_set():
                    return False
            continue

        log(f"Listening for wake word: '{wake_phrase}'...", channel="voice")
        try:
            with stream:
                while True:
                    if stop_event is not None and stop_event.is_set():
                        return False
                    try:
                        data = _audio_q.get(timeout=0.25)
                    except queue.Empty:
                        continue
                    if recognizer.AcceptWaveform(data):
                        result = json.loads(recognizer.Result())
                        text = result.get("text", "").lower()
                        if wake_phrase in text:
                            log(f"Wake word detected in: '{text}'", channel="voice")
                            return True
        except Exception as e:
            log(f"Wake-word audio stream failed ({type(e).__name__}: {e}); reopening.", level="error")
            if stop_event is not None:
                stop_event.wait(1.0)

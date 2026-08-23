"""
Records a short command after the wake word fires, then transcribes it with
Groq's hosted Whisper model (much higher accuracy than the offline wake-word
model, used only for the short recording to save latency/cost).
"""
import tempfile
import wave

import numpy as np
import sounddevice as sd
from groq import Groq

from backend.config import settings
from backend.logger import log, push_status
from backend.voice.audio_device import open_input_stream

SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 500     # amplitude below this = silence
SILENCE_HANG_SECONDS = 1.2  # stop recording after this much trailing silence
MAX_RECORD_SECONDS = 12

client = Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None


def record_command() -> str:
    """Records mic audio until the user stops talking, returns a wav file path."""
    push_status("listening")
    log("Listening for your command...", channel="voice")

    frames = []
    silent_chunks = 0
    chunk_size = 1024
    max_chunks = int(MAX_RECORD_SECONDS * SAMPLE_RATE / chunk_size)
    silence_chunk_limit = int(SILENCE_HANG_SECONDS * SAMPLE_RATE / chunk_size)
    started_talking = False

    try:
        stream, sample_rate = open_input_stream(
            lambda samplerate: sd.InputStream(
                samplerate=samplerate, channels=1, dtype="int16"
            ),
            preferred=SAMPLE_RATE,
        )
        with stream:
            for _ in range(max_chunks):
                audio_chunk, _ = stream.read(chunk_size)
                frames.append(audio_chunk.copy())
                volume = np.abs(audio_chunk).mean()

                if volume > SILENCE_THRESHOLD:
                    started_talking = True
                    silent_chunks = 0
                elif started_talking:
                    silent_chunks += 1
                    if silent_chunks > silence_chunk_limit:
                        break
    except Exception as e:
        log(f"Command recording failed ({type(e).__name__}: {e}).", level="error")
        push_status("idle")
        return ""

    if not frames:
        log("No audio captured from microphone.", level="warning")
        return ""

    # Resample to 16 kHz if the stream had to open at the device's native rate.
    if sample_rate != SAMPLE_RATE:
        raw = np.concatenate(frames).astype(np.float32)
        n_out = int(raw.shape[0] * SAMPLE_RATE / sample_rate)
        x_in = np.linspace(0.0, raw.shape[0] - 1, num=max(n_out, 1))
        audio = np.interp(x_in, np.arange(raw.shape[0]), raw).astype(np.int16)
        sample_rate = SAMPLE_RATE
    else:
        audio = np.concatenate(frames, axis=0)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())
    return tmp.name


def transcribe(wav_path: str) -> str:
    if client is None:
        log("No Groq API key set - can't transcribe.", level="error")
        return ""
    push_status("thinking")
    with open(wav_path, "rb") as f:
        result = client.audio.transcriptions.create(
            file=(wav_path, f.read()),
            model=settings.GROQ_STT_MODEL,
            response_format="text",
        )
    text = str(result).strip()
    log(f"Heard: \"{text}\"", channel="voice")
    return text

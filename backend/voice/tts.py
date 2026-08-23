"""
Text-to-speech using Microsoft Edge's neural voices via edge-tts (free, no
key required). en-IE-EmilyNeural / en-GB-SoniaNeural give the closest vibe
to FRIDAY's accent in the films. Falls back to pyttsx3 (fully offline) if
edge-tts can't reach the network.

Robustness guarantees:
 - edge-tts >= 7.x is REQUIRED: Microsoft now requires the Sec-MS-GEC DRM
   token; older versions get 403 Forbidden handshakes.
 - Playback runs in the CALLER's worker thread (never the FastAPI event
   loop) via a polled subprocess so it can be aborted mid-sentence on
   shutdown; all failures degrade to offline TTS or silence, never crashes.
 - pyttsx3 on Linux needs espeak/espeak-ng; if missing we warn once and
   stay silent so the voice thread keeps running.
"""
import asyncio
import platform
import shutil
import subprocess
import tempfile
import time
from contextlib import aclosing

import edge_tts

from backend.config import settings
from backend.logger import log, push_status

SYSTEM = platform.system()

_TTS_ATTEMPTS = 2
_SYNTH_TIMEOUT_SECONDS = 20
_offline_tts_broken = False


class _TTSAborted(Exception):
    """Raised internally when shutdown was requested during synthesis."""


def _play(path: str, stop_event=None):
    """Play an audio file, aborting early if stop_event fires."""
    try:
        if SYSTEM == "Darwin":
            cmd = ["afplay", path]
        elif SYSTEM == "Windows":
            cmd = ["powershell", "-c", f'(New-Object Media.SoundPlayer "{path}").PlaySync();']
        else:
            cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]

        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while True:
            if proc.poll() is not None:
                return
            if stop_event is not None and stop_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return
            time.sleep(0.05)
    except FileNotFoundError:
        log("No audio player found (install ffmpeg for ffplay, or afplay/powershell).", level="warning")
    except Exception as e:
        log(f"Audio playback error: {e}", level="warning")


async def _synthesize(text: str, out_path: str, stop_event=None):
    """Stream synthesis to disk chunk-by-chunk so a shutdown signal can abort
    mid-flight instead of waiting for the full network transfer. Each attempt
    is also bounded by a hard timeout so a hung connection can't hostage the
    voice thread."""
    last_err: Exception | None = None
    for attempt in range(1, _TTS_ATTEMPTS + 1):
        if stop_event is not None and stop_event.is_set():
            raise _TTSAborted()
        try:
            # Fresh Communicate per attempt: retries regenerate the DRM token,
            # which is what expires/causes 403s with stale clients.
            communicate = edge_tts.Communicate(text, voice=settings.TTS_VOICE, rate=settings.TTS_RATE)
            state = {"wrote_any": False, "aborted": False}

            async def _stream_to_disk():
                # aclosing -> generator (and its websocket/aiohttp session) is
                # closed deterministically even when we break early, so no
                # 'Unclosed client session' / 'Task was destroyed' noise.
                with open(out_path, "wb") as f:
                    async with aclosing(communicate.stream()) as chunks:
                        async for chunk in chunks:
                            if stop_event is not None and stop_event.is_set():
                                state["aborted"] = True
                                break
                            if chunk["type"] == "audio":
                                f.write(chunk["data"])
                                state["wrote_any"] = True

            await asyncio.wait_for(_stream_to_disk(), timeout=_SYNTH_TIMEOUT_SECONDS)
            if state["aborted"] or (stop_event is not None and stop_event.is_set()):
                raise _TTSAborted()
            if not state["wrote_any"]:
                raise RuntimeError("edge-tts returned no audio data")
            return
        except _TTSAborted:
            raise
        except Exception as e:
            last_err = e
            log(f"edge-tts attempt {attempt}/{_TTS_ATTEMPTS} failed: {e}", level="warning")
            await asyncio.sleep(0.8)
    raise last_err  # type: ignore[misc]


def _run_synthesis(text: str, out_path: str, stop_event=None):
    """Runs _synthesize in a fresh event loop while supervising stop_event.
    Cancels the synthesis task within ~50ms of shutdown even if the network
    has gone quiet (no chunks arriving), so the voice thread is never held
    hostage by a slow connection."""

    async def _supervised():
        task = asyncio.ensure_future(_synthesize(text, out_path, stop_event))
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=0.05)
                if done:
                    return task.result()
                if stop_event is not None and stop_event.is_set():
                    raise _TTSAborted()
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(_supervised())


def speak(text: str, stop_event=None):
    global _offline_tts_broken
    if not text:
        return
    push_status("speaking", {"text": text})
    log(f"FRIDAY: {text}", channel="voice")
    spoke = False

    tmp_name = None
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp_name = tmp.name
        try:
            _run_synthesis(text, tmp_name, stop_event)
        except RuntimeError as e:
            # Called from inside a running event loop - don't take it down.
            log(f"TTS skipped (no event loop available: {e})", level="warning")
            raise
        _play(tmp_name, stop_event=stop_event)
        spoke = True
    except _TTSAborted:
        push_status("idle")
        return  # shutdown requested: stay silent, skip playback AND offline TTS
    except Exception as e:
        log(f"edge-tts unavailable ({type(e).__name__}), trying offline TTS.", level="warning")

    finally:
        if tmp_name:
            try:
                import os as _os

                _os.unlink(tmp_name)
            except OSError:
                pass

    if not spoke and not (stop_event is not None and stop_event.is_set()):
        _speak_offline(text)
    push_status("idle")


def _speak_offline(text: str):
    """Offline fallback via pyttsx3/eSpeak. Never raises: if no TTS engine is
    installed we warn once and stay silent so the voice thread keeps running."""
    global _offline_tts_broken
    if _offline_tts_broken:
        return
    if SYSTEM == "Linux" and not (shutil.which("espeak") or shutil.which("espeak-ng")):
        _offline_tts_broken = True
        log(
            "Offline TTS disabled: pyttsx3 needs 'espeak' or 'espeak-ng' "
            "(install via: sudo pacman -S espeak-ng). Continuing silently.",
            level="warning",
        )
        return
    try:
        import pyttsx3

        engine = pyttsx3.init()  # may raise if no driver/backend is available
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        _offline_tts_broken = True
        log(f"Offline TTS failed, continuing silently: {e}", level="warning")

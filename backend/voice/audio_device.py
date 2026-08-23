"""
Shared microphone helpers: explicit default-input-device selection, sample
rate verification (16 kHz preferred, device-native fallback) and stream
opening with exception isolation so audio threads never freeze silently.
"""
import sounddevice as sd

from backend.logger import log

PREFERRED_RATE = 16000
_queue_max_blocks = 64  # ~2.6s of audio at 16k/8000-sample blocks; drops on overflow


def default_input_info() -> dict:
    """Info dict for the OS default input device; empty dict if unavailable."""
    try:
        info = sd.query_devices(kind="input")
        return dict(info) if info else {}
    except Exception as e:
        log(f"No microphone found: {e}", level="error")
        return {}


def candidate_rates(preferred: int = PREFERRED_RATE) -> list[int]:
    """Rates to try in order: preferred first, then the device's native rate."""
    rates = [preferred]
    info = default_input_info()
    try:
        native = int(float(info.get("default_samplerate", 0)))
    except (TypeError, ValueError):
        native = 0
    if native and native not in rates:
        rates.append(native)
    return rates


def open_input_stream(stream_factory, preferred: int = PREFERRED_RATE):
    """Open an input stream via `stream_factory(samplerate=...)`, trying the
    preferred rate first and falling back to the device's native rate.
    Returns (stream, rate_used). Raises the last PortAudioError if all fail."""
    last_err = None
    for rate in candidate_rates(preferred):
        try:
            stream = stream_factory(samplerate=rate)
            info = default_input_info()
            name = info.get("name", "unknown")
            note = "" if rate == PREFERRED_RATE else f" (device rejected {PREFERRED_RATE}Hz)"
            log(f"Microphone: '{name}' @ {rate}Hz{note}", channel="voice")
            return stream, rate
        except Exception as e:
            last_err = e
            log(f"Failed to open mic at {rate}Hz ({type(e).__name__}: {e})", level="warning")
    raise last_err  # type: ignore[misc]


def make_drop_oldest_callback(audio_q, maxsize: int = _queue_max_blocks):
    """sounddevice callback that never blocks and never lets the queue grow
    unbounded (drops oldest blocks on overflow instead of freezing the loop)."""

    def _callback(indata, frames, time_info, status):  # noqa: ANN001
        if status:
            log(f"Audio stream status: {status}", level="warning")
        block = bytes(indata)
        while True:
            try:
                audio_q.put_nowait(block)
                break
            except Exception:
                try:
                    audio_q.get_nowait()  # queue full -> drop oldest, keep newest
                except Exception:
                    break

    return _callback

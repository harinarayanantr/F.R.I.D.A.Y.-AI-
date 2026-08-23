"""
Clean self-shutdown coordination.

The stop_friday tool executes inside worker threads (the voice loop thread or
FastAPI's sync threadpool), so shutdown cannot be driven by asyncio directly.
Instead we send SIGINT to our own process: uvicorn's main-thread signal
handler then runs the normal lifespan teardown (stop_event -> broadcast task
cancelled -> worker threads joined) and the process exits with code 0 -
exactly as if the user pressed Ctrl+C, but hands-free.
"""
import os
import signal
import threading

from backend.logger import log

_fired = threading.Event()


def request_shutdown(reason: str = "", delay_s: float = 0.25):
    """Trigger a graceful process shutdown exactly once.

    `delay_s` lets the current call stack unwind (tool result appended,
    ask_friday returning) before the signal lands."""
    if _fired.is_set():
        return
    _fired.set()
    log(f"Shutdown requested{' (' + reason + ')' if reason else ''}.", channel="system")
    timer = threading.Timer(max(0.0, delay_s), _fire_signal)
    timer.daemon = True
    timer.start()


def _fire_signal():
    try:
        os.kill(os.getpid(), signal.SIGINT)
    except Exception as e:  # pragma: no cover - last-resort path
        log(f"SIGINT self-delivery failed ({e}); forcing exit.", level="warning")
        os._exit(0)


def is_shutdown_pending() -> bool:
    return _fired.is_set()

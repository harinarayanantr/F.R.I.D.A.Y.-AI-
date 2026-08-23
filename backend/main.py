"""
F.R.I.D.A.Y. entry point.

Starts:
  - FastAPI/uvicorn server hosting the HUD (web UI) + REST/WebSocket API
  - Voice loop thread (wake word -> STT -> brain -> TTS)
  - Vision loop thread (gestures + face tracking)
  - ESP32 poller thread
"""
import asyncio
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import webbrowser
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import settings
from backend.logger import log, event_queue, push_status
from backend import approvals, brain
from backend.voice.voice_loop import run_voice_loop
from backend.vision.vision_loop import run_vision_loop
from backend.esp32.esp32_manager import start_esp32_poller, get_status as esp32_status

ROOT_DIR = Path(__file__).resolve().parent.parent
HUD_STATIC_DIR = ROOT_DIR / "backend" / "hud" / "static"
HUD_TEMPLATE = ROOT_DIR / "backend" / "hud" / "templates" / "index.html"

_stop_event = threading.Event()
_voice_thread: threading.Thread | None = None
_vision_thread: threading.Thread | None = None


def _read_hud() -> str:
    try:
        return HUD_TEMPLATE.read_text(encoding="utf-8")
    except OSError as e:
        return f"<h1>HUD template missing</h1><pre>{e}</pre>"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _voice_thread, _vision_thread

    log("=" * 60)
    log("F.R.I.D.A.Y. online.")
    log("=" * 60)

    _voice_thread = threading.Thread(
        target=run_voice_loop, args=(_stop_event,), daemon=True, name="voice-loop"
    )
    _vision_thread = threading.Thread(
        target=run_vision_loop, args=(_stop_event,), daemon=True, name="vision-loop"
    )
    _voice_thread.start()
    _vision_thread.start()
    start_esp32_poller()
    app.state.broadcast_task = asyncio.create_task(_broadcast_loop())

    if settings.OPEN_BROWSER_ON_START:
        try:
            webbrowser.open(f"http://localhost:{settings.HUD_PORT}")
        except Exception:
            pass

    try:
        yield
    finally:
        # SIGINT/SIGTERM lands here: cancel async tasks, signal worker threads
        # to stop, then join briefly so everything exits BEFORE interpreter
        # teardown - all within the 2-second graceful window.
        log("Shutting down F.R.I.D.A.Y. ...", channel="system")
        _stop_event.set()
        task = getattr(app.state, "broadcast_task", None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
        for t in (_voice_thread, _vision_thread):
            if t is not None and t.is_alive():
                t.join(timeout=2.0)
                if t.is_alive():
                    log(f"Thread '{t.name}' did not stop in time; abandoning (daemon).", level="warning")
        log("Goodbye, boss.", channel="system")


app = FastAPI(title="F.R.I.D.A.Y.", lifespan=lifespan)

# Explicit static mount for HUD assets (/static/hud.css, /static/hud.js).
app.mount("/static", StaticFiles(directory=str(HUD_STATIC_DIR)), name="static")

_ws_clients: set[WebSocket] = set()


class CommandIn(BaseModel):
    text: str


@app.get("/", response_class=HTMLResponse)
def hud_page():
    return _read_hud()


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page():
    return _read_hud()


@app.get("/api/status")
def api_status():
    return {"esp32": esp32_status()}


@app.post("/api/command")
def api_command(cmd: CommandIn):
    """Send a typed text command to FRIDAY (no voice needed) - used by the HUD text box."""
    reply = brain.ask_friday(cmd.text)
    push_status("idle")
    return {"reply": reply}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    approvals.client_connected()
    log("HUD client connected.", channel="system")
    try:
        while True:
            raw = await ws.receive_text()
            # The HUD mostly stays quiet, but it answers approval requests.
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(msg, dict) and msg.get("type") == "approval_response":
                approvals.resolve(str(msg.get("request_id", "")), bool(msg.get("approved")))
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)
        approvals.client_disconnected()


async def _broadcast_loop():
    """Drains the sync event_queue (fed by logger.py from other threads) onto
    all websockets.

    Uses non-blocking queue polling instead of run_in_executor: on Python 3.14
    executor submission trips the deprecated asyncio.iscoroutinefunction check
    (DeprecationWarning attributed to this file), and lingering executor
    futures were causing 'cannot schedule new futures after interpreter
    shutdown' errors during Ctrl+C. Events are low-rate (~6 fps max), so a
    50 ms poll is imperceptible."""
    while True:
        try:
            drained = False
            for _ in range(32):  # drain in small bursts; yield between bursts
                try:
                    event = event_queue.get_nowait()
                except Exception:
                    break
                drained = True
                dead = []
                for ws in list(_ws_clients):
                    try:
                        await ws.send_json(event)
                    except Exception:
                        dead.append(ws)
                for d in dead:
                    _ws_clients.discard(d)
            if not drained:
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log(f"Broadcast loop error: {e}", level="warning")
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=settings.HUD_HOST,
        port=settings.HUD_PORT,
        log_level="warning",
        # Keep total Ctrl+C-to-exit under 2 seconds; lifespan cleanup finishes
        # well inside this window.
        timeout_graceful_shutdown=2,
    )

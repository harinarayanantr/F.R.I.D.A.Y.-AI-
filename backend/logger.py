"""
Terminal logging (colored, Tony-Stark-console style) that also fans events
out to the HUD over websockets via an in-memory event bus.
"""
import logging
import queue
import time
import colorlog

# Queue consumed by the FastAPI websocket broadcaster in main.py
event_queue: "queue.Queue[dict]" = queue.Queue()

_handler = colorlog.StreamHandler()
_handler.setFormatter(
    colorlog.ColoredFormatter(
        "%(log_color)s[%(asctime)s] F.R.I.D.A.Y. | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
    )
)

logger = logging.getLogger("friday")
logger.setLevel(logging.INFO)
logger.addHandler(_handler)
logger.propagate = False


def log(message: str, level: str = "info", channel: str = "system"):
    """Log to terminal AND push to HUD event queue."""
    getattr(logger, level, logger.info)(message)
    event_queue.put(
        {
            "type": "log",
            "channel": channel,
            "level": level,
            "message": message,
            "ts": time.time(),
        }
    )


def push_status(status: str, extra: dict | None = None):
    """Push a status update (idle/listening/thinking/speaking) to the HUD."""
    payload = {"type": "status", "status": status, "ts": time.time()}
    if extra:
        payload.update(extra)
    event_queue.put(payload)


def push_event(event_type: str, data: dict):
    payload = {"type": event_type, "ts": time.time()}
    payload.update(data)
    event_queue.put(payload)

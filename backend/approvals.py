"""
Command approval bridge.

Routes shell-command authorization requests to the HUD over the existing
WebSocket event bus instead of a terminal input() prompt - which hangs
forever when FRIDAY is autostarted (.desktop) without an interactive TTY.

Flow for `request_approval()`:
  1. HUD clients connected  -> broadcast `approval_request`
     {request_id, command, description} and suspend the calling worker
     thread on a threading.Event until `resolve()` fires from the WebSocket
     handler (user clicked Approve/Deny) or the timeout expires (auto-reject).
  2. No clients, interactive TTY -> classic stdout/stdin fallback so
     terminal-only setups keep working exactly as before.
  3. No clients, headless -> still broadcast (a user may open the HUD during
     the wait window) and auto-reject after the timeout. Execution NEVER
     hangs indefinitely.

Note on primitives: brain.ask_friday() runs in plain worker threads (the
voice loop thread / FastAPI's sync threadpool), not on the event loop, so a
threading.Event is the correct suspension primitive here; it is the exact
functional equivalent of an asyncio.Event for this calling context and does
not block the FastAPI event loop.
"""
import sys
import threading
import uuid

from backend.config import settings
from backend.logger import log, push_event

_lock = threading.Lock()
_hud_clients = 0
_pending: dict[str, "_PendingApproval"] = {}


class _PendingApproval:
    __slots__ = ("event", "approved")

    def __init__(self):
        self.event = threading.Event()
        self.approved = False


def client_connected():
    global _hud_clients
    with _lock:
        _hud_clients += 1


def client_disconnected():
    global _hud_clients
    with _lock:
        _hud_clients = max(0, _hud_clients - 1)


def hud_client_count() -> int:
    with _lock:
        return _hud_clients


def resolve(request_id: str, approved: bool) -> bool:
    """Called by the WebSocket handler when the HUD answers a request.
    Returns True if the response matched a pending request."""
    with _lock:
        pending = _pending.pop(request_id, None)
    if pending is None:
        return False
    pending.approved = bool(approved)
    pending.event.set()
    log(f"Approval {request_id}: {'APPROVED' if approved else 'DENIED'} via HUD.", channel="system")
    return True


def request_approval(command: str, description: str = "", timeout: float | None = None) -> bool:
    """Ask a human to authorize `command`. Blocks the caller up to `timeout`
    seconds (default APPROVAL_TIMEOUT_SECONDS). Returns True only on explicit
    approval; timeout/denial/no-human all return False."""
    # TEMPORARY testing bypass: auto-approve instantly, no HUD/CLI prompt.
    if settings.COMMAND_APPROVAL_BYPASS:
        log(
            "[WARNING] Command executed automatically (Permission bypass enabled for testing): "
            f"`{command}`",
            level="warning",
            channel="system",
        )
        return True

    if timeout is None:
        timeout = settings.APPROVAL_TIMEOUT_SECONDS

    # Classic path: real terminal attached and nobody watching the dashboard.
    if hud_client_count() == 0 and _stdin_is_interactive():
        return _cli_fallback(command)

    request_id = uuid.uuid4().hex[:12]
    pending = _PendingApproval()
    with _lock:
        _pending[request_id] = pending

    push_event(
        "approval_request",
        {
            "request_id": request_id,
            "command": command,
            "description": description or "FRIDAY wants to run a shell command.",
            "timeout": timeout,
        },
    )
    if hud_client_count() > 0:
        log(
            f"Command needs approval (request {request_id}) - sent to HUD: `{command}`",
            level="warning",
            channel="system",
        )
    else:
        log(
            f"Command needs approval but no HUD client is connected - open "
            f"http://localhost:{settings.HUD_PORT} within {int(timeout)}s to allow: `{command}`",
            level="warning",
            channel="system",
        )

    authorized = pending.event.wait(timeout)

    with _lock:
        _pending.pop(request_id, None)  # clean up if timed out

    if not authorized:
        log(f"Approval {request_id}: auto-rejected after {int(timeout)}s timeout.", level="warning")
    return bool(authorized and pending.approved)


def _stdin_is_interactive() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty() and sys.stdout is not None and sys.stdout.isatty()
    except Exception:
        return False


def _cli_fallback(command: str) -> bool:
    """Original behavior for terminal-launched sessions without the HUD open."""
    log(f"Command requested: `{command}` -- type 'y' in terminal to allow.", level="warning")
    try:
        answer = input(f"[FRIDAY] Allow shell command? `{command}` (y/N): ").strip().lower()
    except (EOFError, OSError):
        # stdin closed/unreadable (autostart edge case) - never hang.
        log("No readable stdin for CLI approval - treating as denied.", level="warning")
        return False
    if answer != "y":
        log("Command denied by user.", level="warning")
        return False
    return True

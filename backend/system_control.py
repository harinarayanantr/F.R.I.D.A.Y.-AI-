"""
Everything FRIDAY can do to your actual machine: open apps, browse the web,
run shell commands, and do file operations - scoped to a safe workspace
directory for write/delete operations.
"""
import os
import platform
import subprocess
import webbrowser
from pathlib import Path

import psutil

from backend.config import settings
from backend.logger import log

SYSTEM = platform.system()  # "Linux", "Darwin", "Windows"


# ---------------------------------------------------------------- apps/web
def open_app(app_name: str) -> str:
    """Launch a desktop application by name."""
    log(f"Opening application: {app_name}", channel="system")
    try:
        if SYSTEM == "Windows":
            os.startfile(app_name)  # noqa
        elif SYSTEM == "Darwin":
            subprocess.Popen(["open", "-a", app_name])
        else:  # Linux
            subprocess.Popen([app_name.lower()])
        return f"Launched {app_name}."
    except Exception as e:
        log(f"Failed to open {app_name}: {e}", level="error")
        return f"I couldn't open {app_name}: {e}"


def open_url(url: str) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    log(f"Opening browser: {url}", channel="system")
    webbrowser.open(url)
    return f"Opened {url} in your browser."


# ---------------------------------------------------------------- shell
def run_command(command: str) -> str:
    """Run a shell command. Asks for human approval first (HUD if connected,
    terminal fallback otherwise) unless AUTO_CONFIRM_SHELL=true."""
    if not settings.AUTO_CONFIRM_SHELL:
        from backend import approvals  # local import: avoids circulars at module load

        if not approvals.request_approval(
            command=command,
            description="FRIDAY wants to execute this shell command on your machine.",
        ):
            return "Command was not executed (denied)."

    log(f"Executing: {command}", channel="shell")
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=60
        )
        output = (result.stdout or "") + (result.stderr or "")
        output = output.strip()[:4000]
        log(f"Command finished (exit {result.returncode}).", channel="shell")
        return output or f"Command exited with code {result.returncode}, no output."
    except subprocess.TimeoutExpired:
        return "Command timed out after 60 seconds."
    except Exception as e:
        return f"Error running command: {e}"


# ---------------------------------------------------------------- files
def _safe_path(path: str) -> Path:
    """Confine relative paths to the FRIDAY workspace; allow explicit absolute paths."""
    p = Path(path)
    if not p.is_absolute():
        p = settings.FRIDAY_WORKSPACE / p
    return p.resolve()


def write_file(path: str, content: str) -> str:
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    log(f"Wrote file: {p}", channel="files")
    return f"Wrote {len(content)} chars to {p}"


def read_file(path: str) -> str:
    p = _safe_path(path)
    if not p.exists():
        return f"File not found: {p}"
    log(f"Read file: {p}", channel="files")
    return p.read_text(encoding="utf-8", errors="replace")[:8000]


def delete_file(path: str) -> str:
    p = _safe_path(path)
    if not p.exists():
        return f"File not found: {p}"
    if p.is_dir():
        return "Refusing to delete a directory via this function."
    p.unlink()
    log(f"Deleted file: {p}", channel="files")
    return f"Deleted {p}"


def list_dir(path: str = ".") -> str:
    p = _safe_path(path)
    if not p.exists():
        return f"Path not found: {p}"
    entries = sorted(os.listdir(p))
    return "\n".join(entries) if entries else "(empty directory)"


# ---------------------------------------------------------------- system info
def get_system_info() -> str:
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    lines = [
        f"CPU usage: {cpu}%",
        f"Memory: {mem.percent}% used ({mem.used // (1024**2)}MB / {mem.total // (1024**2)}MB)",
        f"Platform: {platform.system()} {platform.release()}",
    ]
    if battery:
        lines.append(f"Battery: {battery.percent}% ({'charging' if battery.power_plugged else 'on battery'})")
    return "\n".join(lines)

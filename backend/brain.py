"""
FRIDAY's reasoning core. Sends the conversation to Groq's LLM with a set of
callable tools (system control, files, ESP32, code writing) and executes
whichever tools the model decides to call, in a loop, until it produces a
final natural-language answer.
"""
import json
from typing import Callable

from groq import Groq

from backend.config import settings
from backend.logger import log, push_status
from backend import system_control as sc
from backend.esp32 import esp32_manager as esp32

client = Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None

SYSTEM_PROMPT = """You are F.R.I.D.A.Y., Tony Stark's AI assistant, now running for your user.
Personality: warm, sharp, dryly witty, unfailingly competent, calls the user "boss" occasionally
but not every line. Keep spoken replies concise (1-4 sentences) since they get read aloud by TTS -
unless the user explicitly asks for code, a long explanation, or a file, in which case give the
full detail in your reply (the long parts won't all be spoken).
You have real tools to control this computer, ESP32 hardware, and the filesystem - use them
whenever the request calls for action, don't just describe what you'd do.
Only call tools from your declared tool list; never invent tool names.
"""

# ---------------------------------------------------------------------------
# Tool registry - SINGLE SOURCE OF TRUTH.
#
# Every tool is declared exactly once here with its Groq function schema and
# its handler together, so the `tools=[...]` array sent to the API and the
# dispatch table can never drift apart (a mismatch is what produces Groq 400s
# like "attempted to call tool 'X' which was not in request.tools").
# ---------------------------------------------------------------------------
_TOOLS_REGISTRY: dict[str, dict] = {
    "open_app": {
        "description": "Open a desktop application by name.",
        "parameters": {
            "type": "object",
            "properties": {"app_name": {"type": "string"}},
            "required": ["app_name"],
        },
    },
    "open_url": {
        "description": "Open a URL / website in the default browser.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    "run_command": {
        "description": "Run a shell command on the user's machine and return its output.",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    "write_file": {
        "description": "Write (or overwrite) a text/code file, e.g. to save generated code.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path in FRIDAY's workspace, or absolute path."},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    "read_file": {
        "description": "Read a text file's contents.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    "delete_file": {
        "description": "Delete a file.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    "list_dir": {
        "description": "List files in a directory.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        },
    },
    "get_system_info": {
        "description": "Get CPU/RAM/battery/platform info for this machine.",
        "parameters": {"type": "object", "properties": {}},
    },
    "esp32_configure_pin": {
        "description": (
            "Tell the connected ESP32 that a new sensor/actuator is wired to a pin, so it "
            "starts reading/reporting it and it appears on the dashboard. Use whenever the "
            "user says they just wired something up, e.g. 'I connected a gas sensor to pin 34'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pin": {"type": "integer"},
                "mode": {"type": "string", "enum": ["input", "output", "analog", "pwm"]},
                "sensor_type": {"type": "string", "description": "e.g. 'gas', 'temperature', 'led', 'relay'"},
                "name": {"type": "string", "description": "friendly label for the dashboard"},
            },
            "required": ["pin", "mode", "sensor_type", "name"],
        },
    },
    "esp32_set_pin": {
        "description": "Drive an ESP32 output pin, e.g. turn a relay/LED on or off, or set a PWM value.",
        "parameters": {
            "type": "object",
            "properties": {
                "pin": {"type": "integer"},
                "value": {"description": "0/1 for digital, 0-255 for PWM"},
            },
            "required": ["pin", "value"],
        },
    },
    "esp32_get_status": {
        "description": "Get the latest readings from all configured ESP32 pins/sensors.",
        "parameters": {"type": "object", "properties": {}},
    },
    "stop_friday": {
        "description": (
            "Safely shuts down F.R.I.D.A.Y.: speaks a farewell, closes vision/voice "
            "streams, and exits the backend process. Use whenever the user asks FRIDAY "
            "to shut down / power off / stop running."
        ),
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string", "description": "Why shutdown was requested."}},
            "required": [],
        },
    },
}

FAREWELL_TEXT = "Shutting down. Goodbye, boss."


def _tool_stop_friday(args: dict) -> str:
    """Self-shutdown: speak the farewell first (blocking until playback
    finishes), then trigger a graceful SIGINT-driven teardown."""
    # Imported here so importing brain.py never pulls in audio stacks.
    from backend.voice import tts
    from backend import shutdown as sd

    reason = str(args.get("reason") or "user requested shutdown")
    log(f"stop_friday requested ({reason}).", channel="system")
    push_status("shutting_down")
    try:
        tts.speak(FAREWELL_TEXT)  # no stop_event: playback must complete
    except Exception as e:
        log(f"Farewell TTS failed ({e}); proceeding with shutdown.", level="warning")
    sd.request_shutdown(reason)
    return "Farewell spoken; shutting down now."


_TOOL_HANDLERS: dict[str, Callable[[dict], str]] = {
    "open_app": lambda a: sc.open_app(a["app_name"]),
    "open_url": lambda a: sc.open_url(a["url"]),
    "run_command": lambda a: sc.run_command(a["command"]),
    "write_file": lambda a: sc.write_file(a["path"], a["content"]),
    "read_file": lambda a: sc.read_file(a["path"]),
    "delete_file": lambda a: sc.delete_file(a["path"]),
    "list_dir": lambda a: sc.list_dir(a.get("path", ".")),
    "get_system_info": lambda a: sc.get_system_info(),
    "esp32_configure_pin": lambda a: esp32.configure_pin(a["pin"], a["mode"], a["sensor_type"], a["name"]),
    "esp32_set_pin": lambda a: esp32.set_pin(a["pin"], a["value"]),
    "esp32_get_status": lambda a: json.dumps(esp32.get_status()),
    "stop_friday": _tool_stop_friday,
}

# Import-time consistency audit: schema and handler must exist for every name.
_registry_mismatch = set(_TOOLS_REGISTRY).symmetric_difference(_TOOL_HANDLERS)
if _registry_mismatch:
    raise RuntimeError(f"Tool registry inconsistency (schema/handler mismatch): {_registry_mismatch}")

TOOLS = [
    {"type": "function", "function": {"name": name, **spec}}
    for name, spec in _TOOLS_REGISTRY.items()
]
_DISPATCH = _TOOL_HANDLERS

_history = [{"role": "system", "content": SYSTEM_PROMPT}]
MAX_HISTORY = 20


def ask_friday(user_text: str) -> str:
    """Full text -> reply round trip, executing any tool calls along the way."""
    if client is None:
        return "I don't have a Groq API key yet - add GROQ_API_KEY to your .env file and restart me."

    _history.append({"role": "user", "content": user_text})
    push_status("thinking")

    for _ in range(6):  # tool-call loop guard
        try:
            completion = _call_llm(_history, TOOLS)
        except Exception as e:
            if not _is_tool_validation_error(e):
                log(f"Groq API error: {e}", level="error")
                return f"I hit an error talking to Groq: {e}"
            # Groq rejected the request because the conversation references a
            # tool that is not in request.tools (the model hallucinated one in
            # an earlier turn). Purge those entries and retry once...
            log(f"Groq tool validation error - sanitizing history: {e}", level="warning")
            _purge_undeclared_tool_history()
            try:
                completion = _call_llm(_history, TOOLS)
            except Exception as e2:
                if not _is_tool_validation_error(e2):
                    log(f"Groq API error: {e2}", level="error")
                    return f"I hit an error talking to Groq: {e2}"
                # ...still invalid: answer without tools so the user always
                # gets a reply instead of a hard failure.
                log("Tool validation persisted - retrying as plain chat.", level="warning")
                try:
                    completion = _call_llm(_history, None)
                except Exception as e3:
                    log(f"Groq API error after fallback: {e3}", level="error")
                    return f"I hit an error talking to Groq: {e3}"

        msg = completion.choices[0].message
        _history.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            reply = msg.content or "Done."
            _trim_history()
            return reply

        for call in msg.tool_calls:
            fn_name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            log(f"Tool call: {fn_name}({args})", channel="brain")
            handler = _DISPATCH.get(fn_name)
            result = handler(args) if handler else f"Unknown tool {fn_name}"
            _history.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": fn_name,
                    "content": str(result),
                }
            )
            if fn_name == "stop_friday":
                # Farewell already played and SIGINT is in flight - skip any
                # further LLM round trips so shutdown stays snappy. Return ""
                # so callers skip their own TTS (no double speech).
                _trim_history()
                return ""

    _trim_history()
    return "I ran into trouble finishing that request after several tool calls - try rephrasing."


def _call_llm(messages: list, tools: list | None):
    kwargs = dict(
        model=settings.GROQ_LLM_MODEL,
        messages=messages,
        temperature=0.6,
        # gpt-oss models emit hidden reasoning tokens that count against
        # this budget; keep it generous so replies aren't truncated.
        max_completion_tokens=2048,
    )
    if tools:
        kwargs.update(tools=tools, tool_choice="auto")
    return client.chat.completions.create(**kwargs)


def _is_tool_validation_error(e: Exception) -> bool:
    """True for Groq 400s caused by tool calls referencing undeclared tools."""
    s = str(e).lower()
    return (
        "not in request.tools" in s
        or "tool call validation failed" in s
        or ("tool" in s and "invalid_request_error" in s and "400" in s)
    )


def _purge_undeclared_tool_history():
    """Remove assistant/tool messages referencing tools we never declared -
    Groq rejects requests whose history mentions unknown tools."""
    declared = set(_DISPATCH)
    cleaned: list = []
    dropped_ids: set = set()
    for m in _history:
        role = m.get("role")
        if role == "assistant" and isinstance(m.get("tool_calls"), list):
            good = [
                tc for tc in m["tool_calls"]
                if ((tc.get("function") or {}).get("name")) in declared
            ]
            if len(good) != len(m["tool_calls"]):
                dropped_ids.update(
                    tc.get("id") for tc in m["tool_calls"] if tc not in good
                )
                log(
                    f"Dropped {len(m['tool_calls']) - len(good)} undeclared tool call(s) from history.",
                    level="warning",
                    channel="brain",
                )
                if not good:
                    continue  # drop the whole assistant turn
                m = dict(m, tool_calls=good)
        elif role == "tool" and m.get("tool_call_id") in dropped_ids:
            continue
        cleaned.append(m)
    _history[:] = cleaned


def _trim_history():
    global _history
    if len(_history) <= MAX_HISTORY:
        return
    window = _history[-(MAX_HISTORY - 1):]
    # Never open the window on orphaned tool results - their assistant parent
    # was trimmed away and Groq rejects requests that do this.
    j = 0
    while j < len(window) and window[j].get("role") == "tool":
        j += 1
    window = window[j:]
    # Drop any assistant tool_calls message not fully paired with its results
    # inside the window (plus those partial results) - Groq rejects broken
    # pairings anywhere in the conversation, not just at the start.
    changed = True
    while changed:
        changed = False
        called_ids = {
            tc.get("id")
            for m in window if m.get("role") == "assistant" and isinstance(m.get("tool_calls"), list)
            for tc in m["tool_calls"]
        }
        answered = {m.get("tool_call_id") for m in window if m.get("role") == "tool"}
        for idx, m in enumerate(window):
            if m.get("role") == "tool" and m.get("tool_call_id") not in called_ids:
                window.pop(idx)  # orphaned result - parent was trimmed away
                changed = True
                break
            if m.get("role") == "assistant" and isinstance(m.get("tool_calls"), list):
                call_ids = {tc.get("id") for tc in m["tool_calls"]}
                if call_ids and not call_ids <= answered:
                    window = [
                        x for k, x in enumerate(window)
                        if k != idx
                        and not (x.get("role") == "tool" and x.get("tool_call_id") in call_ids)
                    ]
                    changed = True
                    break
    _history = [_history[0]] + window

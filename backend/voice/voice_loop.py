"""
The main voice thread: wait for "Hey FRIDAY" -> record command -> transcribe
-> send to the brain -> speak the reply -> go back to listening.
"""
import os
import threading

from backend.logger import log, push_status
from backend.voice import wake_word, stt, tts
from backend import brain

STOP_PHRASES = {"go to sleep", "stop listening", "goodnight friday"}


def run_voice_loop(stop_event: threading.Event | None = None):
    push_status("idle")
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            heard = wake_word.listen_for_wake_word(stop_event)
            if not heard or (stop_event is not None and stop_event.is_set()):
                return

            tts.speak("Yes, boss?", stop_event=stop_event)
            if stop_event is not None and stop_event.is_set():
                return

            wav_path = stt.record_command()
            if not wav_path:
                continue
            text = stt.transcribe(wav_path)
            os.remove(wav_path)

            if not text:
                tts.speak("I didn't catch that.", stop_event=stop_event)
                continue
            if text.lower().strip(".") in STOP_PHRASES:
                tts.speak("Going quiet. Say the wake word whenever you need me.", stop_event=stop_event)
                continue

            reply = brain.ask_friday(text)
            if reply:  # empty = farewell already spoken by stop_friday tool
                tts.speak(reply, stop_event=stop_event)
            push_status("idle")

        except FileNotFoundError as e:
            log(str(e), level="error")
            log("Voice loop paused - fix the wake-word model path and restart.", level="error")
            return
        except Exception as e:
            log(f"Voice loop error: {e}", level="error")
            push_status("idle")

"""
Main computer-vision thread: grabs webcam frames, runs hand-gesture and
face tracking on them, and streams a small JPEG preview to the HUD.
"""
import base64
import threading
import time

import cv2

from backend.config import settings
from backend.logger import log, push_event
from backend.vision import gesture_control, face_tracking


def run_vision_loop(stop_event: threading.Event | None = None):
    if not settings.ENABLE_VISION:
        log("Vision disabled (ENABLE_VISION=false in .env).", channel="vision")
        return

    cap = cv2.VideoCapture(settings.CAMERA_INDEX)
    if not cap.isOpened():
        log(f"Couldn't open camera index {settings.CAMERA_INDEX}. Vision disabled.", level="error")
        return

    log("Vision system online: hand gestures + face tracking active.", channel="vision")
    last_stream = 0.0

    while True:
        if stop_event is not None and stop_event.is_set():
            break
        try:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue

            frame = cv2.flip(frame, 1)
            # Per-frame guards: one bad frame/detector must not kill the loop,
            # and shutdown races inside MediaPipe must not raise at exit.
            try:
                frame = gesture_control.process_frame(frame)
                frame = face_tracking.process_frame(frame)
            except (RuntimeError, ValueError) as e:
                log(f"Vision processing skipped a frame: {e}", level="warning")
            except Exception as e:
                log(f"Vision processing error: {e}", level="warning")

            # Stream ~6 fps preview to the HUD (keeps websocket traffic light)
            now = time.time()
            if now - last_stream > 1 / 6:
                small = cv2.resize(frame, (320, 240))
                ok2, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 60])
                if ok2:
                    b64 = base64.b64encode(buf).decode("ascii")
                    push_event("camera_frame", {"jpeg_b64": b64})
                last_stream = now
        except Exception as e:
            log(f"Vision loop error: {e}", level="error")
            time.sleep(0.1)

    cap.release()
    gesture_control.close()
    face_tracking.close()
    log("Vision loop stopped.", channel="vision")

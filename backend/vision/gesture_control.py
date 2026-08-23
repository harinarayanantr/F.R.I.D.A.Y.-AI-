"""
Hand tracking + finger counting with MediaPipe 1.0+. Maps finger counts to
actions defined in .env (GESTURE_1_ACTION, GESTURE_2_ACTION, GESTURE_3_ACTION...).
"""
import time
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from backend.config import settings
from backend.logger import log, push_event
from backend import system_control as sc

# Initialize MediaPipe 1.0+ HandLandmarker in IMAGE mode.
# Guarded: a missing/corrupt model must not take down the whole backend.
try:
    base_options = python.BaseOptions(model_asset_path='hand_landmarker.task')
    options = vision.HandLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.IMAGE,
        num_hands=1,
        min_hand_detection_confidence=0.7,
        min_tracking_confidence=0.6
    )
    _detector = vision.HandLandmarker.create_from_options(options)
except Exception as e:
    _detector = None
    log(f"HandLandmarker init failed - gestures disabled ({e})", level="error")

_TIP_IDS = [4, 8, 12, 16, 20]  # thumb, index, middle, ring, pinky landmark indices
_HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17)
]

_last_trigger_time = 0.0
_last_count = -1


def _count_fingers(landmarks, handedness_label: str) -> int:
    fingers_up = []

    # Thumb: compare x, direction depends on hand
    if handedness_label == "Right":
        fingers_up.append(1 if landmarks[_TIP_IDS[0]].x < landmarks[_TIP_IDS[0] - 1].x else 0)
    else:
        fingers_up.append(1 if landmarks[_TIP_IDS[0]].x > landmarks[_TIP_IDS[0] - 1].x else 0)

    # Other 4 fingers: tip above the joint two below it = finger extended
    for tip_id in _TIP_IDS[1:]:
        fingers_up.append(1 if landmarks[tip_id].y < landmarks[tip_id - 2].y else 0)

    return sum(fingers_up)


def _draw_landmarks(image, landmarks):
    """Draws hand landmarks and connection lines on the frame."""
    h, w, _ = image.shape
    coords = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]

    # Draw connection lines
    for start_idx, end_idx in _HAND_CONNECTIONS:
        cv2.line(image, coords[start_idx], coords[end_idx], (0, 255, 0), 2)

    # Draw joint points
    for pt in coords:
        cv2.circle(image, pt, 5, (0, 0, 255), -1)


def _run_gesture_action(action: str):
    kind, _, value = action.partition(":")
    if kind == "open_url":
        sc.open_url(value)
    elif kind == "open_app":
        sc.open_app(value)
    elif kind == "run_command":
        sc.run_command(value)
    else:
        log(f"Unknown gesture action format: {action}", level="warning")


def process_frame(bgr_frame):
    """Runs hand detection on a frame; triggers configured actions on stable gesture."""
    global _last_trigger_time, _last_count

    if _detector is None:
        return bgr_frame

    try:
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        # RuntimeError/ValueError here typically mean the interpreter or the
        # MediaPipe graph is already tearing down (e.g. during Ctrl+C).
        results = _detector.detect(mp_image)
    except (RuntimeError, ValueError) as e:
        log(f"Hand detector unavailable, skipping frame: {e}", level="warning")
        return bgr_frame
    except Exception as e:
        log(f"Gesture detection error: {e}", level="warning")
        return bgr_frame

    finger_count = None
    if results.hand_landmarks and results.handedness:
        hand_landmarks = results.hand_landmarks[0]
        handedness = results.handedness[0][0].category_name
        finger_count = _count_fingers(hand_landmarks, handedness)

        _draw_landmarks(bgr_frame, hand_landmarks)
        push_event("gesture", {"fingers": finger_count})

    now = time.time()
    if finger_count is not None and finger_count in settings.GESTURE_ACTIONS:
        same_as_last = finger_count == _last_count
        cooled_down = (now - _last_trigger_time) > settings.GESTURE_DEBOUNCE_SECONDS
        if cooled_down and (not same_as_last or (now - _last_trigger_time) > settings.GESTURE_DEBOUNCE_SECONDS * 2):
            action = settings.GESTURE_ACTIONS[finger_count]
            log(f"Gesture detected: {finger_count} fingers -> {action}", channel="vision")
            _run_gesture_action(action)
            _last_trigger_time = now
            _last_count = finger_count

    return bgr_frame


def close():
    """Release the MediaPipe graph so worker threads stop before interpreter exit."""
    global _detector
    if _detector is not None:
        try:
            _detector.close()
        except Exception:
            pass
        _detector = None

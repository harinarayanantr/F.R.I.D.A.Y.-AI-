"""
Face detection + tracking with MediaPipe 1.0+ (always on when vision is enabled).
Optional named face recognition via the `face_recognition` library if
ENABLE_FACE_RECOGNITION=true and it's installed (heavier dependency, needs
dlib/cmake - see setup.sh).
"""
import urllib.request
from pathlib import Path
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from backend.config import settings
from backend.logger import log, push_event

# Ensure verified MediaPipe tflite model is downloaded
MODEL_PATH = Path("detector.tflite")
OFFICIAL_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)

if not MODEL_PATH.exists() or MODEL_PATH.stat().st_size < 100_000:
    try:
        log("Downloading official MediaPipe face detector TFLite model...", channel="vision")
        req = urllib.request.Request(
            OFFICIAL_MODEL_URL,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req) as response, open(MODEL_PATH, "wb") as out_file:
            out_file.write(response.read())
    except Exception as e:
        log(f"Could not download face detector model: {e}", level="error")

# Initialize MediaPipe 1.0+ Face Detector.
# Guarded: a missing/corrupt model must not take down the whole backend.
try:
    base_options = python.BaseOptions(model_asset_path=str(MODEL_PATH))
    options = vision.FaceDetectorOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.IMAGE,
        min_detection_confidence=0.6
    )
    _detector = vision.FaceDetector.create_from_options(options)
except Exception as e:
    _detector = None
    log(f"Face detector init failed - face tracking disabled ({e})", level="error")

KNOWN_FACES_DIR = settings.FRIDAY_WORKSPACE / "known_faces"
KNOWN_FACES_DIR.mkdir(exist_ok=True)

_face_recognition = None
_known_encodings = []
_known_names = []

if settings.ENABLE_FACE_RECOGNITION:
    try:
        import face_recognition as _face_recognition  # noqa

        for img_path in KNOWN_FACES_DIR.glob("*.*"):
            image = _face_recognition.load_image_file(str(img_path))
            encodings = _face_recognition.face_encodings(image)
            if encodings:
                _known_encodings.append(encodings[0])
                _known_names.append(img_path.stem)
        log(f"Loaded {len(_known_names)} known face(s) for recognition.", channel="vision")
    except ImportError:
        log(
            "ENABLE_FACE_RECOGNITION=true but `face_recognition` isn't installed. "
            "Uncomment it in requirements.txt and rerun setup.sh.",
            level="warning",
        )
        _face_recognition = None


def enroll_face(name: str, bgr_frame) -> str:
    """Save the current frame as a known face labelled `name` (for recognition)."""
    path = KNOWN_FACES_DIR / f"{name}.jpg"
    cv2.imwrite(str(path), bgr_frame)
    log(f"Enrolled new face: {name}", channel="vision")
    return f"Saved a reference photo for {name}. Restart FRIDAY to activate recognition of them."


def process_frame(bgr_frame):
    if _detector is None:
        return bgr_frame

    try:
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        # RuntimeError/ValueError here typically mean the interpreter or the
        # MediaPipe graph is already tearing down (e.g. during Ctrl+C).
        results = _detector.detect(mp_image)
    except (RuntimeError, ValueError) as e:
        log(f"Face detector unavailable, skipping frame: {e}", level="warning")
        return bgr_frame
    except Exception as e:
        log(f"Face detection error: {e}", level="warning")
        return bgr_frame

    faces_found = 0
    if results.detections:
        h, w, _ = bgr_frame.shape
        for detection in results.detections:
            faces_found += 1
            bbox = detection.bounding_box
            x, y = bbox.origin_x, bbox.origin_y
            bw, bh = bbox.width, bbox.height

            cv2.rectangle(bgr_frame, (x, y), (x + bw, y + bh), (0, 200, 255), 2)

            label = "Face"
            if _face_recognition is not None and _known_encodings:
                face_img = rgb[max(y, 0): y + bh, max(x, 0): x + bw]
                if face_img.size > 0:
                    encs = _face_recognition.face_encodings(face_img)
                    if encs:
                        matches = _face_recognition.compare_faces(_known_encodings, encs[0], tolerance=0.55)
                        if True in matches:
                            label = _known_names[matches.index(True)]

            cv2.putText(bgr_frame, label, (x, max(y - 8, 0)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)

        push_event("face", {"count": faces_found})

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

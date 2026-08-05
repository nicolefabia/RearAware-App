"""Model loading and inference, extracted from the original rearaware.py loop.

Runs the same custom-trained YOLO model (via ultralytics) used there, at the
same 640x360 input size. Kept as a separate module so main.py's loop only
deals with Detection objects, not model internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ultralytics import YOLO

INPUT_SIZE = (640, 360)  # (width, height), matches rearaware.py


@dataclass
class Box:
    x1: int
    y1: int
    x2: int
    y2: int
    score: float


class Detector:
    def __init__(self, model_path: Path):
        self.model = YOLO(str(model_path))
        self.model_version = model_path.stem

    def detect(self, frame, threshold: float) -> list[Box | None]:
        """Runs inference on `frame`, returns the best box per class
        ([cat, face, butt]) scaled back to frame's own pixel coordinates.
        """

        frame_h, frame_w = frame.shape[:2]
        small = _resize(frame, INPUT_SIZE)

        results = self.model(small, verbose=False)

        best: list[Box | None] = [None, None, None]

        for box in results[0].boxes:
            cls = int(box.cls[0])
            score = float(box.conf[0])

            if not (0 <= cls <= 2) or score < threshold:
                continue
            if best[cls] is not None and best[cls].score >= score:
                continue

            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
            scale_x = frame_w / INPUT_SIZE[0]
            scale_y = frame_h / INPUT_SIZE[1]

            best[cls] = Box(
                x1=int(x1 * scale_x), y1=int(y1 * scale_y),
                x2=int(x2 * scale_x), y2=int(y2 * scale_y),
                score=score,
            )

        return best


def _resize(frame, size: tuple[int, int]):
    import cv2

    return cv2.resize(frame, size)

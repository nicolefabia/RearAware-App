"""Sticker compositing and debug bounding-box drawing.

Three obfuscation modes, matching RearAware-Chrome's content.js STICKER_ASSETS:
standard (censored.png) and nicolas-cage (nicolascage.webp) are static images
with real alpha channels. all-seeing (sauron.webm) is a looping video - note
that OpenCV's VideoCapture doesn't decode per-pixel alpha out of webm the way
a browser's <video> element does, so here it's composited as a semi-transparent
rectangle rather than a shaped cutout. Good enough for v1; revisit if it looks
off in practice (e.g. by shipping an alpha PNG sequence instead of webm).
"""

from __future__ import annotations

import itertools
from pathlib import Path

import cv2
import numpy as np

from classes import DEBUG_CLASS_INFO
from detector import Box

STICKER_CONFIG = {
    "standard": {"type": "image", "file": "censored.png", "scale": 1.6},
    "all-seeing": {"type": "video", "file": "sauron.webm", "scale": 2.4, "opacity": 0.85},
    "nicolas-cage": {"type": "image", "file": "nicolascage.webp", "scale": 2.2},
}


class StickerLibrary:
    """Lazily loads and caches each mode's asset on first use."""

    def __init__(self, assets_dir: Path):
        self._assets_dir = assets_dir
        self._images: dict[str, tuple[np.ndarray, np.ndarray]] = {}  # mode -> (bgr, alpha 0..1)
        self._video_frames: dict[str, itertools.cycle] = {}

    def next_frame(self, mode: str) -> tuple[np.ndarray, np.ndarray]:
        """Returns (bgr, alpha) for one frame of `mode`'s sticker, alpha in [0, 1]."""

        config = STICKER_CONFIG.get(mode, STICKER_CONFIG["standard"])

        if config["type"] == "image":
            return self._load_image(mode, config)
        return self._next_video_frame(mode, config)

    def _load_image(self, mode: str, config: dict) -> tuple[np.ndarray, np.ndarray]:
        if mode not in self._images:
            path = self._assets_dir / config["file"]
            raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if raw is None:
                raise FileNotFoundError(f"couldn't load sticker asset: {path}")

            if raw.shape[2] == 4:
                bgr = raw[:, :, :3]
                alpha = raw[:, :, 3].astype(np.float32) / 255.0
            else:
                bgr = raw
                alpha = np.ones(raw.shape[:2], dtype=np.float32)

            self._images[mode] = (bgr, alpha)

        return self._images[mode]

    def _next_video_frame(self, mode: str, config: dict) -> tuple[np.ndarray, np.ndarray]:
        if mode not in self._video_frames:
            path = self._assets_dir / config["file"]
            cap = cv2.VideoCapture(str(path))
            frames = []
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                frames.append(frame)
            cap.release()

            if not frames:
                raise FileNotFoundError(f"couldn't decode any frames from: {path}")

            self._video_frames[mode] = itertools.cycle(frames)

        bgr = next(self._video_frames[mode])
        alpha = np.full(bgr.shape[:2], config.get("opacity", 0.85), dtype=np.float32)
        return bgr, alpha


def apply_sticker(frame: np.ndarray, box: Box, mode: str, library: StickerLibrary) -> None:
    """Composites the sticker for `mode` onto `frame` in place, centered on `box`
    and scaled to it (matches content.js's positionSticker sizing logic)."""

    bgr, alpha = library.next_frame(mode)
    scale = STICKER_CONFIG.get(mode, STICKER_CONFIG["standard"])["scale"]

    img_h, img_w = bgr.shape[:2]
    box_h = box.y2 - box.y1
    if box_h <= 0:
        return

    new_h = max(1, int(box_h * scale))
    new_w = max(1, int(new_h * (img_w / img_h)))

    resized_bgr = cv2.resize(bgr, (new_w, new_h))
    resized_alpha = cv2.resize(alpha, (new_w, new_h))

    cx, cy = (box.x1 + box.x2) // 2, (box.y1 + box.y2) // 2
    left = max(0, cx - new_w // 2)
    top = max(0, cy - new_h // 2)
    right = min(frame.shape[1], left + new_w)
    bottom = min(frame.shape[0], top + new_h)
    if right <= left or bottom <= top:
        return

    sticker_bgr = resized_bgr[: bottom - top, : right - left]
    sticker_alpha = resized_alpha[: bottom - top, : right - left, None]

    roi = frame[top:bottom, left:right]
    frame[top:bottom, left:right] = (sticker_alpha * sticker_bgr + (1 - sticker_alpha) * roi).astype(np.uint8)


def draw_debug_boxes(frame: np.ndarray, boxes: list[Box | None]) -> None:
    for info, box in zip(DEBUG_CLASS_INFO, boxes):
        if box is None:
            continue
        color = info["color"]
        cv2.rectangle(frame, (box.x1, box.y1), (box.x2, box.y2), color, 2)
        label = f"{info['name']} {box.score:.2f}"
        cv2.putText(
            frame, label, (box.x1, max(0, box.y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA,
        )

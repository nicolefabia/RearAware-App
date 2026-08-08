"""Local-only training-data capture pipeline.

On a rising-edge CAT_BUTT detection, main.py calls capture() with the current
frame and the CAT_00 (whole-cat) box - crops are limited to that box, never
the full frame, so bystanders/background outside the cat aren't captured.

This module only ever writes to a local queue directory - it does not upload
anything. Review and upload are handled entirely on the Electron side (see
desktop/src/main/contributions.js), which shows the user each captured crop
and only sends the ones they explicitly approve. Nothing leaves the device
without that per-image approval.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import cv2

from detector import Box
from protocol import emit

DAILY_CAPTURE_CAP = 50
JPEG_QUALITY = 90

# Anything still sitting unreviewed after this long gets deleted rather than
# accumulating forever - this is local-only data nobody has actively decided
# to keep, so it shouldn't just pile up indefinitely.
RETENTION_DAYS = 30


@dataclass
class CaptureMeta:
    model_version: str
    cat_score: float
    butt_score: float
    butt_box_relative: dict  # {x1,y1,x2,y2} in 0..1, position of the butt box within the crop
    captured_at: str


class ContributionPipeline:
    def __init__(self, queue_dir: Path):
        self.queue_dir = queue_dir
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self._state_path = queue_dir / "state.json"
        self._lock = threading.Lock()
        self._expire_stale_captures()

    def capture(self, frame, cat_box: Box, butt_box: Box, model_version: str) -> int | None:
        """Returns the new total queued (unreviewed) count, or None if this
        capture was skipped (daily cap reached, or a degenerate crop box)."""

        if not self._consume_daily_cap():
            return None

        x1, y1 = max(0, cat_box.x1), max(0, cat_box.y1)
        x2, y2 = min(frame.shape[1], cat_box.x2), min(frame.shape[0], cat_box.y2)
        if x2 <= x1 or y2 <= y1:
            return None

        # .copy() rather than a view: main.py already calls capture() before
        # any overlay drawing touches `frame`, but a plain slice would still
        # be a view into the same array - if a future change ever drew on
        # `frame` before this ran, the crop written below would silently
        # pick up those pixels too (exactly the bug this call ordering fixes
        # today). Cheap insurance against that regression.
        crop = frame[y1:y2, x1:x2].copy()

        # butt_box in coordinates relative to the crop, normalized 0..1 - lets
        # the review UI (and later, re-annotation in Ultralytics) start from a
        # pre-populated box instead of from scratch.
        crop_w, crop_h = x2 - x1, y2 - y1
        relative_butt_box = {
            "x1": max(0.0, (butt_box.x1 - x1) / crop_w),
            "y1": max(0.0, (butt_box.y1 - y1) / crop_h),
            "x2": min(1.0, (butt_box.x2 - x1) / crop_w),
            "y2": min(1.0, (butt_box.y2 - y1) / crop_h),
        }

        stamp = time.strftime("%Y%m%dT%H%M%S")
        base_name = f"{stamp}-{int(time.time() * 1000) % 1000:03d}"
        image_path = self.queue_dir / f"{base_name}.jpg"
        meta_path = self.queue_dir / f"{base_name}.json"

        cv2.imwrite(str(image_path), crop, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        meta = CaptureMeta(
            model_version=model_version,
            cat_score=cat_box.score,
            butt_score=butt_box.score,
            butt_box_relative=relative_butt_box,
            captured_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        meta_path.write_text(json.dumps(asdict(meta)))

        return self._pending_count()

    def _pending_count(self) -> int:
        return sum(1 for p in self.queue_dir.glob("*.json") if p.name != "state.json")

    def _consume_daily_cap(self) -> bool:
        with self._lock:
            today = date.today().isoformat()
            state = {"date": today, "captured_count": 0}
            if self._state_path.exists():
                try:
                    saved = json.loads(self._state_path.read_text())
                    if saved.get("date") == today:
                        state = saved
                except (json.JSONDecodeError, OSError):
                    pass

            if state["captured_count"] >= DAILY_CAPTURE_CAP:
                return False

            state["captured_count"] += 1
            self._state_path.write_text(json.dumps(state))
            return True

    def _expire_stale_captures(self) -> None:
        cutoff = time.time() - RETENTION_DAYS * 86400
        expired = 0

        for meta_path in self.queue_dir.glob("*.json"):
            if meta_path.name == "state.json":
                continue
            if meta_path.stat().st_mtime >= cutoff:
                continue

            meta_path.unlink(missing_ok=True)
            meta_path.with_suffix(".jpg").unlink(missing_ok=True)
            expired += 1

        if expired:
            emit({"type": "contribute_expired", "count": expired})

"""Opt-out training-data contribution pipeline.

On a rising-edge CAT_BUTT detection, main.py calls capture() with the current
frame and the CAT_00 (whole-cat) box - crops are limited to that box, never
the full frame, so bystanders/background outside the cat aren't captured.
Crops are written to a local pending-upload queue rather than uploaded inline,
so a slow or failed upload never blocks the real-time video loop; a background
thread drains the queue independently.

Uploads go to whatever REARAWARE_CONTRIBUTE_URL points at (the rearaware.com
app-contribute route, once it exists) with a shared secret in a header. That's
a weak form of auth on its own - an extracted secret could be used to spam the
endpoint - but everything here is manually reviewed before it ever reaches the
training set, so the worst case is a reviewer deleting junk.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import cv2
import requests

from detector import Box
from protocol import emit, log

DAILY_CAPTURE_CAP = 50
UPLOAD_INTERVAL_SECONDS = 30
MAX_UPLOAD_ATTEMPTS = 5
JPEG_QUALITY = 90


@dataclass
class CaptureMeta:
    model_version: str
    cat_score: float
    butt_score: float
    butt_box_relative: dict  # {x1,y1,x2,y2} in 0..1, position of the butt box within the crop
    captured_at: str
    attempts: int = 0


class ContributionPipeline:
    def __init__(self, queue_dir: Path):
        self.queue_dir = queue_dir
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self._state_path = queue_dir / "state.json"
        self._lock = threading.Lock()

        self._endpoint = os.environ.get("REARAWARE_CONTRIBUTE_URL")
        self._api_key = os.environ.get("REARAWARE_CONTRIBUTE_KEY")
        if not self._endpoint or not self._api_key:
            log(
                "REARAWARE_CONTRIBUTE_URL/KEY not set - contribution capture will "
                "queue locally but uploads will stay pending until configured."
            )

    # ---------------------------------------------------------------- capture

    def capture(self, frame, cat_box: Box, butt_box: Box, model_version: str) -> bool:
        if not self._consume_daily_cap():
            return False

        x1, y1 = max(0, cat_box.x1), max(0, cat_box.y1)
        x2, y2 = min(frame.shape[1], cat_box.x2), min(frame.shape[0], cat_box.y2)
        if x2 <= x1 or y2 <= y1:
            return False

        crop = frame[y1:y2, x1:x2]

        # butt_box in coordinates relative to the crop, normalized 0..1 -
        # lets a reviewer/annotator start from a pre-populated box.
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

        return True

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

    # ----------------------------------------------------------------- upload

    def start_uploader_thread(self) -> threading.Thread:
        thread = threading.Thread(target=self._upload_loop, name="contribute-uploader", daemon=True)
        thread.start()
        return thread

    def _upload_loop(self) -> None:
        while True:
            try:
                self._upload_pending_batch()
            except Exception as err:  # pragma: no cover - defensive, keep the thread alive
                log(f"contribution uploader error: {err}")
            time.sleep(UPLOAD_INTERVAL_SECONDS)

    def _upload_pending_batch(self) -> None:
        uploaded = failed = 0

        for meta_path in sorted(self.queue_dir.glob("*.json")):
            if meta_path.name == "state.json":
                continue

            image_path = meta_path.with_suffix(".jpg")
            if not image_path.exists():
                meta_path.unlink(missing_ok=True)
                continue

            if not self._endpoint or not self._api_key:
                continue  # stay queued until the backend is configured

            meta = json.loads(meta_path.read_text())
            if self._upload_one(image_path, meta):
                image_path.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                uploaded += 1
            else:
                meta["attempts"] = meta.get("attempts", 0) + 1
                if meta["attempts"] >= MAX_UPLOAD_ATTEMPTS:
                    log(f"dropping {image_path.name} after {meta['attempts']} failed upload attempts")
                    image_path.unlink(missing_ok=True)
                    meta_path.unlink(missing_ok=True)
                    failed += 1
                else:
                    meta_path.write_text(json.dumps(meta))

        remaining = sum(1 for p in self.queue_dir.glob("*.json") if p.name != "state.json")
        if uploaded or failed:
            emit({"type": "contribute_status", "queued": remaining, "uploaded": uploaded, "failed": failed})

    def _upload_one(self, image_path: Path, meta: dict) -> bool:
        try:
            with image_path.open("rb") as img_file:
                response = requests.post(
                    self._endpoint,
                    headers={"X-RearAware-Key": self._api_key},
                    files={"image": (image_path.name, img_file, "image/jpeg")},
                    data={"metadata": json.dumps(meta)},
                    timeout=15,
                )
            return response.ok
        except requests.RequestException as err:
            log(f"upload failed for {image_path.name}: {err}")
            return False

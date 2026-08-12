"""Temporal + spatial smoothing for the detected butt box.

Without this, the censor sticker snaps directly to whatever the model
returned on the most recent detection pass: if a single pass comes back
empty, the sticker vanishes immediately (even though the model runs every
2nd frame, so this can happen many times a second), and its position jumps
straight to each new detection's raw coordinates even though those wobble
frame to frame for a perfectly still subject. Both together read as
flickering. RearAware-Chrome's content.js already solved both of these for
the browser version - a grace period before actually hiding, and eased
position tracking rather than snapping - this ports the same two ideas here.
"""

from __future__ import annotations

import time

from detector import Box

GRACE_PERIOD_SECONDS = 1.0  # how long to keep showing the sticker after the last real detection
SMOOTHING_FACTOR = 0.1      # higher = snappier but jumpier, lower = smoother but more "laggy"


class BoxSmoother:
    def __init__(self) -> None:
        self._cx: float | None = None
        self._cy: float | None = None
        self._width: float | None = None
        self._height: float | None = None
        self._score = 0.0
        self._last_detection_time = 0.0

    def update(self, butt_box: Box | None) -> Box | None:
        """Call once per rendered frame with this tick's raw detection (or
        None if this tick didn't find one - including ticks where detection
        didn't even run, per DETECT_EVERY_N_FRAMES). Returns the box to
        actually render - held over and eased - or None if nothing should
        be shown right now."""

        now = time.time()

        if butt_box is not None:
            self._last_detection_time = now
            target_cx = (butt_box.x1 + butt_box.x2) / 2
            target_cy = (butt_box.y1 + butt_box.y2) / 2
            target_width = butt_box.x2 - butt_box.x1
            target_height = butt_box.y2 - butt_box.y1
            target_score = butt_box.score
        elif self._cx is not None and now - self._last_detection_time < GRACE_PERIOD_SECONDS:
            # Within the grace window since the last real detection - hold
            # at the last known position (easing toward itself is a no-op)
            # rather than disappearing on a single missed pass.
            target_cx, target_cy = self._cx, self._cy
            target_width, target_height = self._width, self._height
            target_score = self._score
        else:
            self._cx = None
            return None

        if self._cx is None:
            self._cx, self._cy = target_cx, target_cy
            self._width, self._height = target_width, target_height
        else:
            self._cx += (target_cx - self._cx) * SMOOTHING_FACTOR
            self._cy += (target_cy - self._cy) * SMOOTHING_FACTOR
            self._width += (target_width - self._width) * SMOOTHING_FACTOR
            self._height += (target_height - self._height) * SMOOTHING_FACTOR
        self._score = target_score

        return Box(
            x1=int(self._cx - self._width / 2), y1=int(self._cy - self._height / 2),
            x2=int(self._cx + self._width / 2), y2=int(self._cy + self._height / 2),
            score=self._score,
        )

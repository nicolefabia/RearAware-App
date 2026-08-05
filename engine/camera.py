"""Webcam capture + virtual camera output.

Fixes a bug present in the original rearaware.py: it read the real webcam
resolution but then hardcoded the virtual camera to 1920x1080 regardless,
so on any webcam that isn't exactly that resolution, frames sent to
pyvirtualcam wouldn't match the camera's declared size. This uses the
webcam's actual resolution for both.

Some webcams also don't hold a steady resolution: the first frame(s) read
right after opening can be a different size than what the camera settles
into once it's actually streaming (observed in testing: 1920x1080 on the
first read, 1280x720 from then on). pyvirtualcam's declared size is fixed
once the camera is created, so send_frame() defensively resizes any frame
that doesn't match rather than assuming the first read was representative.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import pyvirtualcam


@dataclass
class CameraSession:
    capture: cv2.VideoCapture
    virtual_cam: pyvirtualcam.Camera
    width: int
    height: int

    def read_frame(self):
        ok, frame = self.capture.read()
        return frame if ok else None

    def send_frame(self, frame) -> None:
        if frame.shape[0] != self.height or frame.shape[1] != self.width:
            frame = cv2.resize(frame, (self.width, self.height))
        self.virtual_cam.send(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        self.virtual_cam.sleep_until_next_frame()

    def close(self) -> None:
        self.capture.release()
        self.virtual_cam.close()


def open_camera_session(device_index: int = 0, fps: int = 30, warmup_frames: int = 10) -> CameraSession:
    capture = cv2.VideoCapture(device_index)
    time.sleep(1)  # some webcams need a moment to warm up before the first read

    # Discard a few frames before trusting the resolution - some webcams report
    # one size on the very first read(s) and settle into a different one once
    # actually streaming (send_frame() also guards against this at runtime).
    frame = None
    for _ in range(warmup_frames):
        ok, frame = capture.read()
        if not ok:
            capture.release()
            raise RuntimeError("couldn't read from webcam")

    height, width = frame.shape[:2]
    virtual_cam = pyvirtualcam.Camera(width=width, height=height, fps=fps)

    return CameraSession(capture=capture, virtual_cam=virtual_cam, width=width, height=height)

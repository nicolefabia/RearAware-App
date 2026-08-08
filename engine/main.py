"""RearAware detection sidecar entry point.

Spawned by the Electron main process. Owns the whole capture -> detect ->
overlay -> virtual-camera loop plus (when enabled) the contribution-capture
pipeline. Controlled entirely over stdin/stdout JSON - see protocol.py.

Run standalone for local testing:
    python engine/main.py
then type a JSON settings line and press enter, e.g.:
    {"type": "settings", "obfuscation": "nicolas-cage", "debugEnabled": true}
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from camera import open_camera_session  # noqa: E402
from classes import CAT_BUTT  # noqa: E402
from contribute import ContributionPipeline  # noqa: E402
from detector import Detector  # noqa: E402
from overlay import StickerLibrary, apply_sticker, draw_debug_boxes  # noqa: E402
from protocol import emit, log, start_command_listener  # noqa: E402
from settings import Settings  # noqa: E402
from sounds import play_random_sound  # noqa: E402

# Read-only bundled resources (model weights, sticker/sound assets). In a
# PyInstaller build these are extracted to sys._MEIPASS at runtime, not
# sitting next to this file the way they are when run from source.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

MODEL_PATH = BASE_DIR / "models" / "30-cfb.pt"
ASSETS_DIR = BASE_DIR / "assets"

# Writable queue dir, unlike the read-only resources above. Electron is the
# source of truth for this (app.getPath("userData"), the standard per-OS
# user-data location) and passes it via env var when it spawns this process -
# see desktop/src/main/sidecar.js. The fallback below only applies when
# running this file directly for standalone testing, without Electron.
QUEUE_DIR = (
    Path(os.environ["REARAWARE_QUEUE_DIR"])
    if "REARAWARE_QUEUE_DIR" in os.environ
    else Path(__file__).resolve().parent / "queue" / "pending"
)

DETECT_EVERY_N_FRAMES = 2       # mirrors rearaware.py's frame skip
SOUND_COOLDOWN_SECONDS = 3.0
STATUS_EVERY_N_FRAMES = 45      # ~1.5s at 30fps, keeps stdout quiet


CAMERA_RETRY_SECONDS = 1.0  # backoff between open attempts while detection is on but the camera failed
IDLE_SLEEP_SECONDS = 0.1    # avoids a tight busy-loop while detection is off and there's no camera to read


class Engine:
    def __init__(self) -> None:
        self.settings = Settings()
        self._settings_lock = threading.Lock()
        self._running = True

        self.detector = Detector(MODEL_PATH)
        self.stickers = StickerLibrary(ASSETS_DIR)
        self.contribution = ContributionPipeline(QUEUE_DIR)
        # Opened lazily, only while detection is actually enabled - not held
        # for as long as the engine process merely exists. Otherwise the
        # webcam (and its indicator light) stay active the whole time
        # RearAware is running quietly in the background, whether or not
        # anyone's actually in a call.
        self.camera = None
        self._last_camera_attempt = 0.0

        self._last_results = [None, None, None]
        self._butt_was_visible = False
        self._last_sound_time = 0.0
        self._frame_count = 0

    def apply_command(self, command: dict) -> None:
        if command.get("type") == "settings":
            with self._settings_lock:
                self.settings = self.settings.updated(command)
            log(f"settings updated: {self.settings}")
        elif command.get("type") == "shutdown":
            self._running = False

    def current_settings(self) -> Settings:
        with self._settings_lock:
            return self.settings

    def run(self) -> None:
        emit({"type": "ready"})
        log("engine ready")

        try:
            while self._running:
                self._tick()
        finally:
            self._release_camera()
            log("engine stopped")

    def _open_camera(self) -> bool:
        try:
            self.camera = open_camera_session()
        except Exception as err:
            self.camera = None
            emit({"type": "error", "message": str(err)})
            log(f"couldn't open camera, will retry: {err}")
            return False

        device_name = self.camera.virtual_cam.device
        emit({"type": "camera_active", "virtualCameraDevice": device_name})
        log(f"camera active - select '{device_name}' as your camera in the meeting app")
        return True

    def _release_camera(self) -> None:
        if self.camera is None:
            return
        self.camera.close()
        self.camera = None
        # Otherwise a quick off-then-on toggle could be delayed by up to
        # CAMERA_RETRY_SECONDS of leftover backoff state from the *previous*
        # (successful, unrelated) open attempt.
        self._last_camera_attempt = 0.0
        emit({"type": "camera_released"})
        log("camera released")

    def _tick(self) -> None:
        settings = self.current_settings()

        if not settings.detectionEnabled:
            self._release_camera()
            time.sleep(IDLE_SLEEP_SECONDS)
            return

        if self.camera is None:
            now = time.time()
            if now - self._last_camera_attempt < CAMERA_RETRY_SECONDS:
                time.sleep(IDLE_SLEEP_SECONDS)
                return
            self._last_camera_attempt = now
            if not self._open_camera():
                return

        frame = self.camera.read_frame()
        if frame is None:
            return

        self._frame_count += 1

        if self._frame_count % DETECT_EVERY_N_FRAMES == 0:
            self._last_results = self.detector.detect(frame, settings.score_threshold)

        cat_box, _face_box, butt_box = self._last_results

        # Computed once, before either handler below runs, and butt_was_visible
        # is only updated once at the end of this tick - both handlers need to
        # see "did this just newly appear," not "is it visible right now."
        detected = butt_box is not None
        is_rising_edge = detected and not self._butt_was_visible

        # Must run before the overlay drawing below - apply_sticker() and
        # draw_debug_boxes() both mutate `frame` in place, and a contribution
        # capture needs the actual raw detected cat, not our own censor
        # sticker (or debug boxes) painted over it.
        self._handle_contribution(settings, frame, cat_box, butt_box, is_rising_edge)

        if settings.debugEnabled:
            draw_debug_boxes(frame, self._last_results)
        elif butt_box is not None:
            apply_sticker(frame, butt_box, settings.obfuscation, self.stickers)

        self._handle_sound(settings, is_rising_edge)
        self._emit_status(settings)

        self._butt_was_visible = detected

        self.camera.send_frame(frame)

    def _handle_sound(self, settings: Settings, is_rising_edge: bool) -> None:
        now = time.time()

        if (
            is_rising_edge
            and settings.soundEnabled
            and now - self._last_sound_time > SOUND_COOLDOWN_SECONDS
        ):
            play_random_sound(ASSETS_DIR)
            self._last_sound_time = now

    def _handle_contribution(self, settings: Settings, frame, cat_box, butt_box, is_rising_edge: bool) -> None:
        # Rising-edge only (mirrors the sound logic above) - one capture per
        # detection episode, not one per frame.
        if not settings.contributeEnabled or not is_rising_edge:
            return
        if cat_box is None:
            return  # nothing to crop to this frame

        queued_count = self.contribution.capture(frame, cat_box, butt_box, self.detector.model_version)
        if queued_count is not None:
            emit({"type": "contribute_captured", "queued": queued_count})

    def _emit_status(self, settings: Settings) -> None:
        if self._frame_count % STATUS_EVERY_N_FRAMES != 0:
            return

        scores = {
            name: (box.score if box else None)
            for name, box in zip(["cat", "face", "butt"], self._last_results)
        }
        emit({"type": "status", "detected": self._last_results[CAT_BUTT] is not None, "scores": scores})


def main() -> None:
    try:
        engine = Engine()

        def handle_command(command: dict) -> None:
            engine.apply_command(command)

        start_command_listener(handle_command)

        def handle_signal(signum, frame) -> None:  # noqa: ARG001
            engine.apply_command({"type": "shutdown"})

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        engine.run()
    except Exception as err:
        # Covers Engine() construction failing (e.g. camera/virtual-cam setup)
        # as well as a failure during run() - either way, the sidecar process
        # is about to exit, and Electron's console should show *why* rather
        # than just a bare non-zero exit code.
        emit({"type": "error", "message": str(err)})
        log(f"fatal: {err}")
        raise


if __name__ == "__main__":
    main()

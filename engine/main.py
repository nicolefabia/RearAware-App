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
from smoothing import BoxSmoother  # noqa: E402
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
        self.box_smoother = BoxSmoother()
        # Opened lazily, only while detection is actually enabled - not held
        # for as long as the engine process merely exists. Otherwise the
        # webcam (and its indicator light) stay active the whole time
        # RearAware is running quietly in the background, whether or not
        # anyone's actually in a call.
        self.camera = None
        self._last_camera_attempt = 0.0

        # Guards _last_results and _detect_busy, both written from the
        # background detection thread spawned by _maybe_submit_detection()
        # and read from the main tick loop.
        self._detect_lock = threading.Lock()
        self._detect_busy = False
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

    def _maybe_submit_detection(self, frame, score_threshold: float) -> None:
        # Model inference is the one variably-slow step in this loop - run it
        # off the main thread so it can never delay a frame that's about to
        # be sent to the virtual camera. Without this, send() timing
        # alternates between "fast tick" (no detection) and "slow tick"
        # (detection), and that irregular delivery cadence is what several
        # meeting apps' own auto-exposure/background-effects processing
        # visibly reacts to as flicker - a real virtual camera (e.g. OBS's)
        # never has this problem because its capture/output pipeline is
        # decoupled from any per-frame ML work the way this one now is.
        with self._detect_lock:
            if self._detect_busy:
                return  # previous detection still running - use last results, don't pile up work
            self._detect_busy = True

        frame_for_detection = frame.copy()  # this tick's frame is about to be mutated (sticker) and sent

        def _run() -> None:
            try:
                results = self.detector.detect(frame_for_detection, score_threshold)
                with self._detect_lock:
                    self._last_results = results
            finally:
                with self._detect_lock:
                    self._detect_busy = False

        threading.Thread(target=_run, daemon=True).start()

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
            self._maybe_submit_detection(frame, settings.score_threshold)

        with self._detect_lock:
            last_results = self._last_results
        cat_box, _face_box, butt_box = last_results

        # Held over across brief gaps in raw detection and eased toward its
        # target position every tick (not just detection ticks), so the
        # sticker doesn't flicker off or jump around between passes - see
        # smoothing.py. Rising-edge tracking below is based on this smoothed
        # presence (what the user actually perceives), not the raw per-tick
        # result, so sound/capture fire once per visible episode rather than
        # once per raw detection blip within it.
        smoothed_butt_box = self.box_smoother.update(butt_box)

        # Computed once, before either handler below runs, and butt_was_visible
        # is only updated once at the end of this tick - both handlers need to
        # see "did this just newly appear," not "is it visible right now."
        detected = smoothed_butt_box is not None
        is_rising_edge = detected and not self._butt_was_visible

        # Must run before the overlay drawing below - apply_sticker() and
        # draw_debug_boxes() both mutate `frame` in place, and a contribution
        # capture needs the actual raw detected cat, not our own censor
        # sticker (or debug boxes) painted over it. Uses the raw butt_box
        # (not smoothed) since it's a one-shot crop, not a rendered overlay -
        # the real detection is what's worth keeping for training.
        self._handle_contribution(settings, frame, cat_box, butt_box, is_rising_edge)

        if settings.debugEnabled:
            draw_debug_boxes(frame, last_results)
        elif smoothed_butt_box is not None:
            apply_sticker(frame, smoothed_butt_box, settings.obfuscation, self.stickers)

        self._handle_sound(settings, is_rising_edge)
        self._emit_status(last_results)

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

    def _emit_status(self, last_results) -> None:
        if self._frame_count % STATUS_EVERY_N_FRAMES != 0:
            return

        scores = {
            name: (box.score if box else None)
            for name, box in zip(["cat", "face", "butt"], last_results)
        }
        emit({"type": "status", "detected": last_results[CAT_BUTT] is not None, "scores": scores})


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

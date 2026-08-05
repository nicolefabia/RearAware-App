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

import signal
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from camera import open_camera_session  # noqa: E402
from classes import CAT_BUTT  # noqa: E402
from contribute import ContributionPipeline  # noqa: E402
from detector import Detector  # noqa: E402
from overlay import StickerLibrary, apply_sticker, draw_debug_boxes  # noqa: E402
from protocol import emit, log, start_command_listener  # noqa: E402
from settings import Settings  # noqa: E402
from sounds import play_random_sound  # noqa: E402

MODEL_PATH = BASE_DIR / "models" / "30-cfb.pt"
ASSETS_DIR = BASE_DIR / "assets"
QUEUE_DIR = BASE_DIR / "engine" / "queue" / "pending"

DETECT_EVERY_N_FRAMES = 2       # mirrors rearaware.py's frame skip
SOUND_COOLDOWN_SECONDS = 3.0
STATUS_EVERY_N_FRAMES = 45      # ~1.5s at 30fps, keeps stdout quiet


class Engine:
    def __init__(self) -> None:
        self.settings = Settings()
        self._settings_lock = threading.Lock()
        self._running = True

        self.detector = Detector(MODEL_PATH)
        self.stickers = StickerLibrary(ASSETS_DIR)
        self.contribution = ContributionPipeline(QUEUE_DIR)
        self.camera = open_camera_session()

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
        self.contribution.start_uploader_thread()
        device_name = self.camera.virtual_cam.device
        emit({"type": "ready", "virtualCameraDevice": device_name})
        log(f"engine ready - select '{device_name}' as your camera in the meeting app")

        try:
            while self._running:
                self._tick()
        finally:
            self.camera.close()
            log("engine stopped")

    def _tick(self) -> None:
        settings = self.current_settings()
        frame = self.camera.read_frame()
        if frame is None:
            return

        self._frame_count += 1

        if not settings.detectionEnabled:
            self.camera.send_frame(frame)
            return

        if self._frame_count % DETECT_EVERY_N_FRAMES == 0:
            self._last_results = self.detector.detect(frame, settings.score_threshold)

        cat_box, _face_box, butt_box = self._last_results

        if settings.debugEnabled:
            draw_debug_boxes(frame, self._last_results)
        elif butt_box is not None:
            apply_sticker(frame, butt_box, settings.obfuscation, self.stickers)

        self._handle_sound(settings, butt_box)
        self._handle_contribution(settings, frame, cat_box, butt_box)
        self._emit_status(settings)

        self.camera.send_frame(frame)

    def _handle_sound(self, settings: Settings, butt_box) -> None:
        detected = butt_box is not None
        now = time.time()

        if (
            detected
            and not self._butt_was_visible
            and settings.soundEnabled
            and now - self._last_sound_time > SOUND_COOLDOWN_SECONDS
        ):
            play_random_sound(ASSETS_DIR)
            self._last_sound_time = now

        self._butt_was_visible = detected

    def _handle_contribution(self, settings: Settings, frame, cat_box, butt_box) -> None:
        # Rising-edge only (mirrors the sound logic above) - one capture per
        # detection episode, not one per frame.
        if not settings.contributeEnabled:
            return
        if butt_box is None or cat_box is None:
            return
        if self._butt_was_visible:  # already captured this episode
            return

        self.contribution.capture(frame, cat_box, butt_box, self.detector.model_version)

    def _emit_status(self, settings: Settings) -> None:
        if self._frame_count % STATUS_EVERY_N_FRAMES != 0:
            return

        scores = {
            name: (box.score if box else None)
            for name, box in zip(["cat", "face", "butt"], self._last_results)
        }
        emit({"type": "status", "detected": self._last_results[CAT_BUTT] is not None, "scores": scores})


def main() -> None:
    engine = Engine()

    def handle_command(command: dict) -> None:
        engine.apply_command(command)

    start_command_listener(handle_command)

    def handle_signal(signum, frame) -> None:  # noqa: ARG001
        engine.apply_command({"type": "shutdown"})

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        engine.run()
    except Exception as err:
        emit({"type": "error", "message": str(err)})
        log(f"fatal: {err}")
        raise


if __name__ == "__main__":
    main()

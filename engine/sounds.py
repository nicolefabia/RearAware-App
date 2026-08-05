"""Random detection sound effects, played without blocking the capture loop.

rearaware.py originally shelled out to macOS's `afplay`, which doesn't exist
on Windows. pygame's mixer plays both .wav and .mp3 on macOS and Windows
without extra system dependencies, so it replaces that approach here.
"""

from __future__ import annotations

import random
import threading
from pathlib import Path

from protocol import log

SOUND_FILENAMES = [
    "duck.wav", "fart1.wav", "fart2.wav", "fart3.wav", "fart4.wav",
    "fart5.wav", "fart6.wav", "fart7.wav", "fart8.wav", "fart9.wav",
    "fart10.wav", "fart11.wav", "fart12.wav",
    "law-and-order.wav", "mgs-alert.wav", "psycho.wav", "wasted.wav",
    "wilhelm.wav", "windows-error.wav",
]

_mixer_ready = False
_mixer_lock = threading.Lock()


def _ensure_mixer() -> bool:
    global _mixer_ready

    if _mixer_ready:
        return True

    with _mixer_lock:
        if _mixer_ready:
            return True
        try:
            import pygame

            pygame.mixer.init()
            _mixer_ready = True
        except Exception as err:  # pragma: no cover - environment dependent
            log(f"sound disabled, mixer init failed: {err}")

    return _mixer_ready


def play_random_sound(assets_dir: Path) -> None:
    """Fire-and-forget: plays a random sound on a background thread."""

    def _play() -> None:
        if not _ensure_mixer():
            return

        import pygame

        sound_path = assets_dir / "sounds" / random.choice(SOUND_FILENAMES)
        try:
            pygame.mixer.Sound(str(sound_path)).play()
        except Exception as err:  # pragma: no cover - bad/missing file
            log(f"failed to play sound {sound_path.name}: {err}")

    threading.Thread(target=_play, daemon=True).start()

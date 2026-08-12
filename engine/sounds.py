"""Random detection sound effects, played without blocking the capture loop.

Uses each OS's own built-in playback mechanism rather than a Python audio
library - afplay on macOS, the Windows Multimedia (MCI) API on Windows via
ctypes. Both ship with the OS itself, so there's nothing extra to bundle -
notably no SDL2, which is what pygame (the previous approach here) needed.
That turned into a real, confirmed bug: opencv's bundled ffmpeg and pygame's
mixer both depend on a same-named-but-different-version copy of libSDL2, and
PyInstaller's packaging only keeps one physical file when two packages
reference the same destination name - it kept opencv's older copy, and
pygame's mixer refuses to initialize against an SDL2 older than what it was
compiled against, so sound silently failed in every packaged build. Dropping
pygame removes the conflict entirely instead of patching around it.
"""

from __future__ import annotations

import random
import subprocess
import sys
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


def _play_macos(path: Path) -> None:
    subprocess.run(
        ["afplay", str(path)],
        check=True,
        capture_output=True,
        timeout=15,
    )


def _play_windows(path: Path) -> None:
    import ctypes

    # MCI (Media Control Interface) - built into Windows since forever, plays
    # both .wav and .mp3 without any extra dependency. Each call needs a
    # unique alias since multiple sounds can legitimately overlap (fired from
    # different background threads) and MCI aliases are process-global.
    winmm = ctypes.windll.winmm  # type: ignore[attr-defined]
    alias = f"rearaware_{threading.get_ident()}_{id(path)}"

    def _mci(command: str) -> None:
        buf = ctypes.create_unicode_buffer(128)
        error = winmm.mciSendStringW(command, buf, len(buf), None)
        if error:
            raise OSError(f"MCI command failed ({error}): {command}")

    try:
        _mci(f'open "{path}" alias {alias}')
        _mci(f"play {alias} wait")
    finally:
        _mci(f"close {alias}")


def play_random_sound(assets_dir: Path) -> None:
    """Fire-and-forget: plays a random sound on a background thread."""

    def _play() -> None:
        sound_path = assets_dir / "sounds" / random.choice(SOUND_FILENAMES)
        try:
            if sys.platform == "darwin":
                _play_macos(sound_path)
            elif sys.platform == "win32":
                _play_windows(sound_path)
            else:
                log(f"sound not supported on this platform ({sys.platform})")
        except Exception as err:  # pragma: no cover - best-effort, never fatal
            log(f"failed to play sound {sound_path.name}: {err}")

    threading.Thread(target=_play, daemon=True).start()

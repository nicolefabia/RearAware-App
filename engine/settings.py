"""Settings schema shared with the Electron settings window.

Mirrors the field names used by RearAware-Chrome's popup.js DEFAULTS, so the
Electron renderer can reuse that schema almost as-is. `contributeEnabled` is
new here and has no Chrome-extension equivalent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


VALID_OBFUSCATION_MODES = {"standard", "all-seeing", "nicolas-cage"}


@dataclass(frozen=True)
class Settings:
    detectionEnabled: bool = True
    confidence: int = 22          # 0-100, matches the popup slider's percentage
    obfuscation: str = "standard"
    soundEnabled: bool = True
    debugEnabled: bool = False
    contributeEnabled: bool = True  # on by default; user can switch off in settings

    @property
    def score_threshold(self) -> float:
        return self.confidence / 100

    def updated(self, patch: dict[str, Any]) -> "Settings":
        """Returns a new Settings with only the recognized, valid fields applied."""

        clean: dict[str, Any] = {}

        if "detectionEnabled" in patch:
            clean["detectionEnabled"] = bool(patch["detectionEnabled"])
        if "confidence" in patch:
            clean["confidence"] = max(0, min(100, int(patch["confidence"])))
        if "obfuscation" in patch and patch["obfuscation"] in VALID_OBFUSCATION_MODES:
            clean["obfuscation"] = patch["obfuscation"]
        if "soundEnabled" in patch:
            clean["soundEnabled"] = bool(patch["soundEnabled"])
        if "debugEnabled" in patch:
            clean["debugEnabled"] = bool(patch["debugEnabled"])
        if "contributeEnabled" in patch:
            clean["contributeEnabled"] = bool(patch["contributeEnabled"])

        return replace(self, **clean)

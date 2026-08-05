"""Newline-delimited JSON protocol between this sidecar and the Electron main process.

Commands come in on stdin, one JSON object per line:
    {"type": "settings", "confidence": 30, ...}   - partial or full settings patch
    {"type": "shutdown"}                          - clean stop

Events go out on stdout, one JSON object per line:
    {"type": "ready"}
    {"type": "status", "detected": bool, "scores": {...}, "backend": "..."}
    {"type": "contribute_status", "queued": N, "uploaded": N, "failed": N}
    {"type": "error", "message": "..."}

stdout is reserved for this protocol - all logging goes to stderr instead.
"""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable, Iterator


def read_commands() -> Iterator[dict]:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as err:
            log(f"ignoring malformed command: {err}")


def emit(event: dict) -> None:
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def log(message: str) -> None:
    sys.stderr.write(f"[engine] {message}\n")
    sys.stderr.flush()


def start_command_listener(on_command: Callable[[dict], None]) -> threading.Thread:
    """Runs read_commands() on a background thread, invoking on_command for each.

    stdin reads block, so this has to live on its own thread - the main loop
    keeps processing frames while commands trickle in independently.
    """

    def _run() -> None:
        for command in read_commands():
            on_command(command)

    thread = threading.Thread(target=_run, name="command-listener", daemon=True)
    thread.start()
    return thread

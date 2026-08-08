// Spawns and supervises the Python detection engine (engine/main.py in dev,
// a PyInstaller-built executable once Phase 4 packaging exists). Talks to it
// over the newline-delimited JSON protocol defined in engine/protocol.py:
// we write "settings"/"shutdown" commands to its stdin, it writes
// "ready"/"status"/"contribute_status"/"error" events to its stdout.

const { spawn } = require("child_process");
const path = require("path");
const readline = require("readline");
const { EventEmitter } = require("events");
const { app } = require("electron");
const { getQueueDir } = require("./paths");

const RESTART_DELAY_MS = 2000;
const MAX_RESTART_DELAY_MS = 30_000;
const MAX_CONSECUTIVE_FAILURES = 5;
// A run has to survive this long before a later failure resets the backoff -
// otherwise one bad run right after a long healthy stretch would be treated
// the same as failing five times in a row (which is when we give up).
const HEALTHY_UPTIME_MS = 10_000;

// stop()'s shutdown escalation: ask nicely (JSON "shutdown" message) first,
// then SIGTERM, then - only if the process is truly stuck - SIGKILL. Each
// stage gets real time to actually release the camera/virtual-cam handles
// before the next, harsher stage fires.
const GRACEFUL_TIMEOUT_MS = 1500;
const SIGTERM_TIMEOUT_MS = 3000;

class Sidecar extends EventEmitter {
  constructor() {
    super();
    this._process = null;
    this._shuttingDown = false;
    this._consecutiveFailures = 0;
    this._startedAt = 0;
  }

  start() {
    this._shuttingDown = false;
    this._consecutiveFailures = 0;
    this._spawn();
  }

  _spawn() {
    const { command, args } = this._resolveCommand();
    const child = spawn(command, args, {
      cwd: path.join(__dirname, "..", "..", ".."),
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, REARAWARE_QUEUE_DIR: getQueueDir() },
    });
    this._process = child;
    this._startedAt = Date.now();

    const stdoutLines = readline.createInterface({ input: child.stdout });
    stdoutLines.on("line", (line) => this._handleLine(line));

    child.stderr.on("data", (chunk) => {
      // The engine logs to stderr, not stdout (stdout is reserved for the
      // protocol) - forward it to the main process's own console for now.
      process.stderr.write(`[engine] ${chunk}`);
    });

    child.on("exit", (code, signal) => {
      this.emit("exit", { code, signal });
      if (this._shuttingDown) return;

      const survivedLongEnough = Date.now() - this._startedAt >= HEALTHY_UPTIME_MS;
      this._consecutiveFailures = survivedLongEnough ? 0 : this._consecutiveFailures + 1;

      if (this._consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
        // Something's persistently wrong (camera busy, permissions, etc.) -
        // retrying forever every couple seconds just churns the camera
        // further. Stop and let the app surface this so a human can look,
        // rather than silently crash-looping in the background.
        this.emit("giveup");
        return;
      }

      const delay = Math.min(RESTART_DELAY_MS * 2 ** (this._consecutiveFailures - 1), MAX_RESTART_DELAY_MS);
      setTimeout(() => this._spawn(), delay);
    });

    child.on("error", (err) => {
      this.emit("error", err);
      // A spawn-level error (e.g. "python3" not found) isn't reliably
      // followed by an 'exit' event on every platform, so the backoff/retry
      // logic above can't be counted on to run. Unlike a runtime crash,
      // retrying this is very unlikely to help - go straight to the
      // "needs a human" state rather than sitting in silent limbo.
      if (!this._shuttingDown) this.emit("giveup");
    });
  }

  _resolveCommand() {
    if (app.isPackaged) {
      // Phase 4: PyInstaller-built executable bundled as an extraResource.
      const exeName = process.platform === "win32" ? "rearaware-engine.exe" : "rearaware-engine";
      return { command: path.join(process.resourcesPath, "engine", exeName), args: [] };
    }

    const pythonCommand = process.platform === "win32" ? "python" : "python3";
    return { command: pythonCommand, args: [path.join(__dirname, "..", "..", "..", "engine", "main.py")] };
  }

  _handleLine(line) {
    if (!line.trim()) return;
    let event;
    try {
      event = JSON.parse(line);
    } catch {
      return; // ignore anything that isn't valid JSON (e.g. stray prints)
    }
    this.emit("event", event);
  }

  sendSettings(settings) {
    this._write({ type: "settings", ...settings });
  }

  _write(message) {
    if (!this._process || !this._process.stdin.writable) return;
    this._process.stdin.write(JSON.stringify(message) + "\n");
  }

  // Restarts a sidecar that gave up after repeated failures (e.g. once the
  // user has freed up the camera) without requiring a full app relaunch.
  restart() {
    this.start();
  }

  stop() {
    this._shuttingDown = true;
    const proc = this._process;
    if (!proc || proc.exitCode !== null) return;

    this._write({ type: "shutdown" });

    const sigtermTimer = setTimeout(() => {
      if (proc.exitCode === null) proc.kill("SIGTERM");
    }, GRACEFUL_TIMEOUT_MS);

    const sigkillTimer = setTimeout(() => {
      if (proc.exitCode === null) proc.kill("SIGKILL");
    }, GRACEFUL_TIMEOUT_MS + SIGTERM_TIMEOUT_MS);

    proc.once("exit", () => {
      clearTimeout(sigtermTimer);
      clearTimeout(sigkillTimer);
    });
  }
}

module.exports = { Sidecar };

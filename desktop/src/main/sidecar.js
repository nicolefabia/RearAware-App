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

const RESTART_DELAY_MS = 2000;

class Sidecar extends EventEmitter {
  constructor() {
    super();
    this._process = null;
    this._shuttingDown = false;
  }

  start() {
    this._shuttingDown = false;
    this._spawn();
  }

  _spawn() {
    const { command, args } = this._resolveCommand();
    const child = spawn(command, args, {
      cwd: path.join(__dirname, "..", "..", ".."),
      stdio: ["pipe", "pipe", "pipe"],
    });
    this._process = child;

    const stdoutLines = readline.createInterface({ input: child.stdout });
    stdoutLines.on("line", (line) => this._handleLine(line));

    child.stderr.on("data", (chunk) => {
      // The engine logs to stderr, not stdout (stdout is reserved for the
      // protocol) - forward it to the main process's own console for now.
      process.stderr.write(`[engine] ${chunk}`);
    });

    child.on("exit", (code, signal) => {
      this.emit("exit", { code, signal });
      if (!this._shuttingDown) {
        setTimeout(() => this._spawn(), RESTART_DELAY_MS);
      }
    });

    child.on("error", (err) => {
      this.emit("error", err);
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

  stop() {
    this._shuttingDown = true;
    if (this._process) {
      this._write({ type: "shutdown" });
      // Give it a moment to exit cleanly before a hard kill.
      const proc = this._process;
      setTimeout(() => {
        if (!proc.killed) proc.kill();
      }, 1500);
    }
  }
}

module.exports = { Sidecar };

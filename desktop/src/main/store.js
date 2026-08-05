// Minimal JSON-file settings store. A dedicated dependency (electron-store)
// wasn't worth pulling in for half a dozen flat fields - this is the whole
// thing: read on startup, write on every change, defaults for anything missing.

const fs = require("fs");
const path = require("path");
const { app } = require("electron");

const DEFAULTS = {
  detectionEnabled: true,
  confidence: 22,
  obfuscation: "standard",
  soundEnabled: true,
  debugEnabled: false,
  contributeEnabled: true, // on by default; user can switch off
  openAtLogin: true,
};

class Store {
  constructor() {
    this._path = path.join(app.getPath("userData"), "settings.json");
    this._data = this._load();
  }

  _load() {
    try {
      const raw = fs.readFileSync(this._path, "utf-8");
      return { ...DEFAULTS, ...JSON.parse(raw) };
    } catch {
      return { ...DEFAULTS };
    }
  }

  _save() {
    fs.mkdirSync(path.dirname(this._path), { recursive: true });
    fs.writeFileSync(this._path, JSON.stringify(this._data, null, 2));
  }

  getAll() {
    return { ...this._data };
  }

  update(patch) {
    this._data = { ...this._data, ...patch };
    this._save();
    return this.getAll();
  }
}

module.exports = { Store, DEFAULTS };

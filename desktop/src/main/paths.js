// Single source of truth for where the contribution-capture queue lives on
// disk, shared by sidecar.js (which tells the Python engine where to write)
// and contributions.js (which reads/uploads/deletes from the same place).
// Using Electron's own per-OS user-data directory rather than a path inside
// the app's install location, since that's read-only once packaged and
// isn't a place a background process should be writing captured photos.

const path = require("path");
const { app } = require("electron");

function getQueueDir() {
  return path.join(app.getPath("userData"), "queue", "pending");
}

// The repo's top-level assets/ dir (sounds, stickers, tray/app icon source)
// isn't inside desktop/, so it's not picked up by electron-builder's `files`
// config automatically - it's bundled separately via `extraResources` (see
// desktop/package.json) into Resources/assets/. In dev mode there's no such
// bundling step, so this just points at the real folder in the repo instead.
function getAssetsDir() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "assets")
    : path.join(__dirname, "..", "..", "..", "assets");
}

module.exports = { getQueueDir, getAssetsDir };

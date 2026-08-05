const path = require("path");
const { app, Tray, Menu, BrowserWindow, ipcMain, shell, nativeImage } = require("electron");
const { Store } = require("./store");
const { Sidecar } = require("./sidecar");

// Dev-only: loads REARAWARE_CONTRIBUTE_URL/KEY from desktop/.env (gitignored,
// see .env.example) into process.env, which sidecar.js's spawn() then
// inherits and passes through to the Python engine. Packaged builds will
// need a real config story for this in Phase 4 - a plain .env file next to
// the app isn't it.
try {
  process.loadEnvFile(path.join(__dirname, "..", "..", ".env"));
} catch {
  // No .env present (e.g. fresh checkout without contribution testing set up) - fine, the
  // engine already degrades gracefully when these are unset (see contribute.py).
}

// RearAware is meant to keep running as a background tray app long after
// whatever launched it (a dev terminal, a login-item launcher) is gone. If
// that terminal closes while stdout/stderr is still attached to it, the next
// console.log/console.error throws EIO/EPIPE - normally an uncaught
// exception that kills the whole process. Swallow just those so a severed
// output stream can't take the app down.
for (const stream of [process.stdout, process.stderr]) {
  stream.on("error", (err) => {
    if (err.code !== "EPIPE" && err.code !== "EIO") throw err;
  });
}

// Only one instance should ever run - a second launch (e.g. clicking the
// app icon again, or an OS autostart racing a manual launch) should just
// focus the existing settings window instead of spawning a second sidecar
// and fighting over the same webcam/virtual camera.
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  let store;
  let sidecar;
  let tray;
  let settingsWindow = null;
  let isQuitting = false; // distinguishes "user closed the window" from "the app is actually shutting down"

  app.on("second-instance", () => {
    openSettingsWindow();
  });

  app.whenReady().then(() => {
    // Background utility app - no dock icon on macOS, matches the
    // Amphetamine/Dropbox-style "lives in the tray, no window on launch" ask.
    if (process.platform === "darwin" && app.dock) {
      app.dock.hide();
    }

    store = new Store();
    applyAutostart(store.getAll().openAtLogin);

    sidecar = new Sidecar();
    sidecar.on("event", handleEngineEvent);
    sidecar.on("exit", ({ code, signal }) => {
      console.error(`[main] engine sidecar exited (code=${code}, signal=${signal}), restarting...`);
    });
    // Without this, a spawn failure (e.g. "python3" not found) emits an
    // unlistened 'error' event, which Node treats as an uncaught exception
    // and can take the whole main process down silently.
    sidecar.on("error", (err) => {
      console.error("[main] engine sidecar failed to start:", err);
    });
    sidecar.start();
    sidecar.sendSettings(store.getAll());

    tray = createTray();
    registerIpcHandlers();
  });

  app.on("window-all-closed", (event) => {
    // Tray app: closing the settings window should never quit the app.
    event.preventDefault();
  });

  app.on("before-quit", () => {
    isQuitting = true;
    if (sidecar) sidecar.stop();
  });

  function createTray() {
    const iconPath = path.join(__dirname, "..", "..", "..", "ra.png");
    let icon = nativeImage.createFromPath(iconPath);
    if (!icon.isEmpty()) icon = icon.resize({ width: 18, height: 18 });

    const t = new Tray(icon);
    t.setToolTip("RearAware");
    // No separate 'click' handler here on purpose: setContextMenu() below
    // already makes any click (left or right) show the dropdown on macOS,
    // so an additional click handler would fire *alongside* that menu
    // rather than instead of it.
    updateTrayMenu(t);
    return t;
  }

  function updateTrayMenu(t) {
    const settings = store.getAll();
    const menu = Menu.buildFromTemplate([
      {
        label: settings.detectionEnabled ? "Detection: On" : "Detection: Off",
        type: "checkbox",
        checked: settings.detectionEnabled,
        click: (item) => applySettingsPatch({ detectionEnabled: item.checked }),
      },
      { type: "separator" },
      { label: "Open Settings...", click: () => openSettingsWindow() },
      { type: "separator" },
      { label: "Quit RearAware", click: () => app.quit() },
    ]);
    t.setContextMenu(menu);
  }

  function openSettingsWindow() {
    if (settingsWindow) {
      settingsWindow.show();
      settingsWindow.focus();
      return;
    }

    settingsWindow = new BrowserWindow({
      width: 342,
      height: 640,
      resizable: false,
      title: "RearAware",
      webPreferences: {
        preload: path.join(__dirname, "..", "preload", "preload.js"),
        contextIsolation: true,
        nodeIntegration: false,
      },
    });

    settingsWindow.setMenuBarVisibility(false);
    settingsWindow.loadFile(path.join(__dirname, "..", "renderer", "settings", "popup.html"));

    settingsWindow.on("close", (event) => {
      if (isQuitting) return; // let real shutdown actually close the window
      // Hide, don't destroy - matches the tray-app pattern (Dropbox etc.):
      // closing the window just puts it away, the app keeps running.
      event.preventDefault();
      settingsWindow.hide();
    });

    settingsWindow.on("closed", () => {
      settingsWindow = null;
    });
  }

  function applySettingsPatch(patch) {
    const updated = store.update(patch);
    sidecar.sendSettings(updated);
    if ("openAtLogin" in patch) applyAutostart(updated.openAtLogin);
    if (tray) updateTrayMenu(tray);
    if (settingsWindow) settingsWindow.webContents.send("settings:changed", updated);
    return updated;
  }

  function applyAutostart(openAtLogin) {
    app.setLoginItemSettings({ openAtLogin: !!openAtLogin });
  }

  function handleEngineEvent(event) {
    if (event.type === "error") {
      console.error("[engine]", event.message);
    }
    if (settingsWindow) {
      settingsWindow.webContents.send("engine:event", event);
    }
  }

  function registerIpcHandlers() {
    ipcMain.handle("settings:get", () => store.getAll());
    ipcMain.handle("settings:set", (_event, patch) => applySettingsPatch(patch));
    ipcMain.handle("shell:openExternal", (_event, url) => {
      if (/^https:\/\//.test(url)) shell.openExternal(url);
    });
    ipcMain.handle("app:getVersion", () => app.getVersion());
  }
}

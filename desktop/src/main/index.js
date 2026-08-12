const path = require("path");
const { app, Tray, Menu, BrowserWindow, ipcMain, shell, nativeImage, dialog } = require("electron");
const { Store } = require("./store");
const { Sidecar } = require("./sidecar");
const contributions = require("./contributions");
const { getAssetsDir } = require("./paths");

const REPORT_ISSUE_URL = "https://github.com/nicolefabia/RearAware-App/issues/new";
const WEBSITE_URL = "https://www.rearaware.com";
const COPYRIGHT = "Copyright © 2026 Nicole Ferreira";
// A human-readable label distinct from package.json's strict-semver "version"
// (which app.getVersion() reads) - same split as the Chrome extension's
// manifest.json version/version_name fields.
const DISPLAY_VERSION = `${require("../../package.json").version} Beta`;
// .png, not the original .jpg - macOS's About panel doesn't reliably render
// JPEG for iconPath. In practice the About panel actually draws from the
// packaged app's own bundle icon (electron-builder's mac.icon config), not
// this at all - this still matters for dock.setIcon() and the Windows
// fallback dialog below.
const APP_ICON_PATH = path.join(getAssetsDir(), "icons", "app-icon-1024.png");

// Loads REARAWARE_CONTRIBUTE_URL/KEY into process.env - read directly by
// contributions.js when a photo is approved (the Python engine has no
// networking code at all, it only ever writes to the local queue).
// In dev mode this is desktop/.env (gitignored, see .env.example). In a
// packaged build there's no repo checkout to find that file in, so
// electron-builder copies the same local .env into the app's own Resources
// folder at build time instead (see extraResources in package.json) - the
// file itself still never touches git either way.
try {
  const envPath = app.isPackaged
    ? path.join(process.resourcesPath, ".env")
    : path.join(__dirname, "..", "..", ".env");
  process.loadEnvFile(envPath);
} catch {
  // No .env present (e.g. fresh checkout without contribution testing set up) - fine, the
  // upload path already degrades to a clear error if approve() is used without it configured.
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
  let engineFailed = false; // sidecar gave up after repeated crashes - needs a manual restart
  let pendingContributionsCount = 0;

  app.on("second-instance", () => {
    openSettingsWindow();
  });

  app.whenReady().then(() => {
    if (process.platform === "darwin" && app.dock) {
      // setAboutPanelOptions()'s iconPath alone didn't actually change what
      // the About panel shows - on macOS it appears to draw from the app's
      // real application icon (NSApp.applicationIconImage), which the Dock
      // API controls. Setting it explicitly here, then immediately hiding
      // the Dock tile - the icon association sticks even though the tile
      // itself matches the Amphetamine/Dropbox-style "lives in the tray, no
      // window on launch" ask.
      app.dock.setIcon(nativeImage.createFromPath(APP_ICON_PATH));
      app.dock.hide();
    }

    if (process.platform === "darwin") {
      app.setAboutPanelOptions({
        applicationName: "RearAware",
        applicationVersion: DISPLAY_VERSION,
        copyright: COPYRIGHT,
        credits: WEBSITE_URL,
        website: WEBSITE_URL,
        iconPath: APP_ICON_PATH,
      });
    }

    store = new Store();
    applyAutostart(store.getAll().openAtLogin);
    pendingContributionsCount = contributions.pendingCount();

    sidecar = new Sidecar();
    sidecar.on("event", handleEngineEvent);
    sidecar.on("exit", ({ code, signal }) => {
      console.error(`[main] engine sidecar exited (code=${code}, signal=${signal})`);
    });
    // Without this, a spawn failure (e.g. "python3" not found) emits an
    // unlistened 'error' event, which Node treats as an uncaught exception
    // and can take the whole main process down silently.
    sidecar.on("error", (err) => {
      console.error("[main] engine sidecar failed to start:", err);
    });
    // Fired after several rapid crashes in a row (see sidecar.js) - retrying
    // forever every couple seconds just churns a broken camera state
    // further, so it stops and waits for a manual restart instead.
    sidecar.on("giveup", () => {
      console.error("[main] engine sidecar crashed repeatedly, giving up - use 'Restart Engine' from the tray menu");
      engineFailed = true;
      if (tray) updateTrayMenu(tray);
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

  app.on("before-quit", (event) => {
    if (isQuitting) return; // second pass, below, after the sidecar has actually exited - let it proceed
    event.preventDefault();
    isQuitting = true;

    if (!sidecar) {
      app.quit();
      return;
    }

    // Electron quitting does NOT kill child processes on its own - without
    // waiting here, the Python engine (and its open webcam/virtual-camera
    // handles) could keep running invisibly after the tray icon is gone.
    let finished = false;
    const finishQuit = () => {
      if (finished) return;
      finished = true;
      app.quit();
    };

    sidecar.once("exit", finishQuit);
    sidecar.stop();
    setTimeout(finishQuit, 6000); // sidecar.stop()'s own escalation tops out under this - just a backstop
  });

  function getTrayIcon(detectionEnabled) {
    // macOS: pure black + alpha art, rendered from source PDFs with no
    // color-profile shift (see assets/icons/tray/mac) - marked as a native
    // "template" image so macOS auto-tints it for light/dark menu bars.
    // Windows: the same art doesn't have that auto-tinting mechanic, so it
    // uses a version with actual color for visibility on the taskbar.
    const platformDir = process.platform === "darwin" ? "mac" : "win";
    const iconPath = path.join(
      getAssetsDir(), "icons", "tray", platformDir,
      detectionEnabled ? "ra-on.png" : "ra-off.png"
    );
    let icon = nativeImage.createFromPath(iconPath);
    if (!icon.isEmpty()) icon = icon.resize({ width: 18, height: 18 });
    if (process.platform === "darwin") icon.setTemplateImage(true);
    return icon;
  }

  function createTray() {
    const t = new Tray(getTrayIcon(store.getAll().detectionEnabled));
    t.setToolTip("RearAware");
    // No separate 'click' handler here on purpose: setContextMenu() below
    // already makes any click (left or right) show the dropdown on macOS,
    // so an additional click handler would fire *alongside* that menu
    // rather than instead of it.
    updateTrayMenu(t);
    return t;
  }

  function showAboutPanel() {
    // The Dock icon is hidden (accessory-style app), which on macOS means
    // native panels like this one can fail to actually come to the
    // foreground without an explicit activation call first.
    app.focus({ steal: true });

    if (process.platform === "darwin") {
      app.showAboutPanel(); // fully native macOS About panel, configured above
      return;
    }
    // Electron has no OS-provided About panel outside macOS - a plain
    // message box is the closest native-feeling equivalent on Windows.
    dialog.showMessageBox({
      type: "info",
      title: "About RearAware",
      message: "RearAware",
      detail: `Version ${DISPLAY_VERSION}\n\n${WEBSITE_URL}\n\n${COPYRIGHT}`,
      icon: nativeImage.createFromPath(APP_ICON_PATH),
      buttons: ["OK"],
    });
  }

  function updateTrayMenu(t) {
    const settings = store.getAll();
    t.setImage(getTrayIcon(settings.detectionEnabled && !engineFailed));
    t.setToolTip(engineFailed ? "RearAware - engine failed to start (camera busy?)" : "RearAware");

    // macOS-only: a small text badge next to the icon itself, so the count
    // is visible without opening the menu. Windows tray icons don't support
    // this - the count is still in the "Review training images..." label.
    if (process.platform === "darwin") {
      t.setTitle(pendingContributionsCount > 0 ? ` ${pendingContributionsCount}` : "");
    }

    // "Detection-related" items (per the menu spec) go inert together when
    // RearAware itself is off, since none of them mean anything without it
    // running. Obfuscation Type additionally goes inert under debug mode,
    // since debug mode shows bounding boxes instead of a censor sticker.
    const detectionDisabled = !settings.detectionEnabled || engineFailed;
    const obfuscationDisabled = detectionDisabled || settings.debugEnabled;

    const obfuscationSubmenu = [
      ["standard", "Standard"],
      ["all-seeing", "All-Seeing"],
      ["nicolas-cage", "Nicolas Cage"],
    ].map(([value, label]) => ({
      label,
      type: "radio",
      checked: settings.obfuscation === value,
      enabled: !obfuscationDisabled,
      click: () => applySettingsPatch({ obfuscation: value }),
    }));

    const template = [
      { label: "About RearAware", click: () => showAboutPanel() },
      { type: "separator" },
    ];

    if (engineFailed) {
      template.push(
        { label: "Engine failed to start - check camera access", enabled: false },
        { label: "Restart Engine", click: () => restartEngine() },
      );
    } else {
      template.push({
        label: "RearAware Enabled",
        type: "checkbox",
        checked: settings.detectionEnabled,
        click: (item) => applySettingsPatch({ detectionEnabled: item.checked }),
      });
    }

    template.push(
      {
        label: "Audio Feedback",
        type: "checkbox",
        checked: settings.soundEnabled,
        enabled: !detectionDisabled,
        click: (item) => applySettingsPatch({ soundEnabled: item.checked }),
      },
      {
        label: "Obfuscation Type",
        enabled: !obfuscationDisabled,
        submenu: obfuscationSubmenu,
      },
      {
        label: "Bounding Boxes (Debug)",
        type: "checkbox",
        checked: settings.debugEnabled,
        enabled: !detectionDisabled,
        click: (item) => applySettingsPatch({ debugEnabled: item.checked }),
      },
      { type: "separator" },
      { label: "Settings...", click: () => openSettingsWindow() },
      { label: `Review training images... (${pendingContributionsCount})`, click: () => openSettingsWindow("training") },
      { label: "Report an Issue...", click: () => shell.openExternal(REPORT_ISSUE_URL) },
      { type: "separator" },
      { label: "Quit RearAware", click: () => app.quit() },
    );

    t.setContextMenu(Menu.buildFromTemplate(template));
  }

  function refreshContributionsCount() {
    pendingContributionsCount = contributions.pendingCount();
    if (tray) updateTrayMenu(tray);
    if (settingsWindow) settingsWindow.webContents.send("contributions:changed", pendingContributionsCount);
  }

  function restartEngine() {
    engineFailed = false;
    if (tray) updateTrayMenu(tray);
    sidecar.restart();
    sidecar.sendSettings(store.getAll());
  }

  function openSettingsWindow(initialTab = "general") {
    if (settingsWindow) {
      settingsWindow.show();
      settingsWindow.focus();
      settingsWindow.webContents.send("settings:show-tab", initialTab);
      return;
    }

    settingsWindow = new BrowserWindow({
      width: 480,
      height: 620,
      resizable: false,
      title: "RearAware",
      webPreferences: {
        preload: path.join(__dirname, "..", "preload", "preload.js"),
        contextIsolation: true,
        nodeIntegration: false,
      },
    });

    settingsWindow.setMenuBarVisibility(false);
    settingsWindow.loadFile(
      path.join(__dirname, "..", "renderer", "settings", "settings.html"),
      { query: { tab: initialTab } }
    );

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
    if (event.type === "contribute_captured" || event.type === "contribute_expired") {
      refreshContributionsCount();
    }
  }

  function registerIpcHandlers() {
    ipcMain.handle("settings:get", () => store.getAll());
    ipcMain.handle("settings:set", (_event, patch) => applySettingsPatch(patch));
    ipcMain.handle("shell:openExternal", (_event, url) => {
      if (/^https:\/\//.test(url)) shell.openExternal(url);
    });
    ipcMain.handle("app:getVersion", () => app.getVersion());

    ipcMain.handle("contributions:list", () => contributions.listPending());
    ipcMain.handle("contributions:approve", async (_event, id) => {
      await contributions.approve(id);
      refreshContributionsCount();
    });
    ipcMain.handle("contributions:reject", (_event, id) => {
      contributions.reject(id);
      refreshContributionsCount();
    });
  }
}

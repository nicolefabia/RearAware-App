const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("rearaware", {
  getSettings: () => ipcRenderer.invoke("settings:get"),
  setSetting: (key, value) => ipcRenderer.invoke("settings:set", { [key]: value }),
  openExternal: (url) => ipcRenderer.invoke("shell:openExternal", url),

  onSettingsChanged: (callback) => {
    const handler = (_event, settings) => callback(settings);
    ipcRenderer.on("settings:changed", handler);
    return () => ipcRenderer.removeListener("settings:changed", handler);
  },

  onEngineEvent: (callback) => {
    const handler = (_event, evt) => callback(evt);
    ipcRenderer.on("engine:event", handler);
    return () => ipcRenderer.removeListener("engine:event", handler);
  },

  getAppVersion: () => ipcRenderer.invoke("app:getVersion"),
});

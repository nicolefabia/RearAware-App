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

  getAppVersion: () => ipcRenderer.invoke("app:getVersion"),

  listContributions: () => ipcRenderer.invoke("contributions:list"),
  approveContribution: (id) => ipcRenderer.invoke("contributions:approve", id),
  rejectContribution: (id) => ipcRenderer.invoke("contributions:reject", id),

  onContributionsChanged: (callback) => {
    const handler = (_event, count) => callback(count);
    ipcRenderer.on("contributions:changed", handler);
    return () => ipcRenderer.removeListener("contributions:changed", handler);
  },

  onShowTab: (callback) => {
    const handler = (_event, tab) => callback(tab);
    ipcRenderer.on("settings:show-tab", handler);
    return () => ipcRenderer.removeListener("settings:show-tab", handler);
  },
});

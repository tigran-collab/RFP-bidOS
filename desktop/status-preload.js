"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("rfpBidos", {
  onStartupStatus(callback) {
    if (typeof callback !== "function") return () => {};
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("startup-status", listener);
    return () => ipcRenderer.removeListener("startup-status", listener);
  },
});

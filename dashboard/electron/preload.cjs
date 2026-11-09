const { contextBridge } = require('electron')

contextBridge.exposeInMainWorld('flowKitDesktop', {
  platform: process.platform,
})

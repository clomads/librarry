const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('library', {
  stack: (...args) => ipcRenderer.invoke('stack', args),
  versions: () => ipcRenderer.invoke('versions'),
  badges: () => ipcRenderer.invoke('badges'),
});

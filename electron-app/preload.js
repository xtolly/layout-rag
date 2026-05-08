const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
    // 调用本地 Exe
    invokeExe: (args) => ipcRenderer.invoke('run-external-exe', args),
    // 提交最终结果给外部调用方
    submitResult: (payload) => ipcRenderer.invoke('submit-layout-result', payload),
    // 强制退出应用
    exitApp: (code) => ipcRenderer.send('exit-app', code)
})

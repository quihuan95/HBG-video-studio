const { app, BrowserWindow, dialog, shell } = require('electron')
const fs = require('node:fs')
const http = require('node:http')
const path = require('node:path')
const { ensureBackend, stopBackend } = require('./backend.cjs')

const MIME_TYPES = {
  '.css': 'text/css',
  '.html': 'text/html',
  '.js': 'text/javascript',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
}

function startRendererServer() {
  const distDir = path.resolve(__dirname, '..', 'dist')
  const server = http.createServer((request, response) => {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname)
    let filePath = path.resolve(distDir, `.${pathname}`)

    if (!filePath.startsWith(`${distDir}${path.sep}`) || !fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
      filePath = path.join(distDir, 'index.html')
    }

    response.setHeader('Content-Type', MIME_TYPES[path.extname(filePath)] || 'application/octet-stream')
    fs.createReadStream(filePath).pipe(response)
  })

  return new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      resolve({ server, url: `http://127.0.0.1:${address.port}` })
    })
  })
}

async function createWindow(rendererUrl) {
  const window = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: 'HBG Video Studio',
    backgroundColor: '#0a0a0a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://') || url.startsWith('http://')) {
      void shell.openExternal(url)
    }
    return { action: 'deny' }
  })

  if (process.argv.includes('--dev')) {
    await window.loadURL('http://127.0.0.1:5173')
    if (process.env.ELECTRON_OPEN_DEVTOOLS === '1') {
      window.webContents.openDevTools({ mode: 'detach' })
    }
  } else {
    await window.loadURL(rendererUrl)
  }
}

app.whenReady().then(async () => {
  try {
    await ensureBackend()
    const renderer = process.argv.includes('--dev') ? null : await startRendererServer()
    await createWindow(renderer?.url)
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) void createWindow(renderer?.url)
    })
  } catch (error) {
    dialog.showErrorBox('Không thể khởi động HBG Video Studio', error.message)
    app.quit()
  }
})

app.on('before-quit', stopBackend)

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const repoRoot = path.resolve(__dirname, '..', '..')
const apiPort = process.env.API_PORT || '8100'
const healthUrl = `http://127.0.0.1:${apiPort}/health`

let ownedProcess = null

async function isHealthy() {
  try {
    const response = await fetch(healthUrl, { signal: AbortSignal.timeout(1000) })
    return response.ok
  } catch {
    return false
  }
}

function pythonCommand() {
  const venvPython = process.platform === 'win32'
    ? path.join(repoRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(repoRoot, '.venv', 'bin', 'python')

  if (fs.existsSync(venvPython)) return { command: venvPython, args: [] }
  return { command: process.platform === 'win32' ? 'python' : 'python3', args: [] }
}

async function waitUntilHealthy(child, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await isHealthy()) return
    if (child.exitCode !== null) {
      throw new Error(`Python backend exited with code ${child.exitCode}.`)
    }
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  throw new Error(`Python backend did not become ready at ${healthUrl} within 30 seconds.`)
}

async function ensureBackend() {
  if (await isHealthy()) {
    console.log(`[desktop] Using backend already running at ${healthUrl}`)
    return { started: false, url: healthUrl }
  }

  const python = pythonCommand()
  console.log(`[desktop] Starting Python backend with ${python.command}`)
  const child = spawn(python.command, [...python.args, '-m', 'agent.main'], {
    cwd: repoRoot,
    env: process.env,
    stdio: 'inherit',
    windowsHide: true,
  })
  ownedProcess = child

  const spawnError = new Promise((_, reject) => {
    child.once('error', error => reject(new Error(`Cannot start Python backend: ${error.message}`)))
  })
  await Promise.race([waitUntilHealthy(child), spawnError])
  console.log(`[desktop] Python backend is ready at ${healthUrl}`)
  return { started: true, url: healthUrl }
}

function stopBackend() {
  if (!ownedProcess || ownedProcess.exitCode !== null) return
  console.log('[desktop] Stopping Python backend')
  ownedProcess.kill()
  ownedProcess = null
}

module.exports = { ensureBackend, stopBackend }

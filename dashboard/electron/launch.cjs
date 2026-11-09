const { spawn } = require('node:child_process')

const electronPath = require('electron')
const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE

const child = spawn(electronPath, ['.', ...process.argv.slice(2)], {
  cwd: require('node:path').resolve(__dirname, '..'),
  env,
  stdio: 'inherit',
})

child.once('error', error => {
  console.error(`Failed to launch Electron: ${error.message}`)
  process.exitCode = 1
})

child.once('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal)
  else process.exitCode = code ?? 0
})

# Flow Kit Desktop Dashboard

The dashboard is the React user interface for Flow Kit. It can run either as an
Electron desktop window or as a normal Vite web application. Both modes use the
existing Python FastAPI service for project data, worker status, and pipeline
events.

## Prerequisites

- Node.js 20 or newer
- npm
- The Flow Kit Python agent running at `http://127.0.0.1:8100`

Install dependencies once:

```bash
npm install
```

## Electron development

Start the Python backend from the repository root:

```bash
python -m agent.main
```

In another terminal, start Vite and Electron together:

```bash
cd dashboard
npm run electron:dev
```

Electron DevTools open automatically in development mode. Vite proxies `/api`,
`/health`, and `/ws` to the Python backend.

## Run the compiled desktop UI

```bash
npm run build
npm run electron:start
```

Electron serves `dist/` from a loopback-only local server and the compiled UI
connects directly to FastAPI on port `8100`.

## Browser mode

```bash
npm run dev
```

Open `http://127.0.0.1:5173`. Browser mode is retained for development and
remote debugging.

## Commands

| Command | Purpose |
|---|---|
| `npm run electron:dev` | Run Vite and Electron with hot reload |
| `npm run build` | Type-check and build the React renderer |
| `npm run electron:start` | Open Electron using the compiled renderer |
| `npm run dev` | Run only the browser dashboard |
| `npm run lint` | Run ESLint |
| `npm run preview` | Preview the Vite production build in a browser |

## Current desktop scope

Electron currently wraps the dashboard UI only. The Python backend and Chrome
extension remain separate processes. Automatic backend startup, packaged
Python/FFmpeg binaries, persistent desktop settings, and a Windows installer
are planned follow-up work.

Repository: <https://github.com/quihuan95/HBG-video-studio>

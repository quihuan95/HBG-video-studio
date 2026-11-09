# Flow Kit Desktop Dashboard

The dashboard is the React user interface for Flow Kit. It can run either as an
Electron desktop window or as a normal Vite web application. Both modes use the
existing Python FastAPI service for project data, worker status, and pipeline
events.

## Prerequisites

- Node.js 20 or newer
- npm
- A project `.venv` with the Python requirements installed

Install dependencies once:

```bash
npm install
```

## Electron development

Start Vite, Electron, and the Python backend together:

```bash
cd dashboard
npm run electron:dev
```

Electron starts the Python backend when it is not already running, waits for its
health check, and stops the owned backend when the app closes. DevTools open
automatically in development mode. Vite proxies `/api`, `/health`, and `/ws` to
the backend.

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

Electron currently manages the local Python backend as a child process. The
Chrome extension remains a separate component. Packaged Python/FFmpeg binaries,
persistent desktop settings, and a Windows installer are planned follow-up work.

Repository: <https://github.com/quihuan95/HBG-video-studio>

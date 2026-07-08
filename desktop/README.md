# RFP BidOS Desktop Launcher

This folder contains the Electron launcher for the existing RFP BidOS FastAPI backend and React/Vite frontend. It does not replace either app.

> **This is a dev-mode convenience, not a packaged distributable.** The launcher
> requires a git checkout in which the backend virtual environment
> (`backend/.venv`) and the frontend dependencies (`frontend/node_modules`) are
> already installed. On launch it starts and orchestrates those local dev
> servers (Ollama, uvicorn, Vite) — it does not embed them. The `package:*`
> commands below currently produce only the launcher shell and are **not** a
> working standalone app (see "Packaging").

## One-Command Startup

The desktop launcher is the startup manager for local RFP BidOS development. It checks or starts Ollama, checks the local model, starts the FastAPI backend, starts the Vite frontend, then opens the Electron window.

Windows:

```cmd
cd desktop
npm.cmd install
npm.cmd run doctor
npm.cmd run desktop
```

macOS:

```bash
cd desktop
npm install
npm run doctor
npm run desktop
```

Linux:

```bash
cd desktop
npm install
npm run doctor
npm run desktop
```

The launcher opens a desktop window titled `RFP BidOS` after the services are ready and loads:

```text
http://localhost:5173
```

## Manual Prerequisites

- Python 3.12+
- Backend venv created at `backend/.venv`
- Backend requirements installed
- Frontend dependencies installed at `frontend/node_modules`
- Node/npm installed and on PATH
- Ollama installed and on PATH
- `qwen3:8b` pulled locally

Backend setup:

```bash
cd backend
python -m venv .venv
python -m pip install -r requirements.txt
python -m app.cli init-db
python -m app.cli seed-demo
python -m app.cli seed-sources
```

Frontend setup:

```bash
cd frontend
npm install
```

Model setup:

```bash
ollama pull qwen3:8b
```

## Startup Behavior

On launch, Electron:

- Checks whether Ollama is reachable at `http://127.0.0.1:11434/api/tags`.
- Starts `ollama serve` only if Ollama is installed and not already reachable.
- Checks for `qwen3:8b` and accepts equivalent local Ollama names such as `qwen3:8b-latest` or `qwen3`.
- Shows `Ollama is running, but qwen3:8b is not installed. Run this command once: ollama pull qwen3:8b` if the configured model is missing.
- Starts the backend on `127.0.0.1:8000` using `backend/.venv` Python directly, with `OLLAMA_BASE_URL` and `OLLAMA_MODEL` set.
- Starts the existing Vite frontend.
- Waits for backend and frontend readiness before loading the app window.
- Stops only the backend, frontend, and Ollama processes that it started. A pre-existing Ollama process is left alone.

The launcher does not silently download `qwen3:8b`. Pull the model once with explicit user approval:

```bash
ollama pull qwen3:8b
```

## Doctor

Run the doctor before launching if startup fails:

Windows:

```cmd
cd desktop
npm.cmd run doctor
```

macOS/Linux:

```bash
cd desktop
npm run doctor
```

Doctor prints PASS/WARN/FAIL lines for platform, app root resolution, backend venv, backend imports, frontend dependencies, npm, Ollama, Ollama API reachability, the `qwen3:8b` model, Electron, and git metadata.

## Logs

Launcher logs are written to:

```text
desktop/logs/launch.log
```

Logs include platform, app root, Node/Electron versions, service commands, working directories, preflight results, stdout/stderr snippets, and full error details.

## Icons

Place icon files in `desktop/assets/`:

- `icon.png` for Linux and development fallback.
- `icon.icns` for macOS packaging.
- `icon.ico` for Windows packaging.

## Packaging

> **Not a working distributable yet.** These `electron-builder` targets bundle
> only the launcher shell (`main.js`, `status.html`, `status-preload.js`, and
> `assets/`). They do **not** include the Python backend, the backend venv, or
> the frontend/`node_modules`, and `main.js` resolves its app root to the repo
> parent directory (`path.resolve(__dirname, "..")`) — so a packaged build will
> not find the backend or frontend at runtime. Use the launcher from a git
> checkout instead (see "One-Command Startup").
>
> Making this a real installable would require shipping `backend/` and
> `frontend/` via `extraResources`, detecting `app.isPackaged` to resolve the
> app root to `process.resourcesPath`, and bundling a Python runtime plus a
> built frontend. That work is not done here.

Packaging uses `electron-builder`.

macOS:

```bash
cd desktop
npm install
npm run package:mac
```

Windows:

```cmd
cd desktop
npm install
npm run package:win
```

Linux:

```bash
cd desktop
npm install
npm run package:linux
```

The configured product name is `RFP BidOS`, producing `RFP BidOS.app` on macOS and `RFP BidOS.exe` on Windows. Packaging should be run on the target OS with the appropriate icon file present.

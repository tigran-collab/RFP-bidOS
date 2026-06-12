# RFP BidOS Desktop Launcher

This folder contains the Electron launcher for the existing RFP BidOS FastAPI backend and React/Vite frontend. It does not replace either app.

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

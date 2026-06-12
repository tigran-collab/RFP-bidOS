# RFP BidOS Desktop Launcher

This folder contains the Electron launcher for the existing RFP BidOS FastAPI backend and React/Vite frontend. It does not replace either app.

## Development Launch

```bash
cd desktop
npm install
npm run desktop
```

The launcher opens a desktop window titled `RFP BidOS` and loads:

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

Setup commands:

```bash
cd backend
python -m pip install -r requirements.txt
python -m app.cli init-db
python -m app.cli seed-demo
python -m app.cli seed-sources

cd ../frontend
npm install

ollama pull qwen3:8b
```

## Startup Behavior

On launch, Electron:

- Checks whether Ollama is reachable at `http://127.0.0.1:11434/api/tags`.
- Starts `ollama serve` only if Ollama is not already reachable.
- Shows `Ollama is running, but qwen3:8b is not installed. Run: ollama pull qwen3:8b` if the configured model is missing.
- Starts the backend on `127.0.0.1:8000` with `OLLAMA_BASE_URL` and `OLLAMA_MODEL` set.
- Starts the existing Vite frontend with `npm run dev`.
- Waits for backend and frontend readiness before loading the app window.
- Stops only the backend, frontend, and Ollama processes that it started.

The launcher does not auto-pull models and does not start background services.

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

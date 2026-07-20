# Setup Guide — Running RFP BidOS on a Fresh Machine

This is a step-by-step quickstart for getting RFP BidOS running on a new
computer from a clean clone. For the full feature-by-feature reference (CLI
commands, API endpoints, scraper/KB details), see [README.md](README.md).

> **Note:** this is a fresh install. The code comes from GitHub, but the local
> database, downloaded documents, browser sessions, and any saved credentials
> (portal logins, Notion token, Claude API key) stay on the original machine —
> they are gitignored and never leave it. You start with clean seed data and
> configure your own credentials locally.

## 1. Install prerequisites

Install these first, before cloning:

- **Git** — https://git-scm.com/downloads
- **Python 3.12 or 3.13** — https://python.org
  (on Windows, check *"Add Python to PATH"* in the installer)
- **Node.js** (LTS) — https://nodejs.org
- **Ollama** — https://ollama.com/download

## 2. Clone the repo

```bash
git clone https://github.com/tigran-collab/RFP-bidOS.git
cd RFP-bidOS
```

## 3. Set up the backend

**Windows:**

```cmd
cd backend
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m app.cli init-db
python -m app.cli seed-demo
python -m app.cli seed-sources
```

**macOS:**

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m app.cli init-db
python -m app.cli seed-demo
python -m app.cli seed-sources
```

## 4. Set up the frontend

```bash
cd ../frontend
npm install
```

## 5. Pull the local AI model

```bash
ollama pull qwen3:8b
```

## 6. Run it

You need **two terminals** — one for the backend, one for the frontend.

**Terminal 1 — backend:**

```bash
cd backend
# Windows: .venv\Scripts\activate.bat
# macOS:   source .venv/bin/activate
uvicorn app.main:app --reload
```

**Terminal 2 — frontend:**

```bash
cd frontend
npm run dev
```

Then open **http://localhost:5173** in a browser.

## Shortcut for later

After the one-time setup above is done (venv created, `npm install` complete),
you can launch both servers without the two-terminal dance:

- **Windows:** double-click `start_rfp_bidos.bat` in the project root.
- **macOS:** run `./start_rfp_bidos_mac.sh`.

There is also a cross-platform Electron desktop launcher — see the "Desktop
Launcher" section in [README.md](README.md).

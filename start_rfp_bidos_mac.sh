#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_URL="http://localhost:5173"
OLLAMA_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"

run_in_terminal() {
  local title="$1"
  local command="$2"
  osascript >/dev/null <<APPLESCRIPT
tell application "Terminal"
  activate
  do script "printf '\\e]0;${title}\\a'; ${command}"
end tell
APPLESCRIPT
}

if ! curl -fsS "${OLLAMA_URL%/}/api/tags" >/dev/null 2>&1; then
  if command -v ollama >/dev/null 2>&1; then
    run_in_terminal "RFP BidOS Ollama" "ollama serve"
    sleep 3
  else
    echo "Ollama is not installed or not on PATH. Install Ollama and run: ollama pull qwen3:8b"
  fi
fi

if [ ! -x "$ROOT_DIR/backend/.venv/bin/python" ]; then
  echo "Backend venv missing. Create it first:"
  echo "  cd backend"
  echo "  python3.12 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  python -m pip install -r requirements.txt"
  exit 1
fi

run_in_terminal \
  "RFP BidOS Backend" \
  "cd $(printf '%q' "$ROOT_DIR/backend") && source .venv/bin/activate && uvicorn app.main:app --reload"

run_in_terminal \
  "RFP BidOS Frontend" \
  "cd $(printf '%q' "$ROOT_DIR/frontend") && npm run dev"

sleep 5
open "$APP_URL"

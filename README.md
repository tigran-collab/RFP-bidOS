# RFP BidOS

Local-first FastAPI and React dashboard for RFP bid tracking, public-page discovery, document parsing, rules-based scoring, local Ollama evaluation, and human-reviewable requirements extraction.

## Backend Setup

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m app.cli init-db
python -m app.cli seed-demo
```

## Frontend Setup

```powershell
cd frontend
npm.cmd install
npm.cmd run build
```

## Run Manually

Backend:

```powershell
cd backend
uvicorn app.main:app --reload
```

Frontend:

```powershell
cd frontend
npm.cmd run dev
```

## Developer Checks

```powershell
cd backend
python -m app.cli init-db
python -m app.cli seed-demo
python -m app.cli score-all-opportunities
python -m app.cli parse-all-documents
python -m app.cli ai-evaluate-all-opportunities
python -m app.cli extract-all-requirements
```

## Local AI

Install Ollama, then pull the local model:

```powershell
ollama pull qwen2.5:3b
```

Run local AI evaluation:

```powershell
cd backend
python -m app.cli ai-evaluate-all-opportunities
```

Environment variables:

```powershell
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

Local AI evaluation uses Ollama only. It does not use OpenAI APIs or cloud AI.

## Parsing

```powershell
cd backend
python -m app.cli parse-all-documents
```

PDF parsing uses `pypdf` by default. PyMuPDF is optional and used only as a fallback when available. OCR is not supported, so scanned or image-only PDFs may produce little or no text.

## Requirements

Parse documents first, then extract requirements:

```powershell
cd backend
python -m app.cli parse-opportunity-documents 1
python -m app.cli extract-requirements 1
python -m app.cli extract-all-requirements
```

Requirements extraction is local-AI-assisted through Ollama and creates a human-reviewable compliance matrix. It does not draft proposals or submit responses.

## Scope Notes

This project currently avoids proposal drafting, OCR, Playwright automation, login scraping, recursive crawling, cloud AI, OpenAI APIs, and automated submission.

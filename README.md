# RFP BidOS

Local-first Python, FastAPI, and React dashboard skeleton for RFP bid workflows.

## Backend Setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m app.cli init-db
python -m app.cli score-opportunity 1
python -m app.cli score-all-opportunities
python -m app.cli scrape-enabled-sources
python -m app.cli download-documents 1
python -m app.cli download-all-documents
python -m app.cli parse-document 1
python -m app.cli parse-opportunity-documents 1
python -m app.cli parse-all-documents
python -m app.cli ai-evaluate-opportunity 1
python -m app.cli ai-evaluate-all-opportunities
uvicorn app.main:app --reload
```

## Frontend Setup

```powershell
cd frontend
npm install
npm run dev
```

## Run Commands

Backend:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

Scoring:

```powershell
python -m app.cli score-opportunity 1
python -m app.cli score-all-opportunities
```

Scraper:

```powershell
python -m app.cli scrape-enabled-sources
```

This phase only supports simple public pages. Login portals, Playwright
automation, document downloading, PDF parsing, and submission workflows are
future phases.

Document downloader:

```powershell
python -m app.cli download-documents 1
python -m app.cli download-all-documents
```

This phase only downloads direct public document URLs. It does not crawl
portals, log in, use Playwright, or parse PDFs.

Parser:

```powershell
python -m app.cli parse-document 1
python -m app.cli parse-opportunity-documents 1
python -m app.cli parse-all-documents
```

This phase only extracts embedded text from PDFs. `pypdf` is the default parser
because it avoids native Windows DLL dependency issues. PyMuPDF/fitz is optional
and used only as a fallback when available. OCR is not supported yet, so
scanned or image-only PDFs may produce little or no text.

Local AI evaluation:

Install Ollama, then pull the local model:

```powershell
ollama pull qwen2.5:3b
```

Run evaluation:

```powershell
python -m app.cli ai-evaluate-opportunity 1
python -m app.cli ai-evaluate-all-opportunities
```

Environment variables:

```powershell
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

Local AI evaluation uses Ollama only. It does not use OpenAI APIs or cloud AI.

Frontend:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

## Warning

Do not commit `.env`, `data/sessions`, `.venv`, or `node_modules`.

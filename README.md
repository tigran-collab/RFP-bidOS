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
python -m app.cli scrape-enabled-sources
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

## Scraper

```powershell
cd backend
python -m app.cli preview-source <source_id>
python -m app.cli scrape-source <source_id>
python -m app.cli scrape-enabled-sources
python -m app.cli check-source-auth <source_id>
python -m app.cli check-all-source-auth
```

The scraper uses source adapters and heuristics for public procurement pages, table listings, notice pages, and direct document links. Preview shows candidates without saving them.

Scraper limitations:

- Public pages only.
- No login portals or credential submission.
- No CAPTCHA bypass.
- No browser automation or Playwright.
- No recursive whole-site crawling.
- No automated submissions.
- Extracted fields require human review.

## Future Authenticated Sources / BidNet Placeholder

- Public scraping is supported for generic public procurement pages.
- Credential-aware source configuration exists: sources may be marked as requiring credentials, with credential type, username, and secret reference fields.
- BidNet can be marked as requiring credentials for future authenticated access via the portal type and credential fields.
- Authenticated scraping is intentionally disabled in this phase. The `BidNetPlaceholderAdapter` returns a controlled "not enabled" message and never performs login, credential submission, or scraping behind a login wall.
- Passwords must not be committed or stored raw in the database.
- Future authenticated access should use:
  - A secure secret store (not plaintext environment variables in production).
  - Review of the portal's terms of service.
  - Rate-limit awareness and human-controlled execution.
  - Explicit user confirmation before any credential submission.
- Scraper capabilities can be checked per source:
  ```powershell
  python -m app.cli source-capabilities <source_id>
  python -m app.cli all-source-capabilities
  ```
- API endpoint: `GET /sources/{id}/scraper-capabilities`

## Scope Notes

This project currently avoids proposal drafting, OCR, Playwright automation, login scraping, recursive crawling, cloud AI, OpenAI APIs, and automated submission.

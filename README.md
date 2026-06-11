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

The public scraper uses heuristic quality filters to reduce page navigation/footer noise (e.g. "Home", "Contact", "Mobile main navigation") before candidates are saved as opportunities. Filtered counts and reasons are reported by `preview-source`, `preview-enabled-sources`, and `scrape-enabled-sources`; use `--show-filtered` on the preview commands to inspect rejected candidates. Results still require human review.

The public scraper attempts to discover solicitation document links (PDFs, addenda, bid packets, specifications, forms, attachments, and other downloadable files) from public pages. Each discovered link gets a confidence score and reason; social/login/nav links are rejected. Downloading and parsing are separate steps:

```powershell
cd backend
python -m app.cli discover-documents <opportunity_id>
python -m app.cli download-all-documents
python -m app.cli parse-all-documents
```

Some portals hide documents behind JavaScript or login and will require future controlled support.

Scraper limitations:

- Public pages only.
- No login portals or credential submission.
- No CAPTCHA bypass.
- No browser automation or Playwright.
- No recursive whole-site crawling.
- No automated submissions.
- Extracted fields require human review.

## Real Source Seeding

Seed curated real public procurement sources for California, Texas, Nevada, and Arizona, then smoke-test them:

```powershell
cd backend
python -m app.cli seed-sources
python -m app.cli preview-enabled-sources
python -m app.cli scrape-enabled-sources
```

Notes:

- Seeded sources are public pages only — no login is required or attempted.
- Seeding is idempotent; rerunning `seed-sources` does not create duplicates.
- JavaScript-heavy portals (Cal eProcure, Texas ESBD, Arizona Procurement Portal, SF City Partner) are seeded disabled with notes, since the HTML scraper gets limited results from them.
- Government portal structures change frequently; scraper results always require human review.
- Login-required sources are skipped cleanly until a future authenticated-source phase.

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

## Bid Logistics

The app extracts critical bid logistics — proposal due date, Q&A deadline, pre-bid meeting date and whether it is mandatory, submission method/portal, required forms, and deadline risk — from parsed document text and opportunity metadata using deterministic regex/heuristics (no AI required, no network).

- Extraction is heuristic and **requires human verification**.
- Deadline risk: `Past Due`, `High` (≤3 days), `Medium` (≤7 days), `Low` (>7 days), `Missing Deadline` (no date found), or `Needs Review` (conflicting dates).
- Conflicting or ambiguous deadlines are recorded in `logistics_notes`, confidence is lowered, and risk is marked `Needs Review`.

```powershell
cd backend
python -m app.cli extract-logistics 1
python -m app.cli extract-logistics-by-status --status Pursue --limit 10
python -m app.cli extract-logistics-all --limit 25
```

API: `POST /opportunities/{id}/extract-logistics` and `POST /opportunities/extract-logistics` (optional `{"review_status","limit"}`, bounded — never unlimited). The Opportunity Detail page has a **Bid Logistics** panel with an Extract Logistics button; the Review Queue shows deadline risk / submission method and can filter by deadline risk; the dashboard surfaces past-due, high-risk, and missing-deadline counts.

## Logistics QA

Bid logistics extraction is heuristic, so a second-pass **Logistics QA** layer reviews the extracted fields and flags missing, contradictory, or risky information before you rely on it. It is deterministic (no AI, no network).

QA flags missing due dates, past-due deadlines, due-within-3-days, passed Q&A deadlines, missing/passed mandatory pre-bid meetings, missing submission method/portal, missing required forms, conflicting deadlines, low extraction confidence, and missing parsed documents for pursued opportunities.

- `qa_status`: `Passed`, `Needs Review`, `Failed`, or `Missing Critical Info`.
- `risk_level`: `Low`, `Medium`, `High`, or `Disqualifying`.
- **Human verification is still required before bidding.**

```powershell
cd backend
python -m app.cli logistics-qa 1
python -m app.cli logistics-qa-by-status --status Pursue --limit 10
```

API: `POST /opportunities/{id}/logistics-qa` (runs + saves), `GET /opportunities/{id}/logistics-qa` (latest result), `POST /opportunities/logistics-qa/by-status`. The Opportunity Detail page has a Logistics QA panel; the Review Queue shows QA status/risk and can filter by QA risk; the dashboard surfaces QA counts and needs-action items.

## Operations Dashboard

The Operations Dashboard is the first page to check each day. It summarizes the review queue, upcoming deadlines (next 30 days), document status (pending download / downloaded / parsed / failed), requirement extraction status, a prioritized "Top Opportunities" list, a "Needs Action" list (what to do next per opportunity), and source health.

```powershell
cd backend
python -m app.cli dashboard
```

API: `GET /dashboard/operations`. The frontend Dashboard page renders summary cards, upcoming deadlines, top opportunities, the needs-action list, and a source-health table.

## Review Queue

Scraped opportunities enter a human-controlled review workflow:

- Newly scraped opportunities start as `New`.
- Rules-based scoring helps prioritize but does **not** replace human review. A clearly negative/noise score suggests `Do Not Pursue`, and a promising score suggests `Needs Review` — but only for opportunities that have not yet been reviewed. Nothing is ever auto-archived or deleted.
- Use `Pursue`, `Do Not Pursue`, `Watchlist`, and `Archived` to control workflow. Set priority (`High` / `Medium` / `Low`) and a next action.
- Documents and AI actions (download, parse, AI evaluation, requirement extraction) should be run deliberately on promising opportunities, not in bulk on noise.

CLI:

```powershell
cd backend
python -m app.cli review-queue
python -m app.cli review-queue --status New
python -m app.cli mark-opportunity 1 --status Pursue
python -m app.cli mark-opportunity 2 --status "Do Not Pursue" --notes "Navigation noise"
```

API: `GET /opportunities/review-queue` (filters: status, priority, state, min_score, max_score, service_type, source_id) and `PATCH /opportunities/{id}/review`. The frontend Review Queue page provides status/priority filters, per-row actions, inline notes, and bulk status changes.

## Pursuit Workflow

The Review Queue controls which opportunities move forward. Once an opportunity is marked `Pursue` or `Watchlist`, **Pursuit Prep** runs the next-step actions deliberately:

1. discover documents
2. download documents
3. parse documents
4. run local AI evaluation
5. extract requirements

Pursuit Prep is only run when you explicitly trigger it — it is never run automatically on every scraped opportunity. Each step's errors are captured and the run continues where it safely can; if the local AI is unavailable, that step records a clean error without failing the whole workflow. After a run, `next_action` is set to `Review Requirements`, `Manual Review`, or `Verify Portal` (when no documents were found). `review_status` is never changed by Pursuit Prep, and nothing is archived or deleted.

Batch prep **requires a review status and a limit** (default 10) so public websites are not hammered; if more items match than the limit, a warning reports how many were skipped.

```powershell
cd backend
python -m app.cli pursuit-prep 1
python -m app.cli pursuit-prep 1 --steps discover_documents,download_documents,parse_documents
python -m app.cli pursuit-prep-by-status --status Pursue --limit 5
```

API: `POST /opportunities/{id}/pursuit-prep` (optional `{"steps": [...]}`) and `POST /opportunities/pursuit-prep/by-status` (`{"status": "Pursue", "limit": 10, "steps": [...]}`). The Review Queue and Opportunity Detail pages have a **Run Pursuit Prep** button.

## Scope Notes

This project currently avoids proposal drafting, OCR, Playwright automation, login scraping, recursive crawling, cloud AI, OpenAI APIs, and automated submission.

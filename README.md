# RFP BidOS

Local-first FastAPI and React dashboard for RFP bid tracking, public-page discovery, document parsing, rules-based scoring, local Ollama evaluation, and human-reviewable requirements extraction.

## Backend Setup

macOS:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m app.cli init-db
python -m app.cli seed-demo
python -m app.cli seed-sources
```

If `python3.12` is not installed, install Python 3.12 or newer and rebuild the backend venv. The app is intended to run on Python 3.12 or 3.13.

Windows:

```cmd
cd backend
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m app.cli init-db
python -m app.cli seed-demo
```

## Frontend Setup

macOS:

```bash
cd frontend
npm install
npm run build
```

Windows:

```cmd
cd frontend
npm.cmd install
npm.cmd run build
```

## Run Manually

Backend:

macOS:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

Windows:

```cmd
cd backend
uvicorn app.main:app
```

Frontend:

macOS:

```bash
cd frontend
npm run dev
```

Windows:

```cmd
cd frontend
npm.cmd run dev
```

Open:

```text
http://localhost:5173
```

## Desktop Launcher

Cross-platform Electron launcher:

```bash
cd desktop
npm install
npm run desktop
```

Manual prerequisites:

- Python 3.12+
- Backend venv created at `backend/.venv`
- Backend requirements installed
- Frontend `npm install` completed
- Ollama installed
- `qwen3:8b` pulled

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

The Electron launcher checks Ollama, starts local backend/frontend development servers, opens a desktop window titled `RFP BidOS`, and loads `http://localhost:5173`. It stops only the processes it started. It does not auto-pull Ollama models.

Icon files can be placed in `desktop/assets/`:

- `icon.png` for Linux and development fallback.
- `icon.icns` for macOS packaging.
- `icon.ico` for Windows packaging.

Packaging commands are documented in `desktop/README.md`.

Legacy script launchers:

Double-click `start_rfp_bidos.bat` from the project root to start the app.

The launcher opens two CMD windows:

- `RFP BidOS Backend`
- `RFP BidOS Frontend`

Keep both windows open while using the app. Closing those windows stops the app.

The launcher waits briefly, then opens:

```cmd
http://localhost:5173
```

To create a Desktop shortcut:

1. Right-click `start_rfp_bidos.bat`.
2. Choose **Show more options** if needed.
3. Choose **Send to > Desktop (create shortcut)**.
4. Rename the shortcut to `RFP BidOS`.

On macOS, run:

```bash
./start_rfp_bidos_mac.sh
```

The Mac launcher checks whether Ollama is reachable at `http://127.0.0.1:11434`, starts `ollama serve` in Terminal if needed, starts backend and frontend Terminal windows, then opens `http://localhost:5173`. It does not install dependencies or create background services.

## Developer Checks

```cmd
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

```cmd
ollama pull qwen3:8b
```

Run local AI evaluation:

```cmd
cd backend
python -m app.cli ai-status
python -m app.cli ai-evaluate-opportunity 1
python -m app.cli ai-evaluate-all-opportunities
```

Environment variables:

macOS:

```bash
export OLLAMA_MODEL=qwen3:8b
export OLLAMA_BASE_URL=http://127.0.0.1:11434
```

Windows:

```cmd
set OLLAMA_MODEL=qwen3:8b
set OLLAMA_BASE_URL=http://127.0.0.1:11434
```

Local AI evaluation uses Ollama only. It does not use OpenAI APIs or cloud AI.
If Ollama is off or the configured model is not installed, CLI/API/frontend surfaces show:
`Local AI model is not available. Start Ollama and make sure qwen3:8b is installed.`
When Ollama is running but `qwen3:8b` is missing, `ai-status` also prints:
`Configured model is not installed. Run: ollama pull qwen3:8b`

## Local AI Chat

The app includes a simple **Local AI Chat** page and an opportunity-aware chat panel on Opportunity Detail. Chat uses local Ollama only with the default model `qwen3:8b`; it does not use OpenAI APIs or cloud AI.

Local AI Chat can use read-only summarized app context, including current opportunities, deadlines, scores, review statuses, requirements, and logistics. It can analyze, rank, compare, and explain opportunities, but it cannot modify records, run scrapers, download documents, parse files, extract requirements, submit bids, or trigger app actions.

Setup:

```bash
ollama pull qwen3:8b
ollama serve
```

Then run the backend and frontend normally. The chat status endpoint checks `http://127.0.0.1:11434` and reports whether `qwen3:8b` is available.

If Ollama is unavailable, the UI shows:

```text
Local AI model is not available. Start Ollama and make sure qwen3:8b is installed.
```

Chat answers are based only on available app data and local model reasoning. Verify official solicitation documents before acting.

## Parsing

```cmd
cd backend
python -m app.cli parse-all-documents
```

PDF parsing uses `pypdf` by default. PyMuPDF is optional and used only as a fallback when available. OCR is not supported, so scanned or image-only PDFs may produce little or no text.

## Requirements

Parse documents first, then extract requirements:

```cmd
cd backend
python -m app.cli parse-opportunity-documents 1
python -m app.cli extract-requirements 1
python -m app.cli extract-all-requirements
```

Requirements extraction is local-AI-assisted through Ollama and creates a human-reviewable compliance matrix. It does not draft proposals or submit responses.

## Scraper

```cmd
cd backend
python -m app.cli preview-source <source_id>
python -m app.cli scrape-source <source_id>
python -m app.cli scrape-enabled-sources
python -m app.cli check-source-auth <source_id>
python -m app.cli check-all-source-auth
```

The scraper uses source adapters and heuristics for public procurement pages, table listings, notice pages, and direct document links. Preview shows candidates without saving them.

The public scraper uses heuristic quality filters to reduce page navigation/footer noise (e.g. "Home", "Contact", "Mobile main navigation") before candidates are saved as opportunities. Filtered counts and reasons are reported by `preview-source`, `preview-enabled-sources`, and `scrape-enabled-sources`; use `--show-filtered` on the preview commands to inspect rejected candidates. Results still require human review.

## Scraper Relevance Filtering

The scraper is keyword-directed toward security services opportunities, especially security guard, armed/unarmed security, patrol, facility security, access control, fire watch, lobby security, alarm response, and similar public safety officer work.

Scraped candidates pass through two filters before they are saved:

1. Quality filtering removes obvious page chrome, navigation links, social links, and generic non-opportunity pages.
2. Relevance filtering scores target security keywords, procurement signals, dates, solicitation numbers, and document links, while rejecting unrelated service categories such as janitorial, landscaping, construction, IT-only work, fleet, supplies, legal/accounting, weapons/ammunition, and similar non-service opportunities.

Only `Relevant` and `Maybe Relevant` candidates are saved. `Not Relevant` candidates can be inspected with preview debug output but are not saved by normal scraping.

As-needed, on-call, standby, bench, task-order, blanket, indefinite-quantity, and no-guaranteed-minimum language is flagged as a caution item. These opportunities are not automatically rejected when they otherwise match security services, but they are marked for manual review before pursuing.

Human review is still required before pursuing or declining any opportunity.

The public scraper attempts to discover solicitation document links (PDFs, addenda, bid packets, specifications, forms, attachments, and other downloadable files) from public pages. Each discovered link gets a confidence score and reason; social/login/nav links are rejected. Downloading and parsing are separate steps:

```cmd
cd backend
python -m app.cli discover-documents <opportunity_id>
python -m app.cli download-documents <opportunity_id>
python -m app.cli parse-opportunity-documents <opportunity_id>
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

```cmd
cd backend
python -m app.cli seed-sources
python -m app.cli preview-enabled-sources
python -m app.cli scrape-enabled-sources
```

Notes:

- Seeded sources are public pages only - no login is required or attempted.
- Seeding is idempotent; rerunning `seed-sources` does not create duplicates.
- JavaScript-heavy portals (Cal eProcure, Texas ESBD, Arizona Procurement Portal, SF City Partner) are seeded enabled with notes; the HTML scraper may return limited results from them, and results require human review.
- Government portal structures change frequently; scraper results always require human review.
- Login-required sources are skipped cleanly until a future authenticated-source phase.

### Socrata Source Discovery

Many governments publish procurement data to Socrata open-data portals. The `discover-socrata-sources` command queries the public Socrata catalog for procurement-related terms, filters to government-looking domains, optionally probes each dataset's columns to guess whether it holds bids, and proposes a best-guess field map.

```cmd
cd backend
python -m app.cli discover-socrata-sources
python -m app.cli discover-socrata-sources --query "bids,solicitations" --limit 30
python -m app.cli discover-socrata-sources --states CA,TX,NV,AZ
python -m app.cli discover-socrata-sources --no-probe
python -m app.cli discover-socrata-sources --seed
```

- Without `--seed`, it prints a table of candidates, clearly separating procurement-shaped datasets from other government datasets, with each candidate's inferred state and suggested field map.
- `--states CA,TX,NV,AZ` keeps only datasets whose domain maps to one of the given states (inferred by domain substring), and applies the filter **before** probing so out-of-state datasets are never fetched. Award/tabulation/historical and charitable-solicitation datasets are never classified as procurement.
- With `--seed`, each procurement candidate that is not already configured is inserted as a **DISABLED** `socrata` SourceConfig. Seeding is idempotent (it echoes created vs. skipped counts) and never enables a source automatically.
- Auto-discovered field maps are **best-guess only** and must be verified by a human before enabling and scraping. The seeded source's notes call this out.
- The catalog query and per-dataset probe are the only network calls, both via the public Socrata API (no key).

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
  ```cmd
  python -m app.cli source-capabilities <source_id>
  python -m app.cli all-source-capabilities
  ```
- API endpoint: `GET /sources/{id}/scraper-capabilities`

## Exports

CSV exports are available for opportunities, requirements, documents, and logistics QA. They are intended for review, sharing, backup, and proposal planning. **No proposal PDFs are generated in this phase.**

```cmd
cd backend
python -m app.cli export-opportunities --output exports/opportunities.csv
python -m app.cli export-requirements --output exports/requirements.csv
python -m app.cli export-documents --output exports/documents.csv
python -m app.cli export-logistics-qa --output exports/logistics_qa.csv
```

The CLI creates the `exports/` directory if missing and prints the row count. API endpoints return `text/csv` downloads: `GET /exports/opportunities.csv` (optional `review_status`, `priority`), `GET /exports/requirements.csv`, `GET /exports/documents.csv`, `GET /exports/logistics-qa.csv` (each optional `opportunity_id`). The Dashboard has one-click export buttons.

## Manual Opportunity Entry

Use manual entry for BidNet, PlanetBids, emails, PDFs, screenshots, and portals that do not scrape cleanly. Manually created opportunities default to `source = "Manual"` and `review_status = "New"`, and appear in the dashboard and review queue alongside scraped ones.

Manual document URLs can be attached to an opportunity, then downloaded, parsed, evaluated, and processed through pursuit prep like any other document. **Manual entry does not submit anything to any portal.**

```cmd
cd backend
python -m app.cli add-opportunity --title "Manual Test Security RFP" --agency "Test Agency" --source-url "https://example.gov/rfp" --due-date 2099-01-01
python -m app.cli update-opportunity 1 --review-status Pursue --priority High --next-action "Download Documents"
python -m app.cli attach-document-url 1 --url "https://example.gov/test.pdf" --label "Manual RFP document"
```

API: `POST /opportunities` (create), `PATCH /opportunities/{id}` (edit - only supplied fields are changed), and `POST /opportunities/{id}/documents/manual-url` (attach a document URL). The frontend has a **New Opportunity** page, an **Edit Opportunity** panel on the detail page, and a manual document URL input.

## Bid Logistics

The app extracts critical bid logistics - proposal due date, Q&A deadline, pre-bid meeting date and whether it is mandatory, submission method/portal, required forms, and deadline risk - from parsed document text and opportunity metadata using deterministic regex/heuristics (no AI required, no network).

- Extraction is heuristic and **requires human verification**.
- Deadline risk: `Past Due`, `High` (3 days or less), `Medium` (7 days or less), `Low` (more than 7 days), `Missing Deadline` (no date found), or `Needs Review` (conflicting dates).
- Conflicting or ambiguous deadlines are recorded in `logistics_notes`, confidence is lowered, and risk is marked `Needs Review`.

```cmd
cd backend
python -m app.cli extract-logistics 1
python -m app.cli extract-logistics-by-status --status Pursue --limit 10
python -m app.cli extract-logistics-all --limit 25
```

API: `POST /opportunities/{id}/extract-logistics` and `POST /opportunities/extract-logistics` (optional `{"review_status","limit"}`, bounded - never unlimited). The Opportunity Detail page has a **Bid Logistics** panel with an Extract Logistics button; the Review Queue shows deadline risk / submission method and can filter by deadline risk; the dashboard surfaces past-due, high-risk, and missing-deadline counts.

## Logistics QA

Bid logistics extraction is heuristic, so a second-pass **Logistics QA** layer reviews the extracted fields and flags missing, contradictory, or risky information before you rely on it. It is deterministic (no AI, no network).

QA flags missing due dates, past-due deadlines, due-within-3-days, passed Q&A deadlines, missing/passed mandatory pre-bid meetings, missing submission method/portal, missing required forms, conflicting deadlines, low extraction confidence, and missing parsed documents for pursued opportunities.

- `qa_status`: `Passed`, `Needs Review`, `Failed`, or `Missing Critical Info`.
- `risk_level`: `Low`, `Medium`, `High`, or `Disqualifying`.
- **Human verification is still required before bidding.**

```cmd
cd backend
python -m app.cli logistics-qa 1
python -m app.cli logistics-qa-by-status --status Pursue --limit 10
```

API: `POST /opportunities/{id}/logistics-qa` (runs + saves), `GET /opportunities/{id}/logistics-qa` (latest result), `POST /opportunities/logistics-qa/by-status`. The Opportunity Detail page has a Logistics QA panel; the Review Queue shows QA status/risk and can filter by QA risk; the dashboard surfaces QA counts and needs-action items.

## Operations Dashboard

The Operations Dashboard is the first page to check each day. It summarizes the review queue, upcoming deadlines (next 30 days), document status (pending download / downloaded / parsed / failed), requirement extraction status, a prioritized "Top Opportunities" list, a "Needs Action" list (what to do next per opportunity), and source health.

```cmd
cd backend
python -m app.cli dashboard
```

API: `GET /dashboard/operations`. The frontend Dashboard page renders summary cards, upcoming deadlines, top opportunities, the needs-action list, and a source-health table.

## Notification Digest

A read-only daily heads-up summarizing what changed and what needs attention. It is deterministic (no AI, no network) and groups opportunities into three buckets: newly relevant opportunities created in the look-back window, deadlines due within the window, and at-risk items (past due or high deadline risk). Archived and Do Not Pursue items are excluded from deadline/risk buckets.

```cmd
cd backend
python -m app.cli digest
python -m app.cli digest --days 14 --limit 25
```

API: `GET /dashboard/digest` (optional `days` default 7, `limit` default 50) returns the structured digest. The digest is review-only and never modifies records.

## Calendar Export

Export bid due dates, Q&A deadlines, and pre-bid meeting dates as a standard RFC 5545 `.ics` calendar that imports into Outlook, Google Calendar, or Apple Calendar. Each deadline becomes an all-day event with a display reminder 2 days before. By default Archived and Do Not Pursue opportunities are excluded; pass an opportunity id to export a single opportunity's deadlines.

```cmd
cd backend
python -m app.cli export-deadlines --output exports/deadlines.ics
python -m app.cli export-deadlines --opportunity-id 1
```

The CLI creates the `exports/` directory if missing and prints the event count. API: `GET /exports/deadlines.ics` (optional `opportunity_id`) returns a `text/calendar` download.

## Daily Run

`daily-run` chains the daily intake into one command: it scrapes all enabled sources (reusing the same per-source scraper as `scrape-enabled-sources`, continuing on per-source errors), re-scores all opportunities, and prints a notification digest. It is CLI-only by design - a synchronous network scrape over HTTP is undesirable.

```cmd
cd backend
python -m app.cli daily-run
python -m app.cli daily-run --days 14
python -m app.cli daily-run --skip-scrape
```

Use `--skip-scrape` to re-score and refresh the digest without touching the network. There is no HTTP endpoint for `daily-run`.

## Review Queue

Scraped opportunities enter a human-controlled review workflow:

- Newly scraped opportunities start as `New`.
- Rules-based scoring helps prioritize but does **not** replace human review. A clearly negative/noise score suggests `Do Not Pursue`, and a promising score suggests `Needs Review` - but only for opportunities that have not yet been reviewed. Nothing is ever auto-archived or deleted.
- Use `Pursue`, `Do Not Pursue`, `Watchlist`, and `Archived` to control workflow. Set priority (`High` / `Medium` / `Low`) and a next action.
- Documents and AI actions (download, parse, AI evaluation, requirement extraction) should be run deliberately on promising opportunities, not in bulk on noise.

CLI:

```cmd
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

Pursuit Prep is only run when you explicitly trigger it - it is never run automatically on every scraped opportunity. Each step's errors are captured and the run continues where it safely can; if the local AI is unavailable, that step records a clean error without failing the whole workflow. After a run, `next_action` is set to `Review Requirements`, `Manual Review`, or `Verify Portal` (when no documents were found). `review_status` is never changed by Pursuit Prep, and nothing is archived or deleted.

Batch prep **requires a review status and a limit** (default 10) so public websites are not hammered; if more items match than the limit, a warning reports how many were skipped.

```cmd
cd backend
python -m app.cli pursuit-prep 1
python -m app.cli pursuit-prep 1 --steps discover_documents,download_documents,parse_documents
python -m app.cli pursuit-prep-by-status --status Pursue --limit 5
```

API: `POST /opportunities/{id}/pursuit-prep` (optional `{"steps": [...]}`) and `POST /opportunities/pursuit-prep/by-status` (`{"status": "Pursue", "limit": 10, "steps": [...]}`). The Review Queue and Opportunity Detail pages have a **Run Pursuit Prep** button.

## Scope Notes

This project currently avoids proposal drafting, OCR, Playwright automation, login scraping, recursive crawling, cloud AI, OpenAI APIs, and automated submission.

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

Install dependencies. The app runs from the Vite **dev server** (`npm run dev`,
see "Run Manually" below) — you do not need to build or serve a `dist/` bundle
to use it. `npm run build` is only needed to verify a production build compiles.

macOS:

```bash
cd frontend
npm install
```

Windows:

```cmd
cd frontend
npm.cmd install
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

> **Dev-mode convenience, not a distributable.** The launcher expects a git
> checkout with the backend venv (`backend/.venv`) and frontend dependencies
> (`frontend/node_modules`) already built — it starts and orchestrates those
> local dev servers. The `electron-builder` packaging targets do **not** produce
> a standalone installable app yet (they bundle only the launcher shell, not the
> Python backend or the frontend). See `desktop/README.md` for details.

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

### AI Summary

The app can generate a concise plain-language summary of an opportunity (and its
parsed documents) to help triage bids. It uses local Ollama only (no cloud/OpenAI)
and is **advisory** - always verify against the official solicitation documents.
If Ollama or the model is unavailable, surfaces show the standard unavailable
message and never crash.

```cmd
cd backend
python -m app.cli ai-summarize-opportunity 1
python -m app.cli ai-summarize-all --limit 25 --status new --force
```

- Endpoint: `POST /opportunities/{id}/ai-summary` (returns `{ok, summary, message}`;
  the saved summary is also returned on the opportunity as `ai_summary` / `ai_summary_at`).
- In-app: a "Generate AI Summary" button on the Opportunity Detail page.

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

Scraper policy and limitations:

- Public data only. No login portals or credential submission, and no scraping behind a login wall.
- **Coverage approach is API-first hybrid.** Preferred order for a source:
  1. A documented/open API (e.g. Socrata SODA).
  2. A portal's own JSON/XHR endpoint called directly with `requests` (the same call the site's JavaScript makes) — no browser required.
  3. Headless-browser rendering (Playwright) **only as a selective fallback** for portals with no reachable API, behind an explicit per-source flag.
- Automated access respects each site's robots.txt, terms of service, and rate limits, and applies polite throttling. No CAPTCHA bypass and no anti-detection/stealth-evasion tooling (reading public data is fine; defeating access controls is out of scope).
- No recursive whole-site crawling; detail-page following is bounded and same-domain by default.
- No automated bid submissions.
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

## Authenticated Sources (assisted login)

Some vendor portals (e.g. PlanetBids) only expose their bids list to a
logged-in user. RFP BidOS supports these through **assisted login**: a real,
visible browser where *you* complete the login (and any CAPTCHA / MFA). The app
never solves CAPTCHAs, forges anti-bot tokens, or bypasses access controls — a
genuine human login is the whole mechanism. Once you log in, the authenticated
session is persisted locally and reused for later scrapes.

> **In-app management (no terminal required).** Everything below can also be
> done from the web UI's **Portals** tab: add a portal (from a template or
> generic), enter credentials, run the assisted login, enable the source, and
> scrape — all from `http://localhost:5173`. Credentials still live only in the
> **OS keychain** (never the app database, never shown back to you), and the
> assisted login still opens a visible browser for you to complete by hand. The
> CLI commands below remain fully supported for scripting.

### One-time setup

```cmd
cd backend
python -m pip install -r requirements.txt
playwright install chromium
```

`keyring` is lightweight and installed with the other requirements. `playwright`
is heavier and only used by the browser path; it is imported lazily, so the app
and the full test suite run without it. `playwright install chromium` downloads
the browser binary and is a required one-time manual step for browser-based
sources.

### Configure a PlanetBids source

Seed the disabled PlanetBids template (via `seed-demo`) or create a
`source_type = "planetbids"` source, then set its real agency/company id
(`cid`) in `config_json`. `config_json` accepts:

```json
{
  "cid": 12345,
  "api_base": "https://api-external.prod.planetbids.com",
  "bids_path": "/papi/bids",
  "params": {"per_page": 100, "page": 1},
  "portal_bid_url_template": "https://vendors.planetbids.com/portal/{cid}/bo/bo-detail/{bid_id}",
  "agency": "Example Agency",
  "field_map": {"id": "id", "title": "title", "solicitation_number": "bidNumber", "due_date": "dueDate", "description": "description"}
}
```

Only `cid` is required; the rest have PlanetBids-sensible defaults. The field
map is config-driven so a portal's schema change degrades gracefully.

### Store credentials and log in

```cmd
cd backend
python -m app.cli set-credentials <source_id> --username you@example.com
python -m app.cli portal-login <source_id>
```

- `set-credentials` prompts for the password **without echoing it** and stores
  it in the **OS keychain** (macOS Keychain / Windows Credential Manager /
  Secret Service). The password is **never** written to the SQLite database,
  committed to git, printed, or logged — only the username and a keychain
  reference are recorded on the source.
- `portal-login` opens a visible browser at the source's `login_url`/`base_url`,
  pre-filling the username/password from the keychain when present (nothing is
  submitted automatically). **Log in once in that window and clear any
  CAPTCHA/MFA.** The window closes when login is detected, or you can close it
  yourself; the authenticated session is persisted to
  `backend/data/browser_profiles/<source_id>/` (gitignored).

### Scrape

```cmd
cd backend
python -m app.cli check-source-auth <source_id>
python -m app.cli scrape-source <source_id>
```

The scrape **reuses the persisted session** headlessly rather than logging in
again, which keeps request volume low. When the session expires, the scrape
returns no records with a clear diagnostic; just re-run `portal-login` to
re-establish it. If Playwright is not installed, authenticated sources are
skipped cleanly (empty result + diagnostic) instead of crashing the batch.

### Add many portals by config (no new code per portal)

Beyond PlanetBids, authenticated portals (BidNet Direct, Bonfire, OpenGov,
DemandStar, or any generic login-gated bids page) are added by **configuration**
using the generic `authenticated_browser` adapter — no new Python per portal.
Each portal keeps its own **keychain entry** and its own **browser profile**
(`backend/data/browser_profiles/<source_id>/`).

Start from a template in the catalog:

```cmd
cd backend
python -m app.cli list-portal-templates
python -m app.cli add-portal --template bidnet --name "City of Example BidNet"
```

`add-portal` creates a **disabled**, credential-requiring source and prints the
next steps. You can also add one from explicit args instead of a template:

```cmd
python -m app.cli add-portal --name "Custom Portal" ^
  --source-type authenticated_browser ^
  --login-url https://portal.example.com/login ^
  --list-url https://portal.example.com/bids
```

Then, per portal:

```cmd
python -m app.cli set-credentials <source_id> --username you@example.com
python -m app.cli portal-login <source_id>
```

The `authenticated_browser` config lives in `config_json`:

```json
{
  "list_url": "https://portal.example.com/bids",
  "wait_selector": "table.bids",
  "agency": "Example Agency",
  "row_selector": "table.bids tbody tr",
  "field_map": {
    "title": "td.title a",
    "solicitation_number": "td.number",
    "due_date": "td.due",
    "agency": "td.agency",
    "source_url": "td.title a"
  }
}
```

Only `list_url` is required. If you omit `row_selector`/`field_map`, the adapter
falls back to the **generic table parser** on the fetched HTML. For a new
generic portal the row/field selectors typically need to be **finalized from a
real logged-in session** — the templates seed placeholders (`TODO_...`), so open
the saved bids-list page after `portal-login` and fill in the real CSS
selectors. (This is why BidNet's selectors are placeholders, not guesses.)

Enable the source, then scrape it like any other:

```cmd
python -m app.cli scrape-source <source_id>
```

### Batch commands across portals

```cmd
cd backend
python -m app.cli portal-login-all          # assisted login, one window at a time
python -m app.cli scrape-authenticated-all  # scrape every enabled authenticated source
```

`portal-login-all` opens each enabled credential source's visible login window
sequentially (pausing between them so windows don't stack).
`scrape-authenticated-all` scrapes every enabled `planetbids` /
`authenticated_browser` source, continuing past per-source failures (e.g. an
expired session) and reporting counts + diagnostics.

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

API: `GET /opportunities/review-queue` (filters: status, priority, state, min_score, max_score, service_type, source_id; optional `sort=priority`) and `PATCH /opportunities/{id}/review`. The frontend Review Queue page provides status/priority filters, per-row actions, inline notes, and bulk status changes.

## Prioritization

A **deterministic** priority score (no AI, no network) helps decide which bids to work first. Each opportunity gets a `priority_rank` (0-100) and a `priority_tier` (`High` >= 60, `Medium` >= 30, else `Low`), computed as a weighted blend of signals already on the row:

- **Relevance** (~0-40): `relevance_decision` (`Relevant` full, `Maybe Relevant` half, otherwise low), scaled by `relevance_score` when present.
- **Deadline urgency** (~0-30): from `due_date` vs now - closer deadlines score higher; past due = 0; a missing due date gets a small neutral credit.
- **Fit** (~0-20): normalized `bid_score` (negatives clamped to 0).
- **As-needed penalty** (-5) when `as_needed_warning` is set.
- **Review-status gate**: `Do Not Pursue`/`Archived` force the rank very low; `Pursue` gets a small boost; `Watchlist` is neutral.

The rank is clamped to `[0, 100]`. This is purely rules/heuristics - no Ollama, no cloud AI.

```cmd
cd backend
python -m app.cli prioritize-all
```

API: `POST /opportunities/prioritize` -> `{"updated": N}`. The Review Queue requests `sort=priority` so the highest-priority rows show first, displays a **Priority** column (e.g. `High (72)`), and has a **Recompute priorities** button that runs the endpoint and reloads.

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

## Notion Connector

The Notion connector syncs opportunities into your own Notion database (your "Government Bid Tracker") so triage/review data can live alongside the rest of your Notion workspace. Syncing **dedups by solicitation number** (matching the "Solicitation Number" property when present) or, failing that, **by title** — existing pages are updated in place (PATCH) rather than duplicated, and new opportunities create a new page.

Only Notion properties that actually exist in your database schema are written, mapped case-insensitively by name: the database's title property ← title; `Agency`, `Due Date`, `Status`, `Priority`, `Relevance`, `Score`, `Solicitation Number`, `Source URL`. Properties whose type is unsupported or that don't exist are skipped, so the connector tolerates any database layout.

**Security:** the Notion integration token is a secret and is stored **only in the OS keychain** (Windows Credential Manager / macOS Keychain / Secret Service) via the same credential store used for portal logins — never in the app database, git, or logs, and never returned by any endpoint. The (non-secret) database id is stored in a small `AppSetting` key/value table.

Setup:

1. Create an internal integration at [notion.so/my-integrations](https://www.notion.so/my-integrations) and copy its token.
2. Open your target database in Notion and share it with the integration (the "..." menu → Connections).
3. Paste the token and database id in **Settings** in the web UI, or run `notion-configure` (below). The database id is the 32-character id in the database URL before `?v=`.

CLI:

```cmd
cd backend
python -m app.cli notion-configure --database-id <DATABASE_ID>   REM prompts for the token without echoing it
python -m app.cli notion-status
python -m app.cli notion-sync --status Pursue --limit 200
```

Endpoints: `GET /notion/status` (never returns the token), `PUT /notion/config` (`{"token": ..., "database_id": ...}`), `DELETE /notion/config`, and `POST /notion/sync` (optional `{"status": ..., "limit": ..., "opportunity_ids": [...]}`). Sync defaults to all non-`Archived` opportunities, bounded by `limit`. The **Settings** page has Save, Test connection, Sync, and Remove-configuration controls.

## Scope Notes

This project currently avoids proposal drafting, OCR, login scraping, recursive crawling, cloud AI, OpenAI APIs, and automated submission.

Scraping approach is **API-first hybrid** (see "Scraper policy and limitations" above): documented/open APIs and portals' own JSON endpoints are preferred; headless-browser rendering (Playwright) is permitted **only as a selective, flagged fallback** for JS-rendered portals that expose no reachable API — with robots.txt/ToS/rate-limit respect and no evasion of access controls. This amends the earlier blanket "no browser automation" note to reflect that most JS portals can be reached via their underlying JSON API without a browser, and that the browser fallback is a deliberate, bounded option for the remainder.

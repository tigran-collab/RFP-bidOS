# RFP BidOS — Prioritized Recommendations

Larger items surfaced by the deep audit (2026-07-07) that were **not**
implemented immediately because they are architectural, need product
decisions, or carry enough risk to deserve their own focused change with
dedicated testing. Ordered by value-to-risk. Everything verifiable and
low-risk from the same audit has already been fixed and committed
(`79004914`..`83fd3a4e`); this file is the deliberate backlog.

---

## P1 — Field provenance / operator-edit protection

**Problem.** Automated writers (scraper relevance refresh, logistics
extractor, daily scorer) can't tell an operator-entered value from a
scraped one. This produces both failure directions: clobbering human
corrections, and refusing to refresh genuinely stale scraped data. The
audit's findings #4, #7, and #13 are all this one root cause. The
committed fixes patch each symptom conservatively (preserve non-empty
fields, lock relevance on reviewed rows), but that also means an operator
*cannot* get an addendum's new due date to refresh a field they once
touched.

**Recommendation.** Add per-field provenance — e.g. a JSON column
`field_sources` on `Opportunity` mapping field name → `"scraped" |
"operator" | "ai"`. Writers consult it: operator-set fields are never
auto-overwritten; scraped/ai fields refresh freely. The Edit form stamps
`"operator"` on changed fields. This retires the scattered preservation
heuristics with one coherent rule.

**Effort:** medium (migration + write-path touch-ups + UI stamp).
**Risk:** low-medium. Do behind tests per writer.

---

## P2 — Pursuit Prep should know the authenticated-portal path and include logistics/QA

**Problem (audit #5).** `pursuit_workflow` runs discover→download→parse→
AI→requirements using only the **public** `requests`-based path. For a
PlanetBids/BidNet opportunity, discover fetches a JS shell (0 docs),
download and requirements then error, and `next_action` becomes "Verify
Portal" — even though the working one-click **Portal Download** exists on
the same page. Separately, logistics extraction and QA are not workflow
steps, so right after a "successful" prep the dashboard immediately flags
the same item "Logistics QA not run yet". The pipeline the UI presents as
complete is not the pipeline the dashboard demands.

**Recommendation.** (a) In pursuit prep, detect an authenticated-portal
source and route document acquisition through
`portal_document_downloader` (with the existing auto-login) instead of the
public downloader. (b) Append `extract-logistics` and `logistics-qa` as
final workflow steps so a completed prep satisfies the dashboard's own
"needs action" checks. (c) Compute `next_action` from **DB state** (does
the opportunity have requirements/logistics now?) rather than this-run
metrics (audit #6), so a re-run while Ollama is down doesn't regress a
good `next_action`.

**Effort:** medium. **Risk:** medium (touches the headed-browser path).
Gate with a source-type branch and integration-style tests using the
existing browser stubs.

---

## P3 — One shared scrape-run/persist service for CLI, API, and daily-run

**Problem (audit #11, #15).** `run_scrape_for_source` + `_scrape_summary`
are duplicated between `cli.py` and `routers/sources.py`; `daily_run`
imports the CLI copy while the UI uses the router copy. They've drifted
once already, and the error handling still differs (CLI
`scrape-enabled-sources` aborts on the first failing source; the API and
daily-run catch per-source and continue). Several smaller CLI/API
divergences ride along: `REVIEW_STATUS_ORDER` duplicated, CLI
`review-queue` missing the API's filters/sort, `portal-login` success
detection differing, `ai-summarize-all --status` filtering the wrong
column, PATCH-can-null vs CLI-can't.

**Recommendation.** Extract one `services/scrape_runner.py` consumed by all
three call sites, returning a structured per-source result; let each caller
choose presentation (raise HTTPException vs print) but share semantics.
Fold the review-queue ordering/filtering into a shared query builder. Fix
`scrape-enabled-sources` to continue-past-failure like the others.

**Effort:** medium. **Risk:** low (mostly mechanical consolidation).

---

## P4 — Distinguish "portal session expired" from "0 new bids"

**Problem (audit #8).** Authenticated adapters degrade to `[]` + a
*diagnostic* on session expiry, and `run_scrape_for_source` marks the run
"completed" when `errors` is empty. So a nightly `daily-run` on an expired
BidNet session reports "completed, 0 found" forever and source-health
shows green — the operator believes there are simply no new bids and
silently misses weeks of opportunities.

**Recommendation.** Have the adapters signal expiry as a first-class
outcome (e.g. set a `session_expired` flag / dedicated ScrapeRun status),
surface it in source-health and the digest ("BidNet needs re-login"), and
have `daily-run` include a re-auth nudge. Pairs naturally with P3.

**Effort:** small-medium. **Risk:** low.

---

## P5 — Global document dedup vs per-opportunity, and requirement→document linkage

**Problem (audit #9, #M3b).** Scraper-side discovery dedups documents by
URL **globally** (`Document.source_url == url` across all opportunities),
while the downloader correctly scopes per-opportunity — so when two bids
link the same "General Terms.pdf", the second never gets its own Document
row and runs its pipeline on an incomplete set. Separately, extracted
requirements are saved with `document_id=None` even though the prompt
carried each snippet's Document id, so requirements can't be traced to
their source file.

**Recommendation.** Scope discovery dedup to the opportunity (match the
downloader). Have the requirement-extraction prompt echo the source
Document id per requirement and persist it (populate `Requirement.
document_id`/`source_file`), enabling per-document compliance tracing and
export columns that are currently always null.

**Effort:** small-medium. **Risk:** low.

---

## P6 — Persistence & migration robustness for growth and non-SQLite

**Problem (audit L1, M7).** `_ensure_columns` requires every new model
column to be mirrored by hand (no drift detection), can't add declared
indexes on migrated DBs, and is skipped entirely for non-SQLite
`DATABASE_URL`. Several hot paths load whole tables
(`get_operations_dashboard` reads six tables/request; `build_digest`
loads all opportunities; `BidLogisticsQA` grows one row per QA run and is
never pruned). Fine at hundreds of rows; these are the first things to
hurt at tens of thousands.

**Recommendation.** Adopt Alembic (or at least a schema-version check that
warns on drift) before the schema grows further; add
`created_at`/status indexes; bound the dashboard/digest queries with
`LIMIT` + aggregate counts instead of full loads; prune or cap
`BidLogisticsQA` history. Not urgent at current scale — do it before any
multi-user or hosted deployment.

**Effort:** medium. **Risk:** medium (migration tooling change).

---

## P7 — Real desktop distribution (or drop the packaging claim)

**Problem (audit 1.3).** The Electron `electron-builder` config ships only
the launcher files; `main.js` resolves the backend venv and frontend
`node_modules` relative to `__dirname`, which points inside `app.asar` in
a packaged build, so `checkPrerequisites()` always fails. The launcher
only works from a git checkout. The READMEs have been corrected to say
"dev-only" and a TODO documents what's needed; this item is the actual
implementation.

**Recommendation.** If a distributable is a goal: ship backend + frontend
via `extraResources`, detect `app.isPackaged` and resolve `appRoot` to
`process.resourcesPath`, and bundle a Python runtime (or pre-built venv)
per platform. This is a real project; scope it deliberately. If not a
goal, the current dev-only launcher + honest docs are sufficient.

**Effort:** large. **Risk:** medium.

---

## P8 — Client-side niceties already scaffolded

Small, safe, do when convenient (not started; the audit rated them
polish): hash-based routing so refresh/Back/bookmarks work and opportunity
detail is linkable (audit 2.4); unsaved-changes guard on the New/Edit
opportunity forms (2.5); sticky table headers offset below the nav so they
don't slide under it; per-page refetch dimming on ReviewQueue filter
changes.

**Effort:** small each. **Risk:** low.

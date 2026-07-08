"""Generic config-driven authenticated (assisted-login) browser adapter.

Many vendor portals (BidNet Direct, Bonfire, OpenGov, DemandStar, ...) only
expose their bids list to a logged-in user, and each renders a different HTML
page. Rather than write a new Python adapter per portal, this ONE adapter reads
everything it needs from ``SourceConfig.config_json`` so a new authenticated
portal is added purely by configuration.

It reuses the SAME assisted-login mechanism as the PlanetBids adapter: a real
human logs in once in a VISIBLE browser (see ``browser_session``); that session
is persisted to an on-disk profile and reused HEADLESSLY here. This adapter
never solves CAPTCHAs, forges anti-bot tokens, or bypasses access controls.

``config_json`` shape::

    {
      "list_url": "https://portal.example.com/bids",   # required
      "wait_selector": "table.bids",                     # optional
      "agency": "Example Agency",                        # optional fallback

      # Option A — per-row extraction with CSS selectors:
      "row_selector": "table.bids tbody tr",
      "field_map": {
        "title": "td.title a",
        "solicitation_number": "td.number",
        "due_date": "td.due",
        "agency": "td.agency",
        "source_url": "td.title a"   # optional; else first row anchor
      }

      # Option B — omit row_selector/field_map to fall back to the generic
      # table parser (parse_tables) on the fetched HTML.
    }

Only ``list_url`` is required. On a missing/expired session, Playwright not
being installed, or a missing ``list_url``, ``scrape`` returns [] and records a
clear diagnostic rather than crashing the batch.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.config import BROWSER_PROFILE_ROOT
from app.services.scrapers.base import ScraperResult
from app.services.scrapers.browser_session import (
    PlaywrightNotInstalledError,
    SessionExpiredError,
    fetch_authenticated_html,
    fetch_authenticated_html_batch,
    playwright_available,
)
from app.services.scrapers.extraction_utils import (
    confidence_from_text,
    enrich_result_from_text,
    extract_due_date,
    extract_solicitation_number,
    normalize_space,
)
from app.services.scrapers.table_parser import parse_tables

SOURCE_TYPE = "authenticated_browser"

def profile_dir_for_source(source_config) -> str:
    source_id = getattr(source_config, "id", None)
    key = str(source_id) if source_id is not None else "unknown"
    return str(BROWSER_PROFILE_ROOT / key)


class AuthenticatedBrowserAdapter:
    def __init__(self, timeout: int = 45) -> None:
        self.timeout = timeout
        self.diagnostics: list[str] = []

    def can_handle(self, source_config) -> bool:
        return (
            getattr(source_config, "source_type", "") or ""
        ).lower() == SOURCE_TYPE

    def check_auth_ready(self, source_config) -> dict:
        """Report whether an authenticated scrape can be attempted.

        Requires: keyring-configured credentials (username + secret ref +
        stored password) and a persisted browser profile from assisted login.
        No network calls; no password value is returned.
        """
        from app.services.source_credentials import get_source_auth_status

        missing: list[str] = []
        auth = get_source_auth_status(source_config)
        if auth.get("auth_status") != "Configured":
            missing.extend(auth.get("missing_fields") or ["credentials not configured"])

        profile_dir = profile_dir_for_source(source_config)
        if not Path(profile_dir).exists():
            missing.append("no persisted browser session (run portal-login)")

        if not playwright_available():
            missing.append("Playwright not installed (run playwright install chromium)")

        ready = not missing
        message = (
            "Authenticated browser access is ready."
            if ready
            else "Authenticated browser access is not ready: " + ", ".join(missing)
        )
        return {"ready": ready, "message": message, "missing_fields": missing}

    def scrape(self, source_config) -> list[ScraperResult]:
        self.diagnostics = []
        config = _load_config(source_config)
        list_url = config.get("list_url")
        if not list_url:
            self.diagnostics.append(
                "authenticated_browser source requires config_json with a list_url."
            )
            return []

        if not playwright_available():
            self.diagnostics.append(
                "Playwright is not installed; skipping authenticated browser "
                "scrape. Run `pip install -r requirements.txt` then "
                "`playwright install chromium`."
            )
            return []

        wait_selector = config.get("wait_selector")
        profile_dir = profile_dir_for_source(source_config)
        # Some portals (e.g. WAF-protected ones) refuse headless automation even
        # with a valid session. Setting "fetch_headless": false reuses the session
        # in a VISIBLE browser window, which reads like a real browser. Default is
        # headless (no window).
        fetch_headless = config.get("fetch_headless", True)

        try:
            html = fetch_authenticated_html(
                list_url,
                profile_dir,
                wait_selector=wait_selector,
                timeout_seconds=self.timeout,
                headless=fetch_headless,
                search_keyword=config.get("search_keyword"),
                search_input_selector=config.get("search_input_selector"),
                search_submit_selector=config.get("search_submit_selector"),
            )
        except SessionExpiredError as exc:
            self.diagnostics.append(
                f"Authenticated browser session expired or not established: {exc} "
                "Run `portal-login` to (re)establish the session."
            )
            return []
        except PlaywrightNotInstalledError as exc:
            self.diagnostics.append(f"Playwright unavailable: {exc}")
            return []
        except Exception as exc:
            self.diagnostics.append(f"Authenticated browser fetch failed: {exc}")
            return []

        agency_fallback = config.get("agency") or getattr(source_config, "name", None)
        row_selector = config.get("row_selector")
        field_map = config.get("field_map") or {}

        if row_selector and field_map:
            results = self._parse_rows(
                html, list_url, row_selector, field_map, agency_fallback
            )
            self.diagnostics.append(
                f"Authenticated browser: mapped {len(results)} row(s) via field_map."
            )
        else:
            # Fallback: reuse the generic table parser on the fetched HTML.
            results = parse_tables(html, list_url, portal_url=list_url)
            for result in results:
                if not result.agency:
                    result.agency = agency_fallback
                result.extraction_method = "authenticated_browser_table"
            self.diagnostics.append(
                f"Authenticated browser: table-parser fallback mapped {len(results)} row(s)."
            )

        self._enrich_from_detail_pages(
            results, config, profile_dir, fetch_headless, agency_fallback
        )
        return results

    def _enrich_from_detail_pages(
        self,
        results: list[ScraperResult],
        config: dict,
        profile_dir: str,
        fetch_headless: bool,
        agency_fallback: str | None,
    ) -> None:
        """Visit each candidate's detail page and fill the breakdown fields.

        List rows carry little beyond title/due date, and on multi-agency
        portals the agency fallback is the PORTAL name — the issuing agency,
        location, service/contract type, value, and description all live on
        the detail page.

        All detail pages are fetched inside ONE reused browser context (see
        ``fetch_authenticated_html_batch``) with a small politeness delay
        between pages, instead of launching a fresh browser per page. Per-page
        failures are diagnostics, never fatal; a session that expires mid-batch
        stops enrichment.
        """
        limit = int(config.get("detail_limit") or 10)
        throttle = float(config.get("detail_throttle_seconds", 0.5) or 0.0)
        list_url = config.get("list_url")
        replace_values = {value for value in (agency_fallback,) if value}

        # Collect the candidates that have a distinct detail page, capped.
        pending: list[tuple[ScraperResult, str]] = []
        eligible = 0
        for result in results:
            url = result.detail_url or result.source_url
            if not url or url == list_url:
                continue
            eligible += 1
            if len(pending) < limit:
                pending.append((result, url))
        if eligible > len(pending):
            self.diagnostics.append(
                f"Detail enrichment capped at {limit} page(s); "
                f"{eligible - len(pending)} candidate(s) left unenriched."
            )
        if not pending:
            return

        try:
            fetched = fetch_authenticated_html_batch(
                [url for _, url in pending],
                profile_dir,
                wait_selector=config.get("detail_wait_selector"),
                timeout_seconds=self.timeout,
                headless=fetch_headless,
                throttle_seconds=throttle,
            )
        except SessionExpiredError as exc:
            self.diagnostics.append(
                f"Detail enrichment stopped: session expired ({exc})"
            )
            return
        except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
            self.diagnostics.append(f"Detail enrichment failed: {exc}")
            return

        enriched = 0
        for (result, url), page in zip(pending, fetched):
            error = page.get("error")
            if error is not None:
                if page.get("session_expired"):
                    self.diagnostics.append(
                        f"Detail enrichment stopped: session expired ({error})"
                    )
                    break
                self.diagnostics.append(f"Detail enrichment failed for {url}: {error}")
                continue
            text = BeautifulSoup(page.get("html") or "", "html.parser").get_text(" ", strip=True)
            enrich_result_from_text(result, text, replace_agency_values=replace_values)
            result.extraction_method = f"{result.extraction_method or 'authenticated_browser'}+detail"
            enriched += 1
        if enriched:
            self.diagnostics.append(
                f"Authenticated browser: enriched {enriched} candidate(s) from detail pages."
            )

    def _parse_rows(
        self,
        html: str,
        list_url: str,
        row_selector: str,
        field_map: dict,
        agency_fallback: str | None,
    ) -> list[ScraperResult]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[ScraperResult] = []
        for row in soup.select(row_selector):
            result = _row_to_result(row, list_url, field_map, agency_fallback)
            if result is not None:
                results.append(result)
        return results


def _row_to_result(
    row, list_url: str, field_map: dict, agency_fallback: str | None
) -> ScraperResult | None:
    def mapped(field: str) -> str | None:
        selector = field_map.get(field)
        if not selector:
            return None
        node = row.select_one(selector)
        if node is None:
            return None
        text = normalize_space(node.get_text(" ", strip=True))
        return text or None

    title = mapped("title")
    if not title:
        return None

    source_url = _resolve_row_url(row, list_url, field_map)
    solicitation = mapped("solicitation_number") or extract_solicitation_number(title)
    due_raw = mapped("due_date")
    due_date = extract_due_date(f"due date: {due_raw}") if due_raw else None
    description = mapped("description") or title
    row_text = normalize_space(row.get_text(" ", strip=True))

    return ScraperResult(
        title=title,
        agency=mapped("agency") or agency_fallback,
        solicitation_number=solicitation,
        source_url=source_url or list_url,
        detail_url=source_url,
        portal_url=list_url,
        due_date=due_date,
        description=description,
        raw_text=row_text or title,
        extraction_method="authenticated_browser_row",
        confidence_score=confidence_from_text(title, row_text, []),
    )


def _resolve_row_url(row, list_url: str, field_map: dict) -> str | None:
    """Resolve the row's detail link against list_url.

    Prefers an explicitly mapped ``source_url`` selector's href; otherwise uses
    the first anchor found in the row.
    """
    selector = field_map.get("source_url")
    anchor = None
    if selector:
        node = row.select_one(selector)
        if node is not None:
            anchor = node if node.name == "a" else node.find("a", href=True)
    if anchor is None:
        anchor = row.find("a", href=True)
    if anchor is None:
        return None
    href = str(anchor.get("href") or "").strip()
    if not href:
        return None
    return urljoin(list_url, href)


def _load_config(source_config) -> dict:
    raw = getattr(source_config, "config_json", None)
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}

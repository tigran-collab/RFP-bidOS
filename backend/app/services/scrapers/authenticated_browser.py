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
      "search_keywords": ["California", "Texas"],        # optional multi-search
      "state_filter": ["CA", "TX"],                      # optional keep-list

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
from app.services.region import (
    ALLOWED_STATES,
    STATE_NAME_BY_CODE,
    allowed_states_label,
    text_mentions_state,
)
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

# Portals that aggregate bids from many states behind one login. Their listings
# mix regions, so when no explicit state_filter is configured they still default
# to the operating region (CA/TX) instead of passing everything through. Matched
# case-insensitively against a source's portal_type / name / URLs.
_MULTI_STATE_AGGREGATOR_MARKERS = ("bidnet", "demandstar")


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

        agency_fallback = config.get("agency") or getattr(source_config, "name", None)
        row_selector = config.get("row_selector")
        field_map = config.get("field_map") or {}
        # Resolve the state allow-list ONCE, up front: enrichment sizing and the
        # final filter must agree, and a multi-state aggregator with no explicit
        # filter still defaults to the operating region.
        allowed_states = self._resolve_allowed_states(config, source_config)
        results: list[ScraperResult] = []

        for search_keyword in _search_keywords(config):
            try:
                html = fetch_authenticated_html(
                    list_url,
                    profile_dir,
                    wait_selector=wait_selector,
                    timeout_seconds=self.timeout,
                    headless=fetch_headless,
                    search_keyword=search_keyword,
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

            page_results = self._parse_listing_html(
                html, list_url, row_selector, field_map, agency_fallback
            )
            if search_keyword:
                self.diagnostics.append(
                    f"Authenticated browser: searched {search_keyword!r} and mapped "
                    f"{len(page_results)} row(s)."
                )
            results.extend(page_results)

        results = _dedupe_results(results, list_url)

        enriched_ids = self._enrich_from_detail_pages(
            results, config, profile_dir, fetch_headless, agency_fallback, allowed_states
        )
        if allowed_states:
            results = self._apply_state_filter(results, allowed_states, list_url, enriched_ids)
        return results

    def _resolve_allowed_states(self, config: dict, source_config) -> set[str]:
        """Determine which states this source's candidates may come from.

        The operating region (CA/TX) is a HARD ceiling: whatever a source
        configures, the effective allow-list is always a subset of
        ``ALLOWED_STATES``. Precedence:
        - An explicit ``state_filter``/``allowed_states`` is honored but clamped
          to the region; a stale out-of-region value (e.g. a leftover ``NV``)
          can never re-open that state. If clamping empties the filter, the
          region default is enforced rather than falling through to "no filter".
        - Otherwise a multi-state aggregator (BidNet, DemandStar) defaults to
          the region so it never leaks out-of-region bids even when its config
          predates the filter.
        - A single-agency portal with no filter is left unfiltered (its bids
          are inherently in its own state; the source is region-gated upstream).
        """
        configured, ignored_state_values = _state_filter(config)
        if ignored_state_values:
            self.diagnostics.append(
                "Authenticated browser: ignored unrecognized state_filter "
                "value(s): " + ", ".join(ignored_state_values) + "."
            )

        if configured:
            allowed_states = configured & set(ALLOWED_STATES)
            dropped = configured - set(ALLOWED_STATES)
            if dropped:
                self.diagnostics.append(
                    "Authenticated browser: state_filter value(s) "
                    f"{', '.join(sorted(dropped))} are outside the operating "
                    f"region and were ignored ({allowed_states_label()} only)."
                )
            if not allowed_states:
                # Configured only out-of-region states: the region rule wins;
                # never fall through to an empty (no-op) filter.
                allowed_states = set(ALLOWED_STATES)
            return allowed_states

        if _is_multi_state_aggregator(source_config, config):
            self.diagnostics.append(
                "Authenticated browser: no state_filter configured for a "
                f"multi-state aggregator; defaulting to {allowed_states_label()} "
                "only."
            )
            return set(ALLOWED_STATES)

        return set()

    def _apply_state_filter(
        self,
        results: list[ScraperResult],
        allowed_states: set[str],
        list_url: str | None,
        enriched_ids: set[int],
    ) -> list[ScraperResult]:
        """Keep only candidates whose own text mentions an allowed state.

        A candidate with no allowed-state mention is dropped even when its
        detail page could not be fetched — the filter's contract is "only
        these states", so unverifiable candidates are named in diagnostics
        rather than passed through.
        """
        kept: list[ScraperResult] = []
        dropped_unverified: list[str] = []
        for result in results:
            if _candidate_matches_allowed_state(result, allowed_states, list_url):
                kept.append(result)
                continue
            if id(result) not in enriched_ids:
                dropped_unverified.append(
                    result.title or result.detail_url or result.source_url or "untitled"
                )
        removed = len(results) - len(kept)
        if removed:
            self.diagnostics.append(
                f"Authenticated browser: state filter removed {removed} "
                f"candidate(s); {len(kept)} remain."
            )
        if dropped_unverified:
            shown = "; ".join(dropped_unverified[:10])
            if len(dropped_unverified) > 10:
                shown += "; …"
            self.diagnostics.append(
                f"State filter dropped {len(dropped_unverified)} candidate(s) "
                f"whose detail page could not be checked: {shown}"
            )
        return kept

    def _parse_listing_html(
        self,
        html: str,
        list_url: str,
        row_selector: str | None,
        field_map: dict,
        agency_fallback: str | None,
    ) -> list[ScraperResult]:
        if row_selector and field_map:
            results = self._parse_rows(
                html, list_url, row_selector, field_map, agency_fallback
            )
            self.diagnostics.append(
                f"Authenticated browser: mapped {len(results)} row(s) via field_map."
            )
            return results

        # Fallback: reuse the generic table parser on the fetched HTML.
        results = parse_tables(html, list_url, portal_url=list_url)
        for result in results:
            if not result.agency:
                result.agency = agency_fallback
            result.extraction_method = "authenticated_browser_table"
        self.diagnostics.append(
            f"Authenticated browser: table-parser fallback mapped {len(results)} row(s)."
        )
        return results

    def _enrich_from_detail_pages(
        self,
        results: list[ScraperResult],
        config: dict,
        profile_dir: str,
        fetch_headless: bool,
        agency_fallback: str | None,
        allowed_states: set[str],
    ) -> set[int]:
        """Visit each candidate's detail page and fill the breakdown fields.

        Returns the ``id()`` of every successfully enriched result so callers
        (the state filter) can tell which candidates actually carry detail-page
        location data.

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
        configured_limit = config.get("detail_limit")
        if allowed_states:
            # The state filter needs detail-page text for EVERY candidate —
            # unverifiable candidates are dropped, so a cap here (even an
            # explicit detail_limit) would silently throw away genuine in-state
            # bids whose list row carries no state token. Region correctness
            # outranks the politeness cap.
            limit = len(results)
        elif configured_limit is not None:
            limit = int(configured_limit)
        else:
            limit = 10
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
            return set()

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
            return set()
        except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
            self.diagnostics.append(f"Detail enrichment failed: {exc}")
            return set()

        enriched_ids: set[int] = set()
        for (result, url), page in zip(pending, fetched, strict=False):
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
            enriched_ids.add(id(result))
        if enriched_ids:
            self.diagnostics.append(
                f"Authenticated browser: enriched {len(enriched_ids)} candidate(s) from detail pages."
            )
        return enriched_ids

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


def _search_keywords(config: dict) -> list[str | None]:
    configured = config.get("search_keywords")
    # Accept a comma-separated string as well as a list, matching _state_filter;
    # hand-edited config_json commonly uses the string form.
    if isinstance(configured, str):
        configured = configured.split(",")
    if isinstance(configured, list):
        keywords = [str(value).strip() for value in configured if str(value).strip()]
        return keywords or [None]

    single = str(config.get("search_keyword") or "").strip()
    return [single] if single else [None]


def _dedupe_results(
    results: list[ScraperResult], list_url: str
) -> list[ScraperResult]:
    deduped: list[ScraperResult] = []
    seen: set[str] = set()
    for result in results:
        key = _dedupe_key(result, list_url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def _dedupe_key(result: ScraperResult, list_url: str) -> str:
    detail_url = (result.detail_url or "").strip()
    if detail_url:
        return f"url:{detail_url}"

    source_url = (result.source_url or "").strip()
    if source_url and source_url != list_url:
        return f"url:{source_url}"

    title = normalize_space(result.title or "").lower()
    solicitation = normalize_space(result.solicitation_number or "").lower()
    agency = normalize_space(result.agency or "").lower()
    return f"text:{title}|{solicitation}|{agency}"


def _state_filter(config: dict) -> tuple[set[str], list[str]]:
    """Parse the configured state filter.

    Returns (accepted state codes, ignored raw values). Any two-letter code is
    accepted — silently dropping an unmapped code like "NM" would either
    disable the filter (empty set) or invert it (explicitly allowed state
    removed), both wrong.
    """
    raw = config.get("state_filter") or config.get("allowed_states")
    values: list[str] = []
    if isinstance(raw, str):
        values = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, list):
        values = [str(part).strip() for part in raw]

    states: set[str] = set()
    ignored: list[str] = []
    for value in values:
        if not value:
            continue
        upper = value.upper()
        if len(upper) == 2 and upper.isalpha():
            states.add(upper)
            continue
        for code, name in STATE_NAME_BY_CODE.items():
            if value.lower() == name:
                states.add(code)
                break
        else:
            ignored.append(value)
    return states, ignored


def _candidate_matches_allowed_state(
    result: ScraperResult, allowed_states: set[str], list_url: str | None = None
) -> bool:
    # portal_url is the shared list page — never per-candidate evidence: a
    # state token in the configured list URL (e.g. .../california/lapg) would
    # make every candidate pass. source_url/detail_url count only when they
    # point somewhere other than the list page.
    candidate_urls = [
        url
        for url in (result.source_url, result.detail_url)
        if url and url != list_url
    ]
    text = " ".join(
        str(value)
        for value in (
            result.title,
            result.agency,
            result.location,
            result.description,
            result.raw_text,
            *candidate_urls,
        )
        if value
    ).lower()

    return any(text_mentions_state(text, state) for state in allowed_states)


def _is_multi_state_aggregator(source_config, config: dict | None = None) -> bool:
    """True for portals that aggregate many states behind one login.

    Scans the source's identity fields AND the config's ``list_url``/``agency``:
    the fetched ``list_url`` is the one field guaranteed to carry the portal's
    real URL (base_url/login_url are optional and often null), so an aggregator
    whose bidnet/demandstar URL lives only in config_json is still recognized.
    """
    parts = [
        str(getattr(source_config, attr, "") or "")
        for attr in ("portal_type", "name", "base_url", "login_url")
    ]
    if config:
        parts.append(str(config.get("list_url") or ""))
        parts.append(str(config.get("agency") or ""))
    haystack = " ".join(parts).lower()
    return any(marker in haystack for marker in _MULTI_STATE_AGGREGATOR_MARKERS)


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

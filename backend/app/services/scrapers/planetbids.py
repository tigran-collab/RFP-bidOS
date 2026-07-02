"""PlanetBids authenticated (assisted-login) adapter.

PlanetBids vendor portals (``vendors.planetbids.com/portal/{cid}/...``) are
Ember SPAs backed by ``https://api-external.prod.planetbids.com`` with the
``papi`` namespace. The portal URL number is the agency/company id (``cid``).
The open-bids list is:

    GET /papi/bids?cid={cid}&page=&per_page=&...

When a real user is LOGGED IN, the portal attaches the auth token and this list
call succeeds legitimately. This adapter therefore reads the bids list through a
persisted, human-established browser session (see ``browser_session``): a real
login the human performed, reused headlessly. It does NOT forge Origin/Referer
headers, bootstrap visit tokens, or otherwise defeat the DIRECT_ACCESS
anti-scraping guard — that boundary is intentionally not crossed.

Configuration lives in SourceConfig.config_json, e.g.:

    {
      "cid": 12345,
      "api_base": "https://api-external.prod.planetbids.com",
      "bids_path": "/papi/bids",
      "params": {"per_page": 100, "page": 1},
      "portal_bid_url_template":
        "https://vendors.planetbids.com/portal/{cid}/bo/bo-detail/{bid_id}",
      "agency": "Example Agency",
      "field_map": {
        "id": "id",
        "title": "title",
        "solicitation_number": "bidNumber",
        "agency": null,
        "due_date": "dueDate",
        "description": "description"
      }
    }

Only ``cid`` is required; everything else has PlanetBids-sensible defaults. On a
missing browser session, an expired session, or Playwright not being installed,
``scrape`` returns [] and records a clear diagnostic rather than crashing the
batch.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from app.services.scrapers.base import ScraperResult
from app.services.scrapers.browser_session import (
    PlaywrightNotInstalledError,
    SessionExpiredError,
    fetch_authenticated_json,
    playwright_available,
)
from app.services.scrapers.extraction_utils import normalize_space, parse_date

DEFAULT_API_BASE = "https://api-external.prod.planetbids.com"
DEFAULT_BIDS_PATH = "/papi/bids"
DEFAULT_PORTAL_BID_URL_TEMPLATE = (
    "https://vendors.planetbids.com/portal/{cid}/bo/bo-detail/{bid_id}"
)
DEFAULT_FIELD_MAP = {
    "id": "id",
    "title": "title",
    "solicitation_number": "bidNumber",
    "agency": None,
    "due_date": "dueDate",
    "description": "description",
}

# Where each source's persisted browser profile lives. Gitignored.
_PROFILE_ROOT = Path(__file__).resolve().parents[3] / "data" / "browser_profiles"


def profile_dir_for_source(source_config) -> str:
    source_id = getattr(source_config, "id", None)
    key = str(source_id) if source_id is not None else "unknown"
    return str(_PROFILE_ROOT / key)


class PlanetBidsAuthAdapter:
    def __init__(self, timeout: int = 45) -> None:
        self.timeout = timeout
        self.diagnostics: list[str] = []

    def can_handle(self, source_config) -> bool:
        return (getattr(source_config, "source_type", "") or "").lower() == "planetbids"

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
            "Authenticated PlanetBids access is ready."
            if ready
            else "PlanetBids assisted-login access is not ready: " + ", ".join(missing)
        )
        return {"ready": ready, "message": message, "missing_fields": missing}

    def scrape(self, source_config) -> list[ScraperResult]:
        self.diagnostics = []
        config = _load_config(source_config)
        cid = config.get("cid")
        if not cid:
            self.diagnostics.append(
                "PlanetBids source requires config_json with a numeric cid."
            )
            return []

        if not playwright_available():
            self.diagnostics.append(
                "Playwright is not installed; skipping PlanetBids authenticated "
                "scrape. Run `pip install -r requirements.txt` then "
                "`playwright install chromium`."
            )
            return []

        api_url = _build_bids_url(config, cid)
        profile_dir = profile_dir_for_source(source_config)

        try:
            payload = fetch_authenticated_json(
                api_url, profile_dir, timeout_seconds=self.timeout
            )
        except SessionExpiredError as exc:
            self.diagnostics.append(
                f"PlanetBids session expired or not established: {exc} "
                "Run `portal-login` to (re)establish the session."
            )
            return []
        except PlaywrightNotInstalledError as exc:
            self.diagnostics.append(f"Playwright unavailable: {exc}")
            return []
        except Exception as exc:
            self.diagnostics.append(f"PlanetBids fetch failed: {exc}")
            return []

        records = _extract_records(payload)
        field_map = {**DEFAULT_FIELD_MAP, **(config.get("field_map") or {})}
        agency_fallback = (
            config.get("agency") or getattr(source_config, "name", None)
        )
        template = config.get("portal_bid_url_template") or DEFAULT_PORTAL_BID_URL_TEMPLATE

        results: list[ScraperResult] = []
        for record in records:
            result = _record_to_result(
                record, field_map, agency_fallback, template, cid
            )
            if result is not None:
                results.append(result)
        self.diagnostics.append(
            f"PlanetBids: mapped {len(results)} bid(s) from {len(records)} record(s)."
        )
        return results


def _record_to_result(
    record: dict,
    field_map: dict,
    agency_fallback: str | None,
    template: str,
    cid,
) -> ScraperResult | None:
    if not isinstance(record, dict):
        return None

    def mapped(field: str):
        column = field_map.get(field)
        if not column:
            return None
        value = record.get(column)
        if value is None or value == "":
            return None
        return normalize_space(str(value))

    title = mapped("title")
    if not title:
        return None

    bid_id = record.get(field_map.get("id") or "id")
    source_url = None
    if bid_id not in (None, "") and template:
        try:
            source_url = template.format(cid=cid, bid_id=bid_id)
        except (KeyError, IndexError):
            source_url = None

    return ScraperResult(
        title=title,
        agency=mapped("agency") or agency_fallback,
        solicitation_number=mapped("solicitation_number"),
        source_url=source_url,
        detail_url=source_url,
        due_date=_parse_date(mapped("due_date")),
        description=mapped("description") or title,
        raw_text=title,
        extraction_method="planetbids_authenticated",
        confidence_score=0.7,
    )


def _extract_records(payload) -> list[dict]:
    """Pull the list of bid objects out of a papi response.

    Tolerates both a bare list and common envelope shapes
    ({"data": [...]}, {"bids": [...]}).
    """
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("data", "bids", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def _build_bids_url(config: dict, cid) -> str:
    api_base = (config.get("api_base") or DEFAULT_API_BASE).rstrip("/")
    bids_path = config.get("bids_path") or DEFAULT_BIDS_PATH
    if not bids_path.startswith("/"):
        bids_path = "/" + bids_path

    params = {"cid": cid}
    params.update(config.get("params") or {})
    query = urlencode(
        {key: value for key, value in params.items() if value not in (None, "")}
    )
    url = f"{api_base}{bids_path}"
    return f"{url}?{query}" if query else url


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


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "").split(".")[0])
    except ValueError:
        return parse_date(value)
    if parsed.tzinfo is not None:
        # Numeric offsets parse as aware datetimes, which cannot be
        # compared/sorted against the naive dates used everywhere else.
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed

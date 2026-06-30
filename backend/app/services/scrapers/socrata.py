"""Socrata Open Data adapter.

Many state, county, and city governments publish their procurement
solicitations to Socrata open-data portals (e.g. citydata.mesaaz.gov). Socrata
exposes a documented, public JSON API (SODA) with no key required for modest
use, so this is a fully sanctioned, stable way to pull real, structured bids.

A Socrata source is configured via SourceConfig.config_json, e.g.:

    {
      "domain": "citydata.mesaaz.gov",
      "dataset_id": "dfcn-ivuc",
      "limit": 500,
      "order": ":id DESC",
      "where": "solicitation='True'",
      "status_field": "contract_status",
      "open_statuses": ["Published", "Active", "Initiated", "Under Review"],
      "agency": "City of Mesa, AZ",
      "app_token": null,
      "field_map": {
        "title": "contract_description",
        "solicitation_number": "contract_no",
        "contract_type": "type",
        "due_date": "due_date",
        "location": null,
        "description": "contract_description",
        "detail_url": null
      }
    }

Only `domain`, `dataset_id`, and `field_map.title` are required. Unknown or
missing columns are tolerated so a portal changing its schema degrades
gracefully rather than crashing the whole scrape.
"""

import json
import time
from datetime import datetime

import requests

from app.services.scrapers.base import ScraperResult
from app.services.scrapers.extraction_utils import normalize_space, parse_date

SOCRATA_USER_AGENT = "RFP-BidOS Public Scraper/0.2 (+socrata-open-data)"


class SocrataAdapter:
    def __init__(self, timeout: int = 25) -> None:
        self.timeout = timeout

    def can_handle(self, source_config) -> bool:
        return (getattr(source_config, "source_type", "") or "").lower() == "socrata"

    def scrape(self, source_config) -> list[ScraperResult]:
        config = _load_config(source_config)
        domain = config.get("domain")
        dataset_id = config.get("dataset_id")
        field_map = config.get("field_map") or {}
        if not domain or not dataset_id or not field_map.get("title"):
            raise ValueError(
                "Socrata source requires config_json with domain, dataset_id, and field_map.title"
            )

        rows = self._fetch_rows(domain, dataset_id, config)
        status_field = config.get("status_field")
        open_statuses = {s.lower() for s in config.get("open_statuses") or []}
        agency_fallback = (
            config.get("agency_fallback")
            or config.get("agency")
            or getattr(source_config, "name", None)
        )
        portal_url = f"https://{domain}/d/{dataset_id}"

        results: list[ScraperResult] = []
        for row in rows:
            if status_field and open_statuses:
                status_value = str(row.get(status_field, "")).strip().lower()
                if status_value and status_value not in open_statuses:
                    continue
            result = self._row_to_result(
                row, field_map, agency_fallback, portal_url, domain
            )
            if result is not None:
                results.append(result)
        return results

    def _fetch_rows(self, domain: str, dataset_id: str, config: dict) -> list[dict]:
        """Fetch all rows for a dataset, paginating with $limit/$offset.

        Pages are fetched of size ``page_size`` (config "limit", default 1000)
        and accumulated until a short page is returned or the hard ``max_rows``
        cap (config "max_rows", default 10000) is reached. Offset paging needs a
        deterministic order, so $order defaults to ":id" when unset. Each page
        request is retried with backoff, and a polite throttle is applied
        between pages.
        """
        url = f"https://{domain}/resource/{dataset_id}.json"
        page_size = int(config.get("limit") or 1000)
        max_rows = int(config.get("max_rows") or 10000)
        throttle = float(config.get("throttle_seconds") or 0.3)

        base_params = {}
        # Stable ordering is required for offset paging not to skip/repeat rows.
        # Append :id as a tiebreaker so a non-unique configured order (e.g.
        # "due_date DESC") can't reorder ties across $offset pages and drop/dup
        # rows. :id is the dataset's unique row identifier.
        base_params["$order"] = _order_with_id_tiebreaker(config.get("order"))
        if config.get("where"):
            base_params["$where"] = config["where"]
        headers = {"User-Agent": SOCRATA_USER_AGENT, "Accept": "application/json"}
        if config.get("app_token"):
            headers["X-App-Token"] = str(config["app_token"])

        rows: list[dict] = []
        offset = 0
        while True:
            params = dict(base_params)
            params["$limit"] = page_size
            params["$offset"] = offset
            page = self._fetch_page_with_retry(url, params, headers, config)
            rows.extend(page)

            if len(page) < page_size:
                break
            if len(rows) >= max_rows:
                # Stop cleanly at the cap rather than paging forever.
                rows = rows[:max_rows]
                break

            offset += page_size
            if throttle:
                time.sleep(throttle)

        return rows

    def _fetch_page_with_retry(
        self, url: str, params: dict, headers: dict, config: dict
    ) -> list[dict]:
        """Fetch a single page, retrying on transient network/5xx errors."""
        attempts = int(config.get("retry_attempts") or 3)
        backoff = float(config.get("retry_backoff") if config.get("retry_backoff") is not None else 0.5)
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return self._fetch_page(url, params, headers)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
            except requests.HTTPError as exc:
                # Only server errors (5xx) are transient and worth retrying.
                # Client errors (4xx) are permanent, so re-raise immediately.
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status is not None and status < 500:
                    raise
                last_exc = exc
            if attempt < attempts and backoff:
                time.sleep(attempt * backoff)
        if last_exc is not None:
            raise last_exc
        return []

    def _fetch_page(self, url: str, params: dict, headers: dict) -> list[dict]:
        """Perform one HTTP request and return its JSON list (or [])."""
        response = requests.get(url, params=params, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []

    def _row_to_result(
        self,
        row: dict,
        field_map: dict,
        agency_fallback: str | None,
        portal_url: str,
        domain: str,
    ) -> ScraperResult | None:
        title = normalize_space(str(_coerce_cell(row.get(field_map["title"])) or ""))
        if not title:
            return None

        def mapped(field: str):
            column = field_map.get(field)
            if not column:
                return None
            value = _coerce_cell(row.get(column))
            if value is None or value == "":
                return None
            return normalize_space(str(value))

        detail_url = mapped("detail_url")
        # Use only the per-row detail link as source_url. Falling back to the
        # shared portal_url would give every row from a detail-less dataset the
        # same source_url, collapsing them into one record in dedup.
        source_url = detail_url
        return ScraperResult(
            title=title,
            agency=mapped("agency") or agency_fallback,
            solicitation_number=mapped("solicitation_number"),
            source_url=source_url,
            detail_url=detail_url,
            portal_url=portal_url,
            location=mapped("location"),
            due_date=_parse_date(mapped("due_date")),
            service_type=mapped("service_type"),
            contract_type=mapped("contract_type"),
            description=mapped("description") or title,
            raw_text=title,
            confidence_score=0.6,
        )


def _order_with_id_tiebreaker(order: str | None) -> str:
    """Return an $order clause guaranteed to end with the unique :id tiebreaker."""
    order = (order or "").strip()
    if not order:
        return ":id"
    # Don't double-append if the configured order already ends with :id.
    last_term = order.split(",")[-1].strip().lower()
    if last_term == ":id" or last_term.startswith(":id "):
        return order
    return f"{order}, :id"


def _coerce_cell(value):
    """Flatten Socrata composite cell types to a scalar.

    URL columns return {"url": "..."}; location columns return
    {"human_address": "...", ...}. Everything else passes through.
    """
    if isinstance(value, dict):
        if value.get("url"):
            return value["url"]
        if value.get("human_address"):
            return _coerce_human_address(value["human_address"])
        return ""
    return value


def _coerce_human_address(value):
    if isinstance(value, dict):
        parts = [
            value.get("address"),
            value.get("city"),
            value.get("state"),
            value.get("zip"),
        ]
        return ", ".join(str(part) for part in parts if part)
    if not isinstance(value, str):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return value
    if not isinstance(parsed, dict):
        return value
    return _coerce_human_address(parsed)


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
    # Socrata floating timestamps look like 2026-05-28T00:00:00.000
    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except ValueError:
        pass
    return parse_date(value)

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
        url = f"https://{domain}/resource/{dataset_id}.json"
        params = {"$limit": int(config.get("limit") or 500)}
        if config.get("order"):
            params["$order"] = config["order"]
        if config.get("where"):
            params["$where"] = config["where"]
        headers = {"User-Agent": SOCRATA_USER_AGENT, "Accept": "application/json"}
        if config.get("app_token"):
            headers["X-App-Token"] = str(config["app_token"])
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
        source_url = detail_url or portal_url
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

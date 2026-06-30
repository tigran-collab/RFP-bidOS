"""Socrata source auto-discovery.

Socrata hosts a public catalog API (https://api.us.socrata.com/api/catalog/v1)
that indexes datasets across every Socrata domain. We can query it for
procurement-related terms, filter to government-looking domains, optionally
probe each candidate dataset for procurement-shaped columns, and propose a
best-guess field map. The output is meant to be seeded DISABLED so a human can
verify the field map before any scraping happens.

Everything is offline-friendly: network calls go through an injected
``http_get`` (defaults to ``requests.get``) so tests pass a fake. Nothing here
touches the network at import time. Parsing is defensive (``.get()`` everywhere)
because the catalog/probe response shapes vary by domain and version.
"""

import json

import requests

from sqlmodel import Session, select

from app.models import SourceConfig

DEFAULT_QUERIES = ("bids", "solicitations", "procurement", "contracts", "purchasing")

CATALOG_URL = "https://api.us.socrata.com/api/catalog/v1"

# Domains we treat as government-run. A domain qualifies if it ends in ".gov"
# OR contains one of these hints. Editable so new jurisdictions can be added.
GOV_DOMAIN_HINTS = (
    "mesaaz",
    "lacity",
    "texas",
    "nevada",
    "arizona",
    "ca.gov",
    "county",
    "cityof",
)

# Column-name substrings that suggest a dataset holds procurement records.
PROCUREMENT_COLUMN_HINTS = (
    "bid",
    "solicitation",
    "contract",
    "rfp",
    "rfq",
    "ifb",
    "due",
    "close",
    "status",
    "award",
    "procurement",
    "vendor",
)

# Dataset-name substrings that mark a dataset as NOT an open-bid list, even when
# its columns look procurement-shaped. These cover closed/historical award
# records (tabulations, results, archives) and charitable-solicitation registries
# that match "solicitation" but are unrelated to government procurement.
EXCLUDE_NAME_HINTS = (
    "tabulation",
    "awarded",
    "not awarded",
    "historical",
    "archive",
    "results",
    "opening",
    "charit",
    "campaign",
    "donor",
    "paid solicitor",
    "fundrais",
)


def _is_gov_domain(domain: str) -> bool:
    if not domain:
        return False
    lowered = domain.lower()
    if lowered.endswith(".gov"):
        return True
    return any(hint in lowered for hint in GOV_DOMAIN_HINTS)


def _columns_from_rows(rows) -> list[str]:
    """Collect the union of column names from a list of sample rows."""
    columns: list[str] = []
    seen: set[str] = set()
    if not isinstance(rows, list):
        return columns
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


def _name_is_excluded(name: str) -> bool:
    """True if the dataset name marks it as closed/historical/charity (not an open-bid list)."""
    lowered = (name or "").lower()
    return any(hint in lowered for hint in EXCLUDE_NAME_HINTS)


def _is_procurement(columns, name: str = "") -> bool:
    # A closed/historical/charity dataset is never an open-bid source, even if
    # its columns look procurement-shaped.
    if _name_is_excluded(name):
        return False
    for column in columns or []:
        lowered = str(column).lower()
        if any(hint in lowered for hint in PROCUREMENT_COLUMN_HINTS):
            return True
    return False


def suggest_field_map(columns) -> dict:
    """Heuristically map dataset columns to ScraperResult fields.

    Best-guess only: unknown targets are left out. ``title`` is always included
    when any plausible column exists, since a Socrata source requires it.
    """
    columns = [str(c) for c in (columns or []) if c]
    lowered = {column: column.lower() for column in columns}

    def first_matching(*needles) -> str | None:
        for column in columns:
            name = lowered[column]
            if any(needle in name for needle in needles):
                return column
        return None

    field_map: dict[str, str] = {}

    title = first_matching("description", "title", "name", "subject")
    if title:
        field_map["title"] = title

    solicitation = first_matching("solicitation", "bid_no", "no", "number", "id")
    if solicitation:
        field_map["solicitation_number"] = solicitation

    due = first_matching("due", "close", "deadline", "end_date")
    if due:
        field_map["due_date"] = due

    status = first_matching("status", "state")
    if status:
        field_map["status_field"] = status

    description = first_matching("description", "title")
    if description:
        field_map["description"] = description

    return field_map


def discover_socrata_sources(
    queries=None,
    limit_per_query: int = 20,
    probe: bool = True,
    http_get=requests.get,
) -> list[dict]:
    """Discover candidate procurement datasets from the Socrata catalog.

    Returns a list of candidate dicts. Each candidate is de-duped by
    (domain, dataset_id). Probing is best-effort per candidate: a failed probe
    records ``probe_error`` rather than aborting the whole run.
    """
    queries = list(queries) if queries else list(DEFAULT_QUERIES)
    candidates: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for term in queries:
        try:
            response = http_get(
                CATALOG_URL,
                params={"q": term, "limit": limit_per_query, "only": "dataset"},
                timeout=25,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            # A failing query term should not abort discovery of the others.
            continue

        results = payload.get("results") if isinstance(payload, dict) else None
        for item in results or []:
            if not isinstance(item, dict):
                continue
            resource = item.get("resource") or {}
            metadata = item.get("metadata") or {}
            dataset_id = resource.get("id")
            domain = metadata.get("domain")
            if not dataset_id or not domain:
                continue
            if not _is_gov_domain(domain):
                continue
            key = (domain, dataset_id)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "domain": domain,
                    "dataset_id": dataset_id,
                    "name": resource.get("name") or "",
                    "description": resource.get("description") or "",
                    "query": term,
                    "is_procurement": False,
                    "columns": [],
                    "suggested_field_map": {},
                    "probe_error": None,
                }
            )

    if probe:
        for candidate in candidates:
            try:
                probe_url = (
                    f"https://{candidate['domain']}/resource/"
                    f"{candidate['dataset_id']}.json"
                )
                response = http_get(
                    probe_url, params={"$limit": 5}, timeout=25
                )
                response.raise_for_status()
                rows = response.json()
                columns = _columns_from_rows(rows)
                candidate["columns"] = columns
                candidate["is_procurement"] = _is_procurement(
                    columns, candidate.get("name", "")
                )
                candidate["suggested_field_map"] = suggest_field_map(columns)
            except Exception as exc:  # noqa: BLE001 - record, don't abort
                candidate["probe_error"] = str(exc) or exc.__class__.__name__

    return candidates


def existing_socrata_keys(session: Session) -> set:
    """Return (domain, dataset_id) pairs already configured as socrata sources."""
    keys: set = set()
    sources = session.exec(
        select(SourceConfig).where(SourceConfig.source_type == "socrata")
    ).all()
    for source in sources:
        raw = source.config_json
        if not raw:
            continue
        try:
            config = raw if isinstance(raw, dict) else json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(config, dict):
            continue
        domain = config.get("domain")
        dataset_id = config.get("dataset_id")
        if domain and dataset_id:
            keys.add((domain, dataset_id))
    return keys


def seed_discovered_sources(session: Session, candidates: list[dict]) -> dict:
    """Idempotently insert procurement candidates as DISABLED socrata sources.

    Candidates are never enabled automatically: the auto-discovered field maps
    are best-guess and must be verified by a human before scraping.
    """
    existing = existing_socrata_keys(session)
    created = 0
    skipped = 0
    for candidate in candidates:
        if not candidate.get("is_procurement"):
            continue
        key = (candidate.get("domain"), candidate.get("dataset_id"))
        if not key[0] or not key[1]:
            continue
        if key in existing:
            skipped += 1
            continue
        name = candidate.get("name") or candidate["dataset_id"]
        session.add(
            SourceConfig(
                name=f"{name} (Auto-discovered)",
                source_type="socrata",
                enabled=False,
                config_json=json.dumps(
                    {
                        "domain": candidate["domain"],
                        "dataset_id": candidate["dataset_id"],
                        "field_map": candidate.get("suggested_field_map") or {},
                    }
                ),
                notes=(
                    "Auto-discovered via Socrata catalog; verify field_map and "
                    "enable before scraping"
                ),
            )
        )
        existing.add(key)
        created += 1
    session.commit()
    return {"created": created, "skipped": skipped}

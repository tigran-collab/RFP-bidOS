"""Tests for Socrata source auto-discovery.

Fully offline: a fake ``http_get`` returns canned catalog and probe responses,
so filtering, procurement detection, field-map suggestion, and seeding are all
verified without any network access.
"""

import json

from sqlmodel import select

from app.models import SourceConfig
from app.services.scrapers.socrata_discovery import (
    _is_procurement,
    discover_socrata_sources,
    infer_states,
    seed_discovered_sources,
    suggest_field_map,
)


def test_infer_states_maps_domains():
    assert infer_states("data.lacity.org") == ["CA"]
    assert infer_states("citydata.mesaaz.gov") == ["AZ"]
    assert infer_states("data.texas.gov") == ["TX"]
    assert infer_states("data.delaware.gov") == []  # out of target geography


def test_states_filter_keeps_only_requested_geography():
    catalog = {
        "results": [
            {
                "resource": {"id": "aaaa-1111", "name": "Open Bids", "description": ""},
                "metadata": {"domain": "citydata.mesaaz.gov"},
            },
            {
                "resource": {"id": "bbbb-2222", "name": "Open Bids", "description": ""},
                "metadata": {"domain": "data.delaware.gov"},
            },
        ]
    }

    def fake_get(url, params=None, timeout=None):
        return FakeResponse(catalog)

    candidates = discover_socrata_sources(
        queries=["bids"], probe=False, states=["AZ"], http_get=fake_get
    )
    domains = {c["domain"] for c in candidates}
    assert domains == {"citydata.mesaaz.gov"}  # Delaware filtered out


def test_award_tabulation_and_charity_names_excluded_despite_procurement_columns():
    procurement_cols = ["bid_number", "contract_description", "status", "due_date"]
    # Real open-bid dataset names pass.
    assert _is_procurement(procurement_cols, "Open Bid Opportunities") is True
    assert _is_procurement(procurement_cols, "Solicitations") is True
    # Closed/historical/award and charity datasets are rejected by name.
    assert _is_procurement(procurement_cols, "Bid Tabulations") is False
    assert _is_procurement(procurement_cols, "Not Awarded Bids") is False
    assert _is_procurement(procurement_cols, "Bid Openings and Results") is False
    assert _is_procurement(procurement_cols, "Bid Tabulations (Historical)") is False
    assert _is_procurement(procurement_cols, "Charitable Solicitation Campaigns") is False


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


# Catalog: one non-gov domain (filtered out), one gov procurement dataset,
# one gov non-procurement dataset.
CATALOG = {
    "results": [
        {
            "resource": {
                "id": "comm-erce",
                "name": "Online Store Sales",
                "description": "E-commerce sales data",
            },
            "metadata": {"domain": "data.acmeshop.com"},
        },
        {
            "resource": {
                "id": "proc-1111",
                "name": "Open Solicitations",
                "description": "City procurement bids",
            },
            "metadata": {"domain": "citydata.mesaaz.gov"},
        },
        {
            "resource": {
                "id": "park-2222",
                "name": "Park Locations",
                "description": "City park amenities",
            },
            "metadata": {"domain": "data.cityof-springfield.gov"},
        },
    ]
}

PROBE_ROWS = {
    "citydata.mesaaz.gov/proc-1111": [
        {
            "contract_description": "Unarmed Security Guard Services",
            "contract_no": "2026170",
            "contract_status": "Published",
            "due_date": "2026-07-15T00:00:00.000",
        }
    ],
    "data.cityof-springfield.gov/park-2222": [
        {"park_name": "Central Park", "acres": "12", "amenities": "playground"}
    ],
}


def make_http_get():
    def http_get(url, params=None, timeout=None):
        params = params or {}
        if url.endswith("/catalog/v1"):
            return FakeResponse(CATALOG)
        # Probe URLs look like https://{domain}/resource/{id}.json
        for key, rows in PROBE_ROWS.items():
            domain, dataset_id = key.split("/", 1)
            if f"https://{domain}/resource/{dataset_id}.json" == url:
                return FakeResponse(rows)
        return FakeResponse([])

    return http_get


def test_filters_non_gov_and_detects_procurement():
    candidates = discover_socrata_sources(
        queries=["bids"], limit_per_query=10, probe=True, http_get=make_http_get()
    )

    # Non-gov shop domain must be filtered out; two gov datasets remain.
    domains = {c["domain"] for c in candidates}
    assert "data.acmeshop.com" not in domains
    assert domains == {"citydata.mesaaz.gov", "data.cityof-springfield.gov"}

    by_id = {c["dataset_id"]: c for c in candidates}
    assert by_id["proc-1111"]["is_procurement"] is True
    assert by_id["park-2222"]["is_procurement"] is False


def test_procurement_candidate_has_suggested_field_map():
    candidates = discover_socrata_sources(
        queries=["bids"], probe=True, http_get=make_http_get()
    )
    proc = next(c for c in candidates if c["dataset_id"] == "proc-1111")

    field_map = proc["suggested_field_map"]
    assert field_map["title"] == "contract_description"
    assert field_map["due_date"] == "due_date"
    assert field_map["status_field"] == "contract_status"
    assert field_map["solicitation_number"] == "contract_no"


def test_suggest_field_map_minimal():
    field_map = suggest_field_map(["title", "close_date", "status"])
    assert field_map["title"] == "title"
    assert field_map["due_date"] == "close_date"
    assert field_map["status_field"] == "status"


def test_suggest_field_map_empty_columns():
    assert suggest_field_map([]) == {}


def test_probe_error_recorded_not_raised():
    def http_get(url, params=None, timeout=None):
        if url.endswith("/catalog/v1"):
            return FakeResponse(CATALOG)
        raise RuntimeError("network down")

    candidates = discover_socrata_sources(
        queries=["bids"], probe=True, http_get=http_get
    )
    # Discovery still returns candidates; each records the probe failure.
    assert candidates
    assert all(c["probe_error"] == "network down" for c in candidates)
    assert all(c["is_procurement"] is False for c in candidates)


def test_seeding_creates_disabled_source_and_is_idempotent(session):
    candidates = discover_socrata_sources(
        queries=["bids"], probe=True, http_get=make_http_get()
    )

    # Only the procurement dataset is seeded, disabled, with the verify note.
    result = seed_discovered_sources(session, candidates)
    assert result == {"created": 1, "skipped": 0}

    rows = list(
        session.exec(
            select(SourceConfig).where(SourceConfig.source_type == "socrata")
        ).all()
    )
    assert len(rows) == 1
    seeded = rows[0]
    assert seeded.enabled is False
    assert seeded.name == "Open Solicitations (Auto-discovered)"
    assert "verify field_map" in seeded.notes
    config = json.loads(seeded.config_json)
    assert config["domain"] == "citydata.mesaaz.gov"
    assert config["dataset_id"] == "proc-1111"
    assert config["field_map"]["title"] == "contract_description"

    # Re-seeding the same candidates is idempotent.
    result2 = seed_discovered_sources(session, candidates)
    assert result2 == {"created": 0, "skipped": 1}
    rows = list(
        session.exec(
            select(SourceConfig).where(SourceConfig.source_type == "socrata")
        ).all()
    )
    assert len(rows) == 1


# --- Fix 6: required title + status_field placement -------------------------
def test_candidate_without_title_is_not_seeded(session):
    # A procurement-shaped candidate whose field_map has no "title" key would
    # raise ValueError if enabled, so it must be skipped, not seeded.
    candidate = {
        "domain": "citydata.mesaaz.gov",
        "dataset_id": "no-title",
        "name": "Statusy Bids",
        "is_procurement": True,
        "suggested_field_map": {"status_field": "status", "due_date": "due_date"},
    }

    result = seed_discovered_sources(session, [candidate])

    assert result == {"created": 0, "skipped": 1}
    rows = list(
        session.exec(
            select(SourceConfig).where(SourceConfig.source_type == "socrata")
        ).all()
    )
    assert rows == []


def test_seeded_config_has_status_field_at_top_level_not_in_field_map(session):
    candidate = {
        "domain": "citydata.mesaaz.gov",
        "dataset_id": "proc-9999",
        "name": "Open Bids",
        "is_procurement": True,
        "suggested_field_map": {
            "title": "contract_description",
            "due_date": "due_date",
            "status_field": "contract_status",
        },
    }

    result = seed_discovered_sources(session, [candidate])
    assert result == {"created": 1, "skipped": 0}

    seeded = session.exec(
        select(SourceConfig).where(SourceConfig.source_type == "socrata")
    ).one()
    config = json.loads(seeded.config_json)

    # status_field lives at the config top level (where socrata.py reads it).
    assert config["status_field"] == "contract_status"
    # ...and is no longer inside field_map.
    assert "status_field" not in config["field_map"]
    # Other mappings remain in field_map.
    assert config["field_map"]["title"] == "contract_description"
    assert config["field_map"]["due_date"] == "due_date"

"""Tests for the Socrata open-data scraper adapter.

These run fully offline by stubbing the HTTP fetch, so they verify the
config parsing, status filtering, and field mapping without hitting the
network or depending on a live dataset.
"""

import json
from types import SimpleNamespace

import pytest
import requests

from app.services.scrapers.socrata import SocrataAdapter

CONFIG = {
    "domain": "citydata.mesaaz.gov",
    "dataset_id": "dfcn-ivuc",
    "status_field": "contract_status",
    "open_statuses": ["Published", "Active"],
    "agency": "City of Mesa, AZ",
    "field_map": {
        "title": "contract_description",
        "solicitation_number": "contract_no",
        "contract_type": "type",
        "description": "contract_description",
        "due_date": "due_date",
    },
}

SAMPLE_ROWS = [
    {
        "contract_no": "2026170",
        "contract_description": "Unarmed Security Guard Services",
        "type": "RFP",
        "contract_status": "Published",
        "due_date": "2026-07-15T00:00:00.000",
    },
    {
        "contract_no": "2026167",
        "contract_description": "Refrigerated Liquid Carbon Dioxide",
        "type": "RFB",
        "contract_status": "Closed",  # filtered out by open_statuses
    },
    {
        "contract_no": "2026164",
        "contract_description": "",  # no title -> dropped
        "type": "RFP",
        "contract_status": "Active",
    },
]


def make_source(config=CONFIG):
    return SimpleNamespace(
        source_type="socrata",
        name="Mesa AZ",
        config_json=json.dumps(config),
    )


def test_can_handle_only_socrata():
    adapter = SocrataAdapter()
    assert adapter.can_handle(make_source()) is True
    assert adapter.can_handle(SimpleNamespace(source_type="public_page")) is False


def test_scrape_maps_filters_and_parses(monkeypatch):
    adapter = SocrataAdapter()
    monkeypatch.setattr(adapter, "_fetch_rows", lambda *a, **k: SAMPLE_ROWS)

    results = adapter.scrape(make_source())

    # Closed row filtered, empty-title row dropped -> only the guard RFP remains.
    assert len(results) == 1
    bid = results[0]
    assert bid.title == "Unarmed Security Guard Services"
    assert bid.solicitation_number == "2026170"
    assert bid.contract_type == "RFP"
    assert bid.agency == "City of Mesa, AZ"
    assert bid.due_date is not None and bid.due_date.year == 2026 and bid.due_date.month == 7
    assert bid.portal_url == "https://citydata.mesaaz.gov/d/dfcn-ivuc"


def test_url_dict_cell_is_extracted(monkeypatch):
    # Socrata URL columns arrive as {"url": "..."}; the adapter must flatten them.
    adapter = SocrataAdapter()
    config = {
        "domain": "data.lacity.org",
        "dataset_id": "hf3r-utnq",
        "status_field": "stagename",
        "open_statuses": ["Open"],
        "agency": "City of Los Angeles (RAMP)",
        "field_map": {
            "title": "title",
            "solicitation_number": "rampid",
            "due_date": "closedate",
            "detail_url": "url",
        },
    }
    row = {
        "rampid": "230596",
        "title": "Armed & Unarmed Contract Security Services",
        "stagename": "Open",
        "closedate": "2026-07-29T21:00:00.000",
        "url": {"url": "https://www.rampla.org/s/opportunity-details?id=abc"},
    }
    monkeypatch.setattr(adapter, "_fetch_rows", lambda *a, **k: [row])
    results = adapter.scrape(make_source(config))
    assert len(results) == 1
    assert results[0].detail_url == "https://www.rampla.org/s/opportunity-details?id=abc"
    assert results[0].source_url == "https://www.rampla.org/s/opportunity-details?id=abc"


def test_row_agency_overrides_fallback(monkeypatch):
    adapter = SocrataAdapter()
    config = {
        "domain": "data.lacity.org",
        "dataset_id": "hf3r-utnq",
        "agency_fallback": "City of Los Angeles (RAMP)",
        "field_map": {
            "title": "title",
            "agency": "department",
        },
    }
    row = {
        "title": "Security Officer Services",
        "department": "Los Angeles World Airports",
    }
    monkeypatch.setattr(adapter, "_fetch_rows", lambda *a, **k: [row])

    results = adapter.scrape(make_source(config))

    assert len(results) == 1
    assert results[0].agency == "Los Angeles World Airports"


def test_location_human_address_json_is_flattened(monkeypatch):
    adapter = SocrataAdapter()
    config = {
        "domain": "example.data.gov",
        "dataset_id": "abcd-1234",
        "field_map": {
            "title": "title",
            "location": "location",
        },
    }
    row = {
        "title": "Mobile Patrol Services",
        "location": {
            "human_address": json.dumps(
                {
                    "address": "100 Main St",
                    "city": "Los Angeles",
                    "state": "CA",
                    "zip": "90012",
                }
            )
        },
    }
    monkeypatch.setattr(adapter, "_fetch_rows", lambda *a, **k: [row])

    results = adapter.scrape(make_source(config))

    assert len(results) == 1
    assert results[0].location == "100 Main St, Los Angeles, CA, 90012"


def test_no_detail_url_yields_none_source_url_and_no_collapse(monkeypatch):
    # Mesa-style config has no detail_url in its field_map. Each row must get
    # source_url=None (so the portal_url is not reused as a shared key) and the
    # two distinct solicitation numbers must produce two distinct results.
    adapter = SocrataAdapter()
    rows = [
        {
            "contract_no": "2026170",
            "contract_description": "Unarmed Security Guard Services",
            "type": "RFP",
            "contract_status": "Published",
        },
        {
            "contract_no": "2026171",
            "contract_description": "Armed Security Guard Services",
            "type": "RFP",
            "contract_status": "Published",
        },
    ]
    monkeypatch.setattr(adapter, "_fetch_rows", lambda *a, **k: rows)

    results = adapter.scrape(make_source())

    assert len(results) == 2
    assert {r.solicitation_number for r in results} == {"2026170", "2026171"}
    for result in results:
        assert result.source_url is None
        assert result.detail_url is None
        assert result.portal_url == "https://citydata.mesaaz.gov/d/dfcn-ivuc"


def test_row_to_result_source_url_none_without_detail_url():
    adapter = SocrataAdapter()
    field_map = {"title": "contract_description", "solicitation_number": "contract_no"}
    row = {"contract_description": "Security Guard Services", "contract_no": "X-1"}

    result = adapter._row_to_result(
        row, field_map, "City of Mesa, AZ", "https://citydata.mesaaz.gov/d/dfcn-ivuc", "citydata.mesaaz.gov"
    )

    assert result is not None
    assert result.source_url is None
    assert result.detail_url is None


def test_missing_required_config_raises(monkeypatch):
    adapter = SocrataAdapter()
    bad = SimpleNamespace(source_type="socrata", name="x", config_json=json.dumps({"domain": "d"}))
    monkeypatch.setattr(adapter, "_fetch_rows", lambda *a, **k: [])
    try:
        adapter.scrape(bad)
        assert False, "expected ValueError for missing dataset_id/title"
    except ValueError:
        pass


# --- Pagination / retry / cap (Part A): these stub _fetch_page, not _fetch_rows ---

FAST_CONFIG = {"throttle_seconds": 0, "retry_backoff": 0}


def test_fetch_rows_paginates_until_short_page(monkeypatch):
    # Two full pages of 2 rows, then a short page of 1 -> 5 rows total.
    adapter = SocrataAdapter()
    pages = [
        [{"id": 1}, {"id": 2}],
        [{"id": 3}, {"id": 4}],
        [{"id": 5}],
    ]
    offsets_seen = []

    def fake_page(url, params, headers):
        offsets_seen.append(params["$offset"])
        return pages.pop(0)

    monkeypatch.setattr(adapter, "_fetch_page", fake_page)
    config = {"limit": 2, **FAST_CONFIG}

    rows = adapter._fetch_rows("data.example.gov", "abcd-1234", config)

    assert [r["id"] for r in rows] == [1, 2, 3, 4, 5]
    # Offsets advance by page_size for each subsequent page.
    assert offsets_seen == [0, 2, 4]


def test_fetch_rows_retries_then_succeeds(monkeypatch):
    # First two attempts raise ConnectionError, third succeeds (single page).
    adapter = SocrataAdapter()
    calls = {"n": 0}

    def flaky_page(url, params, headers):
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.ConnectionError("boom")
        return [{"id": 1}]  # short page -> stop

    monkeypatch.setattr(adapter, "_fetch_page", flaky_page)
    config = {"limit": 5, **FAST_CONFIG}

    rows = adapter._fetch_rows("data.example.gov", "abcd-1234", config)

    assert calls["n"] == 3
    assert [r["id"] for r in rows] == [1]


def test_fetch_rows_raises_after_exhausting_retries(monkeypatch):
    adapter = SocrataAdapter()

    def always_timeout(url, params, headers):
        raise requests.Timeout("slow")

    monkeypatch.setattr(adapter, "_fetch_page", always_timeout)
    config = {"limit": 5, "retry_attempts": 3, **FAST_CONFIG}

    with pytest.raises(requests.Timeout):
        adapter._fetch_rows("data.example.gov", "abcd-1234", config)


def test_fetch_rows_stops_at_max_rows_cap(monkeypatch):
    # Every page is full, so without a cap this would page forever.
    adapter = SocrataAdapter()
    page_count = {"n": 0}

    def full_page(url, params, headers):
        page_count["n"] += 1
        return [{"id": params["$offset"] + i} for i in range(params["$limit"])]

    monkeypatch.setattr(adapter, "_fetch_page", full_page)
    config = {"limit": 2, "max_rows": 5, **FAST_CONFIG}

    rows = adapter._fetch_rows("data.example.gov", "abcd-1234", config)

    # Capped at exactly max_rows and stops (does not loop indefinitely).
    assert len(rows) == 5
    assert page_count["n"] == 3  # pages of 2 -> 2,4,6 accumulated then trimmed


def test_fetch_rows_defaults_order_to_id_for_stable_paging(monkeypatch):
    adapter = SocrataAdapter()
    captured = {}

    def capture_page(url, params, headers):
        captured.update(params)
        return []  # short page -> single fetch

    monkeypatch.setattr(adapter, "_fetch_page", capture_page)
    adapter._fetch_rows("data.example.gov", "abcd-1234", {"limit": 5, **FAST_CONFIG})

    assert captured["$order"] == ":id"


def test_fetch_rows_appends_id_tiebreaker_to_non_unique_order(monkeypatch):
    # A non-unique configured order must get :id appended as a tiebreaker so
    # offset paging cannot skip/dup rows across pages.
    adapter = SocrataAdapter()
    captured = {}

    def capture_page(url, params, headers):
        captured.update(params)
        return []

    monkeypatch.setattr(adapter, "_fetch_page", capture_page)
    adapter._fetch_rows(
        "data.example.gov",
        "abcd-1234",
        {"limit": 5, "order": "due_date DESC", **FAST_CONFIG},
    )

    assert captured["$order"] == "due_date DESC, :id"
    # :id is the last ordering term.
    assert captured["$order"].split(",")[-1].strip() == ":id"


def test_fetch_rows_does_not_double_append_id(monkeypatch):
    adapter = SocrataAdapter()
    captured = {}

    def capture_page(url, params, headers):
        captured.update(params)
        return []

    monkeypatch.setattr(adapter, "_fetch_page", capture_page)
    adapter._fetch_rows(
        "data.example.gov",
        "abcd-1234",
        {"limit": 5, "order": "due_date DESC, :id", **FAST_CONFIG},
    )

    assert captured["$order"] == "due_date DESC, :id"

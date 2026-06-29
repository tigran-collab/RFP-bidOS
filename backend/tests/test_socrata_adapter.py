"""Tests for the Socrata open-data scraper adapter.

These run fully offline by stubbing the HTTP fetch, so they verify the
config parsing, status filtering, and field mapping without hitting the
network or depending on a live dataset.
"""

import json
from types import SimpleNamespace

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


def test_missing_required_config_raises(monkeypatch):
    adapter = SocrataAdapter()
    bad = SimpleNamespace(source_type="socrata", name="x", config_json=json.dumps({"domain": "d"}))
    monkeypatch.setattr(adapter, "_fetch_rows", lambda *a, **k: [])
    try:
        adapter.scrape(bad)
        assert False, "expected ValueError for missing dataset_id/title"
    except ValueError:
        pass

"""Tests for the PlanetBids assisted-login adapter.

These run fully offline by monkeypatching browser_session.fetch_authenticated_json
to return canned papi JSON, so they verify field mapping and graceful
degradation without launching a browser or hitting the network.
"""

import json
from datetime import datetime
from types import SimpleNamespace

from app.services.scrapers import browser_session, planetbids
from app.services.scrapers.browser_session import (
    PlaywrightNotInstalledError,
    SessionExpiredError,
)
from app.services.scrapers.planetbids import PlanetBidsAuthAdapter

CONFIG = {
    "cid": 12345,
    "agency": "Example Transit Authority",
    "params": {"per_page": 100, "page": 1},
    "field_map": {
        "id": "id",
        "title": "title",
        "solicitation_number": "bidNumber",
        "due_date": "dueDate",
        "description": "description",
    },
}

SAMPLE_BIDS = {
    "data": [
        {
            "id": 987,
            "title": "Unarmed Security Guard Services",
            "bidNumber": "RFP-2026-014",
            "dueDate": "2026-08-15T17:00:00.000Z",
            "description": "Provide unarmed security officers at transit facilities.",
        },
        {
            "id": 988,
            "title": "",  # no title -> dropped
            "bidNumber": "RFP-2026-015",
        },
    ]
}


def make_source(config=CONFIG, source_id=42):
    return SimpleNamespace(
        id=source_id,
        source_type="planetbids",
        name="Example Transit PlanetBids",
        config_json=json.dumps(config),
    )


def _force_playwright(monkeypatch, available=True):
    monkeypatch.setattr(planetbids, "playwright_available", lambda: available)


def test_can_handle_only_planetbids():
    adapter = PlanetBidsAuthAdapter()
    assert adapter.can_handle(make_source()) is True
    assert adapter.can_handle(SimpleNamespace(source_type="socrata")) is False


def test_scrape_maps_papi_json(monkeypatch):
    _force_playwright(monkeypatch)
    captured = {}

    def fake_fetch(api_url, profile_dir, timeout_seconds=45):
        captured["api_url"] = api_url
        captured["profile_dir"] = profile_dir
        return SAMPLE_BIDS

    monkeypatch.setattr(planetbids, "fetch_authenticated_json", fake_fetch)

    adapter = PlanetBidsAuthAdapter()
    results = adapter.scrape(make_source())

    # Empty-title bid dropped -> one mapped result.
    assert len(results) == 1
    bid = results[0]
    assert bid.title == "Unarmed Security Guard Services"
    assert bid.solicitation_number == "RFP-2026-014"
    assert bid.agency == "Example Transit Authority"
    assert bid.due_date is not None and bid.due_date.year == 2026 and bid.due_date.month == 8
    assert bid.source_url == (
        "https://vendors.planetbids.com/portal/12345/bo/bo-detail/987"
    )
    assert bid.detail_url == bid.source_url
    # The built API URL targets the papi bids list for the configured cid.
    assert "cid=12345" in captured["api_url"]
    assert "/papi/bids" in captured["api_url"]


def test_scrape_accepts_bare_list_payload(monkeypatch):
    _force_playwright(monkeypatch)
    monkeypatch.setattr(
        planetbids,
        "fetch_authenticated_json",
        lambda *a, **k: [SAMPLE_BIDS["data"][0]],
    )
    adapter = PlanetBidsAuthAdapter()
    results = adapter.scrape(make_source())
    assert len(results) == 1
    assert results[0].title == "Unarmed Security Guard Services"


def test_session_expired_returns_empty_with_diagnostic(monkeypatch):
    _force_playwright(monkeypatch)

    def raise_expired(*a, **k):
        raise SessionExpiredError("redirected to login")

    monkeypatch.setattr(planetbids, "fetch_authenticated_json", raise_expired)
    adapter = PlanetBidsAuthAdapter()
    results = adapter.scrape(make_source())

    assert results == []
    assert any("session expired" in d.lower() for d in adapter.diagnostics)


def test_playwright_not_installed_returns_empty_with_diagnostic(monkeypatch):
    _force_playwright(monkeypatch, available=False)
    # Even if fetch were called it would raise; assert it is never reached.
    def should_not_run(*a, **k):
        raise AssertionError("fetch must not be called without Playwright")

    monkeypatch.setattr(planetbids, "fetch_authenticated_json", should_not_run)
    adapter = PlanetBidsAuthAdapter()
    results = adapter.scrape(make_source())

    assert results == []
    assert any("playwright is not installed" in d.lower() for d in adapter.diagnostics)


def test_playwright_installed_but_fetch_raises_not_installed(monkeypatch):
    # Guards the case where the probe passes but the launch path still reports
    # a partial/missing install at fetch time.
    _force_playwright(monkeypatch)

    def raise_not_installed(*a, **k):
        raise PlaywrightNotInstalledError("no chromium")

    monkeypatch.setattr(planetbids, "fetch_authenticated_json", raise_not_installed)
    adapter = PlanetBidsAuthAdapter()
    results = adapter.scrape(make_source())
    assert results == []
    assert any("playwright unavailable" in d.lower() for d in adapter.diagnostics)


def test_missing_cid_returns_empty(monkeypatch):
    _force_playwright(monkeypatch)
    adapter = PlanetBidsAuthAdapter()
    results = adapter.scrape(make_source(config={"field_map": {"title": "title"}}))
    assert results == []
    assert any("cid" in d.lower() for d in adapter.diagnostics)


def test_parse_date_numeric_offset_converted_to_naive_utc():
    parsed = planetbids._parse_date("2026-08-15T17:00:00+02:00")
    assert parsed == datetime(2026, 8, 15, 15, 0, 0)
    assert parsed.tzinfo is None


def test_parse_date_z_suffix_is_naive():
    parsed = planetbids._parse_date("2026-08-15T17:00:00.000Z")
    assert parsed == datetime(2026, 8, 15, 17, 0, 0)
    assert parsed.tzinfo is None


def test_bids_url_query_is_url_encoded(monkeypatch):
    _force_playwright(monkeypatch)
    captured = {}

    def fake_fetch(api_url, profile_dir, timeout_seconds=45):
        captured["api_url"] = api_url
        return []

    monkeypatch.setattr(planetbids, "fetch_authenticated_json", fake_fetch)
    config = {**CONFIG, "params": {"per_page": 100, "search": "security guard & patrol"}}

    PlanetBidsAuthAdapter().scrape(make_source(config=config))

    assert "search=security+guard+%26+patrol" in captured["api_url"]
    assert "cid=12345" in captured["api_url"]


def test_check_auth_ready_reports_missing_pieces(monkeypatch, tmp_path):
    # No keyring creds, no profile -> not ready, with actionable missing fields.
    monkeypatch.setattr(planetbids, "playwright_available", lambda: True)
    source = SimpleNamespace(
        id=99,
        source_type="planetbids",
        name="PB",
        base_url="https://vendors.planetbids.com/portal/99",
        requires_credentials=True,
        credential_type="Keyring",
        credential_username=None,
        credential_secret_ref=None,
        credential_notes=None,
        auth_last_checked_at=None,
        config_json=None,
    )
    adapter = PlanetBidsAuthAdapter()
    status = adapter.check_auth_ready(source)
    assert status["ready"] is False
    assert any("browser session" in m for m in status["missing_fields"])

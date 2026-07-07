"""Tests for the generic config-driven authenticated browser adapter.

These run fully offline by monkeypatching
browser_session.fetch_authenticated_html (imported into the adapter module) to
return canned HTML, so they verify row/field_map extraction, the table-parser
fallback, and graceful degradation without launching a browser or hitting the
network.
"""

import json
from types import SimpleNamespace

from app.services.scrapers import authenticated_browser
from app.services.scrapers.authenticated_browser import AuthenticatedBrowserAdapter
from app.services.scrapers.browser_session import (
    PlaywrightNotInstalledError,
    SessionExpiredError,
)

ROW_HTML = """
<html><body>
<table class="bids"><tbody>
  <tr class="bid">
    <td class="title"><a href="/bids/RFP-2026-014">Unarmed Security Guard Services</a></td>
    <td class="number">RFP-2026-014</td>
    <td class="due">08/15/2026</td>
    <td class="agency">Example Transit Authority</td>
  </tr>
  <tr class="bid">
    <td class="title"></td>
    <td class="number">RFP-2026-015</td>
    <td class="due">09/01/2026</td>
    <td class="agency">Example Transit Authority</td>
  </tr>
</tbody></table>
</body></html>
"""

TABLE_HTML = """
<html><body>
<table>
  <tr><th>Bid Title</th><th>Bid Number</th><th>Due Date</th></tr>
  <tr>
    <td><a href="/detail/1">Armed Security Patrol RFP</a></td>
    <td>IFB-2026-100</td>
    <td>07/30/2026</td>
  </tr>
</table>
</body></html>
"""

ROW_CONFIG = {
    "list_url": "https://portal.example.com/bids",
    "wait_selector": "table.bids",
    "agency": "Example Transit Authority",
    "row_selector": "table.bids tbody tr.bid",
    "field_map": {
        "title": "td.title a",
        "solicitation_number": "td.number",
        "due_date": "td.due",
        "agency": "td.agency",
        "source_url": "td.title a",
    },
}

TABLE_CONFIG = {"list_url": "https://portal.example.com/bids", "agency": "Fallback Agency"}

DETAIL_HTML = """
<html><body>
<h1>Armed Security Patrol RFP</h1>
<div>Organization: City of Carson</div>
<div>Location: Carson, CA</div>
<div>Pre-bid conference: 07/15/2026 10:00 AM</div>
<div>Estimated value: $250,000</div>
<p>The City seeks armed security guard services on a fixed price basis.</p>
</body></html>
"""


def make_source(config, source_id=42):
    return SimpleNamespace(
        id=source_id,
        source_type="authenticated_browser",
        name="Example Portal",
        config_json=json.dumps(config),
    )


def _force_playwright(monkeypatch, available=True):
    monkeypatch.setattr(
        authenticated_browser, "playwright_available", lambda: available
    )


def test_can_handle_only_authenticated_browser():
    adapter = AuthenticatedBrowserAdapter()
    assert adapter.can_handle(make_source(ROW_CONFIG)) is True
    assert adapter.can_handle(SimpleNamespace(source_type="planetbids")) is False


def test_row_field_map_extraction(monkeypatch):
    _force_playwright(monkeypatch)
    fetched = []

    def fake_fetch(page_url, profile_dir, wait_selector=None, timeout_seconds=45, headless=True, **kwargs):
        fetched.append({"page_url": page_url, "wait_selector": wait_selector})
        return ROW_HTML

    monkeypatch.setattr(authenticated_browser, "fetch_authenticated_html", fake_fetch)

    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(ROW_CONFIG))

    # The empty-title row is dropped -> one mapped result.
    assert len(results) == 1
    bid = results[0]
    assert bid.title == "Unarmed Security Guard Services"
    assert bid.solicitation_number == "RFP-2026-014"
    assert bid.agency == "Example Transit Authority"
    assert bid.due_date is not None and bid.due_date.year == 2026 and bid.due_date.month == 8
    # Row link resolved against list_url.
    assert bid.source_url == "https://portal.example.com/bids/RFP-2026-014"
    assert bid.detail_url == bid.source_url
    assert bid.extraction_method == "authenticated_browser_row+detail"
    assert fetched[0]["wait_selector"] == "table.bids"
    assert fetched[0]["page_url"] == "https://portal.example.com/bids"
    # The candidate's detail page was visited for enrichment.
    assert fetched[1]["page_url"] == bid.detail_url


def test_table_parser_fallback(monkeypatch):
    _force_playwright(monkeypatch)
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html",
        lambda *a, **k: TABLE_HTML,
    )
    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(TABLE_CONFIG))

    assert len(results) == 1
    bid = results[0]
    assert bid.title == "Armed Security Patrol RFP"
    assert bid.solicitation_number == "IFB-2026-100"
    # agency was not in the table, so the fallback applies the config agency.
    assert bid.agency == "Fallback Agency"
    assert bid.extraction_method == "authenticated_browser_table+detail"
    assert any("table-parser fallback" in d for d in adapter.diagnostics)


def test_detail_enrichment_fills_breakdown_fields(monkeypatch):
    _force_playwright(monkeypatch)

    def fake_fetch(page_url, profile_dir, wait_selector=None, timeout_seconds=45, headless=True, **kwargs):
        return TABLE_HTML if page_url == TABLE_CONFIG["list_url"] else DETAIL_HTML

    monkeypatch.setattr(authenticated_browser, "fetch_authenticated_html", fake_fetch)
    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(TABLE_CONFIG))

    assert len(results) == 1
    bid = results[0]
    # The portal-name fallback is replaced by the ISSUING agency on the page.
    assert bid.agency == "City of Carson"
    assert bid.location == "Carson, CA"
    assert bid.pre_bid_date is not None and bid.pre_bid_date.month == 7
    assert bid.estimated_value == 250000.0
    assert bid.service_type == "Security services"
    assert bid.contract_type == "Fixed price"
    assert bid.description and bid.description != bid.title
    # List-page values are kept, not overwritten by the detail page.
    assert bid.solicitation_number == "IFB-2026-100"
    assert bid.due_date is not None and bid.due_date.month == 7 and bid.due_date.day == 30
    assert any("enriched 1 candidate" in d for d in adapter.diagnostics)


def test_detail_enrichment_stops_on_session_expiry(monkeypatch):
    _force_playwright(monkeypatch)
    calls = []

    def fake_fetch(page_url, profile_dir, **kwargs):
        calls.append(page_url)
        if page_url == TABLE_CONFIG["list_url"]:
            return TABLE_HTML
        raise SessionExpiredError("expired mid-enrichment")

    monkeypatch.setattr(authenticated_browser, "fetch_authenticated_html", fake_fetch)
    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(TABLE_CONFIG))

    # Candidates are still returned; enrichment stops with a diagnostic.
    assert len(results) == 1
    assert results[0].agency == "Fallback Agency"
    assert any("session expired" in d.lower() for d in adapter.diagnostics)


def test_missing_list_url_returns_empty(monkeypatch):
    _force_playwright(monkeypatch)
    # fetch must never be called when list_url is missing.
    def should_not_run(*a, **k):
        raise AssertionError("fetch must not run without list_url")

    monkeypatch.setattr(authenticated_browser, "fetch_authenticated_html", should_not_run)
    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source({"row_selector": "tr"}))
    assert results == []
    assert any("list_url" in d for d in adapter.diagnostics)


def test_session_expired_returns_empty_with_diagnostic(monkeypatch):
    _force_playwright(monkeypatch)

    def raise_expired(*a, **k):
        raise SessionExpiredError("redirected to login")

    monkeypatch.setattr(authenticated_browser, "fetch_authenticated_html", raise_expired)
    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(ROW_CONFIG))

    assert results == []
    assert any("session expired" in d.lower() for d in adapter.diagnostics)


def test_playwright_not_installed_returns_empty_with_diagnostic(monkeypatch):
    _force_playwright(monkeypatch, available=False)

    def should_not_run(*a, **k):
        raise AssertionError("fetch must not be called without Playwright")

    monkeypatch.setattr(authenticated_browser, "fetch_authenticated_html", should_not_run)
    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(ROW_CONFIG))

    assert results == []
    assert any("playwright is not installed" in d.lower() for d in adapter.diagnostics)


def test_playwright_installed_but_fetch_raises_not_installed(monkeypatch):
    _force_playwright(monkeypatch)

    def raise_not_installed(*a, **k):
        raise PlaywrightNotInstalledError("no chromium")

    monkeypatch.setattr(
        authenticated_browser, "fetch_authenticated_html", raise_not_installed
    )
    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(ROW_CONFIG))
    assert results == []
    assert any("playwright unavailable" in d.lower() for d in adapter.diagnostics)


def test_scraper_dispatches_and_does_not_skip(monkeypatch):
    # The scraper's _select_adapter must route authenticated_browser to the new
    # adapter, and _auth_skip_message must NOT skip it despite requiring creds.
    from app.services import scraper

    source = SimpleNamespace(
        id=7,
        source_type="authenticated_browser",
        name="Portal",
        base_url="https://portal.example.com/",
        requires_credentials=True,
        login_url="https://portal.example.com/",
    )
    adapter = scraper._select_adapter(source, None)
    assert isinstance(adapter, AuthenticatedBrowserAdapter)
    assert scraper._auth_skip_message(source) is None


def test_check_auth_ready_reports_missing_pieces(monkeypatch):
    monkeypatch.setattr(authenticated_browser, "playwright_available", lambda: True)
    source = SimpleNamespace(
        id=99,
        source_type="authenticated_browser",
        name="Portal",
        base_url="https://portal.example.com/",
        requires_credentials=True,
        credential_type="Keyring",
        credential_username=None,
        credential_secret_ref=None,
        credential_notes=None,
        auth_last_checked_at=None,
        config_json=None,
    )
    adapter = AuthenticatedBrowserAdapter()
    status = adapter.check_auth_ready(source)
    assert status["ready"] is False
    assert any("browser session" in m for m in status["missing_fields"])

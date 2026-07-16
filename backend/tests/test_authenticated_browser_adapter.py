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


def make_source(config, source_id=42, **overrides):
    fields = dict(
        id=source_id,
        source_type="authenticated_browser",
        name="Example Portal",
        portal_type=None,
        base_url=None,
        login_url=None,
        config_json=json.dumps(config),
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _force_playwright(monkeypatch, available=True):
    monkeypatch.setattr(
        authenticated_browser, "playwright_available", lambda: available
    )


def test_can_handle_only_authenticated_browser():
    adapter = AuthenticatedBrowserAdapter()
    assert adapter.can_handle(make_source(ROW_CONFIG)) is True
    assert adapter.can_handle(SimpleNamespace(source_type="planetbids")) is False


def _batch_returning(html_by_url):
    """Build a fetch_authenticated_html_batch stub from a url->html callable/map."""

    def fake_batch(
        urls, profile_dir, wait_selector=None, timeout_seconds=45, headless=True, throttle_seconds=0.0
    ):
        resolve = html_by_url if callable(html_by_url) else (lambda u: html_by_url)
        return [
            {"url": url, "html": resolve(url), "error": None, "session_expired": False}
            for url in urls
        ]

    return fake_batch


def test_row_field_map_extraction(monkeypatch):
    _force_playwright(monkeypatch)
    fetched = []

    def fake_fetch(page_url, profile_dir, wait_selector=None, timeout_seconds=45, headless=True, **kwargs):
        fetched.append({"page_url": page_url, "wait_selector": wait_selector})
        return ROW_HTML

    batched = {}

    def fake_batch(urls, profile_dir, wait_selector=None, timeout_seconds=45, headless=True, throttle_seconds=0.0):
        batched["urls"] = list(urls)
        batched["throttle_seconds"] = throttle_seconds
        return [
            {"url": url, "html": ROW_HTML, "error": None, "session_expired": False}
            for url in urls
        ]

    monkeypatch.setattr(authenticated_browser, "fetch_authenticated_html", fake_fetch)
    monkeypatch.setattr(authenticated_browser, "fetch_authenticated_html_batch", fake_batch)

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
    # The list page was fetched once (singly); detail pages went through the
    # single-context batch, which received exactly the candidate's detail URL.
    assert len(fetched) == 1
    assert batched["urls"] == [bid.detail_url]


def test_table_parser_fallback(monkeypatch):
    _force_playwright(monkeypatch)
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html",
        lambda *a, **k: TABLE_HTML,
    )
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html_batch",
        _batch_returning(TABLE_HTML),
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

    monkeypatch.setattr(
        authenticated_browser, "fetch_authenticated_html", lambda *a, **k: TABLE_HTML
    )
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html_batch",
        _batch_returning(DETAIL_HTML),
    )
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


def test_search_keywords_fetch_each_term(monkeypatch):
    _force_playwright(monkeypatch)
    calls = []

    def fake_fetch(
        page_url,
        profile_dir,
        wait_selector=None,
        timeout_seconds=45,
        headless=True,
        search_keyword=None,
        search_input_selector=None,
        search_submit_selector=None,
    ):
        calls.append(
            {
                "search_keyword": search_keyword,
                "search_input_selector": search_input_selector,
                "search_submit_selector": search_submit_selector,
            }
        )
        slug = (search_keyword or "none").lower()
        return ROW_HTML.replace(
            "/bids/RFP-2026-014", f"/bids/{slug}"
        ).replace(
            "Unarmed Security Guard Services",
            f"{search_keyword} Security Guard Services",
        )

    monkeypatch.setattr(authenticated_browser, "fetch_authenticated_html", fake_fetch)
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html_batch",
        _batch_returning(DETAIL_HTML),
    )

    config = dict(ROW_CONFIG)
    config["search_keywords"] = ["California", "Texas"]
    config["search_input_selector"] = "#solicitationSingleBoxSearch"
    config["search_submit_selector"] = "#topSearchButton"

    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(config))

    assert [call["search_keyword"] for call in calls] == ["California", "Texas"]
    assert {result.title for result in results} == {
        "California Security Guard Services",
        "Texas Security Guard Services",
    }
    assert all(
        call["search_input_selector"] == "#solicitationSingleBoxSearch"
        for call in calls
    )
    assert all(call["search_submit_selector"] == "#topSearchButton" for call in calls)


def test_state_filter_keeps_only_allowed_states_after_detail_enrichment(monkeypatch):
    _force_playwright(monkeypatch)
    html = """
    <html><body>
    <table class="bids"><tbody>
      <tr class="bid">
        <td class="title"><a href="/bids/ca">Security Guard Services</a></td>
        <td class="number">RFP-CA</td>
        <td class="due">08/15/2026</td>
        <td class="agency">BidNet Direct</td>
      </tr>
      <tr class="bid">
        <td class="title"><a href="/bids/nv">Security Guard Services</a></td>
        <td class="number">RFP-NV</td>
        <td class="due">08/16/2026</td>
        <td class="agency">BidNet Direct</td>
      </tr>
    </tbody></table>
    </body></html>
    """

    def detail_for(url):
        if url.endswith("/ca"):
            return """
            <html><body>
            <div>Organization: City of San Diego</div>
            <div>Location: San Diego, CA</div>
            <div>Pre-bid conference: 07/20/2026 10:00 AM</div>
            <p>Security guard services for city facilities.</p>
            </body></html>
            """
        return """
        <html><body>
        <div>Organization: City of Las Vegas</div>
        <div>Location: Las Vegas, NV</div>
        <div>Pre-bid conference: 07/21/2026 10:00 AM</div>
        <p>Security guard services for city facilities.</p>
        </body></html>
        """

    monkeypatch.setattr(
        authenticated_browser, "fetch_authenticated_html", lambda *a, **k: html
    )
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html_batch",
        _batch_returning(detail_for),
    )

    config = dict(ROW_CONFIG)
    config["agency"] = "BidNet Direct"
    config["state_filter"] = ["CA", "TX"]

    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(config))

    assert len(results) == 1
    assert results[0].solicitation_number == "RFP-CA"
    assert results[0].location == "San Diego, CA"
    assert any("state filter removed 1 candidate" in d for d in adapter.diagnostics)


def test_detail_enrichment_uses_single_batch_call(monkeypatch):
    # Two candidates -> the detail pages are fetched with ONE batch call (one
    # reused browser context), and the configured throttle is passed through.
    _force_playwright(monkeypatch)
    monkeypatch.setattr(
        authenticated_browser, "fetch_authenticated_html", lambda *a, **k: ROW_HTML
    )
    calls = []

    def fake_batch(urls, profile_dir, wait_selector=None, timeout_seconds=45, headless=True, throttle_seconds=0.0):
        calls.append({"urls": list(urls), "throttle_seconds": throttle_seconds})
        return [
            {"url": url, "html": DETAIL_HTML, "error": None, "session_expired": False}
            for url in urls
        ]

    monkeypatch.setattr(authenticated_browser, "fetch_authenticated_html_batch", fake_batch)

    config = dict(ROW_CONFIG)
    config["row_selector"] = "table.bids tbody tr.bid"
    config["detail_throttle_seconds"] = 1.5
    # Give both rows a distinct title so neither is dropped.
    html_two_rows = ROW_HTML.replace('<td class="title"></td>', '<td class="title"><a href="/bids/RFP-2026-015">Armed Guard Services</a></td>')
    monkeypatch.setattr(
        authenticated_browser, "fetch_authenticated_html", lambda *a, **k: html_two_rows
    )
    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(config))

    assert len(results) == 2
    assert len(calls) == 1
    assert len(calls[0]["urls"]) == 2
    assert calls[0]["throttle_seconds"] == 1.5


def test_detail_enrichment_stops_on_session_expiry(monkeypatch):
    _force_playwright(monkeypatch)

    monkeypatch.setattr(
        authenticated_browser, "fetch_authenticated_html", lambda *a, **k: TABLE_HTML
    )

    def fake_batch(urls, *a, **k):
        return [
            {
                "url": urls[0],
                "html": "",
                "error": SessionExpiredError("expired mid-enrichment"),
                "session_expired": True,
            }
        ]

    monkeypatch.setattr(authenticated_browser, "fetch_authenticated_html_batch", fake_batch)
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


STATE_FILTER_LIST_HTML = """
<html><body>
<table class="bids"><tbody>
  <tr class="bid">
    <td class="title"><a href="/bids/first">Security Guard Services</a></td>
    <td class="number">RFP-CA</td>
    <td class="due">08/15/2026</td>
    <td class="agency">BidNet Direct</td>
  </tr>
  <tr class="bid">
    <td class="title"><a href="/bids/second">Security Guard Services</a></td>
    <td class="number">RFP-NV</td>
    <td class="due">08/16/2026</td>
    <td class="agency">BidNet Direct</td>
  </tr>
</tbody></table>
</body></html>
"""


def _state_filter_detail(url):
    if url.endswith("/first"):
        return """
        <html><body>
        <div>Organization: City of San Diego</div>
        <div>Location: San Diego, CA</div>
        <p>Security guard services for city facilities.</p>
        </body></html>
        """
    return """
    <html><body>
    <div>Organization: City of Las Vegas</div>
    <div>Location: Las Vegas, NV</div>
    <p>Security guard services for city facilities.</p>
    </body></html>
    """


def test_state_filter_ignores_state_token_in_list_url(monkeypatch):
    # The list page URL is shared by every candidate; a state token inside it
    # (BidNet regional groups look like /california/lapg) must not make the
    # filter pass everything.
    _force_playwright(monkeypatch)
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html",
        lambda *a, **k: STATE_FILTER_LIST_HTML,
    )
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html_batch",
        _batch_returning(_state_filter_detail),
    )

    config = dict(ROW_CONFIG)
    config["list_url"] = "https://portal.example.com/california/lapg"
    config["agency"] = "BidNet Direct"
    config["state_filter"] = ["CA"]

    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(config))

    assert [r.solicitation_number for r in results] == ["RFP-CA"]
    assert any("state filter removed 1 candidate" in d for d in adapter.diagnostics)


def test_state_filter_clamps_configured_states_to_operating_region(monkeypatch):
    # The CA/TX ceiling is a HARD rule: a stale/out-of-region value in
    # state_filter (e.g. "NV") can never re-open that state. The parser still
    # accepts 2-letter codes; the clamp happens in _resolve_allowed_states.
    from app.services.scrapers.authenticated_browser import _state_filter

    assert _state_filter({"state_filter": ["NV", "Federal District"]}) == (
        {"NV"},
        ["Federal District"],
    )

    _force_playwright(monkeypatch)
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html",
        lambda *a, **k: STATE_FILTER_LIST_HTML,
    )
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html_batch",
        _batch_returning(_state_filter_detail),
    )

    config = dict(ROW_CONFIG)
    config["agency"] = "BidNet Direct"
    config["state_filter"] = ["NV", "Federal District"]

    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(config))

    # NV is clamped out; the effective filter falls back to the region, so the
    # CA row is kept and the NV row is dropped.
    assert [r.solicitation_number for r in results] == ["RFP-CA"]
    assert any("Federal District" in d for d in adapter.diagnostics)
    assert any("outside the operating region" in d for d in adapter.diagnostics)


def test_state_filter_drops_out_of_region_code_but_keeps_in_region(monkeypatch):
    # A mixed filter like ["CA","NV"] keeps CA and drops NV (clamped to region).
    _force_playwright(monkeypatch)
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html",
        lambda *a, **k: STATE_FILTER_LIST_HTML,
    )
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html_batch",
        _batch_returning(_state_filter_detail),
    )

    config = dict(ROW_CONFIG)
    config["agency"] = "BidNet Direct"
    config["state_filter"] = ["CA", "NV"]

    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(config))

    assert [r.solicitation_number for r in results] == ["RFP-CA"]
    assert any("outside the operating region" in d for d in adapter.diagnostics)


def test_aggregator_detected_via_config_list_url(monkeypatch):
    # An aggregator whose bidnet URL lives ONLY in config_json.list_url (generic
    # name/portal_type, null base_url/login_url) must still default to CA/TX.
    _force_playwright(monkeypatch)
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html",
        lambda *a, **k: STATE_FILTER_LIST_HTML,
    )
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html_batch",
        _batch_returning(_state_filter_detail),
    )

    config = dict(ROW_CONFIG)
    config["list_url"] = "https://www.bidnetdirect.com/private/supplier/bids"
    config["agency"] = "Regional Purchasing Group"
    config.pop("state_filter", None)

    source = make_source(
        config, name="Regional Purchasing Group", portal_type="Other",
        base_url=None, login_url=None,
    )
    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(source)

    assert [r.solicitation_number for r in results] == ["RFP-CA"]
    assert any("defaulting to CA/TX" in d for d in adapter.diagnostics)


def test_state_filter_drops_unverified_candidates_and_names_them(monkeypatch):
    # The filter's contract is "only these states": a candidate whose detail
    # page could not be fetched (here: a per-page fetch error) is unverifiable,
    # so it is dropped and the diagnostics NAME it so the drop is never silent.
    _force_playwright(monkeypatch)
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html",
        lambda *a, **k: STATE_FILTER_LIST_HTML,
    )

    def fake_batch(urls, profile_dir, wait_selector=None, timeout_seconds=45,
                   headless=True, throttle_seconds=0.0):
        out = []
        for url in urls:
            if url.endswith("/first"):
                out.append({
                    "url": url,
                    "html": "<html><body><div>Location: San Diego, CA</div></body></html>",
                    "error": None,
                    "session_expired": False,
                })
            else:
                # The NV candidate's detail page fails to fetch -> unverifiable.
                out.append({"url": url, "html": "", "error": "fetch error", "session_expired": False})
        return out

    monkeypatch.setattr(authenticated_browser, "fetch_authenticated_html_batch", fake_batch)

    config = dict(ROW_CONFIG)
    config["agency"] = "BidNet Direct"
    config["state_filter"] = ["CA"]

    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(config))

    assert [r.solicitation_number for r in results] == ["RFP-CA"]
    assert any(
        "could not be checked" in d and "Security Guard Services" in d
        for d in adapter.diagnostics
    )


def test_state_filter_enriches_all_candidates_despite_detail_limit(monkeypatch):
    # Regression: a detail_limit must NOT cap enrichment while a state filter is
    # active, or in-region bids whose list row carries no state token would be
    # dropped as unverified. Both rows must be enriched; the CA row survives.
    _force_playwright(monkeypatch)
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html",
        lambda *a, **k: STATE_FILTER_LIST_HTML,
    )
    batch_urls = []

    def fake_batch(urls, profile_dir, wait_selector=None, timeout_seconds=45,
                   headless=True, throttle_seconds=0.0):
        batch_urls.extend(urls)
        return [
            {
                "url": url,
                "html": (
                    "<html><body><div>Location: San Diego, CA</div></body></html>"
                    if url.endswith("/first")
                    else "<html><body><div>Location: Las Vegas, NV</div></body></html>"
                ),
                "error": None,
                "session_expired": False,
            }
            for url in urls
        ]

    monkeypatch.setattr(authenticated_browser, "fetch_authenticated_html_batch", fake_batch)

    config = dict(ROW_CONFIG)
    config["agency"] = "BidNet Direct"
    config["state_filter"] = ["CA"]
    config["detail_limit"] = 1  # must be ignored while the state filter is active

    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(config))

    assert len(batch_urls) == 2  # BOTH enriched despite detail_limit=1
    assert [r.solicitation_number for r in results] == ["RFP-CA"]


def test_state_filter_enriches_every_candidate_by_default(monkeypatch):
    # With a state filter configured and no explicit detail_limit, the default
    # 10-page enrichment cap must not apply — every candidate needs its detail
    # page checked or it would be dropped as unverifiable.
    _force_playwright(monkeypatch)
    many_rows = "".join(
        f"""
        <tr class="bid">
          <td class="title"><a href="/bids/item-{index}">Security Guard Services {index}</a></td>
          <td class="number">RFP-{index}</td>
          <td class="due">08/15/2026</td>
          <td class="agency">BidNet Direct</td>
        </tr>
        """
        for index in range(12)
    )
    html = f'<html><body><table class="bids"><tbody>{many_rows}</tbody></table></body></html>'
    batch_urls = []

    def fake_batch(urls, profile_dir, wait_selector=None, timeout_seconds=45,
                   headless=True, throttle_seconds=0.0):
        batch_urls.extend(urls)
        return [
            {
                "url": url,
                "html": "<html><body><div>Location: San Diego, CA</div></body></html>",
                "error": None,
                "session_expired": False,
            }
            for url in urls
        ]

    monkeypatch.setattr(
        authenticated_browser, "fetch_authenticated_html", lambda *a, **k: html
    )
    monkeypatch.setattr(
        authenticated_browser, "fetch_authenticated_html_batch", fake_batch
    )

    config = dict(ROW_CONFIG)
    config["agency"] = "BidNet Direct"
    config["state_filter"] = ["CA"]

    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(make_source(config))

    assert len(batch_urls) == 12
    assert len(results) == 12


def test_bidnet_defaults_to_ca_tx_when_no_state_filter_configured(monkeypatch):
    # The user's core requirement: a BidNet source that forgot to configure a
    # state_filter must STILL drop out-of-state bids. A multi-state aggregator
    # defaults to the CA/TX operating region.
    _force_playwright(monkeypatch)
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html",
        lambda *a, **k: STATE_FILTER_LIST_HTML,
    )
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html_batch",
        _batch_returning(_state_filter_detail),
    )

    config = dict(ROW_CONFIG)
    config["agency"] = "BidNet Direct"
    config.pop("state_filter", None)  # explicitly NOT configured

    source = make_source(
        config, portal_type="BidNet", base_url="https://www.bidnetdirect.com/"
    )
    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(source)

    assert [r.solicitation_number for r in results] == ["RFP-CA"]
    assert any("defaulting to CA/TX" in d for d in adapter.diagnostics)
    assert any("state filter removed 1 candidate" in d for d in adapter.diagnostics)


def test_non_aggregator_without_state_filter_is_unfiltered(monkeypatch):
    # A single-agency portal (not a multi-state aggregator) with no state_filter
    # is left unfiltered — its bids are inherently in its own state, and a
    # positive CA/TX filter would wrongly drop in-state rows lacking state text.
    _force_playwright(monkeypatch)
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html",
        lambda *a, **k: STATE_FILTER_LIST_HTML,
    )
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html_batch",
        _batch_returning(_state_filter_detail),
    )

    config = dict(ROW_CONFIG)
    config["agency"] = "City Portal"
    config.pop("state_filter", None)

    source = make_source(
        config, portal_type="Bonfire", name="City of Carson Bonfire"
    )
    adapter = AuthenticatedBrowserAdapter()
    results = adapter.scrape(source)

    assert {r.solicitation_number for r in results} == {"RFP-CA", "RFP-NV"}
    assert not any("defaulting to CA/TX" in d for d in adapter.diagnostics)


def test_search_keywords_accepts_comma_separated_string(monkeypatch):
    _force_playwright(monkeypatch)
    keywords_seen = []

    def fake_fetch(page_url, profile_dir, wait_selector=None, timeout_seconds=45,
                   headless=True, search_keyword=None, search_input_selector=None,
                   search_submit_selector=None):
        keywords_seen.append(search_keyword)
        return ROW_HTML

    monkeypatch.setattr(authenticated_browser, "fetch_authenticated_html", fake_fetch)
    monkeypatch.setattr(
        authenticated_browser,
        "fetch_authenticated_html_batch",
        _batch_returning(DETAIL_HTML),
    )

    config = dict(ROW_CONFIG)
    config["search_keywords"] = "California, Texas"

    adapter = AuthenticatedBrowserAdapter()
    adapter.scrape(make_source(config))

    assert keywords_seen == ["California", "Texas"]

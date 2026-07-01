"""Tests for generic public scraper structural candidate validation."""

from types import SimpleNamespace

import requests

from app.services.scraper import preview_source
from app.services.scrapers.generic_public import (
    GenericPublicAdapter,
    NO_STATIC_RECORDS_DIAGNOSTIC,
)
from app.services.scrapers.keywords import score_candidate_relevance


BASE_URL = "https://example.gov/solicitations"


def _source(**kwargs):
    values = {
        "id": 101,
        "name": "Example Procurement",
        "source_type": "public_page",
        "base_url": BASE_URL,
        "enabled": True,
        "requires_credentials": False,
        "login_url": None,
    }
    values.update(kwargs)
    return SimpleNamespace(**values)


def _scrape(html_by_url: dict[str, str], base_url: str = BASE_URL, detail_limit: int = 5):
    adapter = GenericPublicAdapter(detail_limit=detail_limit)

    def fake_fetch(url: str):
        if url not in html_by_url:
            raise requests.RequestException(f"unexpected fetch: {url}")
        return html_by_url[url], url

    adapter._fetch_page = fake_fetch
    results = adapter.scrape(_source(base_url=base_url))
    return adapter, results


def test_listing_h1_only_returns_zero_candidates():
    html = """
    <html><head><title>Solicitations</title></head>
      <body><h1>Solicitations</h1><p>Use this page to search open bids.</p></body>
    </html>
    """
    adapter, results = _scrape({BASE_URL: html})

    assert results == []
    assert NO_STATIC_RECORDS_DIAGNOSTIC in adapter.diagnostics


def test_candidate_url_equal_to_listing_url_is_rejected():
    html = """
    <html><body>
      <h1>Solicitations</h1>
      <article class="solicitation-card">
        <h2>Security Services Solicitation</h2>
        <a href="/solicitations">Solicitation details</a>
        <p>RFP-2026-10 due date: 07/20/2026</p>
      </article>
    </body></html>
    """
    adapter, results = _scrape({BASE_URL: html}, detail_limit=0)

    assert results == []
    assert adapter.filtered_reasons["candidate URL matches source/listing page"] >= 1


def test_generic_page_title_candidate_is_rejected_even_with_procurement_terms():
    html = """
    <html><head><title>Bid Opportunities</title></head>
      <body>
        <h1>Bid Opportunities</h1>
        <article class="bid-card">
          <h2>Bid Opportunities</h2>
          <a href="/opportunities">Bid Opportunities</a>
          <p>Find bid, quote, and solicitation opportunities.</p>
        </article>
      </body>
    </html>
    """
    adapter, results = _scrape({BASE_URL: html})

    assert results == []
    assert (
        adapter.filtered_reasons["candidate title matches page or generic portal heading"]
        >= 1
    )


def test_javascript_shell_returns_zero_candidates_with_diagnostic():
    html = """
    <html>
      <head><title>Vendor Portal</title><script src="/app.js"></script></head>
      <body><div id="root"></div><noscript>Please enable JavaScript.</noscript></body>
    </html>
    """
    adapter, results = _scrape({BASE_URL: html})

    assert results == []
    assert NO_STATIC_RECORDS_DIAGNOSTIC in adapter.diagnostics


def test_static_solicitation_table_row_is_accepted():
    html = """
    <table>
      <tr><th>Bid Title</th><th>Solicitation Number</th><th>Due Date</th></tr>
      <tr>
        <td>Unarmed Security Guard Services</td>
        <td>RFP-2026-17</td>
        <td>07/31/2026</td>
      </tr>
    </table>
    """
    _adapter, results = _scrape({BASE_URL: html}, detail_limit=0)

    assert len(results) == 1
    assert results[0].title == "Unarmed Security Guard Services"
    assert results[0].solicitation_number == "RFP-2026-17"
    assert results[0].extraction_method == "table_row"


def test_static_solicitation_card_with_unique_detail_url_is_accepted():
    html = """
    <article class="solicitation-card">
      <h2>Mobile Patrol Security Services</h2>
      <a href="/solicitations/RFP-2026-20">View solicitation</a>
      <p>RFP-2026-20 closes on due date: 08/15/2026.</p>
    </article>
    """
    _adapter, results = _scrape({BASE_URL: html})

    assert len(results) == 1
    assert results[0].title == "Mobile Patrol Security Services"
    assert results[0].detail_url == "https://example.gov/solicitations/RFP-2026-20"
    assert results[0].solicitation_number == "2026-20"


def test_direct_detail_source_page_with_notice_facts_is_accepted():
    detail_url = "https://example.gov/solicitations/RFP-2026-30"
    html = """
    <html><body>
      <h1>Solicitation Details</h1>
      <p>Solicitation Number: RFP-2026-30</p>
      <p>Due Date: 09/01/2026</p>
      <p>Unarmed security guard services for municipal facilities.</p>
      <a href="/docs/RFP-2026-30.pdf">RFP document</a>
    </body></html>
    """
    _adapter, results = _scrape({detail_url: html}, base_url=detail_url)

    assert len(results) == 1
    assert results[0].title == "Solicitation Details"
    assert results[0].solicitation_number == "RFP-2026-30"
    assert results[0].document_urls == ["https://example.gov/docs/RFP-2026-30.pdf"]


def test_deduplication_and_relevance_still_work_for_real_detail_links():
    detail_url = "https://example.gov/solicitations/RFP-2026-40"
    listing_html = """
    <a href="/solicitations/RFP-2026-40">RFP-2026-40 Security Guard Services</a>
    <a href="/solicitations/RFP-2026-40#top">RFP-2026-40 Security Guard Services</a>
    """
    detail_html = """
    <h1>Security Guard Services</h1>
    <p>Solicitation Number: RFP-2026-40</p>
    <p>Due Date: 09/15/2026</p>
    <p>Unarmed security guard services and patrol services.</p>
    """
    _adapter, results = _scrape({BASE_URL: listing_html, detail_url: detail_html})

    assert len(results) == 1
    relevance = score_candidate_relevance(results[0])
    assert relevance["relevance_decision"] == "Relevant"


def test_preview_records_zero_candidate_diagnostic(monkeypatch):
    adapter = GenericPublicAdapter()
    adapter.diagnostics = [NO_STATIC_RECORDS_DIAGNOSTIC]
    monkeypatch.setattr("app.services.scraper._select_adapter", lambda *_: adapter)
    monkeypatch.setattr(adapter, "scrape", lambda _source: [])

    result = preview_source(_source())

    assert result["records_found"] == 0
    assert result["diagnostics"] == [NO_STATIC_RECORDS_DIAGNOSTIC]

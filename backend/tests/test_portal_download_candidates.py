"""Regression tests for the headed portal download failure on BidNet.

A real run treated BidNet navigation links (search tabs, saved searches, the
site root, ?innerTabId= self-links) as document candidates, clicked them, and
kept erroring through the queue after the human closed the browser window.
Pure logic tests -- no network, no Playwright.
"""

import pytest

from app.services.scrapers.browser_session import (
    BrowserClosedError,
    _browser_gone,
    _download_by_selector,
    _filter_download_candidates,
)
from app.services.scrapers.extraction_utils import (
    extract_document_candidates,
    extract_document_view_links,
)

PAGE_URL = "https://www.bidnetdirect.com/private/supplier/solicitations/notice/2697523412/abstract"


def _candidate(url, confidence=0.9):
    return {"url": url, "label": "doc", "confidence_score": confidence}


# --- extraction: navigation links must not score as documents ----------------
def _extract(html):
    return extract_document_candidates(html, PAGE_URL, allow_external=True)


def test_nav_search_link_rejected_despite_solicitation_keyword_in_url():
    html = '<a href="/private/supplier/solicitations/search?target=init">Solicitations</a>'
    assert _extract(html) == []


def test_saved_searches_and_favorites_rejected():
    html = (
        '<a href="/private/solicitations/saved-searches">My saved searches</a>'
        '<a href="/private/supplier/favorites">Favorites</a>'
    )
    assert _extract(html) == []


def test_site_root_link_rejected():
    html = '<a href="https://www.bidnetdirect.com/">Download</a>'
    assert _extract(html) == []


def test_direct_file_in_navigation_path_still_accepted():
    html = '<a href="/private/supplier/search/RFP-packet.pdf">RFP packet</a>'
    candidates = _extract(html)
    assert len(candidates) == 1
    assert candidates[0]["url"].endswith("RFP-packet.pdf")


def test_real_document_link_still_accepted():
    html = '<a href="/documents/download/12345">Addendum 1 - Scope of Work</a>'
    candidates = _extract(html)
    assert len(candidates) == 1


# --- queue filtering: self-links, duplicates, confidence ---------------------
def test_self_link_tab_anchors_dropped():
    candidates = [
        _candidate(f"{PAGE_URL}?innerTabId=documents"),
        _candidate(f"{PAGE_URL}?innerTabId=amendments"),
        _candidate(f"{PAGE_URL}"),
    ]
    assert _filter_download_candidates(candidates, PAGE_URL, 0.3) == []


def test_duplicate_urls_dropped_but_distinct_queries_kept():
    kept_a = _candidate("https://example.gov/download.aspx?id=1")
    kept_b = _candidate("https://example.gov/download.aspx?id=2")
    candidates = [kept_a, dict(kept_a), kept_b]
    assert _filter_download_candidates(candidates, PAGE_URL, 0.3) == [kept_a, kept_b]


def test_below_confidence_dropped():
    candidates = [_candidate("https://example.gov/doc.pdf", confidence=0.2)]
    assert _filter_download_candidates(candidates, PAGE_URL, 0.3) == []


# --- document view discovery (tab links worth visiting, not downloading) -----
def test_bidnet_documents_tab_discovered_as_view():
    html = (
        f'<a href="{PAGE_URL}?innerTabId=documents">Documents</a>'
        f'<a href="{PAGE_URL}?innerTabId=categories">Categories</a>'
    )
    views = extract_document_view_links(html, PAGE_URL)
    assert views == [f"{PAGE_URL}?innerTabId=documents"]


def test_labeled_attachments_link_discovered_even_on_other_path():
    html = '<a href="/portal/notice/999/attachments-list">Attachments</a>'
    views = extract_document_view_links(html, PAGE_URL)
    assert views == ["https://www.bidnetdirect.com/portal/notice/999/attachments-list"]


def test_external_and_generic_links_not_views():
    html = (
        '<a href="https://other.example.com/documents">Documents</a>'
        '<a href="/private/supplier/favorites">Favorites</a>'
        f'<a href="{PAGE_URL}">Abstract</a>'
    )
    assert extract_document_view_links(html, PAGE_URL) == []


def test_documents_view_sorted_first():
    html = (
        '<a href="/portal/notice/999/misc">Attachments</a>'
        f'<a href="{PAGE_URL}?innerTabId=documents">Documents</a>'
    )
    views = extract_document_view_links(html, PAGE_URL)
    assert views[0] == f"{PAGE_URL}?innerTabId=documents"


# --- closed browser detection ------------------------------------------------
def test_browser_gone_matches_playwright_messages():
    assert _browser_gone(Exception("Target page, context or browser has been closed"))
    assert _browser_gone(Exception("APIRequestContext.get: Request context disposed"))
    assert not _browser_gone(Exception("net::ERR_CONNECTION_REFUSED"))


def test_selector_download_raises_browser_closed():
    class GonePage:
        def locator(self, selector):
            raise Exception("Target page, context or browser has been closed")

    result = {"downloaded_files": [], "errors": []}
    with pytest.raises(BrowserClosedError):
        _download_by_selector(
            GonePage(),
            {"selector": "#download", "selector_index": 0},
            output_dir=None,
            timeout_ms=1000,
            result=result,
        )
    assert result["errors"] == []

"""Regression tests for the headed portal download failure on BidNet.

A real run treated BidNet navigation links (search tabs, saved searches, the
site root, ?innerTabId= self-links) as document candidates, clicked them, and
kept erroring through the queue after the human closed the browser window.
Pure logic tests -- no network, no Playwright.
"""

import pytest

from app.services.scrapers import browser_session
from app.services.scrapers.browser_session import (
    BrowserClosedError,
    _browser_gone,
    _download_by_browser_request,
    _download_by_selector,
    _filter_download_candidates,
    _save_click_download,
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


class _FakeRequestContext:
    def __init__(self, response):
        self._response = response

    def get(self, url, timeout):
        return self._response


class _FakeContext:
    def __init__(self, response):
        self.request = _FakeRequestContext(response)


class _FakeResponse:
    def __init__(self, body=b"%PDF-1.4", headers=None):
        self.status = 200
        self.headers = headers or {"content-type": "application/pdf"}
        self.url = "https://example.gov/doc.pdf"
        self._body = body

    def body(self):
        return self._body


def test_browser_request_download_rejects_declared_oversize(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_session, "MAX_DOWNLOAD_BYTES", 8)
    response = _FakeResponse(headers={"content-type": "application/pdf", "content-length": "9"})
    result = {"downloaded_files": [], "errors": []}

    outcome = _download_by_browser_request(
        _FakeContext(response),
        _candidate("https://example.gov/doc.pdf"),
        tmp_path,
        1000,
        result,
    )

    assert result["downloaded_files"] == []
    assert "content-length exceeds" in result["errors"][0]
    # "skipped" tells the caller not to fall back to the click path, which
    # would download the entire oversize file through the browser anyway.
    assert outcome == "skipped"


def test_browser_request_download_rejects_body_oversize(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_session, "MAX_DOWNLOAD_BYTES", 8)
    response = _FakeResponse(body=b"123456789")
    result = {"downloaded_files": [], "errors": []}

    outcome = _download_by_browser_request(
        _FakeContext(response),
        _candidate("https://example.gov/doc.pdf"),
        tmp_path,
        1000,
        result,
    )

    assert result["downloaded_files"] == []
    assert "response body exceeds" in result["errors"][0]
    assert outcome == "skipped"


def test_browser_request_download_success_returns_downloaded(tmp_path):
    result = {"downloaded_files": [], "errors": []}

    outcome = _download_by_browser_request(
        _FakeContext(_FakeResponse()),
        _candidate("https://example.gov/doc.pdf"),
        tmp_path,
        1000,
        result,
    )

    assert outcome == "downloaded"
    assert len(result["downloaded_files"]) == 1
    assert result["errors"] == []


def test_browser_request_download_failure_returns_retry(tmp_path):
    class FailingRequestContext:
        def get(self, url, timeout):
            raise Exception("net::ERR_CONNECTION_REFUSED")

    class FailingContext:
        request = FailingRequestContext()

    result = {"downloaded_files": [], "errors": []}

    outcome = _download_by_browser_request(
        FailingContext(),
        _candidate("https://example.gov/doc.pdf"),
        tmp_path,
        1000,
        result,
    )

    assert outcome == "retry"
    assert result["downloaded_files"] == []


def test_click_download_rejects_saved_oversize(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_session, "MAX_DOWNLOAD_BYTES", 8)

    class FakeDownload:
        suggested_filename = "big.pdf"

        def save_as(self, path):
            with open(path, "wb") as handle:
                handle.write(b"123456789")

    class FakeDownloadInfo:
        value = FakeDownload()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakePage:
        def expect_download(self, timeout):
            return FakeDownloadInfo()

    class FakeLocator:
        def click(self, timeout):
            return None

    result = {"downloaded_files": [], "errors": []}

    _save_click_download(
        FakePage(),
        FakeLocator(),
        _candidate("https://example.gov/big.pdf"),
        tmp_path,
        1000,
        result,
    )

    assert result["downloaded_files"] == []
    assert not (tmp_path / "big.pdf").exists()
    assert "downloaded file exceeds" in result["errors"][0]

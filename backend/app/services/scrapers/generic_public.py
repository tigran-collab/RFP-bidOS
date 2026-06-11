from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.services.scrapers.base import ScraperResult
from app.services.scrapers.extraction_utils import (
    confidence_from_text,
    extract_contract_type,
    extract_document_urls,
    extract_due_date,
    extract_estimated_value,
    extract_location,
    extract_page_title,
    extract_pre_bid_date,
    extract_q_and_a_deadline,
    extract_service_type,
    extract_solicitation_number,
    normalize_space,
    visible_text_from_html,
)
from app.services.scrapers.source_classifier import classify_source
from app.services.scrapers.table_parser import parse_tables

SCRAPER_USER_AGENT = "RFP-BidOS Public Scraper/0.2 (+source-adapters)"
BID_KEYWORDS = (
    "bid",
    "bids",
    "rfp",
    "rfq",
    "ifb",
    "itb",
    "solicitation",
    "procurement",
    "proposal",
    "quote",
    "security",
    "guard",
    "patrol",
    "armed",
    "unarmed",
)


class GenericPublicAdapter:
    def __init__(
        self,
        detail_limit: int = 10,
        allow_external_detail_pages: bool = False,
        timeout: int = 20,
    ) -> None:
        self.detail_limit = detail_limit
        self.allow_external_detail_pages = allow_external_detail_pages
        self.timeout = timeout

    def can_handle(self, source_config) -> bool:
        source_type = (getattr(source_config, "source_type", "") or "").lower()
        return source_type in {"public_page", "generic_html", "table_listing", "portal_listing", ""}

    def scrape(self, source_config) -> list[ScraperResult]:
        base_url = getattr(source_config, "base_url", None)
        if not base_url:
            return []

        html = self._fetch(base_url)
        source_kind = classify_source(html, base_url)
        results = parse_tables(html, base_url, portal_url=base_url)
        document_urls = extract_document_urls(html, base_url)

        if document_urls:
            page_text = visible_text_from_html(html)
            page_title = extract_page_title(html, fallback=getattr(source_config, "name", base_url))
            results.append(
                self._result_from_text(
                    title=page_title,
                    text=page_text,
                    source_url=base_url,
                    detail_url=None,
                    portal_url=base_url,
                    document_urls=document_urls,
                    source_config=source_config,
                )
            )

        detail_limit = self.detail_limit if source_kind != "document_listing" else 0
        detail_links = self._candidate_detail_links(html, base_url)
        for link in detail_links[:detail_limit]:
            try:
                detail_html = self._fetch(link["url"])
            except requests.RequestException:
                continue
            detail_documents = extract_document_urls(detail_html, link["url"])
            text = visible_text_from_html(detail_html)
            title = extract_page_title(detail_html, fallback=link["title"])
            results.append(
                self._result_from_text(
                    title=title,
                    text=text,
                    source_url=link["url"],
                    detail_url=link["url"],
                    portal_url=base_url,
                    document_urls=detail_documents,
                    source_config=source_config,
                )
            )

        return _dedupe_results(results)

    def _fetch(self, url: str) -> str:
        response = requests.get(
            url,
            headers={"User-Agent": SCRAPER_USER_AGENT},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.text

    def _candidate_detail_links(self, html: str, base_url: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            title = normalize_space(anchor.get_text(" ", strip=True))
            href = str(anchor.get("href") or "").strip()
            if not href:
                continue
            url = urljoin(base_url, href)
            if url in seen or not self._is_allowed_detail_url(base_url, url):
                continue

            haystack = f"{title} {url}".lower()
            if not any(keyword in haystack for keyword in BID_KEYWORDS):
                continue

            seen.add(url)
            links.append({"title": title or url, "url": url})
        return links

    def _is_allowed_detail_url(self, base_url: str, detail_url: str) -> bool:
        if self.allow_external_detail_pages:
            return True
        return urlparse(base_url).netloc.lower() == urlparse(detail_url).netloc.lower()

    def _result_from_text(
        self,
        title: str,
        text: str,
        source_url: str,
        detail_url: str | None,
        portal_url: str,
        document_urls: list[str],
        source_config,
    ) -> ScraperResult:
        title = normalize_space(title) or "Untitled opportunity"
        description = text[:1000] if text else None
        return ScraperResult(
            title=title,
            agency=getattr(source_config, "name", None),
            solicitation_number=extract_solicitation_number(text),
            source_url=source_url,
            detail_url=detail_url,
            portal_url=portal_url,
            location=extract_location(text),
            due_date=extract_due_date(text),
            pre_bid_date=extract_pre_bid_date(text),
            q_and_a_deadline=extract_q_and_a_deadline(text),
            service_type=extract_service_type(f"{title} {text}"),
            contract_type=extract_contract_type(text),
            estimated_value=extract_estimated_value(text),
            description=description,
            document_urls=document_urls,
            raw_text=text,
            confidence_score=confidence_from_text(title, text, document_urls),
        )


def _dedupe_results(results: list[ScraperResult]) -> list[ScraperResult]:
    deduped: list[ScraperResult] = []
    seen: set[tuple[str | None, str | None, str]] = set()
    for result in results:
        key = (
            result.detail_url or result.source_url,
            result.solicitation_number,
            result.title.lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped

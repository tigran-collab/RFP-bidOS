import re
import time
from urllib.parse import parse_qsl, urlencode, urldefrag, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from app.services.scrapers.base import ScraperResult
from app.services.scrapers.extraction_utils import (
    confidence_from_text,
    extract_contract_type,
    extract_document_candidates,
    extract_document_urls,
    extract_due_date,
    extract_estimated_value,
    extract_location,
    extract_page_title,
    extract_pre_bid_date,
    extract_q_and_a_deadline,
    extract_service_type,
    extract_solicitation_number,
    is_document_url,
    normalize_space,
    visible_text_from_html,
)
from app.services.scrapers.keywords import (
    PRIMARY_SECURITY_KEYWORDS,
    SECONDARY_SECURITY_KEYWORDS,
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
    *PRIMARY_SECURITY_KEYWORDS,
    *SECONDARY_SECURITY_KEYWORDS,
)

GENERIC_PORTAL_TITLES = frozenset(
    {
        "active solicitations",
        "bid opportunities",
        "bids",
        "current opportunities",
        "electronic state business daily search",
        "open bids",
        "procurement",
        "requests for bids",
        "requests for proposals",
        "solicitation details",
        "solicitations",
        "vendor portal",
    }
)

NAVIGATION_URL_TERMS = (
    "about",
    "account",
    "award",
    "awards",
    "calendar",
    "closed",
    "contact",
    "faq",
    "help",
    "login",
    "logout",
    "privacy",
    "register",
    "registration",
    "search",
    "signin",
    "sign-in",
    "sitemap",
    "terms",
    "vendor-registration",
)

NO_STATIC_RECORDS_DIAGNOSTIC = (
    "No static solicitation records found; page appears to be a portal shell or listing page."
)


class GenericPublicAdapter:
    def __init__(
        self,
        detail_limit: int = 10,
        allow_external_detail_pages: bool = False,
        timeout: int = 20,
        detail_throttle_seconds: float = 0.5,
    ) -> None:
        self.detail_limit = detail_limit
        self.allow_external_detail_pages = allow_external_detail_pages
        self.timeout = timeout
        # Polite delay between successive detail-page fetches so a single source
        # (now that many portals are enabled) doesn't hammer a site.
        self.detail_throttle_seconds = detail_throttle_seconds
        self.diagnostics: list[str] = []
        self.filtered_reasons: dict[str, int] = {}

    def can_handle(self, source_config) -> bool:
        source_type = (getattr(source_config, "source_type", "") or "").lower()
        return source_type in {"public_page", "generic_html", "table_listing", "portal_listing", ""}

    def scrape(self, source_config) -> list[ScraperResult]:
        self.diagnostics = []
        self.filtered_reasons = {}
        base_url = getattr(source_config, "base_url", None)
        if not base_url:
            return []

        html, page_url = self._fetch_page(base_url)
        source_kind = classify_source(html, page_url)
        source_title = getattr(source_config, "name", base_url)
        page_title = extract_page_title(html, fallback=source_title)
        listing_urls = {_normalize_url(base_url), _normalize_url(page_url)}

        raw_results: list[ScraperResult] = []
        raw_results.extend(parse_tables(html, page_url, portal_url=base_url))
        raw_results.extend(self._bounded_block_candidates(html, page_url, base_url, source_config))

        document_candidates = extract_document_candidates(html, page_url)
        document_urls = [c["url"] for c in document_candidates if is_document_url(c["url"])]

        source_page_result = self._result_from_text(
            title=page_title,
            text=visible_text_from_html(html),
            source_url=page_url,
            detail_url=None,
            portal_url=base_url,
            document_urls=document_urls,
            document_candidates=document_candidates,
            source_config=source_config,
            extraction_method="source_page",
        )
        detail_limit = self.detail_limit if source_kind != "document_listing" else 0
        detail_links = self._candidate_detail_links(html, page_url, listing_urls)

        if (
            not raw_results
            and not detail_links
            and self._has_direct_notice_evidence(source_page_result)
        ):
            page_text = visible_text_from_html(html)
            raw_results.append(
                self._result_from_text(
                    title=page_title,
                    text=page_text,
                    source_url=page_url,
                    detail_url=None,
                    portal_url=base_url,
                    document_urls=document_urls,
                    document_candidates=document_candidates,
                    source_config=source_config,
                    extraction_method="source_page",
                )
            )

        for index, link in enumerate(detail_links[:detail_limit]):
            if index and self.detail_throttle_seconds:
                time.sleep(self.detail_throttle_seconds)
            try:
                detail_html, detail_url = self._fetch_page(link["url"])
            except requests.RequestException:
                continue
            detail_candidates = extract_document_candidates(detail_html, detail_url)
            detail_documents = [
                c["url"] for c in detail_candidates if is_document_url(c["url"])
            ]
            text = visible_text_from_html(detail_html)
            title = extract_page_title(detail_html, fallback=link["title"])
            raw_results.append(
                self._result_from_text(
                    title=title,
                    text=text,
                    source_url=detail_url,
                    detail_url=detail_url,
                    portal_url=base_url,
                    document_urls=detail_documents,
                    document_candidates=detail_candidates,
                    source_config=source_config,
                    extraction_method="detail_page",
                )
            )

        results = [
            result
            for result in raw_results
            if self._valid_candidate(
                result,
                source_url=base_url,
                page_url=page_url,
                page_title=page_title,
                source_title=source_title,
                listing_urls=listing_urls,
            )
        ]
        if not results:
            self.diagnostics.append(NO_STATIC_RECORDS_DIAGNOSTIC)
        return _dedupe_results(results)

    def _fetch(self, url: str) -> str:
        html, _final_url = self._fetch_page(url)
        return html

    def _fetch_page(self, url: str) -> tuple[str, str]:
        response = requests.get(
            url,
            headers={"User-Agent": SCRAPER_USER_AGENT},
            timeout=self.timeout,
        )
        response.raise_for_status()
        # Without a charset in the Content-Type header requests decodes text/*
        # as ISO-8859-1, mojibaking UTF-8 pages; sniff the real encoding then.
        content_type = response.headers.get("Content-Type") or ""
        if response.encoding is None or "charset" not in content_type.lower():
            response.encoding = response.apparent_encoding
        return response.text, response.url

    def _candidate_detail_links(
        self, html: str, base_url: str, listing_urls: set[str] | None = None
    ) -> list[dict[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            title = normalize_space(anchor.get_text(" ", strip=True))
            href = str(anchor.get("href") or "").strip()
            if not href or _is_disallowed_url(href):
                continue
            url = _defrag_url(urljoin(base_url, href))
            normalized = _normalize_url(url)
            if (
                not normalized
                or normalized in seen
                or normalized in (listing_urls or set())
                or is_document_url(url)
                or _is_navigation_link(title, url)
                or not self._is_allowed_detail_url(base_url, url)
            ):
                continue

            haystack = f"{title} {url}".lower()
            if not any(keyword in haystack for keyword in BID_KEYWORDS):
                continue

            seen.add(normalized)
            links.append({"title": title or url, "url": url})
        return links

    def _bounded_block_candidates(
        self, html: str, page_url: str, portal_url: str, source_config
    ) -> list[ScraperResult]:
        soup = BeautifulSoup(html, "html.parser")
        selectors = (
            "article",
            "li",
            "[class*=bid]",
            "[class*=solicit]",
            "[class*=opportun]",
            "[class*=procurement]",
            "[class*=card]",
            "[id*=bid]",
            "[id*=solicit]",
            "[id*=opportun]",
        )
        candidates: list[ScraperResult] = []
        seen_blocks: set[str] = set()
        for block in soup.select(", ".join(selectors)):
            text = normalize_space(block.get_text(" ", strip=True))
            if len(text) < 20:
                continue
            block_key = text[:200].lower()
            if block_key in seen_blocks:
                continue
            anchor = block.find("a", href=True)
            if anchor is None:
                continue
            href = str(anchor.get("href") or "").strip()
            if not href or _is_disallowed_url(href):
                continue
            detail_url = _defrag_url(urljoin(page_url, href))
            title = _best_block_title(block, anchor) or text[:120]
            documents = extract_document_urls(str(block), page_url)
            document_candidates = extract_document_candidates(str(block), page_url)
            seen_blocks.add(block_key)
            candidates.append(
                self._result_from_text(
                    title=title,
                    text=text,
                    source_url=detail_url,
                    detail_url=detail_url,
                    portal_url=portal_url,
                    document_urls=documents,
                    document_candidates=document_candidates,
                    source_config=source_config,
                    extraction_method="card",
                )
            )
        return candidates

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
        document_candidates: list[dict] | None = None,
        extraction_method: str | None = None,
    ) -> ScraperResult:
        title = normalize_space(title) or "Untitled opportunity"
        description = text[:1000] if text else None
        return ScraperResult(
            title=title,
            extraction_method=extraction_method,
            agency=getattr(source_config, "name", None) if source_config is not None else None,
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
            document_candidates=document_candidates or [],
            raw_text=text,
            confidence_score=confidence_from_text(title, text, document_urls),
        )

    def _valid_candidate(
        self,
        candidate: ScraperResult,
        source_url: str,
        page_url: str,
        page_title: str,
        source_title: str,
        listing_urls: set[str],
    ) -> bool:
        reason = _candidate_reject_reason(
            candidate,
            source_url=source_url,
            page_url=page_url,
            page_title=page_title,
            source_title=source_title,
            listing_urls=listing_urls,
        )
        if reason is None:
            return True
        self.filtered_reasons[reason] = self.filtered_reasons.get(reason, 0) + 1
        return False

    def _has_direct_notice_evidence(self, candidate: ScraperResult) -> bool:
        if not _has_concrete_notice_evidence(candidate):
            return False
        if not _is_generic_title(candidate.title):
            return True
        return bool(
            candidate.solicitation_number
            and (candidate.due_date or candidate.document_urls or candidate.document_candidates)
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


def _candidate_reject_reason(
    candidate: ScraperResult,
    source_url: str,
    page_url: str,
    page_title: str,
    source_title: str,
    listing_urls: set[str],
) -> str | None:
    title = candidate.title or ""
    method = candidate.extraction_method or ""
    candidate_url = candidate.detail_url or candidate.source_url or ""
    normalized_url = _normalize_url(candidate_url)
    normalized_listing_urls = listing_urls | {_normalize_url(source_url), _normalize_url(page_url)}

    if not candidate_url or _is_disallowed_url(candidate_url):
        return "empty or script candidate URL"
    if _is_navigation_link(title, candidate_url):
        return "navigation/account/help/footer link"

    is_listing_url = normalized_url in normalized_listing_urls
    if is_listing_url and not (
        method == "table_row" and _has_bounded_record_evidence(candidate)
    ) and not (
        method == "source_page" and _has_concrete_notice_evidence(candidate)
    ):
        return "candidate URL matches source/listing page"

    if _title_matches(title, source_title):
        return "candidate title matches page or generic portal heading"

    if _title_matches(title, page_title) or _is_generic_title(title):
        if not (
            candidate.solicitation_number
            and (candidate.due_date or candidate.document_urls or candidate.document_candidates)
        ):
            return "candidate title matches page or generic portal heading"

    if not _has_opportunity_evidence(candidate, normalized_listing_urls):
        return "no opportunity-level evidence"

    return None


def _has_opportunity_evidence(candidate: ScraperResult, listing_urls: set[str]) -> bool:
    method = candidate.extraction_method or ""
    candidate_url = candidate.detail_url or candidate.source_url or ""
    normalized_url = _normalize_url(candidate_url)
    distinct_detail_url = bool(candidate.detail_url) and normalized_url not in listing_urls
    text = f"{candidate.title or ''} {candidate.raw_text or candidate.description or ''}".lower()
    has_procurement_text = any(keyword in text for keyword in BID_KEYWORDS)

    if distinct_detail_url and has_procurement_text:
        return True
    if _has_concrete_notice_evidence(candidate):
        return True
    if method in {"table_row", "card"} and _has_bounded_record_evidence(candidate):
        return True
    return False


def _has_concrete_notice_evidence(candidate: ScraperResult) -> bool:
    return bool(
        candidate.solicitation_number
        or candidate.due_date
        or candidate.document_urls
        or any(is_document_url(c.get("url", "")) for c in candidate.document_candidates)
    )


def _has_bounded_record_evidence(candidate: ScraperResult) -> bool:
    text = f"{candidate.title or ''} {candidate.raw_text or candidate.description or ''}".lower()
    has_notice_term = any(
        token in text
        for token in ("rfp", "rfq", "ifb", "itb", "bid", "solicitation", "proposal", "quote")
    )
    return bool(
        candidate.solicitation_number
        or candidate.due_date
        or candidate.document_urls
        or (candidate.detail_url and has_notice_term)
    )


def _normalize_url(url: str | None) -> str:
    if not url:
        return ""
    try:
        url, _fragment = urldefrag(url.strip())
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        # Malformed authority (e.g. a non-numeric port) — treat as no URL.
        return ""
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if port and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunparse((scheme, host, path, "", query, ""))


def _defrag_url(url: str) -> str:
    cleaned, _fragment = urldefrag(url)
    return cleaned


def _is_disallowed_url(url: str | None) -> bool:
    if not url:
        return True
    lowered = url.strip().lower()
    return lowered.startswith(("javascript:", "mailto:", "tel:", "#"))


def _normalize_title_for_compare(title: str | None) -> str:
    value = normalize_space(title or "").lower()
    value = re.sub(r"[\W_]+", " ", value)
    value = re.sub(r"\b(city|county|state|of|the|and|for|public|online)\b", " ", value)
    return normalize_space(value)


def _title_matches(title: str | None, other: str | None) -> bool:
    left = _normalize_title_for_compare(title)
    right = _normalize_title_for_compare(other)
    if not left or not right:
        return False
    if left == right:
        return True
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return False
    if min(len(left_tokens), len(right_tokens)) >= 3 and (
        left_tokens <= right_tokens or right_tokens <= left_tokens
    ):
        return True
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))
    return overlap >= 0.8 and min(len(left_tokens), len(right_tokens)) <= 5


def _is_generic_title(title: str | None) -> bool:
    normalized = _normalize_title_for_compare(title)
    if normalized in GENERIC_PORTAL_TITLES:
        return True
    return any(_title_matches(normalized, generic) for generic in GENERIC_PORTAL_TITLES)


def _is_navigation_link(title: str | None, url: str | None) -> bool:
    lowered_title = _normalize_title_for_compare(title)
    parsed = urlparse(url or "")
    path = (parsed.path or "").strip("/").lower()
    if lowered_title in {"home", "help", "contact", "login", "sign in", "register", "search"}:
        return True
    haystack = f"{lowered_title} {path}".replace("_", "-")
    return any(term in haystack for term in NAVIGATION_URL_TERMS)


def _best_block_title(block, anchor) -> str | None:
    for selector in ("h1", "h2", "h3", "h4", "strong", "b"):
        heading = block.find(selector)
        if heading:
            text = normalize_space(heading.get_text(" ", strip=True))
            if text:
                return text
    text = normalize_space(anchor.get_text(" ", strip=True))
    return text or None

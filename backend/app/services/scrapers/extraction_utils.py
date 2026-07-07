import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

SECURITY_SERVICE_KEYWORDS = (
    "security guard",
    "armed security",
    "unarmed security",
    "patrol",
    "mobile patrol",
    "vehicle patrol",
    "fire watch",
    "courthouse security",
    "facility security",
    "campus security",
    "parking security",
    "hospital security",
    "public safety officer",
)

AS_NEEDED_WARNING_KEYWORDS = (
    "as needed",
    "as-needed",
    "on-call",
    "standby",
    "no guaranteed minimum",
    "task order",
    "blanket",
    "bench",
)

DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".zip",
    ".txt",
}

# Strong solicitation-document signals: high confidence even without a file
# extension, because the link text alone clearly names a bid document.
STRONG_DOCUMENT_KEYWORDS = (
    "rfp",
    "rfq",
    "ifb",
    "itb",
    "bid packet",
    "bid documents",
    "solicitation",
    "addendum",
    "addenda",
    "attachment",
    "exhibit",
    "scope of work",
    "sow",
    "specification",
    "specs",
    "proposal form",
    "bid form",
    "price sheet",
    "pricing sheet",
    "sample contract",
    "notice inviting bids",
    "nib",
)

# Weaker but still document-like signals.
WEAK_DOCUMENT_KEYWORDS = (
    "insurance",
    "terms and conditions",
    "q&a",
    "questions and answers",
    "amendment",
    "form",
    "packet",
)

GENERIC_LINK_TEXT = {
    "",
    "click here",
    "click",
    "download",
    "view",
    "open",
    "read more",
    "more",
    "link",
    "here",
    "details",
    "learn more",
}

# URL path segments that mark portal navigation (search pages, account areas),
# never documents, unless the href is itself a direct downloadable file.
NAVIGATION_URL_SEGMENTS = {
    "search",
    "searches",
    "saved-searches",
    "favorites",
    "favourites",
    "login",
    "logout",
    "signin",
    "sign-in",
    "register",
    "registration",
    "account",
    "profile",
    "settings",
    "notifications",
    "dashboard",
    "home",
    "cart",
}

# Nav/footer link text that should never be treated as a document, unless the
# href is itself a direct downloadable file.
DOCUMENT_REJECT_KEYWORDS = (
    "privacy",
    "accessibility",
    "terms of use",
    "contact",
    "contact us",
    "careers",
    "sitemap",
    "site map",
    "login",
    "log in",
    "sign in",
    "register",
    "registration",
    "vendor registration",
    "subscribe",
    "home",
)

SOCIAL_DOMAINS = (
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "flickr.com",
    "pinterest.com",
    "tiktok.com",
)

DATE_PATTERNS = (
    r"\b\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d{1,2}:\d{2}\s*(?:am|pm)?)?",
    r"\b\d{4}-\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2})?",
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}",
)


def normalize_space(value: str | None) -> str:
    return " ".join((value or "").split())


def visible_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return normalize_space(soup.get_text(" ", strip=True))


def extract_page_title(html: str, fallback: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find(["h1", "h2"])
    if heading:
        text = normalize_space(heading.get_text(" ", strip=True))
        if text:
            return text
    if soup.title:
        text = normalize_space(soup.title.get_text(" ", strip=True))
        if text:
            return text
    return fallback


def extract_document_candidates(
    html: str, base_url: str, allow_external: bool = False
) -> list[dict]:
    """Discover document-like links from a page.

    Returns a list of dicts with url, label, file_type, confidence_score, and
    reason, sorted by confidence descending. Relative URLs are resolved,
    fragments stripped, and mailto/tel/javascript/social/nav links rejected.
    """
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlparse(base_url).netloc.lower()
    seen: set[str] = set()
    candidates: list[dict] = []
    for anchor in soup.find_all("a", href=True):
        raw = str(anchor.get("href") or "").strip()
        if not raw or raw.lower().startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url, _fragment = urldefrag(urljoin(base_url, raw))
        if not url.lower().startswith(("http://", "https://")) or url in seen:
            continue

        host = urlparse(url).netloc.lower()
        is_file = is_document_url(url)
        # Same-host by default; external links only when they are direct files
        # or external document hosting is explicitly allowed.
        if host != base_host and not (is_file or allow_external):
            continue

        text = normalize_space(anchor.get_text(" ", strip=True))
        scored = _score_document_link(text, url, is_file)
        if scored is None:
            continue

        seen.add(url)
        candidates.append(
            {
                "url": url,
                "label": text or _filename_label(url),
                "file_type": _file_type(url),
                "confidence_score": scored[0],
                "reason": scored[1],
            }
        )
    candidates.sort(key=lambda candidate: candidate["confidence_score"], reverse=True)
    return candidates


def extract_document_urls(html: str, base_url: str) -> list[str]:
    """Direct downloadable document file URLs only (feeds the downloader)."""
    return [
        candidate["url"]
        for candidate in extract_document_candidates(html, base_url)
        if is_document_url(candidate["url"])
    ]


def is_document_url(url: str) -> bool:
    parsed = urlparse(url)
    suffix = Path(unquote(parsed.path)).suffix.lower()
    return suffix in DOCUMENT_EXTENSIONS


def _file_type(url: str) -> str | None:
    suffix = Path(unquote(urlparse(url).path)).suffix.lower().lstrip(".")
    return suffix or None


def _filename_label(url: str) -> str:
    name = Path(unquote(urlparse(url).path)).name
    return name or url


def _score_document_link(text: str, url: str, is_file: bool) -> tuple[float, str] | None:
    """Return (confidence, reason) or None if the link should be rejected."""
    text_lower = text.lower()
    url_lower = url.lower()
    host = urlparse(url_lower).netloc

    if any(domain in host for domain in SOCIAL_DOMAINS):
        return None

    # Reject nav/footer links unless the href is itself a direct file.
    if not is_file and any(
        keyword in text_lower for keyword in DOCUMENT_REJECT_KEYWORDS
    ):
        return None

    # Reject site roots and portal-navigation URLs (search pages, account
    # areas). Keyword matching below also scans the URL, so without this a
    # nav link like /solicitations/search scores as a "solicitation" hit.
    if not is_file:
        path_segments = [
            segment for segment in urlparse(url_lower).path.split("/") if segment
        ]
        if not path_segments or any(
            segment in NAVIGATION_URL_SEGMENTS for segment in path_segments
        ):
            return None

    haystack = f"{text_lower} {url_lower}"
    has_strong = any(keyword in haystack for keyword in STRONG_DOCUMENT_KEYWORDS)
    has_weak = any(keyword in haystack for keyword in WEAK_DOCUMENT_KEYWORDS)
    is_generic = text_lower.strip() in GENERIC_LINK_TEXT

    if is_file and has_strong:
        return 0.95, "document file with solicitation keyword"
    if is_file:
        return 0.8, "direct document file"
    if has_strong:
        return 0.6, "solicitation keyword link"
    if has_weak:
        return 0.5, "document-like keyword link"
    if is_generic:
        return 0.3, "generic download/click link"
    return None


def extract_due_date(text: str) -> datetime | None:
    return _date_after_keywords(
        text,
        ("due date", "closing date", "deadline", "bids due", "proposal due", "submittal deadline"),
    )


def extract_pre_bid_date(text: str) -> datetime | None:
    return _date_after_keywords(text, ("pre-bid", "pre bid", "pre-proposal", "pre proposal"))


def extract_q_and_a_deadline(text: str) -> datetime | None:
    return _date_after_keywords(
        text,
        ("q&a deadline", "questions due", "question deadline", "rfi deadline"),
    )


def extract_solicitation_number(text: str) -> str | None:
    patterns = (
        r"(?:solicitation|bid|rfp|rfq|ifb|itb|project)\s*(?:number|no\.?|#)?\s*[:#-]\s*([A-Za-z0-9][A-Za-z0-9._/-]{1,})",
        r"\b(?:RFP|RFQ|IFB|ITB)\s*[-#:]?\s*([A-Za-z0-9][A-Za-z0-9._/-]{1,})",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            candidate = match.group(1).strip(" .;,")
            # Real solicitation numbers contain at least one digit; this rejects
            # prose matches like "RFP for ..." capturing the stopword "for".
            if candidate and any(ch.isdigit() for ch in candidate):
                return candidate
    return None


def extract_contract_type(text: str) -> str | None:
    lowered = text.lower()
    if any(keyword in lowered for keyword in AS_NEEDED_WARNING_KEYWORDS):
        return "As-needed / on-call"
    if "blanket" in lowered:
        return "Blanket agreement"
    if "fixed price" in lowered or "firm fixed" in lowered:
        return "Fixed price"
    if "multi-year" in lowered or "multiyear" in lowered:
        return "Multi-year"
    return None


def extract_service_type(text: str) -> str | None:
    lowered = text.lower()
    for keyword in SECURITY_SERVICE_KEYWORDS:
        if keyword in lowered:
            if any(warning in lowered for warning in AS_NEEDED_WARNING_KEYWORDS):
                return "As-needed security services"
            return "Security services"
    return None


def extract_location(text: str) -> str | None:
    match = re.search(
        r"(?:location|place of performance|work location|county|city)\s*[:#-]\s*([^.;\n\r]{3,80})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return normalize_space(match.group(1)).strip(" ,")
    return None


def extract_estimated_value(text: str) -> float | None:
    match = re.search(
        r"(?:estimated value|budget|contract value|not to exceed)\s*[:#-]?\s*\$?\s*([0-9][0-9,]*(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def confidence_from_text(title: str, text: str, document_urls: list[str]) -> float:
    haystack = f"{title} {text}".lower()
    score = 0.2
    if any(token in haystack for token in ("rfp", "rfq", "ifb", "itb", "bid", "solicitation")):
        score += 0.25
    if extract_solicitation_number(haystack):
        score += 0.15
    if extract_due_date(haystack):
        score += 0.15
    if extract_service_type(haystack):
        score += 0.15
    if document_urls:
        score += 0.1
    return min(round(score, 2), 1.0)


def _date_after_keywords(text: str, keywords: tuple[str, ...]) -> datetime | None:
    for keyword in keywords:
        pattern = rf"{re.escape(keyword)}[^A-Za-z0-9]{{0,20}}({_combined_date_pattern()})"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            parsed = parse_date(match.group(1))
            if parsed:
                return parsed
    # No global fallback: returning the first unrelated date anywhere in the
    # text fabricates due/pre-bid/Q&A dates from dates that have nothing to do
    # with the deadline. If no keyword-anchored date is found, return None.
    return None


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = normalize_space(value).replace(",", "")
    formats = (
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%y %I:%M %p",
        "%m/%d/%Y %H:%M",
        "%m/%d/%y %H:%M",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%B %d %Y",
        "%b %d %Y",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        if not _is_plausible_bid_year(parsed.year):
            return None
        return parsed
    return None


def _is_plausible_bid_year(year: int) -> bool:
    """Reject dates outside a sane bid window.

    A bid solicitation's relevant dates fall near the present. Years before
    last year or more than ~5 years out are implausible (and also defuse a
    2-digit %y year mapping to 19xx, e.g. "01/15/70" -> 1970).
    """
    today = datetime.now(UTC).replace(tzinfo=None)
    return (today.year - 1) <= year <= (today.year + 5)


def _combined_date_pattern() -> str:
    return "|".join(DATE_PATTERNS)

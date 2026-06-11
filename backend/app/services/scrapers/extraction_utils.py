import re
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

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
}

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


def extract_document_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        url = urljoin(base_url, str(anchor.get("href") or "").strip())
        if not is_document_url(url) or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def is_document_url(url: str) -> bool:
    parsed = urlparse(url)
    suffix = Path(unquote(parsed.path)).suffix.lower()
    return suffix in DOCUMENT_EXTENSIONS


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
        r"(?:solicitation|bid|rfp|rfq|ifb|itb|project)\s*(?:number|no\.?|#)?\s*[:#-]\s*([A-Za-z0-9][A-Za-z0-9._/-]{2,})",
        r"\b(?:RFP|RFQ|IFB|ITB)\s*[-#:]?\s*([A-Za-z0-9][A-Za-z0-9._/-]{2,})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .;,")
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
        r"(?:estimated value|budget|contract value|not to exceed)\s*[:#-]?\s*\$?\s*([0-9][0-9,]*(?:\.\d{2})?)",
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
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            parsed = parse_date(match.group(0))
            if parsed:
                return parsed
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
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _combined_date_pattern() -> str:
    return "|".join(DATE_PATTERNS)

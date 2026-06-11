"""
Deterministic candidate quality filtering for the public scraper.

Generic government pages produce many page-chrome / navigation / footer
links that are not real opportunities. These heuristics score each
candidate and decide whether it is worth saving as an Opportunity.

No network access, no AI — pure string heuristics.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

from app.services.scrapers.extraction_utils import (
    SECURITY_SERVICE_KEYWORDS,
    extract_due_date,
    extract_solicitation_number,
    normalize_space,
)

# Default minimum score a candidate must reach to be saved.
QUALITY_THRESHOLD = 0.45

PROCUREMENT_KEYWORDS = (
    "bid",
    "rfp",
    "rfq",
    "ifb",
    "itb",
    "solicitation",
    "proposal",
    "quote",
    "tender",
    "contract",
    "procurement",
    "opportunity",
    "opportunities",
)

EXTRA_SECURITY_KEYWORDS = ("armed", "unarmed", "guard", "security")

URL_GOOD_TOKENS = (
    "bids",
    "bid",
    "solicitation",
    "solicitations",
    "procurement",
    "purchasing",
    "opportunit",
    "contract",
    "rfp",
    "rfq",
    "ifb",
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
    "nextdoor.com",
    "tiktok.com",
)

# Titles that are never opportunities. Compared case-insensitively after
# normalizing whitespace and stripping trailing punctuation.
HARD_REJECT_TITLES = frozenset(
    {
        "home",
        "search",
        "contact",
        "contacts",
        "contact us",
        "careers",
        "jobs",
        "news",
        "events",
        "calendar",
        "facebook",
        "twitter",
        "linkedin",
        "youtube",
        "instagram",
        "subscribe",
        "privacy policy",
        "privacy",
        "terms of use",
        "terms",
        "terms and conditions",
        "accessibility",
        "mobile main navigation",
        "main navigation",
        "navigation",
        "menu",
        "skip to main content",
        "skip to content",
        "departments",
        "services",
        "government",
        "business",
        "doing business",
        "residents",
        "visitors",
        "comptroller",
        "vendor registration",
        "purchasing home",
        "sitemap",
        "site map",
        "login",
        "log in",
        "sign in",
        "register",
        "faq",
        "faqs",
        "help",
        "about",
        "about us",
        "organizational chart",
        "public guardian",
        "community services",
    }
)

# Substrings that strongly indicate chrome/nav even inside longer titles.
CHROME_TERMS = (
    "navigation",
    "skip to",
    "privacy policy",
    "terms of use",
    "accessibility statement",
    "cookie",
    "subscribe to",
    "follow us",
    "social media",
    "back to top",
)


@dataclass
class CandidateQuality:
    score: float
    keep: bool
    reason: str | None  # populated when keep is False


def _normalize_title(title: str | None) -> str:
    return normalize_space(title or "").strip(" .:-|").lower()


def _is_social_or_contact_url(url: str | None) -> bool:
    if not url:
        return False
    lowered = url.lower()
    if lowered.startswith("mailto:") or lowered.startswith("tel:") or lowered.startswith("javascript:"):
        return True
    host = urlparse(lowered).netloc
    return any(domain in host for domain in SOCIAL_DOMAINS)


def _is_homepage_only(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    return path == "" and not parsed.query


def assess_candidate(candidate, source_config=None, source_title: str | None = None) -> CandidateQuality:
    """Score a ScraperResult and decide whether to keep it."""
    title = candidate.title or ""
    norm_title = _normalize_title(title)
    title_lower = title.lower()
    text_lower = (candidate.raw_text or candidate.description or "").lower()
    combined = f"{title_lower} {text_lower}"
    url = candidate.detail_url or candidate.source_url or ""
    url_lower = url.lower()

    # --- Hard rejections (decided before scoring) ---
    if _is_social_or_contact_url(url):
        return CandidateQuality(0.0, False, "social/contact link")
    if norm_title in HARD_REJECT_TITLES:
        return CandidateQuality(0.0, False, "navigation/chrome title")
    if any(term in title_lower for term in CHROME_TERMS):
        return CandidateQuality(0.0, False, "chrome/footer text in title")
    if title_lower.startswith(("http://", "https://", "www.")):
        return CandidateQuality(0.0, False, "title is a raw URL")
    if len(norm_title) < 4:
        return CandidateQuality(0.0, False, "title too short")

    # --- Signal detection ---
    has_proc_in_title = any(kw in title_lower for kw in PROCUREMENT_KEYWORDS)
    has_proc_anywhere = any(kw in combined for kw in PROCUREMENT_KEYWORDS)
    has_security = any(kw in combined for kw in SECURITY_SERVICE_KEYWORDS) or any(
        kw in combined for kw in EXTRA_SECURITY_KEYWORDS
    )
    has_solicitation_number = bool(
        candidate.solicitation_number or extract_solicitation_number(combined)
    )
    has_due_date = bool(candidate.due_date or extract_due_date(combined))
    url_good = any(token in url_lower for token in URL_GOOD_TOKENS)
    has_docs = bool(candidate.document_urls)
    word_count = len(norm_title.split())

    # --- Positive signals ---
    score = 0.0
    if has_proc_in_title:
        score += 0.4
    elif has_proc_anywhere:
        score += 0.2
    if has_security:
        score += 0.3
    if has_solicitation_number:
        score += 0.25
    if has_due_date:
        score += 0.2
    if url_good:
        score += 0.2
    if has_docs:
        score += 0.1
    if word_count >= 4:
        score += 0.1

    # --- Negative signals ---
    if word_count < 2:
        score -= 0.25  # single-word nav link
    if _is_homepage_only(url) and not has_proc_in_title:
        score -= 0.25
    if not (has_proc_anywhere or has_security or has_solicitation_number or has_due_date):
        score -= 0.3  # no procurement signal anywhere
    if source_title and norm_title == _normalize_title(source_title):
        score -= 0.3  # duplicate of the source/landing page title

    score = round(max(0.0, min(score, 1.0)), 2)

    if score < QUALITY_THRESHOLD:
        if not (has_proc_anywhere or has_security):
            reason = "no procurement keywords"
        elif word_count < 2:
            reason = "single-word nav link"
        else:
            reason = "below quality threshold"
        return CandidateQuality(score, False, reason)

    return CandidateQuality(score, True, None)

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from sqlmodel import Session, select

from app.db import engine
from app.models import Opportunity


SCRAPER_USER_AGENT = "RFP-BidOS Public Scraper/0.1 (+single-page review)"
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
SECURITY_KEYWORDS = ("security", "guard", "patrol", "armed", "unarmed")


def fetch_public_page(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": SCRAPER_USER_AGENT},
        timeout=20,
    )
    response.raise_for_status()
    return response.text


def extract_candidate_links(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[dict] = []
    seen_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        title = " ".join(anchor.get_text(" ", strip=True).split())
        href = str(anchor.get("href") or "").strip()
        if not title and not href:
            continue

        url = urljoin(base_url, href)
        haystack = f"{title} {url}".lower()
        matched_terms = [keyword for keyword in BID_KEYWORDS if keyword in haystack]
        if not matched_terms or url in seen_urls:
            continue

        seen_urls.add(url)
        classification = classify_candidate_link(title or url, url)
        candidates.append(
            {
                "title": title or url,
                "url": url,
                "source": base_url,
                "source_url": url,
                "initial_match_reason": classification["initial_match_reason"],
                "security_likelihood": classification["security_likelihood"],
            }
        )

    return candidates


def classify_candidate_link(title: str, url: str) -> dict:
    haystack = f"{title} {url}".lower()
    matched_terms = [keyword for keyword in BID_KEYWORDS if keyword in haystack]
    security_terms = [keyword for keyword in SECURITY_KEYWORDS if keyword in haystack]

    if security_terms:
        security_likelihood = "high"
    elif any(keyword in matched_terms for keyword in ("rfp", "bid", "solicitation", "procurement")):
        security_likelihood = "unknown"
    else:
        security_likelihood = "low"

    reason = (
        f"Matched keywords: {', '.join(matched_terms[:5])}"
        if matched_terms
        else "No procurement keywords matched"
    )

    return {
        "initial_match_reason": reason,
        "security_likelihood": security_likelihood,
    }


def scrape_source(source_config: Any) -> dict:
    result = {
        "records_found": 0,
        "created_count": 0,
        "skipped_duplicates": 0,
        "errors": [],
    }

    if not getattr(source_config, "enabled", False):
        result["errors"].append("Source is disabled")
        return result

    base_url = getattr(source_config, "base_url", None)
    if not base_url:
        result["errors"].append("Source has no base_url")
        return result

    try:
        html = fetch_public_page(base_url)
        candidates = extract_candidate_links(html, base_url)
    except requests.RequestException as exc:
        result["errors"].append(str(exc))
        return result

    result["records_found"] = len(candidates)

    with Session(engine) as session:
        for candidate in candidates:
            existing = session.exec(
                select(Opportunity).where(Opportunity.source_url == candidate["url"])
            ).first()
            if existing is not None:
                result["skipped_duplicates"] += 1
                continue

            opportunity = Opportunity(
                title=candidate["title"],
                agency=source_config.name,
                source=source_config.name,
                source_url=candidate["url"],
                portal_url=base_url,
                status="Needs Review",
                bid_decision="Needs Review",
                service_type=_guess_service_type(candidate),
                updated_at=_utc_now(),
            )
            session.add(opportunity)
            result["created_count"] += 1

        session.commit()

    return result


def _guess_service_type(candidate: dict) -> str | None:
    haystack = f"{candidate.get('title', '')} {candidate.get('url', '')}".lower()
    if any(keyword in haystack for keyword in SECURITY_KEYWORDS):
        return "Security services"
    return None


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)

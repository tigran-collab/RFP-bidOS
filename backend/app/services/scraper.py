from datetime import UTC, datetime
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from sqlmodel import Session, select

from app.db import engine
from app.models import Document, Opportunity
from app.services.scrapers import (
    AuthenticatedBrowserAdapter,
    GenericPublicAdapter,
    PlanetBidsAuthAdapter,
    ScraperResult,
    SocrataAdapter,
)
from app.services.scrapers.extraction_utils import (
    extract_document_candidates,
    is_document_url,
)
from app.services.scrapers.quality import assess_candidate
from app.services.scrapers.keywords import score_candidate_relevance

DISCOVERY_USER_AGENT = "RFP-BidOS Public Scraper/0.2 (+document-discovery)"

AUTH_REQUIRED_MESSAGE = (
    "This source requires credentials. Authenticated scraping is not enabled in this phase."
)


def preview_source(
    source_config, detail_limit: int | None = None, include_filtered: bool = False
) -> dict:
    result = _empty_result()
    skip_message = _auth_skip_message(source_config)
    if skip_message:
        result["errors"].append(skip_message)
        return result

    candidates = _scrape_candidates(source_config, result, detail_limit=detail_limit)
    quality_kept, quality_filtered, reasons = _filter_candidates(candidates, source_config)
    kept, relevance_filtered = _apply_relevance_filter(quality_kept)
    relevance_counts = _relevance_counts(kept, relevance_filtered)

    result["total_candidates_found"] = len(candidates)
    result["candidates_found"] = len(candidates)
    result["candidates_kept"] = len(kept)
    result["candidates_filtered"] = len(quality_filtered)
    result["candidates_filtered_quality"] = len(quality_filtered)
    result["candidates_filtered_relevance"] = len(relevance_filtered)
    result["filter_reasons"] = reasons
    result["records_found"] = len(kept)
    result.update(relevance_counts)
    shown = kept + quality_filtered + relevance_filtered if include_filtered else kept
    result["candidates"] = [_candidate_to_dict(candidate) for candidate in shown]
    return result


def scrape_source(source_config) -> dict:
    result = _empty_result()

    if not getattr(source_config, "enabled", False):
        result["errors"].append("Source is disabled")
        return result

    skip_message = _auth_skip_message(source_config)
    if skip_message:
        result["errors"].append(skip_message)
        return result

    candidates = _scrape_candidates(source_config, result)
    quality_kept, quality_filtered, reasons = _filter_candidates(candidates, source_config)
    kept, relevance_filtered = _apply_relevance_filter(quality_kept)
    relevance_counts = _relevance_counts(kept, relevance_filtered)
    result["total_candidates_found"] = len(candidates)
    result["candidates_found"] = len(candidates)
    result["candidates_kept"] = len(kept)
    result["candidates_filtered"] = len(quality_filtered)
    result["candidates_filtered_quality"] = len(quality_filtered)
    result["candidates_filtered_relevance"] = len(relevance_filtered)
    result["filter_reasons"] = reasons
    result["records_found"] = len(kept)
    result.update(relevance_counts)

    with Session(engine) as session:
        for candidate in kept:
            existing = _find_existing_opportunity(session, candidate, source_config)
            if existing is None:
                opportunity = _create_opportunity(candidate, source_config)
                session.add(opportunity)
                session.flush()
                doc_counts = _attach_document_urls(session, opportunity, candidate.document_urls)
                result["documents_discovered"] += doc_counts["discovered"]
                result["documents_skipped"] += doc_counts["skipped"]
                result["created_count"] += 1
                continue

            updated = _update_opportunity_if_safe(existing, candidate)
            doc_counts = _attach_document_urls(session, existing, candidate.document_urls)
            result["documents_discovered"] += doc_counts["discovered"]
            result["documents_skipped"] += doc_counts["skipped"]
            if updated:
                existing.updated_at = _utc_now()
                session.add(existing)
                result["updated_count"] += 1
            else:
                result["skipped_duplicates"] += 1

        session.commit()

    return result


def _scrape_candidates(
    source_config, result: dict, detail_limit: int | None = None
) -> list[ScraperResult]:
    base_url = getattr(source_config, "base_url", None)
    if not base_url:
        result["errors"].append("Source has no base_url")
        return []

    adapter = _select_adapter(source_config, detail_limit)
    if adapter is None or not adapter.can_handle(source_config):
        result["errors"].append(f"Unsupported source type: {source_config.source_type}")
        return []

    try:
        candidates = adapter.scrape(source_config)
        result["diagnostics"].extend(getattr(adapter, "diagnostics", []) or [])
        return candidates
    except requests.RequestException as exc:
        result["errors"].append(str(exc))
    except Exception as exc:
        result["errors"].append(f"Scraper failed: {exc}")
    return []


def _select_adapter(source_config, detail_limit: int | None):
    """Pick the scraper adapter for a source by its source_type.

    Defaults to the generic public-HTML adapter so existing public_page,
    table_listing, and portal_listing sources keep working unchanged.
    """
    source_type = (getattr(source_config, "source_type", "") or "").lower()
    if source_type == "socrata":
        return SocrataAdapter()
    if source_type == "planetbids":
        return PlanetBidsAuthAdapter()
    if source_type == "authenticated_browser":
        return AuthenticatedBrowserAdapter()
    if detail_limit is not None:
        return GenericPublicAdapter(detail_limit=detail_limit)
    return GenericPublicAdapter()


def discover_documents_for_opportunity(opportunity_id: int, session) -> dict:
    """Fetch an opportunity's detail/source page and discover document links.

    Saves new pending Document records for direct file URLs (deduped by URL).
    Does not download — that remains a separate step.
    """
    summary = {
        "documents_discovered": 0,
        "documents_skipped": 0,
        "candidates": [],
        "errors": [],
    }
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        summary["errors"].append("Opportunity not found")
        return summary

    page_url = opportunity.source_url or opportunity.portal_url
    if not page_url:
        summary["errors"].append("Opportunity has no source_url or portal_url")
        return summary

    # If the opportunity URL is itself a direct file, nothing to crawl.
    if is_document_url(page_url):
        summary["errors"].append("Opportunity URL is a direct document, not a page to crawl")
        return summary

    try:
        response = requests.get(
            page_url,
            headers={"User-Agent": DISCOVERY_USER_AGENT},
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        summary["errors"].append(str(exc))
        return summary

    candidates = extract_document_candidates(response.text, page_url)
    summary["candidates"] = candidates
    file_urls = [c["url"] for c in candidates if is_document_url(c["url"])]

    counts = _attach_document_urls(session, opportunity, file_urls)
    session.commit()
    summary["documents_discovered"] = counts["discovered"]
    summary["documents_skipped"] = counts["skipped"]
    return summary


def _filter_candidates(
    candidates: list[ScraperResult], source_config
) -> tuple[list[ScraperResult], list[ScraperResult], dict]:
    """Split candidates into kept/filtered by quality heuristics.

    Returns (kept, filtered, reason_counts). Each candidate's quality_score
    is populated for transparency.
    """
    source_title = getattr(source_config, "name", None)
    kept: list[ScraperResult] = []
    filtered: list[ScraperResult] = []
    reasons: dict[str, int] = {}
    for candidate in candidates:
        assessment = assess_candidate(candidate, source_config, source_title=source_title)
        candidate.quality_score = assessment.score
        if assessment.keep:
            kept.append(candidate)
        else:
            filtered.append(candidate)
            reason = assessment.reason or "below quality threshold"
            reasons[reason] = reasons.get(reason, 0) + 1
    return kept, filtered, reasons


def _apply_relevance_filter(
    candidates: list[ScraperResult],
) -> tuple[list[ScraperResult], list[ScraperResult]]:
    kept: list[ScraperResult] = []
    filtered: list[ScraperResult] = []
    for candidate in candidates:
        relevance = score_candidate_relevance(candidate)
        _set_candidate_relevance(candidate, relevance)
        if relevance["relevance_decision"] in {"Relevant", "Maybe Relevant"}:
            kept.append(candidate)
        else:
            filtered.append(candidate)
    return kept, filtered


def _set_candidate_relevance(candidate: ScraperResult, relevance: dict) -> None:
    candidate.relevance_score = relevance["relevance_score"]
    candidate.keyword_matches = relevance["keyword_matches"]
    candidate.negative_matches = relevance["negative_matches"]
    candidate.as_needed_matches = relevance["as_needed_matches"]
    candidate.relevance_decision = relevance["relevance_decision"]
    candidate.relevance_reason = relevance["relevance_reason"]


def _relevance_counts(
    kept: list[ScraperResult], filtered: list[ScraperResult]
) -> dict[str, int]:
    all_scored = kept + filtered
    return {
        "candidates_saved": len(kept),
        "relevant": sum(1 for c in all_scored if c.relevance_decision == "Relevant"),
        "maybe_relevant": sum(
            1 for c in all_scored if c.relevance_decision == "Maybe Relevant"
        ),
        "not_relevant": sum(
            1 for c in all_scored if c.relevance_decision == "Not Relevant"
        ),
        "as_needed_warning_count": sum(1 for c in all_scored if c.as_needed_matches),
    }


def _auth_skip_message(source_config) -> str | None:
    # PlanetBids and the generic authenticated_browser adapter use assisted-login
    # authenticated scraping: their adapters read the bids list through a
    # human-established, persisted browser session and degrade gracefully
    # (returns [] + a diagnostic) when the session is missing/expired or
    # Playwright is absent. They self-gate, so they are NOT skipped here even
    # though they require credentials.
    source_type = (getattr(source_config, "source_type", "") or "").lower()
    if source_type in ("planetbids", "authenticated_browser"):
        return None

    requires_credentials = bool(getattr(source_config, "requires_credentials", False))
    name = (getattr(source_config, "name", "") or "").lower()
    base_url = (getattr(source_config, "base_url", "") or "").lower()
    is_bidnet = "bidnet" in name or "bidnet" in base_url
    if requires_credentials or is_bidnet and getattr(source_config, "login_url", None):
        return AUTH_REQUIRED_MESSAGE
    return None


def _find_existing_opportunity(session: Session, candidate: ScraperResult, source_config):
    urls = {candidate.source_url, candidate.detail_url}
    urls.discard(None)
    for url in urls:
        existing = session.exec(select(Opportunity).where(Opportunity.source_url == url)).first()
        if existing is not None:
            return existing

    if candidate.solicitation_number:
        # Solicitation numbers are only unique within one agency's portal, so
        # scope the match to this source or two agencies reusing a number
        # (e.g. "RFP-2026-01") would collapse into one record.
        existing = session.exec(
            select(Opportunity).where(
                Opportunity.solicitation_number == candidate.solicitation_number,
                Opportunity.source == getattr(source_config, "name", None),
            )
        ).first()
        if existing is not None:
            return existing

    existing = session.exec(
        select(Opportunity).where(
            Opportunity.title == candidate.title,
            Opportunity.source == getattr(source_config, "name", None),
        )
    ).first()
    return existing


def _create_opportunity(candidate: ScraperResult, source_config) -> Opportunity:
    warning = _as_needed_warning_text()
    return Opportunity(
        title=candidate.title,
        agency=candidate.agency or getattr(source_config, "name", None),
        solicitation_number=candidate.solicitation_number,
        source=getattr(source_config, "name", None),
        source_url=candidate.detail_url or candidate.source_url,
        portal_url=candidate.portal_url or getattr(source_config, "base_url", None),
        location=candidate.location,
        due_date=candidate.due_date,
        pre_bid_date=candidate.pre_bid_date,
        q_and_a_deadline=candidate.q_and_a_deadline,
        service_type=candidate.service_type,
        contract_type=candidate.contract_type,
        estimated_value=candidate.estimated_value,
        status="Needs Review",
        bid_decision="Needs Review",
        review_status=(
            "Needs Review"
            if candidate.relevance_decision == "Maybe Relevant"
            else "New"
        ),
        next_action="Manual Review" if candidate.as_needed_matches else None,
        notes=warning if candidate.as_needed_matches else None,
        relevance_score=candidate.relevance_score,
        relevance_decision=candidate.relevance_decision,
        keyword_matches_json=json.dumps(candidate.keyword_matches),
        negative_matches_json=json.dumps(candidate.negative_matches),
        as_needed_warning=bool(candidate.as_needed_matches),
        relevance_reason=candidate.relevance_reason,
        updated_at=_utc_now(),
    )


def _update_opportunity_if_safe(opportunity: Opportunity, candidate: ScraperResult) -> bool:
    updated = False
    safe_fields = (
        "agency",
        "solicitation_number",
        "portal_url",
        "location",
        "due_date",
        "pre_bid_date",
        "q_and_a_deadline",
        "service_type",
        "contract_type",
        "estimated_value",
    )
    for field in safe_fields:
        if getattr(opportunity, field) in (None, "") and getattr(candidate, field) not in (None, ""):
            setattr(opportunity, field, getattr(candidate, field))
            updated = True
    if not opportunity.source_url and (candidate.detail_url or candidate.source_url):
        opportunity.source_url = candidate.detail_url or candidate.source_url
        updated = True
    relevance_updated = _update_relevance_metadata(opportunity, candidate)
    updated = updated or relevance_updated
    return updated


def _update_relevance_metadata(opportunity: Opportunity, candidate: ScraperResult) -> bool:
    updates = {
        "relevance_score": candidate.relevance_score,
        "relevance_decision": candidate.relevance_decision,
        "keyword_matches_json": json.dumps(candidate.keyword_matches),
        "negative_matches_json": json.dumps(candidate.negative_matches),
        "as_needed_warning": bool(candidate.as_needed_matches),
        "relevance_reason": candidate.relevance_reason,
    }
    changed = False
    for field, value in updates.items():
        if getattr(opportunity, field) != value:
            setattr(opportunity, field, value)
            changed = True

    if candidate.as_needed_matches:
        warning = _as_needed_warning_text()
        if not opportunity.next_action:
            opportunity.next_action = "Manual Review"
            changed = True
        if warning not in (opportunity.notes or ""):
            opportunity.notes = f"{opportunity.notes}\n{warning}".strip() if opportunity.notes else warning
            changed = True
    return changed


def _as_needed_warning_text() -> str:
    return "As-needed / no-guaranteed-minimum language detected. Review before pursuing."


def _attach_document_urls(
    session: Session, opportunity: Opportunity, document_urls: list[str]
) -> dict:
    """Create pending Document records for discovered URLs, deduped by URL.

    Returns {"discovered": n, "skipped": n}.
    """
    counts = {"discovered": 0, "skipped": 0}
    if opportunity.id is None:
        return counts
    for url in document_urls:
        existing = session.exec(select(Document).where(Document.source_url == url)).first()
        if existing is not None:
            counts["skipped"] += 1
            continue
        document = Document(
            opportunity_id=opportunity.id,
            filename=_filename_from_url(url),
            path="",
            file_type=Path(urlparse(url).path).suffix.lower().lstrip(".") or None,
            source_url=url,
            parsed_status="Not Downloaded",
        )
        session.add(document)
        counts["discovered"] += 1
    return counts


def _candidate_to_dict(candidate: ScraperResult) -> dict:
    return {
        "title": candidate.title,
        "agency": candidate.agency,
        "solicitation_number": candidate.solicitation_number,
        "source_url": candidate.source_url,
        "detail_url": candidate.detail_url,
        "portal_url": candidate.portal_url,
        "location": candidate.location,
        "due_date": candidate.due_date.isoformat() if candidate.due_date else None,
        "pre_bid_date": candidate.pre_bid_date.isoformat() if candidate.pre_bid_date else None,
        "q_and_a_deadline": (
            candidate.q_and_a_deadline.isoformat() if candidate.q_and_a_deadline else None
        ),
        "service_type": candidate.service_type,
        "contract_type": candidate.contract_type,
        "estimated_value": candidate.estimated_value,
        "description": candidate.description,
        "document_urls": candidate.document_urls,
        "document_count": len(candidate.document_urls),
        "document_candidates": candidate.document_candidates,
        "document_candidate_count": len(candidate.document_candidates),
        "confidence_score": candidate.confidence_score,
        "quality_score": candidate.quality_score,
        "relevance_score": candidate.relevance_score,
        "keyword_matches": candidate.keyword_matches,
        "negative_matches": candidate.negative_matches,
        "as_needed_matches": candidate.as_needed_matches,
        "as_needed_warning": bool(candidate.as_needed_matches),
        "relevance_decision": candidate.relevance_decision,
        "relevance_reason": candidate.relevance_reason,
    }


def _filename_from_url(url: str) -> str:
    name = Path(unquote(urlparse(url).path)).name
    return name or "document"


def _empty_result() -> dict:
    return {
        "records_found": 0,
        "total_candidates_found": 0,
        "candidates_found": 0,
        "candidates_kept": 0,
        "candidates_filtered": 0,
        "candidates_filtered_quality": 0,
        "candidates_filtered_relevance": 0,
        "candidates_saved": 0,
        "relevant": 0,
        "maybe_relevant": 0,
        "not_relevant": 0,
        "as_needed_warning_count": 0,
        "filter_reasons": {},
        "created_count": 0,
        "updated_count": 0,
        "skipped_duplicates": 0,
        "documents_discovered": 0,
        "documents_skipped": 0,
        "errors": [],
        "diagnostics": [],
        "candidates": [],
    }


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)

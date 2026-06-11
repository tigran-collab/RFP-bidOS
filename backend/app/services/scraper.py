from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from sqlmodel import Session, select

from app.db import engine
from app.models import Document, Opportunity
from app.services.scrapers import GenericPublicAdapter, ScraperResult
from app.services.scrapers.quality import assess_candidate

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
    kept, filtered, reasons = _filter_candidates(candidates, source_config)

    result["total_candidates_found"] = len(candidates)
    result["candidates_kept"] = len(kept)
    result["candidates_filtered"] = len(filtered)
    result["filter_reasons"] = reasons
    result["records_found"] = len(kept)
    shown = kept + filtered if include_filtered else kept
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
    kept, filtered, reasons = _filter_candidates(candidates, source_config)
    result["total_candidates_found"] = len(candidates)
    result["candidates_kept"] = len(kept)
    result["candidates_filtered"] = len(filtered)
    result["filter_reasons"] = reasons
    result["records_found"] = len(kept)

    with Session(engine) as session:
        for candidate in kept:
            existing = _find_existing_opportunity(session, candidate, source_config)
            if existing is None:
                opportunity = _create_opportunity(candidate, source_config)
                session.add(opportunity)
                session.flush()
                _attach_document_urls(session, opportunity, candidate.document_urls)
                result["created_count"] += 1
                continue

            updated = _update_opportunity_if_safe(existing, candidate)
            _attach_document_urls(session, existing, candidate.document_urls)
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

    adapter = (
        GenericPublicAdapter(detail_limit=detail_limit)
        if detail_limit is not None
        else GenericPublicAdapter()
    )
    if not adapter.can_handle(source_config):
        result["errors"].append(f"Unsupported source type: {source_config.source_type}")
        return []

    try:
        return adapter.scrape(source_config)
    except requests.RequestException as exc:
        result["errors"].append(str(exc))
    except Exception as exc:
        result["errors"].append(f"Scraper failed: {exc}")
    return []


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


def _auth_skip_message(source_config) -> str | None:
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
        existing = session.exec(
            select(Opportunity).where(
                Opportunity.solicitation_number == candidate.solicitation_number
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
    return updated


def _attach_document_urls(session: Session, opportunity: Opportunity, document_urls: list[str]) -> None:
    if opportunity.id is None:
        return
    for url in document_urls:
        existing = session.exec(select(Document).where(Document.source_url == url)).first()
        if existing is not None:
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
        "confidence_score": candidate.confidence_score,
        "quality_score": candidate.quality_score,
    }


def _filename_from_url(url: str) -> str:
    name = Path(unquote(urlparse(url).path)).name
    return name or "document"


def _empty_result() -> dict:
    return {
        "records_found": 0,
        "total_candidates_found": 0,
        "candidates_kept": 0,
        "candidates_filtered": 0,
        "filter_reasons": {},
        "created_count": 0,
        "updated_count": 0,
        "skipped_duplicates": 0,
        "errors": [],
        "candidates": [],
    }


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)

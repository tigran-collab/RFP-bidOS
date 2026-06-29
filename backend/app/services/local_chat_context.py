import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.models import Document, Opportunity, Requirement

DEFAULT_OPPORTUNITY_LIMIT = 25
DEFAULT_CONTEXT_LIMIT = 25
MAX_LIMIT = 50
MAX_REQUIREMENTS_PER_OPPORTUNITY = 5
MAX_DOCUMENT_SNIPPETS = 3
MAX_DOCUMENT_SNIPPET_CHARS = 1000
MAX_CONTEXT_CHARS = 16000

AUTO_APP_TERMS = (
    "all opportunities",
    "currently",
    "presently",
    "right now",
    "top opportunities",
    "best security",
    "best pursuits",
    "what should i work on",
    "work on next",
    "no-bid",
    "no bid",
    "pursue",
    "watchlist",
    "as-needed",
    "as needed",
    "risky",
    "missing deadlines",
    "document review",
    "mandatory pre-bid",
)
AUTO_DEADLINE_TERMS = ("due soon", "deadlines", "coming up", "missing deadline")
AUTO_PURSUIT_TERMS = (
    "worth pursuing",
    "best pursuits",
    "top 5",
    "top five",
    "bid score",
    "work on next",
)


def build_app_overview_context(session: Session, limit: int = DEFAULT_OPPORTUNITY_LIMIT) -> dict:
    all_opportunities = list(session.exec(select(Opportunity)).all())
    opportunities = sorted(all_opportunities, key=_action_sort_key)[
        :_bounded_limit(limit, default=DEFAULT_OPPORTUNITY_LIMIT)
    ]
    docs_by_opp, reqs_by_opp = _rollups(session)
    compact = [_compact_opportunity(opp, docs_by_opp, reqs_by_opp) for opp in opportunities]
    no_bid = [
        opp
        for opp in all_opportunities
        if (opp.review_status or "") == "Do Not Pursue" or (opp.bid_decision or "").lower() == "no bid"
    ]
    as_needed = [opp for opp in all_opportunities if opp.as_needed_warning]
    missing_deadline = [
        opp
        for opp in all_opportunities
        if not opp.due_date or opp.deadline_risk == "Missing Deadline"
    ]
    mandatory_pre_bid = [opp for opp in all_opportunities if opp.pre_bid_mandatory]
    needs_document_review = [
        opp
        for opp in all_opportunities
        if _needs_document_review(opp, docs_by_opp.get(opp.id or 0, []))
    ]
    return _guard_context(
        {
            "mode": "app_overview",
            "read_only": True,
            "opportunities": compact,
            "opportunity_count": len(all_opportunities),
            "opportunities_limited_to": len(compact),
            "included_requirements": False,
            "included_documents": False,
            "counts": _counts(compact),
            "no_bid_opportunities": [
                _compact_opportunity(opp, docs_by_opp, reqs_by_opp)
                for opp in sorted(no_bid, key=_action_sort_key)[:10]
            ],
            "as_needed_risky_opportunities": [
                _compact_opportunity(opp, docs_by_opp, reqs_by_opp)
                for opp in sorted(as_needed, key=_action_sort_key)[:10]
            ],
            "missing_deadline_opportunities": [
                _compact_opportunity(opp, docs_by_opp, reqs_by_opp)
                for opp in sorted(missing_deadline, key=_action_sort_key)[:10]
            ],
            "mandatory_pre_bid_opportunities": [
                _compact_opportunity(opp, docs_by_opp, reqs_by_opp)
                for opp in sorted(mandatory_pre_bid, key=_action_sort_key)[:10]
            ],
            "needs_document_review": [
                _compact_opportunity(opp, docs_by_opp, reqs_by_opp)
                for opp in sorted(needs_document_review, key=_action_sort_key)[:10]
            ],
        }
    )


def build_opportunity_context(
    session: Session,
    opportunity_id: int,
    include_requirements: bool = True,
    include_logistics: bool = True,
    include_documents: bool = False,
) -> dict:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return {
            "mode": "opportunity",
            "read_only": True,
            "opportunity_count": 0,
            "included_requirements": False,
            "included_documents": False,
            "error": f"Opportunity not found: {opportunity_id}",
        }

    docs_by_opp, reqs_by_opp = _rollups(session)
    context: dict[str, Any] = {
        "mode": "opportunity",
        "read_only": True,
        "opportunity": _compact_opportunity(opportunity, docs_by_opp, reqs_by_opp),
        "opportunity_count": 1,
        "included_requirements": include_requirements,
        "included_documents": include_documents,
    }
    if include_logistics:
        context["logistics"] = _logistics_fields(opportunity)
    if include_requirements:
        requirements = reqs_by_opp.get(opportunity.id or 0, [])[:MAX_REQUIREMENTS_PER_OPPORTUNITY]
        context["requirements"] = [_requirement_summary(req) for req in requirements]
        context["requirements_limited_to"] = MAX_REQUIREMENTS_PER_OPPORTUNITY
    if include_documents:
        documents = docs_by_opp.get(opportunity.id or 0, [])[:MAX_DOCUMENT_SNIPPETS]
        context["documents"] = [_document_summary(doc, include_snippet=True) for doc in documents]
        context["document_snippets_limited_to"] = MAX_DOCUMENT_SNIPPETS
    return _guard_context(context)


def build_deadline_context(
    session: Session,
    days: int = 30,
    limit: int = DEFAULT_CONTEXT_LIMIT,
) -> dict:
    now = _utc_now()
    window_end = now + timedelta(days=max(1, days))
    opportunities = list(session.exec(select(Opportunity)).all())
    docs_by_opp, reqs_by_opp = _rollups(session)
    upcoming = [
        opp
        for opp in opportunities
        if opp.due_date and now <= _naive(opp.due_date) <= window_end
    ]
    missing = [
        opp
        for opp in opportunities
        if not opp.due_date or opp.deadline_risk == "Missing Deadline"
    ]
    upcoming.sort(key=lambda opp: to_naive_utc(opp.due_date) if opp.due_date else datetime.max)
    missing.sort(key=_action_sort_key)
    upcoming_context = [
        _compact_opportunity(opp, docs_by_opp, reqs_by_opp)
        for opp in upcoming[:_bounded_limit(limit)]
    ]
    missing_context = [
        _compact_opportunity(opp, docs_by_opp, reqs_by_opp)
        for opp in missing[:_bounded_limit(limit)]
    ]
    return _guard_context(
        {
            "mode": "deadlines",
            "read_only": True,
            "days": days,
            "upcoming_deadlines": upcoming_context,
            "missing_deadlines": missing_context,
            "opportunity_count": len(upcoming_context) + len(missing_context),
            "included_requirements": False,
            "included_documents": False,
        }
    )


def build_pursuit_context(session: Session, limit: int = DEFAULT_CONTEXT_LIMIT) -> dict:
    opportunities = list(session.exec(select(Opportunity)).all())
    docs_by_opp, reqs_by_opp = _rollups(session)
    candidates = [
        opp
        for opp in opportunities
        if (opp.review_status or "New") not in {"Archived", "Do Not Pursue"}
    ]
    candidates.sort(key=_action_sort_key)
    compact = [
        _compact_opportunity(opp, docs_by_opp, reqs_by_opp)
        for opp in candidates[:_bounded_limit(limit)]
    ]
    return _guard_context(
        {
            "mode": "pursuit",
            "read_only": True,
            "opportunities": compact,
            "opportunity_count": len(compact),
            "included_requirements": False,
            "included_documents": False,
            "ranking_note": (
                "Sorted by active review status, bid score, AI score, deadline presence, "
                "and upcoming due date. As-needed opportunities require extra caution."
            ),
        }
    )


def build_chat_context(
    session: Session,
    message: str,
    context_request: dict | None = None,
) -> dict:
    request = context_request or {}
    mode = request.get("mode") or "auto"
    if mode == "auto":
        mode = infer_context_mode(message, request)

    limit = _bounded_limit(request.get("limit") or DEFAULT_CONTEXT_LIMIT)
    if mode == "opportunity" and request.get("opportunity_id"):
        return build_opportunity_context(
            session,
            int(request["opportunity_id"]),
            include_requirements=bool(request.get("include_requirements", True)),
            include_logistics=bool(request.get("include_logistics", True)),
            include_documents=bool(request.get("include_documents", False)),
        )
    if mode == "deadlines":
        return build_deadline_context(session, limit=limit)
    if mode == "pursuit":
        return build_pursuit_context(session, limit=limit)
    if mode == "app_overview":
        return build_app_overview_context(session, limit=request.get("limit") or DEFAULT_OPPORTUNITY_LIMIT)
    if request.get("opportunity_id"):
        return build_opportunity_context(
            session,
            int(request["opportunity_id"]),
            include_requirements=bool(request.get("include_requirements", True)),
            include_logistics=bool(request.get("include_logistics", True)),
            include_documents=bool(request.get("include_documents", False)),
        )
    return {
        "mode": mode,
        "read_only": True,
        "opportunity_count": 0,
        "included_requirements": False,
        "included_documents": False,
        "note": "No app context selected.",
    }


def context_summary(context: dict) -> dict:
    return {
        "mode": context.get("mode", "auto"),
        "opportunity_count": context.get("opportunity_count", 0),
        "included_requirements": bool(context.get("included_requirements")),
        "included_documents": bool(context.get("included_documents")),
        "read_only": True,
    }


def infer_context_mode(message: str, context_request: dict | None = None) -> str:
    request = context_request or {}
    if request.get("opportunity_id"):
        return "opportunity"
    text = message.lower()
    if any(term in text for term in AUTO_DEADLINE_TERMS):
        return "deadlines"
    if any(term in text for term in AUTO_PURSUIT_TERMS):
        return "pursuit"
    if any(term in text for term in AUTO_APP_TERMS):
        return "app_overview"
    return "app_overview"


def _rollups(session: Session) -> tuple[dict[int, list[Document]], dict[int, list[Requirement]]]:
    docs_by_opp: dict[int, list[Document]] = {}
    for document in session.exec(select(Document)).all():
        docs_by_opp.setdefault(document.opportunity_id, []).append(document)

    reqs_by_opp: dict[int, list[Requirement]] = {}
    for requirement in session.exec(select(Requirement)).all():
        reqs_by_opp.setdefault(requirement.opportunity_id, []).append(requirement)
    return docs_by_opp, reqs_by_opp


def _compact_opportunity(
    opportunity: Opportunity,
    docs_by_opp: dict[int, list[Document]],
    reqs_by_opp: dict[int, list[Requirement]],
) -> dict:
    docs = docs_by_opp.get(opportunity.id or 0, [])
    requirements = reqs_by_opp.get(opportunity.id or 0, [])
    return {
        "id": opportunity.id,
        "title": opportunity.title,
        "agency": opportunity.agency,
        "solicitation_number": opportunity.solicitation_number,
        "location": opportunity.location,
        "due_date": _jsonable(opportunity.due_date),
        "q_and_a_deadline": _jsonable(opportunity.q_and_a_deadline),
        "pre_bid_date": _jsonable(opportunity.pre_bid_date),
        "pre_bid_mandatory": opportunity.pre_bid_mandatory,
        "service_type": opportunity.service_type,
        "contract_type": opportunity.contract_type,
        "estimated_value": opportunity.estimated_value,
        "bid_score": opportunity.bid_score,
        "bid_decision": opportunity.bid_decision,
        "review_status": opportunity.review_status,
        "priority": opportunity.priority,
        "next_action": opportunity.next_action,
        "ai_recommendation": opportunity.ai_recommendation,
        "ai_score": opportunity.ai_score,
        "ai_risk_level": opportunity.ai_risk_level,
        "ai_reason": _truncate(opportunity.ai_reason or "", 400),
        "relevance_score": opportunity.relevance_score,
        "relevance_decision": opportunity.relevance_decision,
        "as_needed_warning": opportunity.as_needed_warning,
        "deadline_risk": opportunity.deadline_risk,
        "logistics_confidence_score": opportunity.logistics_confidence_score,
        "document_count": len(docs),
        "requirement_count": len(requirements),
    }


def _logistics_fields(opportunity: Opportunity) -> dict:
    return {
        "due_date": _jsonable(opportunity.due_date),
        "q_and_a_deadline": _jsonable(opportunity.q_and_a_deadline),
        "pre_bid_date": _jsonable(opportunity.pre_bid_date),
        "pre_bid_mandatory": opportunity.pre_bid_mandatory,
        "submission_method": opportunity.submission_method,
        "submission_portal": opportunity.submission_portal,
        "required_forms_summary": opportunity.required_forms_summary,
        "deadline_risk": opportunity.deadline_risk,
        "logistics_confidence_score": opportunity.logistics_confidence_score,
        "logistics_notes": opportunity.logistics_notes,
        "missing_logistics_flags": _missing_logistics_flags(opportunity, []),
    }


def _requirement_summary(requirement: Requirement) -> dict:
    return {
        "id": requirement.id,
        "type": requirement.requirement_type,
        "title": requirement.title,
        "mandatory": requirement.mandatory,
        "status": requirement.status,
        "risk": requirement.risk,
        "source_file": requirement.source_file,
        "source_page": requirement.source_page,
        "summary": _truncate(requirement.requirement_text or "", 600),
    }


def _document_summary(document: Document, include_snippet: bool = False) -> dict:
    return {
        "id": document.id,
        "filename": document.filename,
        "source_url": document.source_url,
        "parsed_status": document.parsed_status,
        "page_count": document.page_count,
        "snippet": _read_snippet(document.extracted_text_path) if include_snippet else "",
    }


def _missing_logistics_flags(opportunity: Opportunity, docs: list[Document]) -> list[str]:
    flags = []
    if not opportunity.due_date:
        flags.append("missing_due_date")
    if not opportunity.submission_method:
        flags.append("missing_submission_method")
    if opportunity.logistics_confidence_score is not None and opportunity.logistics_confidence_score < 0.6:
        flags.append("low_logistics_confidence")
    if opportunity.deadline_risk == "Missing Deadline":
        flags.append("deadline_risk_missing")
    if docs and not any(doc.parsed_status == "Parsed" for doc in docs):
        flags.append("documents_need_parsing")
    if not docs:
        flags.append("no_documents")
    return flags


def _needs_document_review(opportunity: Opportunity, docs: list[Document]) -> bool:
    if not docs:
        return True
    if any(not doc.path for doc in docs):
        return True
    if any(doc.path and doc.parsed_status != "Parsed" for doc in docs):
        return True
    if opportunity.next_action in {"Download Documents", "Parse Documents"}:
        return True
    return False


def _counts(opportunities: list[dict]) -> dict:
    return {
        "pursue": sum(1 for opp in opportunities if opp.get("review_status") == "Pursue"),
        "watchlist": sum(1 for opp in opportunities if opp.get("review_status") == "Watchlist"),
        "needs_review": sum(1 for opp in opportunities if opp.get("review_status") == "Needs Review"),
        "no_bid": sum(
            1
            for opp in opportunities
            if opp.get("review_status") == "Do Not Pursue" or opp.get("bid_decision") == "No Bid"
        ),
        "as_needed_risky": sum(1 for opp in opportunities if opp.get("as_needed_warning")),
        "missing_deadline": sum(
            1
            for opp in opportunities
            if not opp.get("due_date") or opp.get("deadline_risk") == "Missing Deadline"
        ),
        "mandatory_pre_bid": sum(1 for opp in opportunities if opp.get("pre_bid_mandatory")),
    }


def _action_sort_key(opportunity: Opportunity) -> tuple:
    status_rank = {
        "Pursue": 0,
        "Watchlist": 1,
        "Needs Review": 2,
        "New": 3,
        "Do Not Pursue": 4,
        "Archived": 5,
    }
    return (
        status_rank.get(opportunity.review_status or "New", 3),
        -(opportunity.bid_score if opportunity.bid_score is not None else -1e9),
        -(opportunity.ai_score if opportunity.ai_score is not None else -1e9),
        0 if opportunity.due_date else 1,
        to_naive_utc(opportunity.due_date) if opportunity.due_date else datetime.max,
        opportunity.id or 0,
    )


def _guard_context(context: dict) -> dict:
    text = _json_text(context)
    if len(text) <= MAX_CONTEXT_CHARS:
        return context
    if "opportunities" in context:
        while len(_json_text(context)) > MAX_CONTEXT_CHARS and len(context["opportunities"]) > 5:
            context["opportunities"].pop()
        context["context_truncated"] = True
        context["opportunity_count"] = len(context["opportunities"])
    if "requirements" in context:
        while len(_json_text(context)) > MAX_CONTEXT_CHARS and context["requirements"]:
            context["requirements"].pop()
        context["context_truncated"] = True
    if "documents" in context:
        for document in context["documents"]:
            document["snippet"] = _truncate(document.get("snippet", ""), 300)
        context["context_truncated"] = True
    for key in [
        "no_bid_opportunities",
        "as_needed_risky_opportunities",
        "missing_deadline_opportunities",
        "mandatory_pre_bid_opportunities",
        "needs_document_review",
        "upcoming_deadlines",
        "missing_deadlines",
    ]:
        while len(_json_text(context)) > MAX_CONTEXT_CHARS and len(context.get(key, [])) > 3:
            context[key].pop()
            context["context_truncated"] = True
    return context


def _read_snippet(path_value: str | None) -> str:
    if not path_value:
        return ""
    try:
        path = Path(path_value)
        if not path.exists():
            return ""
        return _truncate(
            path.read_text(encoding="utf-8", errors="replace"),
            MAX_DOCUMENT_SNIPPET_CHARS,
        )
    except OSError:
        return ""


def _bounded_limit(value: Any, default: int = DEFAULT_CONTEXT_LIMIT) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, MAX_LIMIT))


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def to_naive_utc(value: datetime) -> datetime:
    """Return a naive-UTC datetime so it can be compared against naive sentinels.

    Aware values are converted to UTC and stripped of tzinfo; already-naive
    values pass through unchanged. This prevents TypeError when mixing aware
    due_date/checked_at/updated_at values with naive datetime.max/min sentinels.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _naive(value: datetime) -> datetime:
    return to_naive_utc(value)


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _jsonable(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _json_text(context: dict) -> str:
    return json.dumps(context, ensure_ascii=True, default=str, separators=(",", ":"))

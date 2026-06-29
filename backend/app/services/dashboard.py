"""
Operations dashboard: a read-only command-center summary of what needs
attention across opportunities, documents, AI evaluation, requirements, and
source health. No network access, no mutations.
"""

from datetime import UTC, datetime

from sqlmodel import select

from app.models import (
    BidLogisticsQA,
    Document,
    Opportunity,
    OpportunityEvaluation,
    Requirement,
    SourceConfig,
)
from app.services.local_chat_context import to_naive_utc
from app.services.scrapers.capabilities import get_source_scraper_capabilities

UPCOMING_WINDOW_DAYS = 30
NEEDS_ACTION_DUE_DAYS = 14
ACTIVE_STATUSES = {"Pursue", "Watchlist", "Needs Review"}

# Lower number sorts first in the top-opportunities ranking.
TOP_STATUS_RANK = {
    "Pursue": 0,
    "Watchlist": 1,
    "Needs Review": 2,
    "New": 3,
    "Do Not Pursue": 4,
    "Archived": 5,
}


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _days_until(due: datetime, now: datetime) -> float:
    return (to_naive_utc(due) - now).total_seconds() / 86400.0


def _checked_at_key(qa: "BidLogisticsQA") -> datetime:
    return to_naive_utc(qa.checked_at) if qa.checked_at else datetime.min


def get_operations_dashboard(session) -> dict:
    now = _utc_now()
    opportunities = list(session.exec(select(Opportunity)).all())
    documents = list(session.exec(select(Document)).all())
    requirements = list(session.exec(select(Requirement)).all())
    sources = list(session.exec(select(SourceConfig)).all())
    evaluations = list(session.exec(select(OpportunityEvaluation)).all())
    qa_records = list(session.exec(select(BidLogisticsQA)).all())

    # Latest QA per opportunity (by checked_at).
    latest_qa: dict[int, BidLogisticsQA] = {}
    for qa in qa_records:
        current = latest_qa.get(qa.opportunity_id)
        if current is None or _checked_at_key(qa) > _checked_at_key(current):
            latest_qa[qa.opportunity_id] = qa

    # --- per-opportunity document rollups ---
    docs_by_opp: dict[int, list[Document]] = {}
    for doc in documents:
        docs_by_opp.setdefault(doc.opportunity_id, []).append(doc)
    requirement_opp_ids = {req.opportunity_id for req in requirements}
    evaluated_opp_ids = {ev.opportunity_id for ev in evaluations}

    def status_of(opp: Opportunity) -> str:
        return opp.review_status or "New"

    counts = {
        "total_opportunities": len(opportunities),
        "new": sum(1 for o in opportunities if status_of(o) == "New"),
        "needs_review": sum(1 for o in opportunities if status_of(o) == "Needs Review"),
        "pursue": sum(1 for o in opportunities if status_of(o) == "Pursue"),
        "watchlist": sum(1 for o in opportunities if status_of(o) == "Watchlist"),
        "do_not_pursue": sum(1 for o in opportunities if status_of(o) == "Do Not Pursue"),
        "archived": sum(1 for o in opportunities if status_of(o) == "Archived"),
        "documents_pending_download": sum(1 for d in documents if not d.path),
        "documents_downloaded": sum(1 for d in documents if d.path),
        "documents_parsed": sum(1 for d in documents if d.parsed_status == "Parsed"),
        "documents_parse_failed": sum(
            1 for d in documents if d.parsed_status == "Parse Failed"
        ),
        "requirements_extracted": len(requirements),
        "sources_enabled": sum(1 for s in sources if s.enabled),
        "sources_requiring_credentials": sum(
            1 for s in sources if s.requires_credentials
        ),
        "deadline_risk_high": sum(1 for o in opportunities if o.deadline_risk == "High"),
        "deadline_past_due": sum(1 for o in opportunities if o.deadline_risk == "Past Due"),
        "deadline_missing": sum(
            1 for o in opportunities if o.deadline_risk == "Missing Deadline"
        ),
        "logistics_qa_needs_review": sum(
            1 for qa in latest_qa.values() if qa.qa_status == "Needs Review"
        ),
        "logistics_qa_failed": sum(
            1 for qa in latest_qa.values() if qa.qa_status == "Failed"
        ),
        "missing_critical_logistics": sum(
            1 for qa in latest_qa.values() if qa.qa_status == "Missing Critical Info"
        ),
    }

    upcoming_deadlines = _upcoming_deadlines(opportunities, now)
    top_opportunities = _top_opportunities(opportunities)
    needs_action = _needs_action(
        opportunities, docs_by_opp, requirement_opp_ids, evaluated_opp_ids, latest_qa, now
    )
    source_health = _source_health(sources)
    recent_activity = _recent_activity(opportunities)

    return {
        "counts": counts,
        "upcoming_deadlines": upcoming_deadlines,
        "top_opportunities": top_opportunities,
        "needs_action": needs_action,
        "source_health": source_health,
        "recent_activity": recent_activity,
    }


def _opp_brief(opp: Opportunity) -> dict:
    return {
        "id": opp.id,
        "title": opp.title,
        "agency": opp.agency,
        "due_date": opp.due_date.isoformat() if opp.due_date else None,
        "review_status": opp.review_status or "New",
        "bid_score": opp.bid_score,
        "ai_recommendation": opp.ai_recommendation,
        "ai_score": opp.ai_score,
        "next_action": opp.next_action,
        "deadline_risk": opp.deadline_risk,
        "submission_method": opp.submission_method,
    }


def _upcoming_deadlines(opportunities: list[Opportunity], now: datetime) -> list[dict]:
    items = []
    for opp in opportunities:
        if not opp.due_date:
            continue
        days = _days_until(opp.due_date, now)
        if 0 <= days <= UPCOMING_WINDOW_DAYS:
            items.append(opp)
    items.sort(key=lambda o: to_naive_utc(o.due_date))
    return [_opp_brief(o) for o in items]


def _top_opportunities(opportunities: list[Opportunity], limit: int = 10) -> list[dict]:
    candidates = [
        o
        for o in opportunities
        if (o.review_status or "New") not in {"Archived", "Do Not Pursue"}
    ]
    # Fall back to declined items only if nothing better exists.
    if not candidates:
        candidates = [o for o in opportunities if (o.review_status or "New") != "Archived"]

    def sort_key(o: Opportunity) -> tuple:
        return (
            TOP_STATUS_RANK.get(o.review_status or "New", 3),
            -(o.bid_score if o.bid_score is not None else -1e9),
            -(o.ai_score if o.ai_score is not None else -1e9),
            0 if o.due_date else 1,
            to_naive_utc(o.due_date) if o.due_date else datetime.max,
        )

    candidates.sort(key=sort_key)
    return [_opp_brief(o) for o in candidates[:limit]]


def _needs_action(
    opportunities: list[Opportunity],
    docs_by_opp: dict[int, list[Document]],
    requirement_opp_ids: set[int],
    evaluated_opp_ids: set[int],
    latest_qa: dict[int, "BidLogisticsQA"],
    now: datetime,
) -> list[dict]:
    items: list[dict] = []
    for opp in opportunities:
        status = opp.review_status or "New"
        # Declined/terminal items do not need attention.
        if status in {"Archived", "Do Not Pursue"}:
            continue
        docs = docs_by_opp.get(opp.id, [])
        pending = [d for d in docs if not d.path]
        downloaded = [d for d in docs if d.path]
        parsed = [d for d in docs if d.parsed_status == "Parsed"]

        reason = None
        suggested_action = None

        # Deadline/logistics signals are the most urgent.
        active = status in {"Pursue", "Watchlist"}
        qa = latest_qa.get(opp.id)
        pre_bid_soon = (
            opp.pre_bid_mandatory
            and opp.pre_bid_date
            and 0 <= _days_until(opp.pre_bid_date, now) <= 7
        )
        if qa is not None and qa.qa_status == "Failed":
            reason = f"Logistics QA failed ({qa.risk_level} risk)"
            suggested_action = "Verify Portal"
        elif qa is not None and qa.qa_status == "Missing Critical Info":
            reason = "Logistics QA: missing critical info"
            suggested_action = "Extract Logistics"
        elif opp.deadline_risk == "Past Due":
            reason = "Due date is past due"
            suggested_action = "Verify Portal"
        elif active and qa is None:
            reason = "Logistics QA not run yet"
            suggested_action = "Run Logistics QA"
        elif opp.deadline_risk == "Missing Deadline" and active:
            reason = "No due date found"
            suggested_action = "Verify Portal"
        elif opp.deadline_risk == "High":
            reason = "Due date within 3 days (high deadline risk)"
            suggested_action = "Manual Review"
        elif pre_bid_soon:
            reason = "Mandatory pre-bid meeting within 7 days"
            suggested_action = "Verify Portal"
        elif active and not opp.submission_method:
            reason = "No submission method identified"
            suggested_action = "Extract Logistics"
        elif pending:
            reason = f"{len(pending)} document(s) discovered but not downloaded"
            suggested_action = "Download Documents"
        elif downloaded and not parsed:
            reason = f"{len(downloaded)} document(s) downloaded but not parsed"
            suggested_action = "Parse Documents"
        elif status in {"Pursue", "Watchlist"} and opp.id not in evaluated_opp_ids:
            reason = "No local AI evaluation yet"
            suggested_action = "Run AI Evaluation"
        elif (
            status in {"Pursue", "Watchlist"}
            and parsed
            and opp.id not in requirement_opp_ids
        ):
            reason = "Documents parsed but requirements not extracted"
            suggested_action = "Extract Requirements"
        elif status in {"New", "Needs Review"} and opp.next_action:
            reason = f"Needs triage ({status})"
            suggested_action = opp.next_action
        elif opp.due_date and 0 <= _days_until(opp.due_date, now) <= NEEDS_ACTION_DUE_DAYS:
            reason = "Due date within 14 days"
            suggested_action = opp.next_action or "Manual Review"

        if reason:
            items.append(
                {
                    "id": opp.id,
                    "title": opp.title,
                    "reason": reason,
                    "suggested_action": suggested_action,
                }
            )
    return items


def _source_health(sources: list[SourceConfig]) -> list[dict]:
    health = []
    for source in sources:
        try:
            capabilities = get_source_scraper_capabilities(source)
            message = capabilities.get("message")
        except Exception:
            message = None
        health.append(
            {
                "id": source.id,
                "name": source.name,
                "state": getattr(source, "state", None),
                "portal_type": source.portal_type,
                "enabled": source.enabled,
                "requires_credentials": source.requires_credentials,
                "auth_status": source.auth_status,
                "last_scrape_status": source.last_scrape_status,
                "last_scrape_at": (
                    source.last_scrape_at.isoformat() if source.last_scrape_at else None
                ),
                "capabilities_message": message,
            }
        )
    return health


def _recent_activity(opportunities: list[Opportunity], limit: int = 10) -> list[dict]:
    def _activity_key(o: Opportunity) -> datetime:
        value = o.updated_at or o.created_at
        return to_naive_utc(value) if value else datetime.min

    ordered = sorted(opportunities, key=_activity_key, reverse=True)
    activity = []
    for opp in ordered[:limit]:
        activity.append(
            {
                "id": opp.id,
                "title": opp.title,
                "review_status": opp.review_status or "New",
                "next_action": opp.next_action,
                "updated_at": opp.updated_at.isoformat() if opp.updated_at else None,
            }
        )
    return activity

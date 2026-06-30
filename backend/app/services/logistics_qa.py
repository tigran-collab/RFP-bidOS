"""
Deterministic second-pass QA for extracted bid logistics.

Reviews the logistics fields on an opportunity and flags missing, conflicting,
risky, or low-confidence information before the user relies on it. No AI, no
network. Results are advisory and require human verification.
"""

import json
from datetime import UTC, datetime

from sqlmodel import select

from app.models import BidLogisticsQA, Document, Opportunity, Requirement

LOW_CONFIDENCE_THRESHOLD = 0.4
DUE_SOON_DAYS = 3
ACTIVE_STATUSES = {"Pursue", "Watchlist"}

# Risk severity ordering (higher = worse).
RISK_ORDER = {"Low": 0, "Medium": 1, "High": 2, "Disqualifying": 3}
RISK_BY_RANK = {v: k for k, v in RISK_ORDER.items()}


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _today() -> datetime:
    return _utc_now().replace(hour=0, minute=0, second=0, microsecond=0)


def _days_until(value: datetime, today: datetime) -> int:
    due = value
    if due.tzinfo is not None:
        due = due.astimezone(UTC).replace(tzinfo=None)
    return (due.replace(hour=0, minute=0, second=0, microsecond=0) - today).days


def build_logistics_qa_summary(opportunity, requirements=None, documents=None) -> dict:
    """Deterministically assess an opportunity's logistics. Returns a dict with
    qa_status, risk_level, summary, issues, recommended_actions."""
    documents = documents or []
    today = _today()
    status = opportunity.review_status or "New"
    active = status in ACTIVE_STATUSES

    issues: list[dict] = []
    actions: list[str] = []

    def add(message: str, risk: str, action: str | None = None) -> None:
        issues.append({"issue": message, "risk": risk})
        if action and action not in actions:
            actions.append(action)

    # --- due date ---
    due = opportunity.due_date
    failed = False
    missing_critical = False
    if due is None:
        missing_critical = True
        add("Proposal due date is missing", "High", "Find and confirm the proposal due date")
    else:
        days = _days_until(due, today)
        if days < 0:
            failed = True
            add("Proposal due date is past due", "Disqualifying", "Confirm whether this solicitation is closed")
        elif days <= DUE_SOON_DAYS:
            add(f"Proposal due in {days} day(s)", "High", "Decide bid/no-bid immediately and prepare submission")

    # --- Q&A deadline ---
    if opportunity.q_and_a_deadline is not None and active:
        if _days_until(opportunity.q_and_a_deadline, today) < 0:
            add("Q&A deadline has passed", "Medium", "Proceed without submitting questions, or confirm clarifications")

    # --- pre-bid meeting ---
    if opportunity.pre_bid_mandatory:
        if opportunity.pre_bid_date is None:
            add("Mandatory pre-bid meeting date is missing", "High", "Find and confirm the mandatory pre-bid date")
        else:
            pre_days = _days_until(opportunity.pre_bid_date, today)
            if pre_days < 0:
                add(
                    "Mandatory pre-bid meeting has already passed",
                    "Disqualifying" if active else "High",
                    "Confirm pre-bid attendance requirement; may be disqualifying",
                )
                if active:
                    failed = True
            elif pre_days <= DUE_SOON_DAYS:
                add(f"Mandatory pre-bid meeting in {pre_days} day(s)", "High", "Register and attend the mandatory pre-bid")
    elif opportunity.pre_bid_date is not None:
        # A pre-bid date exists but mandatory status was not confirmed.
        add("Pre-bid mandatory status not confirmed", "Medium", "Confirm whether the pre-bid meeting is mandatory")

    # --- submission method / portal ---
    method = opportunity.submission_method
    if active and not method:
        add("Submission method not identified", "Medium", "Identify how the bid must be submitted")
    if method and not opportunity.submission_portal:
        lowered = method.lower()
        if "electronic" in lowered or "portal" in lowered:
            add("Submission method is electronic/portal but portal is not identified", "Medium", "Identify the submission portal")

    # --- required forms ---
    if active and not opportunity.required_forms_summary:
        add("Required forms summary is missing", "Medium", "Identify required bid forms and attachments")

    # --- conflicting deadlines ---
    notes = (opportunity.logistics_notes or "").lower()
    if "multiple candidate due dates" in notes or "conflict" in notes:
        add("Conflicting candidate deadlines were detected", "Medium", "Resolve the correct due date from the source documents")

    # --- low confidence ---
    confidence = opportunity.logistics_confidence_score
    if confidence is not None and confidence < LOW_CONFIDENCE_THRESHOLD:
        add(
            f"Low logistics confidence score ({confidence})",
            "Medium",
            "Verify logistics manually; extraction confidence is low",
        )

    # --- parsed documents present? ---
    has_parsed = any(getattr(d, "parsed_status", None) == "Parsed" for d in documents)
    if active and not has_parsed:
        add(
            "No parsed documents available",
            "Medium",
            "Documents should be downloaded/parsed before relying on logistics",
        )

    # --- aggregate ---
    if issues:
        worst_rank = max(RISK_ORDER.get(i["risk"], 0) for i in issues)
        risk_level = RISK_BY_RANK[worst_rank]
    else:
        risk_level = "Low"

    if failed:
        qa_status = "Failed"
    elif missing_critical:
        qa_status = "Missing Critical Info"
    elif issues:
        qa_status = "Needs Review"
    else:
        qa_status = "Passed"

    summary = _summarize(qa_status, risk_level, issues)

    return {
        "qa_status": qa_status,
        "risk_level": risk_level,
        "summary": summary,
        "issues": issues,
        "recommended_actions": actions,
    }


def _summarize(qa_status: str, risk_level: str, issues: list[dict]) -> str:
    if not issues:
        return "All critical logistics present; no issues detected."
    return f"{qa_status} ({risk_level} risk): {len(issues)} issue(s) flagged."


def run_logistics_qa(opportunity_id: int, session) -> dict:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return {"error": "Opportunity not found", "opportunity_id": opportunity_id}

    requirements = list(
        session.exec(
            select(Requirement).where(Requirement.opportunity_id == opportunity_id)
        ).all()
    )
    documents = list(
        session.exec(
            select(Document).where(Document.opportunity_id == opportunity_id)
        ).all()
    )

    assessment = build_logistics_qa_summary(opportunity, requirements, documents)
    now = _utc_now()
    record = BidLogisticsQA(
        opportunity_id=opportunity_id,
        qa_status=assessment["qa_status"],
        risk_level=assessment["risk_level"],
        summary=assessment["summary"],
        issues_json=json.dumps(assessment["issues"]),
        recommended_actions_json=json.dumps(assessment["recommended_actions"]),
        checked_at=now,
        created_at=now,
    )
    session.add(record)
    session.commit()
    session.refresh(record)

    return {
        "opportunity_id": opportunity_id,
        "title": opportunity.title,
        "qa_status": assessment["qa_status"],
        "risk_level": assessment["risk_level"],
        "summary": assessment["summary"],
        "issues": assessment["issues"],
        "recommended_actions": assessment["recommended_actions"],
        "checked_at": now.isoformat(),
    }


def _logistics_qa_dict(record: BidLogisticsQA) -> dict:
    return {
        "id": record.id,
        "opportunity_id": record.opportunity_id,
        "qa_status": record.qa_status,
        "risk_level": record.risk_level,
        "summary": record.summary,
        "issues": json.loads(record.issues_json) if record.issues_json else [],
        "recommended_actions": (
            json.loads(record.recommended_actions_json)
            if record.recommended_actions_json
            else []
        ),
        "checked_at": record.checked_at.isoformat() if record.checked_at else None,
    }


def get_latest_logistics_qa(opportunity_id: int, session) -> dict | None:
    record = session.exec(
        select(BidLogisticsQA)
        .where(BidLogisticsQA.opportunity_id == opportunity_id)
        .order_by(BidLogisticsQA.checked_at.desc())
    ).first()
    if record is None:
        return None
    return _logistics_qa_dict(record)


def get_latest_logistics_qa_map(session) -> dict[int, dict]:
    """Latest QA record per opportunity id, in a single query.

    Equivalent to calling get_latest_logistics_qa for every opportunity but
    without the N+1 round-trips. Rows are read newest-first (same ordering as
    get_latest_logistics_qa) and the first seen per opportunity_id wins, so the
    selected record matches the single-row lookup.
    """
    records = session.exec(
        select(BidLogisticsQA).order_by(BidLogisticsQA.checked_at.desc())
    ).all()
    latest: dict[int, dict] = {}
    for record in records:
        if record.opportunity_id not in latest:
            latest[record.opportunity_id] = _logistics_qa_dict(record)
    return latest


def run_logistics_qa_for_status(status: str, session, limit: int = 10) -> dict:
    limit = max(1, int(limit))
    matching = list(
        session.exec(
            select(Opportunity)
            .where(Opportunity.review_status == status)
            .order_by(Opportunity.id)
        ).all()
    )
    matched_count = len(matching)
    selected = matching[:limit]
    truncated = matched_count > limit
    batch = {
        "status": status,
        "limit": limit,
        "matched_count": matched_count,
        "processed_count": len(selected),
        "truncated": truncated,
        "warning": None,
        "results": [],
    }
    if truncated:
        batch["warning"] = (
            f"{matched_count} opportunities match status '{status}'; only the first "
            f"{limit} were processed. Re-run with a higher limit to process more."
        )
    for opportunity in selected:
        batch["results"].append(run_logistics_qa(opportunity.id, session))
    return batch

"""
Deterministic bid logistics extractor.

Pulls critical bid logistics (proposal due date, Q&A deadline, pre-bid meeting,
mandatory pre-bid, submission method/portal, required forms, deadline risk) from
parsed document text and opportunity metadata using regex/heuristics only.

No AI is required. No network access. Results are heuristic and require human
verification.
"""

import re
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import select

from app.models import Document, Opportunity
from app.services.scrapers.extraction_utils import DATE_PATTERNS, normalize_space, parse_date

MAX_TEXT_CHARS = 40000

DUE_DATE_KEYWORDS = (
    "proposals due",
    "proposal due",
    "bids due",
    "bid due",
    "responses due",
    "response due",
    "due date and time",
    "due date/time",
    "due date",
    "closing date",
    "closing time",
    "bid closing",
    "submission deadline",
    "submittal deadline",
    "deadline for submission",
    "must be received by",
    "received no later than",
    "due no later than",
    "rfp due",
    "rfq due",
    "sealed bids will be received until",
    "will be received until",
)
Q_AND_A_KEYWORDS = (
    "q&a deadline",
    "questions due",
    "question deadline",
    "deadline for questions",
    "last day for questions",
    "last day to submit questions",
    "rfi deadline",
    "inquiry deadline",
    "questions must be submitted by",
)
PRE_BID_KEYWORDS = (
    "pre-bid",
    "pre bid",
    "prebid",
    "pre-proposal",
    "pre proposal",
    "pre-submittal",
    "pre submittal",
    "site visit",
    "job walk",
    "walk-through",
    "walkthrough",
)

PORTAL_NAMES = {
    "planetbids": "PlanetBids",
    "bonfire": "Bonfire",
    "bidnet": "BidNet",
    "demandstar": "DemandStar",
    "public purchase": "Public Purchase",
    "publicpurchase": "Public Purchase",
    "periscope": "Periscope S2G",
    "bidsync": "BidSync",
    "opengov": "OpenGov",
    "sam.gov": "SAM.gov",
    "ionwave": "IonWave",
    "bidexpress": "Bid Express",
}

REQUIRED_FORM_PATTERNS = (
    ("Bid Form", r"\bbid form\b"),
    ("Proposal Form", r"\bproposal form\b"),
    ("Pricing Form", r"\b(?:pricing|price|cost) (?:form|sheet|schedule|proposal)\b"),
    ("Addendum Acknowledgment", r"\baddend(?:um|a)\s+acknowled"),
    ("Non-Collusion Affidavit", r"\bnon[- ]collusion\b"),
    ("References Form", r"\breferences?\s+form\b"),
    ("W-9", r"\bw-?9\b"),
    ("Insurance Certificate", r"\b(?:certificate of insurance|insurance certificate|acord)\b"),
    ("Bid Bond", r"\bbid bond\b"),
    ("Statement of Qualifications", r"\bstatement of qualifications\b|\bsoq\b"),
    ("Exhibit/Attachment", r"\b(?:exhibit|attachment)\s+[A-Z0-9]"),
)

_COMBINED_DATES = "|".join(DATE_PATTERNS)


def _utc_today() -> datetime:
    now = datetime.now(UTC).replace(tzinfo=None)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _find_dates_after_keywords(text: str, keywords: tuple[str, ...]) -> list[tuple[str, datetime]]:
    """Return (keyword, date) pairs where a date follows a keyword within ~40 chars."""
    found: list[tuple[str, datetime]] = []
    for keyword in keywords:
        # Allow a short run of intervening words (e.g. "pre-bid meeting will be
        # held on <date>"), non-greedy so the nearest date wins.
        pattern = rf"{re.escape(keyword)}[\s\S]{{0,60}}?({_COMBINED_DATES})"
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            parsed = parse_date(match.group(1))
            if parsed:
                found.append((keyword, parsed))
    return found


def extract_logistics_from_text(text: str) -> dict:
    text = (text or "")[:MAX_TEXT_CHARS]
    lowered = text.lower()
    notes: list[str] = []

    # --- due date (with conflict detection) ---
    due_hits = _find_dates_after_keywords(text, DUE_DATE_KEYWORDS)
    distinct_due = sorted({d.date() for _, d in due_hits})
    due_date = None
    conflicting = False
    if due_hits:
        # Best-supported: the date value with the most keyword hits, earliest on ties.
        tally: dict[datetime, int] = {}
        for _, d in due_hits:
            tally[d] = tally.get(d, 0) + 1
        due_date = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        if len(distinct_due) > 1:
            conflicting = True
            others = ", ".join(d.isoformat() for d in distinct_due)
            notes.append(f"Multiple candidate due dates found: {others}")

    q_hits = _find_dates_after_keywords(text, Q_AND_A_KEYWORDS)
    q_and_a_deadline = min((d for _, d in q_hits), default=None)

    pre_hits = _find_dates_after_keywords(text, PRE_BID_KEYWORDS)
    pre_bid_date = min((d for _, d in pre_hits), default=None)

    # --- mandatory / optional pre-bid ---
    pre_bid_mandatory = None
    if any(k in lowered for k in PRE_BID_KEYWORDS) or pre_bid_date:
        mandatory_window = _phrase_window(lowered, PRE_BID_KEYWORDS, 120)
        if "mandatory" in mandatory_window or "required" in mandatory_window:
            pre_bid_mandatory = True
        elif "non-mandatory" in mandatory_window or "optional" in mandatory_window or "not mandatory" in mandatory_window:
            pre_bid_mandatory = False

    submission_method, submission_portal, method_notes = _detect_submission(lowered)
    notes.extend(method_notes)

    required_forms = _detect_required_forms(lowered)
    required_forms_summary = ", ".join(required_forms) if required_forms else None

    # --- confidence ---
    confidence = 0.0
    if due_hits:
        confidence += 0.4
    if q_hits:
        confidence += 0.15
    if pre_hits:
        confidence += 0.15
    if submission_method:
        confidence += 0.15
    if required_forms:
        confidence += 0.15
    if conflicting:
        confidence = max(0.0, confidence - 0.2)
    confidence = round(min(confidence, 1.0), 2)

    return {
        "due_date": due_date,
        "due_date_candidates": distinct_due,
        "q_and_a_deadline": q_and_a_deadline,
        "pre_bid_date": pre_bid_date,
        "pre_bid_mandatory": pre_bid_mandatory,
        "submission_method": submission_method,
        "submission_portal": submission_portal,
        "required_forms_summary": required_forms_summary,
        "conflicting": conflicting,
        "logistics_confidence_score": confidence,
        "logistics_notes": "; ".join(notes) if notes else None,
    }


def _phrase_window(lowered: str, keywords: tuple[str, ...], radius: int) -> str:
    for keyword in keywords:
        idx = lowered.find(keyword)
        if idx >= 0:
            start = max(0, idx - radius)
            end = min(len(lowered), idx + len(keyword) + radius)
            return lowered[start:end]
    return ""


def _detect_submission(lowered: str) -> tuple[str | None, str | None, list[str]]:
    notes: list[str] = []
    methods: list[str] = []
    portal = None

    for token, label in PORTAL_NAMES.items():
        if token in lowered:
            portal = label
            methods.append(f"Electronic ({label})")
            break

    if not portal and any(
        k in lowered
        for k in ("submit electronically", "electronic submission", "upload your", "online submission", "submitted online")
    ):
        methods.append("Electronic / online")

    if any(k in lowered for k in ("email your", "submit via email", "emailed to", "submit by email", "e-mail submission")):
        methods.append("Email")

    if any(
        k in lowered
        for k in ("sealed bid", "sealed proposal", "hand-delivered", "hand delivered", "mailed to", "delivered to the", "physical delivery", "mail or deliver")
    ):
        methods.append("Mail / physical delivery")

    if len(methods) > 1:
        notes.append(f"Multiple submission methods referenced: {', '.join(methods)}")

    submission_method = methods[0] if methods else None
    return submission_method, portal, notes


def _detect_required_forms(lowered: str) -> list[str]:
    forms: list[str] = []
    for label, pattern in REQUIRED_FORM_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            forms.append(label)
    return forms


def _opportunity_metadata_text(opportunity: Opportunity) -> str:
    parts = [
        opportunity.title,
        opportunity.agency,
        opportunity.location,
        opportunity.service_type,
        opportunity.contract_type,
        opportunity.source,
        opportunity.source_url,
        opportunity.review_notes,
    ]
    return " ".join(str(p) for p in parts if p)


def _load_parsed_text(opportunity_id: int, session, max_chars: int) -> str:
    documents = list(
        session.exec(select(Document).where(Document.opportunity_id == opportunity_id)).all()
    )
    chunks: list[str] = []
    remaining = max_chars
    for document in documents:
        if remaining <= 0 or not document.extracted_text_path:
            continue
        path = Path(document.extracted_text_path)
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        chunk = text[:remaining]
        remaining -= len(chunk)
        chunks.append(chunk)
    return "\n\n".join(chunks)


def compute_deadline_risk(due_date: datetime | None, conflicting: bool) -> str:
    if conflicting:
        return "Needs Review"
    if due_date is None:
        return "Missing Deadline"
    today = _utc_today()
    due = due_date
    if due.tzinfo is not None:
        due = due.astimezone(UTC).replace(tzinfo=None)
    days = (due.replace(hour=0, minute=0, second=0, microsecond=0) - today).days
    if days < 0:
        return "Past Due"
    if days <= 3:
        return "High"
    if days <= 7:
        return "Medium"
    return "Low"


def extract_logistics_from_opportunity(opportunity: Opportunity, session) -> dict:
    parsed_text = _load_parsed_text(opportunity.id, session, MAX_TEXT_CHARS)
    metadata_text = _opportunity_metadata_text(opportunity)
    combined = f"{metadata_text}\n\n{parsed_text}"[:MAX_TEXT_CHARS]
    result = extract_logistics_from_text(combined)

    # Preserve any stored deadline (an operator may have hand-corrected it, and
    # the scrape's structured value is usually more reliable than a regex hit
    # from run-together document text). Only fall back to the freshly extracted
    # date to FILL a field that is currently empty.
    due_date = opportunity.due_date or result["due_date"]
    q_and_a = opportunity.q_and_a_deadline or result["q_and_a_deadline"]
    pre_bid = opportunity.pre_bid_date or result["pre_bid_date"]
    pre_bid_mandatory = (
        result["pre_bid_mandatory"]
        if result["pre_bid_mandatory"] is not None
        else opportunity.pre_bid_mandatory
    )

    deadline_risk = compute_deadline_risk(due_date, result["conflicting"])

    return {
        "due_date": due_date,
        "q_and_a_deadline": q_and_a,
        "pre_bid_date": pre_bid,
        "pre_bid_mandatory": bool(pre_bid_mandatory) if pre_bid_mandatory is not None else False,
        "submission_method": result["submission_method"],
        "submission_portal": result["submission_portal"],
        "required_forms_summary": result["required_forms_summary"],
        "deadline_risk": deadline_risk,
        "logistics_confidence_score": result["logistics_confidence_score"],
        "logistics_notes": result["logistics_notes"],
        "has_parsed_text": bool(parsed_text.strip()),
    }


def apply_logistics_to_opportunity(opportunity_id: int, session) -> dict:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return {"error": "Opportunity not found", "opportunity_id": opportunity_id}

    extracted = extract_logistics_from_opportunity(opportunity, session)

    opportunity.due_date = extracted["due_date"]
    opportunity.q_and_a_deadline = extracted["q_and_a_deadline"]
    opportunity.pre_bid_date = extracted["pre_bid_date"]
    opportunity.pre_bid_mandatory = extracted["pre_bid_mandatory"]
    opportunity.submission_method = (
        extracted["submission_method"]
        if extracted["submission_method"] is not None
        else opportunity.submission_method
    )
    opportunity.submission_portal = (
        extracted["submission_portal"]
        if extracted["submission_portal"] is not None
        else opportunity.submission_portal
    )
    opportunity.required_forms_summary = (
        extracted["required_forms_summary"]
        if extracted["required_forms_summary"] is not None
        else opportunity.required_forms_summary
    )
    opportunity.deadline_risk = extracted["deadline_risk"]
    opportunity.logistics_confidence_score = (
        extracted["logistics_confidence_score"]
        if extracted["logistics_confidence_score"] is not None
        else opportunity.logistics_confidence_score
    )
    opportunity.logistics_notes = (
        extracted["logistics_notes"]
        if extracted["logistics_notes"] is not None
        else opportunity.logistics_notes
    )
    opportunity.updated_at = datetime.now(UTC).replace(tzinfo=None)

    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)

    return {
        "opportunity_id": opportunity_id,
        "title": opportunity.title,
        "due_date": opportunity.due_date.isoformat() if opportunity.due_date else None,
        "q_and_a_deadline": (
            opportunity.q_and_a_deadline.isoformat() if opportunity.q_and_a_deadline else None
        ),
        "pre_bid_date": opportunity.pre_bid_date.isoformat() if opportunity.pre_bid_date else None,
        "pre_bid_mandatory": opportunity.pre_bid_mandatory,
        "submission_method": opportunity.submission_method,
        "submission_portal": opportunity.submission_portal,
        "required_forms_summary": opportunity.required_forms_summary,
        "deadline_risk": opportunity.deadline_risk,
        "logistics_confidence_score": opportunity.logistics_confidence_score,
        "logistics_notes": opportunity.logistics_notes,
        "has_parsed_text": extracted["has_parsed_text"],
    }


def apply_logistics_for_status(status: str, session, limit: int = 10) -> dict:
    limit = max(1, int(limit))
    matching = list(
        session.exec(
            select(Opportunity)
            .where(Opportunity.review_status == status)
            .order_by(Opportunity.id)
        ).all()
    )
    return _run_batch(matching, session, limit, label=f"status '{status}'")


def apply_logistics_all(session, limit: int = 25) -> dict:
    limit = max(1, int(limit))
    matching = list(session.exec(select(Opportunity).order_by(Opportunity.id)).all())
    return _run_batch(matching, session, limit, label="all opportunities")


def _run_batch(matching: list[Opportunity], session, limit: int, label: str) -> dict:
    matched_count = len(matching)
    selected = matching[:limit]
    truncated = matched_count > limit
    batch = {
        "label": label,
        "limit": limit,
        "matched_count": matched_count,
        "processed_count": len(selected),
        "truncated": truncated,
        "warning": None,
        "results": [],
    }
    if truncated:
        batch["warning"] = (
            f"{matched_count} opportunities match {label}; only the first {limit} "
            f"were processed. Re-run with a higher limit to process more."
        )
    for opportunity in selected:
        batch["results"].append(apply_logistics_to_opportunity(opportunity.id, session))
    return batch

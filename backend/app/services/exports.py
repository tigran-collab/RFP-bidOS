"""
CSV export helpers for opportunities, requirements, documents, and logistics QA.

Pure read-only serialization with the standard library csv module. No network,
no AI, no PDF generation.
"""

import csv
import io
from datetime import UTC, datetime

from sqlmodel import select

from app.models import (
    BidLogisticsQA,
    Document,
    Opportunity,
    Requirement,
)
from app.utils.dates import to_naive_utc

ICS_PRODID = "-//RFP BidOS//Deadlines//EN"
ICS_EXCLUDED_STATUSES = {"Archived", "Do Not Pursue"}

OPPORTUNITY_COLUMNS = [
    "id",
    "title",
    "agency",
    "solicitation_number",
    "source",
    "source_url",
    "portal_url",
    "location",
    "service_type",
    "contract_type",
    "estimated_value",
    "due_date",
    "q_and_a_deadline",
    "pre_bid_date",
    "pre_bid_mandatory",
    "submission_method",
    "submission_portal",
    "deadline_risk",
    "logistics_confidence_score",
    "bid_score",
    "bid_decision",
    "ai_recommendation",
    "ai_score",
    "review_status",
    "priority",
    "next_action",
    "review_notes",
    "created_at",
    "updated_at",
    # Appended user-relevant persisted columns (order above kept stable).
    "description",
    "relevance_decision",
    "relevance_score",
    "priority_tier",
    "priority_rank",
    "ai_risk_level",
    "bid_reason",
]

REQUIREMENT_COLUMNS = [
    "opportunity_id",
    "opportunity_title",
    "requirement_id",
    "requirement_type",
    "title",
    "requirement_text",
    "source_page",
    "source_section",
    "mandatory",
    "due_date",
    "status",
    "assigned_response_section",
    "notes",
    # Appended requirement columns present on the model (order above kept stable).
    "risk",
    "owner",
    "evidence_needed",
    "response_location",
    "source_file",
]

DOCUMENT_COLUMNS = [
    "opportunity_id",
    "opportunity_title",
    "document_id",
    "filename",
    "url",
    "path",
    "file_type",
    "parsed_status",
    "extracted_text_path",
    "created_at",
]

LOGISTICS_QA_COLUMNS = [
    "opportunity_id",
    "opportunity_title",
    "qa_id",
    "qa_status",
    "risk_level",
    "summary",
    "issues_json",
    "recommended_actions_json",
    "checked_at",
    "created_at",
]


# Leading characters a spreadsheet may interpret as the start of a formula.
_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _defuse_csv_value(value):
    """Prefix a single quote to a string that could be read as a formula.

    Spreadsheet apps treat a cell beginning with =, +, -, @, tab, or CR as a
    formula; an exported title like ``=HYPERLINK("x")`` would then execute.
    Prefixing ``'`` forces the cell to be treated as literal text.
    """
    if isinstance(value, str) and value and value[0] in _CSV_INJECTION_PREFIXES:
        return "'" + value
    return value


def _value(obj, name):
    value = getattr(obj, name, None)
    if value is None:
        return ""
    # datetimes -> ISO strings; everything else stringifies cleanly.
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return value.isoformat()
    return value


def _write_csv(columns: list[str], rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _defuse_csv_value(val) for key, val in row.items()})
    return buffer.getvalue()


def export_opportunities_csv(session, filters: dict | None = None) -> tuple[str, int]:
    filters = filters or {}
    opportunities = list(session.exec(select(Opportunity).order_by(Opportunity.id)).all())

    review_status = filters.get("review_status")
    priority = filters.get("priority")
    if review_status:
        opportunities = [
            o for o in opportunities if (o.review_status or "New") == review_status
        ]
    if priority:
        opportunities = [o for o in opportunities if (o.priority or "") == priority]

    rows = [{name: _value(o, name) for name in OPPORTUNITY_COLUMNS} for o in opportunities]
    return _write_csv(OPPORTUNITY_COLUMNS, rows), len(rows)


def _opportunity_titles(session) -> dict[int, str]:
    return {
        o.id: o.title for o in session.exec(select(Opportunity)).all()
    }


def export_requirements_csv(session, opportunity_id: int | None = None) -> tuple[str, int]:
    statement = select(Requirement)
    if opportunity_id is not None:
        statement = statement.where(Requirement.opportunity_id == opportunity_id)
    requirements = list(session.exec(statement.order_by(Requirement.id)).all())
    titles = _opportunity_titles(session)

    rows = []
    for req in requirements:
        rows.append(
            {
                "opportunity_id": req.opportunity_id,
                "opportunity_title": titles.get(req.opportunity_id, ""),
                "requirement_id": req.id,
                "requirement_type": _value(req, "requirement_type"),
                "title": _value(req, "title"),
                "requirement_text": _value(req, "requirement_text"),
                "source_page": _value(req, "source_page"),
                "source_section": _value(req, "source_section"),
                "mandatory": _value(req, "mandatory"),
                "due_date": _value(req, "due_date"),
                "status": _value(req, "status"),
                "assigned_response_section": _value(req, "assigned_response_section"),
                "notes": _value(req, "notes"),
                "risk": _value(req, "risk"),
                "owner": _value(req, "owner"),
                "evidence_needed": _value(req, "evidence_needed"),
                "response_location": _value(req, "response_location"),
                "source_file": _value(req, "source_file"),
            }
        )
    return _write_csv(REQUIREMENT_COLUMNS, rows), len(rows)


def export_documents_csv(session, opportunity_id: int | None = None) -> tuple[str, int]:
    statement = select(Document)
    if opportunity_id is not None:
        statement = statement.where(Document.opportunity_id == opportunity_id)
    documents = list(session.exec(statement.order_by(Document.id)).all())
    titles = _opportunity_titles(session)

    rows = []
    for doc in documents:
        # Document has no created_at column; fall back to downloaded_at.
        created = _value(doc, "created_at") or _value(doc, "downloaded_at")
        rows.append(
            {
                "opportunity_id": doc.opportunity_id,
                "opportunity_title": titles.get(doc.opportunity_id, ""),
                "document_id": doc.id,
                "filename": _value(doc, "filename"),
                "url": _value(doc, "source_url"),
                "path": _value(doc, "path"),
                "file_type": _value(doc, "file_type"),
                "parsed_status": _value(doc, "parsed_status"),
                "extracted_text_path": _value(doc, "extracted_text_path"),
                "created_at": created,
            }
        )
    return _write_csv(DOCUMENT_COLUMNS, rows), len(rows)


def export_logistics_qa_csv(session, opportunity_id: int | None = None) -> tuple[str, int]:
    statement = select(BidLogisticsQA)
    if opportunity_id is not None:
        statement = statement.where(BidLogisticsQA.opportunity_id == opportunity_id)
    records = list(session.exec(statement.order_by(BidLogisticsQA.id)).all())
    titles = _opportunity_titles(session)

    rows = []
    for qa in records:
        rows.append(
            {
                "opportunity_id": qa.opportunity_id,
                "opportunity_title": titles.get(qa.opportunity_id, ""),
                "qa_id": qa.id,
                "qa_status": _value(qa, "qa_status"),
                "risk_level": _value(qa, "risk_level"),
                "summary": _value(qa, "summary"),
                "issues_json": _value(qa, "issues_json"),
                "recommended_actions_json": _value(qa, "recommended_actions_json"),
                "checked_at": _value(qa, "checked_at"),
                "created_at": _value(qa, "created_at"),
            }
        )
    return _write_csv(LOGISTICS_QA_COLUMNS, rows), len(rows)


def _ics_escape(value) -> str:
    """Escape text per RFC 5545: backslash, comma, semicolon, and newlines."""
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace(",", "\\,")
    text = text.replace(";", "\\;")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    return text


def _ics_date(value: datetime) -> str:
    """Format the date portion of a datetime as an all-day VALUE=DATE string."""
    return to_naive_utc(value).strftime("%Y%m%d")


def _ics_timestamp(value: datetime | None) -> str:
    """Format a UTC DTSTAMP value (YYYYMMDDTHHMMSSZ)."""
    if value is None:
        value = datetime.now(UTC).replace(tzinfo=None)
    return to_naive_utc(value).strftime("%Y%m%dT%H%M%SZ")


def _fold_line(line: str) -> str:
    """Fold a content line per RFC 5545: no line exceeds 75 octets.

    Continuation lines are joined with CRLF + a single leading space. Folding
    respects UTF-8 octet counts but only breaks on character boundaries, so a
    multi-byte character is never split across a fold.
    """
    if len(line.encode("utf-8")) <= 75:
        return line
    pieces: list[str] = []
    current = ""
    # The first line may use 75 octets; continuation lines reserve one octet
    # for the leading space, so they cap at 74.
    budget = 75
    for char in line:
        char_octets = len(char.encode("utf-8"))
        if len(current.encode("utf-8")) + char_octets > budget:
            pieces.append(current)
            current = char
            budget = 74
        else:
            current += char
    if current:
        pieces.append(current)
    return "\r\n ".join(pieces)


def _ics_event(opp: Opportunity, kind: str, date_value: datetime, summary: str, dtstamp: str) -> list[str]:
    description_parts = []
    if opp.agency:
        description_parts.append(f"Agency: {opp.agency}")
    if opp.source_url:
        description_parts.append(f"Source: {opp.source_url}")
    if opp.submission_method:
        description_parts.append(f"Submission: {opp.submission_method}")
    description = " | ".join(description_parts)

    lines = [
        "BEGIN:VEVENT",
        _fold_line(f"UID:{opp.id}-{kind}@rfp-bidos"),
        _fold_line(f"DTSTAMP:{dtstamp}"),
        _fold_line(f"DTSTART;VALUE=DATE:{_ics_date(date_value)}"),
        _fold_line(f"SUMMARY:{_ics_escape(summary)}"),
    ]
    if description:
        lines.append(_fold_line(f"DESCRIPTION:{_ics_escape(description)}"))
    lines.extend(
        [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "TRIGGER:-P2D",
            _fold_line(f"DESCRIPTION:{_ics_escape('Reminder: ' + summary)}"),
            "END:VALARM",
            "END:VEVENT",
        ]
    )
    return lines


def export_deadlines_ics(session, opportunity_id: int | None = None) -> str:
    """Return an RFC 5545 VCALENDAR string of opportunity deadlines.

    Emits an all-day VEVENT (with a 2-day display reminder) for each present
    deadline date among due_date, q_and_a_deadline, and pre_bid_date. Filtered
    to a single opportunity when opportunity_id is given; otherwise excludes
    Archived/Do Not Pursue. Read-only; no network, no AI.
    """
    statement = select(Opportunity).order_by(Opportunity.id)
    if opportunity_id is not None:
        statement = statement.where(Opportunity.id == opportunity_id)
    opportunities = list(session.exec(statement).all())
    if opportunity_id is None:
        opportunities = [
            o for o in opportunities if (o.review_status or "New") not in ICS_EXCLUDED_STATUSES
        ]

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{ICS_PRODID}",
        "CALSCALE:GREGORIAN",
    ]

    for opp in opportunities:
        dtstamp = _ics_timestamp(opp.updated_at or opp.created_at)
        if opp.due_date:
            lines.extend(
                _ics_event(opp, "due", opp.due_date, f"Bid Due: {opp.title}", dtstamp)
            )
        if opp.q_and_a_deadline:
            lines.extend(
                _ics_event(
                    opp,
                    "qa",
                    opp.q_and_a_deadline,
                    f"Q&A Deadline: {opp.title}",
                    dtstamp,
                )
            )
        if opp.pre_bid_date:
            label = "Pre-Bid Meeting"
            if opp.pre_bid_mandatory:
                label += " (MANDATORY)"
            lines.extend(
                _ics_event(
                    opp,
                    "prebid",
                    opp.pre_bid_date,
                    f"{label}: {opp.title}",
                    dtstamp,
                )
            )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"

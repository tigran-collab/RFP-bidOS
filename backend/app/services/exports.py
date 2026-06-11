"""
CSV export helpers for opportunities, requirements, documents, and logistics QA.

Pure read-only serialization with the standard library csv module. No network,
no AI, no PDF generation.
"""

import csv
import io

from sqlmodel import select

from app.models import (
    BidLogisticsQA,
    Document,
    Opportunity,
    Requirement,
)

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
        writer.writerow(row)
    return buffer.getvalue()


def export_opportunities_csv(session, filters: dict | None = None) -> str:
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
    return _write_csv(OPPORTUNITY_COLUMNS, rows)


def _opportunity_titles(session) -> dict[int, str]:
    return {
        o.id: o.title for o in session.exec(select(Opportunity)).all()
    }


def export_requirements_csv(session, opportunity_id: int | None = None) -> str:
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
            }
        )
    return _write_csv(REQUIREMENT_COLUMNS, rows)


def export_documents_csv(session, opportunity_id: int | None = None) -> str:
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
    return _write_csv(DOCUMENT_COLUMNS, rows)


def export_logistics_qa_csv(session, opportunity_id: int | None = None) -> str:
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
    return _write_csv(LOGISTICS_QA_COLUMNS, rows)

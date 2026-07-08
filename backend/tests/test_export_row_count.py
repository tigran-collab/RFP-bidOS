"""Export row counts must reflect actual data rows.

Counting raw "\n" characters overcounts when a quoted field contains an
embedded newline; the export functions return the real row count alongside
the CSV content.
"""

import csv
import io

from app.models import Document, Opportunity, Requirement
from app.services.exports import (
    export_documents_csv,
    export_opportunities_csv,
    export_requirements_csv,
)


def test_opportunities_row_count_with_embedded_newline(session):
    session.add(Opportunity(title="Line one\nLine two", review_status="New"))
    session.add(Opportunity(title="Plain Title", review_status="New"))
    session.commit()

    content, row_count = export_opportunities_csv(session)

    assert row_count == 2
    parsed = list(csv.DictReader(io.StringIO(content)))
    assert len(parsed) == 2
    # Naive newline counting would report more than 2 rows here.
    assert content.count("\n") - 1 > 2


def test_opportunities_row_count_empty(session):
    content, row_count = export_opportunities_csv(session)
    assert row_count == 0
    assert list(csv.DictReader(io.StringIO(content))) == []


def test_documents_row_count_matches_rows(session):
    opp = Opportunity(title="With Docs", review_status="New")
    session.add(opp)
    session.commit()
    session.refresh(opp)
    session.add(Document(opportunity_id=opp.id, filename="a.pdf", path="a.pdf"))
    session.add(Document(opportunity_id=opp.id, filename="b.pdf", path="b.pdf"))
    session.commit()

    content, row_count = export_documents_csv(session, opportunity_id=opp.id)

    assert row_count == 2
    assert len(list(csv.DictReader(io.StringIO(content)))) == 2


def test_opportunities_csv_has_new_columns(session):
    opp = Opportunity(
        title="Guard Services",
        review_status="New",
        description="BSIS licensed guards required.",
        relevance_decision="Relevant",
        relevance_score=88,
        priority_tier="High",
        priority_rank=72.5,
        ai_risk_level="Low",
        bid_reason="Bid: Security services match.",
    )
    session.add(opp)
    session.commit()

    content, _ = export_opportunities_csv(session)
    reader = csv.DictReader(io.StringIO(content))
    header = reader.fieldnames
    for col in (
        "description",
        "relevance_decision",
        "relevance_score",
        "priority_tier",
        "priority_rank",
        "ai_risk_level",
        "bid_reason",
    ):
        assert col in header
    # Existing columns and their leading order remain stable.
    assert header[:4] == ["id", "title", "agency", "solicitation_number"]

    row = next(reader)
    assert row["relevance_decision"] == "Relevant"
    assert row["priority_tier"] == "High"
    assert row["ai_risk_level"] == "Low"


def test_requirements_csv_has_new_columns(session):
    opp = Opportunity(title="Guard Services", review_status="New")
    session.add(opp)
    session.commit()
    session.refresh(opp)
    session.add(
        Requirement(
            opportunity_id=opp.id,
            requirement_text="Provide proof of BSIS licensure.",
            risk="High",
            owner="Compliance",
            evidence_needed="Copy of PPO license",
            response_location="Section 3",
            source_file="rfp.pdf",
        )
    )
    session.commit()

    content, row_count = export_requirements_csv(session, opportunity_id=opp.id)
    assert row_count == 1
    reader = csv.DictReader(io.StringIO(content))
    header = reader.fieldnames
    for col in ("risk", "owner", "evidence_needed", "response_location", "source_file"):
        assert col in header
    row = next(reader)
    assert row["risk"] == "High"
    assert row["owner"] == "Compliance"
    assert row["source_file"] == "rfp.pdf"

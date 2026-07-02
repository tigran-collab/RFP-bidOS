"""Export row counts must reflect actual data rows.

Counting raw "\n" characters overcounts when a quoted field contains an
embedded newline; the export functions return the real row count alongside
the CSV content.
"""

import csv
import io

from app.models import Document, Opportunity
from app.services.exports import export_documents_csv, export_opportunities_csv


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

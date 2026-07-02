"""Tests for CSV formula-injection defusing in exports (Fix 3).

A spreadsheet treats a cell beginning with =, +, -, @, tab, or CR as a formula.
Exported values starting with those characters must be prefixed with a single
quote so they are rendered as literal text. Normal values are untouched.
"""

import csv
import io

from app.models import Opportunity
from app.services.exports import export_opportunities_csv


def _rows(csv_text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(csv_text)))


def test_formula_like_titles_are_defused(session):
    session.add(Opportunity(title='=HYPERLINK("http://evil")', review_status="New"))
    session.add(Opportunity(title="@SUM(1)", review_status="New"))
    session.add(Opportunity(title="+1+1", review_status="New"))
    session.add(Opportunity(title="-2-2", review_status="New"))
    session.commit()

    content, _ = export_opportunities_csv(session)
    rows = _rows(content)
    titles = sorted(r["title"] for r in rows)

    assert titles == sorted(
        ["'=HYPERLINK(\"http://evil\")", "'@SUM(1)", "'+1+1", "'-2-2"]
    )


def test_normal_values_untouched(session):
    session.add(Opportunity(title="Security Guard Services", review_status="New"))
    session.commit()

    content, _ = export_opportunities_csv(session)
    rows = _rows(content)

    assert rows[0]["title"] == "Security Guard Services"

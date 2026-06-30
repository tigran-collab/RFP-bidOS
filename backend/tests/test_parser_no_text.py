"""Tests for empty/scanned-document detection in the parser (Fix 2).

Offline: uses the in-memory `session` fixture and the .txt parse path (which,
like the PDF path, prefixes each page with a "--- Page N ---" header). A doc
whose extracted body is only page headers must be marked "Parsed (No Text)"
rather than "Parsed", and logistics QA must treat it as not parsed.
"""

from pathlib import Path

from app.models import Document, Opportunity
from app.services import parser as parser_module
from app.services.logistics_qa import build_logistics_qa_summary
from app.services.parser import parse_document


def _make_opp(session) -> Opportunity:
    opp = Opportunity(title="Security Guard Services", review_status="Pursue")
    session.add(opp)
    session.commit()
    session.refresh(opp)
    return opp


def _make_txt_document(session, opp_id, tmp_path, body: str) -> Document:
    source = tmp_path / "doc.txt"
    source.write_text(body, encoding="utf-8")
    doc = Document(
        opportunity_id=opp_id,
        filename="doc.txt",
        path=str(source),
        file_type="txt",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def test_empty_document_marked_parsed_no_text(session, tmp_path, monkeypatch):
    monkeypatch.setattr(parser_module, "PROCESSED_ROOT", tmp_path / "processed")
    opp = _make_opp(session)
    # Only whitespace -> the extracted body is just the page header.
    doc = _make_txt_document(session, opp.id, tmp_path, "   \n  ")

    result = parse_document(doc.id, session)

    assert result["parsed_status"] == "Parsed (No Text)"
    # Still records the extracted-text path and page count.
    assert result["extracted_text_path"] is not None
    assert Path(result["extracted_text_path"]).exists()
    session.refresh(doc)
    assert doc.parsed_status == "Parsed (No Text)"


def test_document_with_real_text_marked_parsed(session, tmp_path, monkeypatch):
    monkeypatch.setattr(parser_module, "PROCESSED_ROOT", tmp_path / "processed")
    opp = _make_opp(session)
    doc = _make_txt_document(
        session,
        opp.id,
        tmp_path,
        "Request for Proposal for unarmed security guard services at City Hall.",
    )

    result = parse_document(doc.id, session)

    assert result["parsed_status"] == "Parsed"
    session.refresh(doc)
    assert doc.parsed_status == "Parsed"


def test_logistics_qa_flags_no_text_document_as_missing_parsed(session):
    opp = Opportunity(title="Security Guard Services", review_status="Pursue")
    no_text_doc = Document(
        opportunity_id=1,
        filename="scan.pdf",
        path="scan.pdf",
        file_type="pdf",
        parsed_status="Parsed (No Text)",
    )

    summary = build_logistics_qa_summary(opp, documents=[no_text_doc])

    issue_messages = [i["issue"] for i in summary["issues"]]
    assert "No parsed documents available" in issue_messages

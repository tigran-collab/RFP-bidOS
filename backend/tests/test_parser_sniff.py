"""L4: files with a missing/unknown type are sniffed by magic bytes.

A PDF served from ".../download?id=3" as application/octet-stream lands with no
extension and file_type=None; the parser must detect %PDF- and parse it rather
than marking it "Unsupported File Type".
"""

from app.models import Document, Opportunity
from app.services import parser


def _seed(session, filename, path, file_type=None):
    opportunity = Opportunity(title="Security Guard Services")
    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)
    document = Document(
        opportunity_id=opportunity.id,
        filename=filename,
        path=str(path),
        file_type=file_type,
        parsed_status="Not Parsed",
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def test_extensionless_pdf_is_sniffed_and_parsed(session, tmp_path, monkeypatch):
    monkeypatch.setattr(parser, "PROCESSED_ROOT", tmp_path / "processed", raising=True)
    # No extension, no file_type — mimics octet-stream ".../download?id=3".
    blob = tmp_path / "download"
    blob.write_bytes(
        b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    )
    document = _seed(session, filename="download", path=blob, file_type=None)

    result = parser.parse_document(document.id, session)

    # It must not be rejected as unsupported; it is recognized as a PDF.
    assert result["status"] != parser.STATUS_UNSUPPORTED
    assert result["parser_used"] in {"pypdf", "pymupdf"}


def test_extensionless_text_is_sniffed_and_parsed(session, tmp_path, monkeypatch):
    monkeypatch.setattr(parser, "PROCESSED_ROOT", tmp_path / "processed", raising=True)
    blob = tmp_path / "notes"
    blob.write_text("Proposal submission is due on the listed date. Include forms A-C.")
    document = _seed(session, filename="notes", path=blob, file_type=None)

    result = parser.parse_document(document.id, session)

    assert result["parsed_status"] == parser.STATUS_PARSED
    assert result["parser_used"] == "text"


def test_unknown_binary_still_unsupported(session, tmp_path, monkeypatch):
    monkeypatch.setattr(parser, "PROCESSED_ROOT", tmp_path / "processed", raising=True)
    blob = tmp_path / "blob"
    blob.write_bytes(b"\x00\x01\x02\x03binary\x00garbage")
    document = _seed(session, filename="blob", path=blob, file_type=None)

    result = parser.parse_document(document.id, session)

    assert result["parsed_status"] == parser.STATUS_UNSUPPORTED

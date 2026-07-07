"""Tests for the document downloader.

Offline: requests.get is monkeypatched and downloads land in tmp_path.
"""

from sqlmodel import select

from app.models import Document, Opportunity
from app.services import downloader


class _FakeResponse:
    def __init__(self, content, content_type="application/pdf"):
        self.content = content
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        return None


def _seed_opportunity(session):
    opportunity = Opportunity(title="Security Guard Services")
    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)
    return opportunity


def test_duplicate_content_deletes_pending_document(session, tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, "DOWNLOAD_ROOT", tmp_path)
    opportunity = _seed_opportunity(session)

    content = b"%PDF-1.4 fake document body"
    monkeypatch.setattr(
        downloader.requests, "get", lambda url, **kwargs: _FakeResponse(content)
    )

    first = downloader.download_document(
        "https://example.com/docs/original.pdf", opportunity.id, session
    )
    assert first["downloaded_count"] == 1

    pending = Document(
        opportunity_id=opportunity.id,
        filename="",
        path="",
        source_url="https://example.com/docs/copy.pdf",
    )
    session.add(pending)
    session.commit()

    result = downloader.download_documents_for_opportunity(opportunity.id, session)
    assert result["skipped_count"] == 1
    assert result["downloaded_count"] == 0

    documents = list(
        session.exec(
            select(Document).where(Document.opportunity_id == opportunity.id)
        ).all()
    )
    assert len(documents) == 1
    assert documents[0].path
    assert documents[0].filename == "original.pdf"


def test_pending_document_downloads_new_content(session, tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, "DOWNLOAD_ROOT", tmp_path)
    opportunity = _seed_opportunity(session)

    monkeypatch.setattr(
        downloader.requests,
        "get",
        lambda url, **kwargs: _FakeResponse(f"body of {url}".encode()),
    )

    pending = Document(
        opportunity_id=opportunity.id,
        filename="",
        path="",
        source_url="https://example.com/docs/addendum.pdf",
    )
    session.add(pending)
    session.commit()

    result = downloader.download_documents_for_opportunity(opportunity.id, session)
    assert result["downloaded_count"] == 1

    session.refresh(pending)
    assert pending.path
    assert pending.filename == "addendum.pdf"
    assert pending.sha256


def test_stale_document_path_is_redownloaded(session, tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, "DOWNLOAD_ROOT", tmp_path)
    opportunity = _seed_opportunity(session)

    stale = Document(
        opportunity_id=opportunity.id,
        filename="missing.pdf",
        path=str(tmp_path / "opportunity_1" / "missing.pdf"),
        source_url="https://example.com/docs/missing.pdf",
    )
    session.add(stale)
    session.commit()

    monkeypatch.setattr(
        downloader.requests,
        "get",
        lambda url, **kwargs: _FakeResponse(b"%PDF-1.4 replacement"),
    )

    result = downloader.download_documents_for_opportunity(opportunity.id, session)

    assert result["downloaded_count"] == 1
    session.refresh(stale)
    assert stale.path
    assert downloader.resolve_downloaded_document_path(stale).exists()

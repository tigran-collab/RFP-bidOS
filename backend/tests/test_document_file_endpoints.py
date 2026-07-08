import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  (register tables)
from app.main import app
from app.models import Document, Opportunity
from app.services import downloader


@pytest.fixture
def document_client(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.routers.documents.engine", engine, raising=True)
    monkeypatch.setattr(downloader, "DOWNLOAD_ROOT", tmp_path, raising=True)
    client = TestClient(app)
    client._engine = engine
    client._download_root = tmp_path
    return client


def _seed_document(client, path="", source_url="https://example.com/rfp.pdf"):
    with Session(client._engine) as session:
        opp = Opportunity(title="Security Guard Services")
        session.add(opp)
        session.commit()
        session.refresh(opp)
        doc = Document(
            opportunity_id=opp.id,
            filename="rfp.pdf",
            path=path,
            file_type="pdf",
            source_url=source_url,
            parsed_status="Not Downloaded",
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        return doc.id


def test_downloaded_document_file_is_served(document_client):
    file_path = document_client._download_root / "opportunity_1" / "rfp.pdf"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"%PDF-1.4 file body")
    doc_id = _seed_document(document_client, path=str(file_path))

    response = document_client.get(f"/documents/{doc_id}/file")

    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 file body"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "rfp.pdf" in response.headers["content-disposition"]


def test_missing_downloaded_file_returns_404(document_client):
    doc_id = _seed_document(document_client, path="")

    response = document_client.get(f"/documents/{doc_id}/file")

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "Downloaded file not found. Run Download Documents first."
    )


def test_document_download_endpoint_fetches_pending_document(
    document_client, monkeypatch
):
    doc_id = _seed_document(document_client)

    monkeypatch.setattr(
        downloader.requests,
        "get",
        lambda url, **kwargs: _FakeResponse(b"%PDF-1.4 downloaded"),
    )

    response = document_client.post(f"/documents/{doc_id}/download")

    assert response.status_code == 200
    assert response.json()["downloaded_count"] == 1
    file_response = document_client.get(f"/documents/{doc_id}/file")
    assert file_response.status_code == 200
    assert file_response.content == b"%PDF-1.4 downloaded"


class _FakeResponse:
    def __init__(self, content, content_type="application/pdf"):
        self.content = content
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=65536):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]

    def close(self):
        return None

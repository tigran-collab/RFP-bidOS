import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app import models  # noqa: F401  (register tables)
from app.main import app
from app.models import Document, Opportunity, SourceConfig
from app.services import downloader, portal_document_downloader


@pytest.fixture
def opportunity_client(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.routers.opportunities.engine", engine, raising=True)
    monkeypatch.setattr(downloader, "DOWNLOAD_ROOT", tmp_path, raising=True)
    monkeypatch.setattr(portal_document_downloader, "DOWNLOAD_ROOT", tmp_path, raising=True)
    client = TestClient(app)
    client._engine = engine
    client._download_root = tmp_path
    return client


def test_download_documents_discovers_and_fetches_file(opportunity_client, monkeypatch):
    with Session(opportunity_client._engine) as session:
        opp = Opportunity(
            title="Security Guard Services",
            source_url="https://example.gov/bids/security",
        )
        session.add(opp)
        session.commit()
        session.refresh(opp)
        opp_id = opp.id

    def fake_get(url, **kwargs):
        if url == "https://example.gov/bids/security":
            return _FakeResponse(
                b"",
                text='<a href="/docs/rfp.pdf">RFP document</a>',
                content_type="text/html",
            )
        if url == "https://example.gov/docs/rfp.pdf":
            return _FakeResponse(b"%PDF-1.4 downloaded")
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("app.services.scraper.requests.get", fake_get)
    monkeypatch.setattr(downloader.requests, "get", fake_get)

    response = opportunity_client.post(f"/opportunities/{opp_id}/download-documents")

    assert response.status_code == 200
    body = response.json()
    assert body["documents_discovered"] == 1
    assert body["downloaded_count"] == 1
    with Session(opportunity_client._engine) as session:
        doc = session.exec(
            select(Document).where(Document.opportunity_id == opp_id)
        ).first()
    assert doc is not None
    assert (opportunity_client._download_root / f"opportunity_{opp_id}" / "rfp.pdf").exists()


def test_headed_portal_download_endpoint(opportunity_client, monkeypatch, tmp_path):
    with Session(opportunity_client._engine) as session:
        source = SourceConfig(
            name="Portal Source",
            source_type="authenticated_browser",
            base_url="https://portal.example.gov",
            enabled=True,
        )
        session.add(source)
        session.commit()
        session.refresh(source)
        opp = Opportunity(
            title="Security Guard Services",
            source=source.name,
            source_url="https://portal.example.gov/bids/security",
        )
        session.add(opp)
        session.commit()
        session.refresh(opp)
        opp_id = opp.id

    def fake_browser_download(page_url, profile_dir, output_dir, **kwargs):
        path = tmp_path / "headed.pdf"
        path.write_bytes(b"%PDF-1.4 headed")
        return {
            "candidates_found": 1,
            "downloads_attempted": 1,
            "downloaded_files": [
                {
                    "url": "https://portal.example.gov/download/headed",
                    "filename": "headed.pdf",
                    "path": str(path),
                    "label": "RFP",
                }
            ],
            "errors": [],
        }

    monkeypatch.setattr(
        portal_document_downloader.browser_session,
        "download_document_links_headed",
        fake_browser_download,
    )

    response = opportunity_client.post(
        f"/opportunities/{opp_id}/download-portal-documents"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["candidates_found"] == 1
    assert body["downloads_attempted"] == 1
    assert body["downloaded_count"] == 1


class _FakeResponse:
    def __init__(self, content, text=None, content_type="application/pdf"):
        self.content = content
        self.text = text if text is not None else content.decode("utf-8", errors="replace")
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=65536):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]

    def close(self):
        return None

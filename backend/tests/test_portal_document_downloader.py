import json

from sqlmodel import Session

from app.models import Document, Opportunity, SourceConfig
from app.services import portal_document_downloader as portal_downloader
from app.services.scrapers.browser_session import SessionExpiredError


def _seed_portal_opportunity(session):
    source = SourceConfig(
        name="City Portal",
        source_type="authenticated_browser",
        base_url="https://portal.example.gov",
        enabled=True,
        requires_credentials=True,
        config_json=json.dumps(
            {
                "document_download": {
                    "wait_selector": ".documents",
                    "download_click_selectors": [".download-all"],
                    "max_downloads": 5,
                }
            }
        ),
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    opportunity = Opportunity(
        title="Security Guard Services",
        source=source.name,
        source_url="https://portal.example.gov/bids/123",
    )
    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)
    return source, opportunity


def test_headed_portal_download_registers_files(session, tmp_path, monkeypatch):
    source, opportunity = _seed_portal_opportunity(session)
    monkeypatch.setattr(portal_downloader, "DOWNLOAD_ROOT", tmp_path)

    captured = {}

    def fake_browser_download(page_url, profile_dir, output_dir, **kwargs):
        captured.update(kwargs)
        captured["page_url"] = page_url
        captured["profile_dir"] = profile_dir
        path = tmp_path / "browser-temp" / "rfp.pdf"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"%PDF-1.4 portal file")
        return {
            "candidates_found": 1,
            "downloads_attempted": 1,
            "downloaded_files": [
                {
                    "url": "https://portal.example.gov/downloads/rfp",
                    "filename": "rfp.pdf",
                    "path": str(path),
                    "label": "RFP",
                }
            ],
            "errors": [],
        }

    monkeypatch.setattr(
        portal_downloader.browser_session,
        "download_document_links_headed",
        fake_browser_download,
    )

    result = portal_downloader.download_portal_documents_headed(opportunity.id, session)

    assert result["downloaded_count"] == 1
    assert result["skipped_count"] == 0
    assert captured["wait_selector"] == ".documents"
    assert captured["download_click_selectors"] == [".download-all"]
    assert captured["max_downloads"] == 5
    assert captured["page_url"] == opportunity.source_url
    assert str(source.id) in captured["profile_dir"]

    document = session.get(Document, result["files"][0]["document_id"])
    assert document is not None
    assert document.filename == "rfp.pdf"
    assert document.file_type == "pdf"
    assert document.sha256
    assert document.parsed_status == "Not Parsed"
    assert (tmp_path / f"opportunity_{opportunity.id}" / "rfp.pdf").exists()


def test_headed_portal_download_requires_portal_source(session):
    opportunity = Opportunity(
        title="Security Guard Services",
        source="Public Page",
        source_url="https://example.gov/bids/123",
    )
    source = SourceConfig(
        name="Public Page",
        source_type="public_page",
        base_url="https://example.gov",
    )
    session.add(source)
    session.add(opportunity)
    session.commit()
    session.refresh(opportunity)

    result = portal_downloader.download_portal_documents_headed(opportunity.id, session)

    assert result["downloaded_count"] == 0
    assert "not an assisted-login portal source" in result["errors"][0]


def test_headed_portal_download_reports_missing_session(session, monkeypatch):
    _source, opportunity = _seed_portal_opportunity(session)

    def raise_expired(*args, **kwargs):
        raise SessionExpiredError("run portal-login first")

    monkeypatch.setattr(
        portal_downloader.browser_session,
        "download_document_links_headed",
        raise_expired,
    )

    result = portal_downloader.download_portal_documents_headed(opportunity.id, session)

    assert result["downloaded_count"] == 0
    assert "Portal session unavailable" in result["errors"][0]

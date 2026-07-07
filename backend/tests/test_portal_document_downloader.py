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


def test_expired_session_auto_logs_in_and_retries(session, tmp_path, monkeypatch):
    source, opportunity = _seed_portal_opportunity(session)
    source.credential_username = "vendor@example.com"
    source.credential_secret_ref = "rfp-bidos/city-portal"
    session.add(source)
    session.commit()
    monkeypatch.setattr(portal_downloader, "DOWNLOAD_ROOT", tmp_path)

    calls = {"download": 0}
    login_kwargs = {}

    def fake_browser_download(page_url, profile_dir, output_dir, **kwargs):
        calls["download"] += 1
        if calls["download"] == 1:
            raise SessionExpiredError("session expired")
        path = tmp_path / "browser-temp" / "rfp.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
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

    def fake_assisted_login(login_url, profile_dir, **kwargs):
        login_kwargs.update(kwargs)
        login_kwargs["login_url"] = login_url
        return {"ok": True, "message": "Login detected; session persisted."}

    monkeypatch.setattr(
        portal_downloader.browser_session,
        "download_document_links_headed",
        fake_browser_download,
    )
    monkeypatch.setattr(
        portal_downloader.browser_session, "assisted_login", fake_assisted_login
    )
    monkeypatch.setattr(
        portal_downloader.credential_store,
        "get_password",
        lambda ref, username: "keychain-secret",
    )

    result = portal_downloader.download_portal_documents_headed(opportunity.id, session)

    assert result["login_performed"] is True
    assert result["downloaded_count"] == 1
    assert calls["download"] == 2
    assert login_kwargs["login_url"] == source.base_url
    assert login_kwargs["prefill_username"] == "vendor@example.com"
    assert login_kwargs["prefill_password"] == "keychain-secret"


def test_failed_auto_login_reports_error_without_retry(session, monkeypatch):
    _source, opportunity = _seed_portal_opportunity(session)

    calls = {"download": 0}

    def raise_expired(*args, **kwargs):
        calls["download"] += 1
        raise SessionExpiredError("session expired")

    monkeypatch.setattr(
        portal_downloader.browser_session,
        "download_document_links_headed",
        raise_expired,
    )
    monkeypatch.setattr(
        portal_downloader.browser_session,
        "assisted_login",
        lambda *args, **kwargs: {"ok": False, "message": "Login did not complete."},
    )

    result = portal_downloader.download_portal_documents_headed(opportunity.id, session)

    assert result["login_performed"] is False
    assert result["downloaded_count"] == 0
    assert calls["download"] == 1
    assert "Login did not complete." in result["errors"]


def test_session_still_expired_after_login_reports_clearly(session, monkeypatch):
    _source, opportunity = _seed_portal_opportunity(session)

    def raise_expired(*args, **kwargs):
        raise SessionExpiredError("still expired")

    monkeypatch.setattr(
        portal_downloader.browser_session,
        "download_document_links_headed",
        raise_expired,
    )
    monkeypatch.setattr(
        portal_downloader.browser_session,
        "assisted_login",
        lambda *args, **kwargs: {"ok": True, "message": "Session persisted."},
    )

    result = portal_downloader.download_portal_documents_headed(opportunity.id, session)

    assert result["login_performed"] is True
    assert result["downloaded_count"] == 0
    assert "still unavailable after login" in result["errors"][0]

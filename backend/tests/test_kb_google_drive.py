"""Tests for the Google Drive connector: config (keychain, tokens never
returned), listing, importing into the vault (incl. Google-native export),
unsupported-type skipping, and refresh-on-401. HTTP is injected — no network."""

import pytest

from app.services.kb import documents as kb_documents
from app.services.kb import google_drive_connector as gd
from app.services.kb import processing as kb_processing
from tests.kb_factories import make_admin, make_reader


@pytest.fixture
def fake_keychain(monkeypatch):
    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(gd.credential_store, "set_password",
                        lambda ref, acct, secret: (store.__setitem__((ref, acct), secret), {"ok": True})[1])
    monkeypatch.setattr(gd.credential_store, "get_password",
                        lambda ref, acct: store.get((ref, acct)))
    monkeypatch.setattr(gd.credential_store, "delete_password",
                        lambda ref, acct: (store.pop((ref, acct), None), {"ok": True})[1])
    monkeypatch.setattr(gd.credential_store, "is_available", lambda: True)
    return store


@pytest.fixture(autouse=True)
def _isolate_doc_root(tmp_path, monkeypatch):
    monkeypatch.setattr(kb_documents, "KB_DOCUMENT_ROOT", tmp_path)
    # Don't spawn background processing threads in tests.
    monkeypatch.setattr(kb_processing, "enqueue_processing", lambda doc_id: None)


class FakeResp:
    def __init__(self, status_code=200, json_data=None, content=b""):
        self.status_code = status_code
        self._json = json_data or {}
        self.content = content
        self.text = ""

    def json(self):
        return self._json


def make_http(routes):
    """routes: list of (predicate(method,url,kwargs) -> bool, FakeResp or callable)."""
    def http(method, url, **kwargs):
        for pred, resp in routes:
            if pred(method, url, kwargs):
                return resp(method, url, kwargs) if callable(resp) else resp
        return FakeResp(404, {"error": {"message": "no route"}})
    return http


# --- config ------------------------------------------------------------------


def test_status_default(session, fake_keychain):
    status = gd.get_status(session)
    assert status["configured"] is False
    assert status["has_refresh"] is False
    assert "access_token" not in status and "token" not in str(status)


def test_configure_stores_secret_never_returns_it(session, fake_keychain):
    status = gd.configure(session, {
        "access_token": "ya29.secret", "folder_id": "folder123",
        "refresh_token": "rt", "client_id": "cid", "client_secret": "cs",
    })
    assert status["configured"] is True
    assert status["folder_id"] == "folder123"
    assert status["has_refresh"] is True
    assert "ya29.secret" not in str(status) and "rt" not in str(status)
    gd.clear(session)
    assert gd.get_status(session)["configured"] is False


def test_configure_requires_access_token(session, fake_keychain):
    with pytest.raises(gd.DriveConfigError):
        gd.configure(session, {"folder_id": "x"})


# --- listing -----------------------------------------------------------------


def test_list_files(session, fake_keychain):
    gd.configure(session, {"access_token": "tok", "folder_id": "F"})
    http = make_http([
        (lambda m, u, k: m == "GET" and u.endswith("/files"),
         FakeResp(200, {"files": [{"id": "1", "name": "caps.pdf", "mimeType": "application/pdf"}]})),
    ])
    out = gd.list_files(session, http=http)
    assert out["files"][0]["name"] == "caps.pdf"


def test_list_not_configured(session, fake_keychain):
    out = gd.list_files(session, http=make_http([]))
    assert out["files"] == [] and "not configured" in out["error"].lower()


# --- import ------------------------------------------------------------------


def test_import_regular_file(session, fake_keychain):
    admin = make_admin(session)
    gd.configure(session, {"access_token": "tok"})
    http = make_http([
        (lambda m, u, k: "/files/1" in u and k.get("params", {}).get("fields"),
         FakeResp(200, {"id": "1", "name": "capabilities.txt", "mimeType": "text/plain"})),
        (lambda m, u, k: "/files/1" in u and k.get("params", {}).get("alt") == "media",
         FakeResp(200, content=b"Aventus capabilities statement.")),
    ])
    result = gd.import_files(session, admin, ["1"], http=http)
    assert result["imported"] == 1
    assert result["documents"][0]["filename"].endswith(".txt")
    # The document is in the vault.
    from sqlmodel import select
    from app.kb_models import KbDocument
    docs = session.exec(select(KbDocument)).all()
    assert any(d.filename.endswith(".txt") for d in docs)


def test_import_google_doc_is_exported_to_docx(session, fake_keychain):
    admin = make_admin(session)
    gd.configure(session, {"access_token": "tok"})
    http = make_http([
        (lambda m, u, k: "/files/2" in u and "export" not in u and k.get("params", {}).get("fields"),
         FakeResp(200, {"id": "2", "name": "Company Overview", "mimeType": "application/vnd.google-apps.document"})),
        (lambda m, u, k: "/export" in u,
         FakeResp(200, content=b"PK\x03\x04 fake docx bytes")),
    ])
    result = gd.import_files(session, admin, ["2"], http=http)
    assert result["imported"] == 1
    assert result["documents"][0]["filename"].endswith(".docx")


def test_import_unsupported_google_type_skipped(session, fake_keychain):
    admin = make_admin(session)
    gd.configure(session, {"access_token": "tok"})
    http = make_http([
        (lambda m, u, k: "/files/3" in u,
         FakeResp(200, {"id": "3", "name": "Survey", "mimeType": "application/vnd.google-apps.form"})),
    ])
    result = gd.import_files(session, admin, ["3"], http=http)
    assert result["imported"] == 0 and result["skipped"] == 1


def test_refresh_on_401_then_succeeds(session, fake_keychain):
    gd.configure(session, {
        "access_token": "expired", "refresh_token": "rt",
        "client_id": "cid", "client_secret": "cs",
    })
    calls = {"list": 0}

    def list_handler(m, u, k):
        calls["list"] += 1
        # First list call 401s (expired token); after refresh, succeeds.
        if calls["list"] == 1:
            return FakeResp(401, {"error": {"message": "invalid"}})
        return FakeResp(200, {"files": [{"id": "9", "name": "f.pdf", "mimeType": "application/pdf"}]})

    http = make_http([
        (lambda m, u, k: u == gd.GOOGLE_TOKEN_URL, FakeResp(200, {"access_token": "fresh"})),
        (lambda m, u, k: u.endswith("/files"), list_handler),
    ])
    out = gd.list_files(session, http=http)
    assert out["files"][0]["id"] == "9"
    assert calls["list"] == 2  # retried after refresh
    # The refreshed token was persisted.
    assert gd._load_creds()["access_token"] == "fresh"


def test_read_only_cannot_import(session, fake_keychain):
    reader = make_reader(session)
    gd.configure(session, {"access_token": "tok"})
    http = make_http([
        (lambda m, u, k: "/files/1" in u and k.get("params", {}).get("fields"),
         FakeResp(200, {"id": "1", "name": "f.txt", "mimeType": "text/plain"})),
        (lambda m, u, k: k.get("params", {}).get("alt") == "media",
         FakeResp(200, content=b"data")),
    ])
    # create_document enforces the uploader permission -> collected as an error.
    result = gd.import_files(session, reader, ["1"], http=http)
    assert result["imported"] == 0
    assert result["errors"]

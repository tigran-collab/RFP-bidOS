"""KB HTTP API: meta, upload+process, permission enforcement (403), drafting.

Follows the repo's endpoint-test pattern: a fresh in-memory engine monkeypatched
onto the router (and processing) modules, driven through TestClient.
"""

import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import kb_models, models  # noqa: F401  (register tables)
from app.main import app
from app.services.kb import claims as claims_service
from app.services.kb import drafting
from app.services.kb.permissions import resolve_acting_user
from app.services.kb.seed import seed_kb


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.routers.kb.engine", engine, raising=True)
    monkeypatch.setattr("app.services.kb.processing.engine", engine, raising=True)
    with Session(engine) as session:
        seed_kb(session)
    test_client = TestClient(app)
    test_client._engine = engine
    return test_client


def _read_only_user_id(client) -> int:
    from app.kb_models import KbUser
    from sqlmodel import select

    with Session(client._engine) as session:
        user = session.exec(select(KbUser).where(KbUser.role == "read_only")).first()
        return user.id


def test_meta_endpoint(client):
    resp = client.get("/kb/meta")
    assert resp.status_code == 200
    body = resp.json()
    assert any(r["value"] == "administrator" for r in body["roles"])
    assert "Armed Security" in body["claim_categories"]


def test_whoami_defaults_to_admin(client):
    resp = client.get("/kb/whoami")
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "administrator"


def test_upload_and_process_document(client):
    content = b"Aventus employs 450 officers and holds PPO license 12345 in California."
    resp = client.post(
        "/kb/documents",
        files=[("files", ("caps.txt", content, "text/plain"))],
        data={"process": "false", "category": "Company Overview"},
    )
    assert resp.status_code == 201, resp.text
    doc_id = resp.json()["documents"][0]["id"]

    proc = client.post(f"/kb/documents/{doc_id}/process")
    assert proc.status_code == 200, proc.text
    assert proc.json()["chunks"] >= 1

    detail = client.get(f"/kb/documents/{doc_id}")
    assert detail.status_code == 200
    assert detail.json()["chunks"]


def test_permission_denied_for_read_only(client):
    ro_id = _read_only_user_id(client)
    resp = client.post(
        "/kb/claims",
        json={"title": "T", "canonical_text": "x"},
        headers={"X-KB-User-Id": str(ro_id)},
    )
    assert resp.status_code == 403


def test_generate_endpoint(client, monkeypatch):
    # Seed an approved claim to retrieve.
    with Session(client._engine) as session:
        admin = resolve_acting_user(session, None)
        claim = claims_service.create_claim(
            session, admin,
            {"title": "Experience", "canonical_text": "Aventus provides armed guards in California."},
        )
        claims_service.approve_claim(session, admin, claim.id)

    monkeypatch.setattr(
        drafting, "generate_text", lambda prompt, **kw: "Aventus provides armed guards [1]."
    )
    resp = client.post(
        "/kb/responses/generate",
        json={"question": "Describe your armed guard services.", "state": "CA"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["citations"]
    assert body["response"]["confidence_score"] > 0


_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_gallery_upload_list_and_file(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.kb.gallery.KB_GALLERY_ROOT", tmp_path, raising=True)
    resp = client.post(
        "/kb/gallery",
        files=[("files", ("logo.png", _PNG_1x1, "image/png"))],
        data={"category": "Logo", "title": "Company Logo"},
    )
    assert resp.status_code == 201, resp.text
    asset = resp.json()["assets"][0]
    aid = asset["id"]
    assert asset["category"] == "Logo"
    assert asset["mime_type"] == "image/png"

    listing = client.get("/kb/gallery")
    assert listing.status_code == 200
    assert any(a["id"] == aid for a in listing.json())

    served = client.get(f"/kb/gallery/{aid}/file")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/png")
    assert served.content == _PNG_1x1


def _mock_keychain(monkeypatch):
    from app.services.kb import claude_client
    store: dict = {}

    def _set(ref, acct, secret):
        store[(ref, acct)] = secret
        return {"ok": True}

    def _del(ref, acct):
        store.pop((ref, acct), None)
        return {"deleted": True}

    monkeypatch.setattr(claude_client.credential_store, "set_password", _set)
    monkeypatch.setattr(claude_client.credential_store, "get_password",
                        lambda ref, acct: store.get((ref, acct)))
    monkeypatch.setattr(claude_client.credential_store, "delete_password", _del)
    monkeypatch.setattr(claude_client.credential_store, "is_available", lambda: True)
    monkeypatch.setattr("app.services.ollama_client.is_ollama_available", lambda: False, raising=False)
    return store


def test_ai_config_status_default(client, monkeypatch):
    _mock_keychain(monkeypatch)
    resp = client.get("/kb/ai-config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["claude"]["configured"] is False
    assert "api_key" not in str(body)
    assert any(p["value"] == "claude" for p in body["providers"])


def test_read_only_cannot_configure_claude(client, monkeypatch):
    _mock_keychain(monkeypatch)
    ro_id = _read_only_user_id(client)
    resp = client.put(
        "/kb/ai-config/claude",
        json={"api_key": "sk-ant-x", "model": "claude-opus-4-8"},
        headers={"X-KB-User-Id": str(ro_id)},
    )
    assert resp.status_code == 403


def test_admin_configures_claude_key_never_returned(client, monkeypatch):
    _mock_keychain(monkeypatch)
    resp = client.put(
        "/kb/ai-config/claude",
        json={"api_key": "sk-ant-secret", "model": "claude-opus-4-8"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configured"] is True
    assert body["model"] == "claude-opus-4-8"
    assert "sk-ant-secret" not in resp.text  # key never echoed back
    # Now status reflects configured.
    assert client.get("/kb/ai-config").json()["claude"]["configured"] is True


def test_generate_with_claude_provider_unconfigured_503(client, monkeypatch):
    _mock_keychain(monkeypatch)  # keychain empty -> Claude not configured
    # An approved claim is required so the pipeline reaches the model call rather
    # than short-circuiting on empty retrieval.
    created = client.post(
        "/kb/claims",
        json={
            "title": "Armed guard coverage",
            "canonical_text": "Aventus provides armed guard coverage across California.",
            "status": "Approved",
        },
    )
    assert created.status_code in (200, 201), created.text
    resp = client.post(
        "/kb/responses/generate",
        json={"question": "Describe your armed guard coverage.", "provider": "claude"},
    )
    assert resp.status_code == 503, resp.text


def test_google_drive_status_default(client, monkeypatch):
    _mock_keychain(monkeypatch)
    resp = client.get("/kb/google-drive/status")
    assert resp.status_code == 200
    assert resp.json()["configured"] is False


def test_read_only_cannot_configure_google_drive(client, monkeypatch):
    _mock_keychain(monkeypatch)
    ro_id = _read_only_user_id(client)
    resp = client.put(
        "/kb/google-drive/config",
        json={"access_token": "ya29.x", "folder_id": "F"},
        headers={"X-KB-User-Id": str(ro_id)},
    )
    assert resp.status_code == 403


def test_admin_configures_google_drive_token_never_returned(client, monkeypatch):
    _mock_keychain(monkeypatch)
    resp = client.put(
        "/kb/google-drive/config",
        json={"access_token": "ya29.secret", "folder_id": "folder123"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configured"] is True
    assert body["folder_id"] == "folder123"
    assert "ya29.secret" not in resp.text  # token never echoed back


def test_gallery_read_only_cannot_upload(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.kb.gallery.KB_GALLERY_ROOT", tmp_path, raising=True)
    ro_id = _read_only_user_id(client)
    resp = client.post(
        "/kb/gallery",
        files=[("files", ("logo.png", _PNG_1x1, "image/png"))],
        headers={"X-KB-User-Id": str(ro_id)},
    )
    assert resp.status_code == 403


def test_read_only_cannot_process_document(client):
    # Upload as admin (default), then try to reprocess as read-only -> 403.
    content = b"Aventus holds PPO license 12345."
    up = client.post(
        "/kb/documents",
        files=[("files", ("a.txt", content, "text/plain"))],
        data={"process": "false"},
    )
    doc_id = up.json()["documents"][0]["id"]
    ro_id = _read_only_user_id(client)
    resp = client.post(f"/kb/documents/{doc_id}/process", headers={"X-KB-User-Id": str(ro_id)})
    assert resp.status_code == 403


def test_expire_and_detect_require_permission(client):
    ro_id = _read_only_user_id(client)
    headers = {"X-KB-User-Id": str(ro_id)}
    assert client.post("/kb/claims/expire", headers=headers).status_code == 403
    assert client.post("/kb/conflicts/detect", json={}, headers=headers).status_code == 403


def test_generate_ai_unavailable_returns_503(client, monkeypatch):
    from app.services.ollama_client import LOCAL_AI_UNAVAILABLE, LocalAIUnavailableError

    with Session(client._engine) as session:
        admin = resolve_acting_user(session, None)
        claim = claims_service.create_claim(
            session, admin, {"title": "X", "canonical_text": "armed guard services california"}
        )
        claims_service.approve_claim(session, admin, claim.id)

    def _boom(*a, **k):
        raise LocalAIUnavailableError(LOCAL_AI_UNAVAILABLE)

    monkeypatch.setattr(drafting, "generate_text", _boom)
    resp = client.post("/kb/responses/generate", json={"question": "Describe armed guard services."})
    assert resp.status_code == 503

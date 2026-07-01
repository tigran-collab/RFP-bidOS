"""Tests for the in-app Portals endpoints (routers/portals.py).

These verify the security invariants that matter most: the password is stored
only in the (mocked) OS keychain and is NEVER echoed by any response, add-portal
creates a disabled credential-requiring source, portal-login degrades cleanly
when Playwright is missing and otherwise starts a background worker whose state
is reflected by login-status.

The DB is an isolated in-memory SQLite; the routers' module-level engine is
monkeypatched onto it. credential_store and browser_session are mocked so no
real keychain or browser is touched.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  (register tables)
from app.main import app
from app.models import SourceConfig

SECRET_PASSWORD = "super-secret-password-should-never-leak"


class FakeKeyring:
    """In-memory stand-in for credential_store keyed by (ref, username)."""

    def __init__(self):
        self.store = {}
        self.available = True

    def is_available(self):
        return self.available

    def set_password(self, ref, username, password):
        if not ref or not username:
            return {"ok": False, "message": "ref and username are required"}
        self.store[(ref, username)] = password
        return {"ok": True, "message": "Credential stored in OS keychain."}

    def get_password(self, ref, username):
        return self.store.get((ref, username))

    def delete_password(self, ref, username):
        self.store.pop((ref, username), None)
        return {"ok": True, "message": "Credential deleted from OS keychain."}

    def has_password(self, ref, username):
        return bool(self.store.get((ref, username)))


@pytest.fixture
def portal_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    # Point every module that opened its own Session(engine) at the test engine.
    monkeypatch.setattr("app.routers.portals.engine", engine, raising=True)
    monkeypatch.setattr("app.routers.sources.engine", engine, raising=True)
    monkeypatch.setattr("app.cli.engine", engine, raising=True)
    monkeypatch.setattr("app.cli.init_db", lambda: None, raising=True)

    fake = FakeKeyring()
    # credential_store is used both directly and via source_credentials.has_password.
    monkeypatch.setattr("app.routers.portals.credential_store", fake, raising=True)
    monkeypatch.setattr(
        "app.services.credential_store.is_available", fake.is_available, raising=True
    )
    monkeypatch.setattr(
        "app.services.credential_store.has_password", fake.has_password, raising=True
    )
    monkeypatch.setattr(
        "app.services.credential_store.get_password", fake.get_password, raising=True
    )

    # Reset the module-level in-memory login state between tests.
    import app.routers.portals as portals_module

    portals_module.LOGIN_STATE.clear()

    client = TestClient(app)
    client._engine = engine
    client._fake_keyring = fake
    yield client
    portals_module.LOGIN_STATE.clear()


def _add_source(engine, **kwargs) -> int:
    defaults = dict(
        name="Test Portal",
        source_type="planetbids",
        login_url="https://vendors.example.com/portal/1/bo/bo-search",
        enabled=False,
        requires_credentials=True,
        credential_type="Keyring",
        credential_secret_ref="rfp-bidos:test-portal",
    )
    defaults.update(kwargs)
    with Session(engine) as session:
        source = SourceConfig(**defaults)
        session.add(source)
        session.commit()
        session.refresh(source)
        return source.id


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
def test_portal_templates_lists_catalog(portal_client):
    response = portal_client.get("/sources/portal-templates")
    assert response.status_code == 200
    slugs = {t["slug"] for t in response.json()}
    assert "planetbids" in slugs
    assert "generic" in slugs


# ---------------------------------------------------------------------------
# add-portal
# ---------------------------------------------------------------------------
def test_add_portal_creates_disabled_credential_source(portal_client):
    response = portal_client.post(
        "/sources/add-portal",
        json={"template": "planetbids", "name": "My Agency PlanetBids"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "My Agency PlanetBids"
    assert body["enabled"] is False
    assert body["requires_credentials"] is True
    assert body["credential_type"] == "Keyring"
    assert body["credential_secret_ref"]
    # No password field anywhere in the created source read model.
    assert "password" not in body


def test_add_portal_unknown_template_is_422(portal_client):
    response = portal_client.post(
        "/sources/add-portal",
        json={"template": "does-not-exist", "name": "Bad"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# PUT credentials — stores in keychain, never returns the password
# ---------------------------------------------------------------------------
def test_set_credentials_stores_and_never_returns_password(portal_client):
    source_id = _add_source(portal_client._engine)
    response = portal_client.put(
        f"/sources/{source_id}/credentials",
        json={"username": "vendor@example.com", "password": SECRET_PASSWORD},
    )
    assert response.status_code == 200

    # Password stored in the (fake) keychain under the source's ref + username.
    assert portal_client._fake_keyring.get_password(
        "rfp-bidos:test-portal", "vendor@example.com"
    ) == SECRET_PASSWORD

    # The response body must NEVER contain the password.
    assert SECRET_PASSWORD not in response.text
    body = response.json()
    assert body["credential_username"] == "vendor@example.com"
    assert body["auth_status"] == "Configured"


def test_set_credentials_derives_ref_when_missing(portal_client):
    source_id = _add_source(portal_client._engine, credential_secret_ref=None)
    response = portal_client.put(
        f"/sources/{source_id}/credentials",
        json={"username": "u@example.com", "password": SECRET_PASSWORD},
    )
    assert response.status_code == 200
    assert SECRET_PASSWORD not in response.text
    body_ref = response.json()["credential_secret_ref"]
    assert body_ref
    assert portal_client._fake_keyring.get_password(body_ref, "u@example.com") == SECRET_PASSWORD


def test_set_credentials_requires_keyring(portal_client):
    portal_client._fake_keyring.available = False
    source_id = _add_source(portal_client._engine)
    response = portal_client.put(
        f"/sources/{source_id}/credentials",
        json={"username": "u@example.com", "password": SECRET_PASSWORD},
    )
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# DELETE credentials
# ---------------------------------------------------------------------------
def test_delete_credentials_clears_username_and_keychain(portal_client):
    source_id = _add_source(portal_client._engine)
    portal_client.put(
        f"/sources/{source_id}/credentials",
        json={"username": "vendor@example.com", "password": SECRET_PASSWORD},
    )
    response = portal_client.delete(f"/sources/{source_id}/credentials")
    assert response.status_code == 200
    assert SECRET_PASSWORD not in response.text
    assert not portal_client._fake_keyring.has_password(
        "rfp-bidos:test-portal", "vendor@example.com"
    )
    assert response.json()["credential_username"] is None


# ---------------------------------------------------------------------------
# portal-login — Playwright missing fails cleanly; present starts a thread
# ---------------------------------------------------------------------------
def test_portal_login_playwright_missing_fails_cleanly(portal_client, monkeypatch):
    source_id = _add_source(portal_client._engine)
    monkeypatch.setattr(
        "app.services.scrapers.browser_session.playwright_available",
        lambda: False,
    )
    response = portal_client.post(f"/sources/{source_id}/portal-login")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "failed"
    assert "playwright" in body["message"].lower()


def test_portal_login_starts_worker_and_status_reflects_success(
    portal_client, monkeypatch
):
    source_id = _add_source(portal_client._engine)
    portal_client.put(
        f"/sources/{source_id}/credentials",
        json={"username": "vendor@example.com", "password": SECRET_PASSWORD},
    )

    monkeypatch.setattr(
        "app.services.scrapers.browser_session.playwright_available",
        lambda: True,
    )

    captured = {}

    def fake_assisted_login(portal_url, profile_dir, **kwargs):
        # Password may be pre-filled but must never be logged; capture that it
        # was passed so we know prefill wiring works, then report success.
        captured["prefill_password"] = kwargs.get("prefill_password")
        captured["prefill_username"] = kwargs.get("prefill_username")
        return {"ok": True, "message": "Login detected; session persisted."}

    monkeypatch.setattr(
        "app.services.scrapers.browser_session.assisted_login",
        fake_assisted_login,
    )

    response = portal_client.post(f"/sources/{source_id}/portal-login")
    assert response.status_code == 200
    assert response.json()["state"] in {"launching", "awaiting_user", "success"}

    # The worker runs on a daemon thread; join it via the module state helper.
    import time

    for _ in range(50):
        status = portal_client.get(f"/sources/{source_id}/login-status").json()
        if status["state"] in {"success", "failed", "expired"}:
            break
        time.sleep(0.05)

    status = portal_client.get(f"/sources/{source_id}/login-status").json()
    assert status["state"] == "success"
    # login-status leaks neither the password nor auth-status password fields.
    assert SECRET_PASSWORD not in portal_client.get(
        f"/sources/{source_id}/login-status"
    ).text
    assert "auth_status" in status
    # Prefill received the keychain password internally (not exposed via API).
    assert captured["prefill_username"] == "vendor@example.com"


def test_login_status_default_idle(portal_client):
    source_id = _add_source(portal_client._engine)
    response = portal_client.get(f"/sources/{source_id}/login-status")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "idle"
    assert body["has_session_profile"] is False
    assert SECRET_PASSWORD not in response.text


def test_login_status_404_for_missing_source(portal_client):
    response = portal_client.get("/sources/99999/login-status")
    assert response.status_code == 404

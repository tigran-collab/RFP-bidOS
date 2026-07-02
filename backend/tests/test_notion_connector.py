"""Tests for the Notion connector service.

Fully offline: the Notion HTTP calls go through an injected fake `http`
callable, and the OS keychain is monkeypatched to an in-memory dict. These
verify the security invariant (token never leaks from status), configure
round-trips, and that sync creates/updates/dedups and only sets properties
present in the database schema.
"""

from datetime import datetime

import pytest

from app.models import Opportunity
from app.services import credential_store, notion_connector
from app.services.settings_store import get_setting

TOKEN = "secret-notion-token-should-never-leak"
DATABASE_ID = "db-1234567890"


class FakeKeyring:
    """In-memory stand-in for credential_store keyed by (ref, username)."""

    def __init__(self):
        self.store = {}
        self.available = True

    def is_available(self):
        return self.available

    def set_password(self, ref, username, password):
        self.store[(ref, username)] = password
        return {"ok": True, "message": "Credential stored in OS keychain."}

    def get_password(self, ref, username):
        return self.store.get((ref, username))

    def delete_password(self, ref, username):
        self.store.pop((ref, username), None)
        return {"ok": True, "message": "Credential deleted from OS keychain."}


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or str(self._payload)

    def json(self):
        return self._payload


def _schema(properties):
    return {"properties": properties}


# A canned DB schema: a title, plus a subset of the mappable properties. Note it
# intentionally OMITS "Priority" and "Relevance" so we can assert those are
# skipped, and includes "Solicitation Number" as rich_text for dedup.
CANNED_SCHEMA = _schema(
    {
        "Name": {"type": "title"},
        "Agency": {"type": "rich_text"},
        "Due Date": {"type": "date"},
        "Status": {"type": "select"},
        "Score": {"type": "number"},
        "Solicitation Number": {"type": "rich_text"},
        "Source URL": {"type": "url"},
    }
)


@pytest.fixture
def fake_keyring(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(credential_store, "is_available", fake.is_available)
    monkeypatch.setattr(credential_store, "set_password", fake.set_password)
    monkeypatch.setattr(credential_store, "get_password", fake.get_password)
    monkeypatch.setattr(credential_store, "delete_password", fake.delete_password)
    return fake


def _make_opp(session, **kwargs):
    defaults = dict(
        title="Armed Security Guard Services",
        agency="City of Example",
        solicitation_number="RFP-2026-001",
        due_date=datetime(2026, 8, 1),
        review_status="Pursue",
        bid_score=88.0,
        source_url="https://example.gov/rfp-2026-001",
        priority_tier="High",
        relevance_decision="Relevant",
    )
    defaults.update(kwargs)
    opp = Opportunity(**defaults)
    session.add(opp)
    session.commit()
    session.refresh(opp)
    return opp


# ---------------------------------------------------------------------------
# configure / status
# ---------------------------------------------------------------------------
def test_configure_stores_token_in_keychain_and_db_id_in_settings(session, fake_keyring):
    def http(method, url, **kwargs):
        # configure() validates via GET /databases/{id}.
        assert method == "GET"
        return FakeResponse(200, CANNED_SCHEMA)

    status = notion_connector.configure(
        session, token=TOKEN, database_id=DATABASE_ID, http=http
    )
    # Token in the (fake) keychain, db id in settings.
    assert fake_keyring.get_password(
        notion_connector.KEYRING_REF, notion_connector.KEYRING_USERNAME
    ) == TOKEN
    assert get_setting(session, notion_connector.DATABASE_ID_KEY) == DATABASE_ID

    assert status["configured"] is True
    assert status["connection_ok"] is True
    # The token must NEVER appear in the returned status.
    assert TOKEN not in repr(status)


def test_status_never_leaks_token(session, fake_keyring):
    notion_connector.configure(
        session, token=TOKEN, database_id=DATABASE_ID,
        http=lambda *a, **k: FakeResponse(200, CANNED_SCHEMA),
    )
    status = notion_connector.notion_status(
        session, http=lambda *a, **k: FakeResponse(200, CANNED_SCHEMA)
    )
    assert status["configured"] is True
    assert status["connection_ok"] is True
    assert "token" not in status
    assert TOKEN not in repr(status)


def test_status_not_configured_makes_no_http_call(session, fake_keyring):
    def http(*args, **kwargs):
        raise AssertionError("no HTTP call should be made when not configured")

    status = notion_connector.notion_status(session, http=http)
    assert status["configured"] is False
    assert status["connection_ok"] is None
    assert "not configured" in status["message"].lower()


def test_status_reports_connection_failure(session, fake_keyring):
    notion_connector.configure(
        session, token=TOKEN, database_id=DATABASE_ID,
        http=lambda *a, **k: FakeResponse(200, CANNED_SCHEMA),
    )
    status = notion_connector.notion_status(
        session,
        http=lambda *a, **k: FakeResponse(401, {"message": "Unauthorized"}),
    )
    assert status["connection_ok"] is False
    assert "401" in status["message"]


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------
def _configure(session, fake_keyring):
    notion_connector.configure(
        session, token=TOKEN, database_id=DATABASE_ID,
        http=lambda *a, **k: FakeResponse(200, CANNED_SCHEMA),
    )


def test_sync_not_configured_returns_message_without_http(session, fake_keyring):
    _make_opp(session)

    def http(*args, **kwargs):
        raise AssertionError("no HTTP call should be made when not configured")

    result = notion_connector.sync_opportunities(session, http=http)
    assert result["created"] == 0
    assert result["updated"] == 0
    assert "not configured" in result["message"].lower()


def test_sync_creates_page_when_query_returns_no_results(session, fake_keyring):
    _configure(session, fake_keyring)
    opp = _make_opp(session)

    calls = []

    def http(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "GET":
            return FakeResponse(200, CANNED_SCHEMA)
        if method == "POST" and url.endswith("/query"):
            return FakeResponse(200, {"results": []})
        if method == "POST" and url.endswith("/pages"):
            return FakeResponse(200, {"id": "page-new"})
        raise AssertionError(f"unexpected call {method} {url}")

    result = notion_connector.sync_opportunities(session, http=http)
    assert result["created"] == 1
    assert result["updated"] == 0
    assert result["synced_ids"] == [opp.id]

    # The create call only set properties present in the canned schema.
    create_call = next(c for c in calls if c[1].endswith("/pages"))
    props = create_call[2]["json"]["properties"]
    assert "Name" in props  # title
    assert "Agency" in props
    assert "Due Date" in props
    assert "Status" in props
    assert "Score" in props
    assert "Solicitation Number" in props
    assert "Source URL" in props
    # Omitted from the schema -> skipped.
    assert "Priority" not in props
    assert "Relevance" not in props
    # Token never travels in the JSON body; only via the Authorization header.
    assert TOKEN not in str(create_call[2].get("json"))


def test_sync_updates_page_when_query_returns_existing(session, fake_keyring):
    _configure(session, fake_keyring)
    opp = _make_opp(session)

    calls = []

    def http(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "GET":
            return FakeResponse(200, CANNED_SCHEMA)
        if method == "POST" and url.endswith("/query"):
            return FakeResponse(200, {"results": [{"id": "page-existing"}]})
        if method == "PATCH":
            return FakeResponse(200, {"id": "page-existing"})
        raise AssertionError(f"unexpected call {method} {url}")

    result = notion_connector.sync_opportunities(session, http=http)
    assert result["created"] == 0
    assert result["updated"] == 1
    assert result["synced_ids"] == [opp.id]

    patch_call = next(c for c in calls if c[0] == "PATCH")
    assert "page-existing" in patch_call[1]


def test_sync_dedup_query_filters_by_solicitation_number(session, fake_keyring):
    _configure(session, fake_keyring)
    _make_opp(session, solicitation_number="RFP-XYZ")

    seen_filter = {}

    def http(method, url, **kwargs):
        if method == "GET":
            return FakeResponse(200, CANNED_SCHEMA)
        if method == "POST" and url.endswith("/query"):
            seen_filter["body"] = kwargs["json"]["filter"]
            return FakeResponse(200, {"results": []})
        if method == "POST" and url.endswith("/pages"):
            return FakeResponse(200, {"id": "page-new"})
        raise AssertionError(f"unexpected call {method} {url}")

    notion_connector.sync_opportunities(session, http=http)
    assert seen_filter["body"]["property"] == "Solicitation Number"
    assert seen_filter["body"]["rich_text"]["equals"] == "RFP-XYZ"


def test_sync_records_per_opportunity_error_and_continues(session, fake_keyring):
    _configure(session, fake_keyring)
    _make_opp(session, title="First", solicitation_number="A-1")
    _make_opp(session, title="Second", solicitation_number="A-2")

    def http(method, url, **kwargs):
        if method == "GET":
            return FakeResponse(200, CANNED_SCHEMA)
        if method == "POST" and url.endswith("/query"):
            return FakeResponse(200, {"results": []})
        if method == "POST" and url.endswith("/pages"):
            body = kwargs["json"]["properties"]
            # Fail creating the first opportunity, succeed for the second.
            title = body["Name"]["title"][0]["text"]["content"]
            if title == "First":
                return FakeResponse(400, {"message": "bad request"})
            return FakeResponse(200, {"id": "page-ok"})
        raise AssertionError(f"unexpected call {method} {url}")

    result = notion_connector.sync_opportunities(session, http=http)
    assert result["created"] == 1
    assert len(result["errors"]) == 1
    assert "First" in result["errors"][0]


def test_sync_default_excludes_archived(session, fake_keyring):
    _configure(session, fake_keyring)
    _make_opp(session, title="Active", solicitation_number="ACT-1", review_status="Pursue")
    _make_opp(session, title="Old", solicitation_number="ARCH-1", review_status="Archived")

    synced_titles = []

    def http(method, url, **kwargs):
        if method == "GET":
            return FakeResponse(200, CANNED_SCHEMA)
        if method == "POST" and url.endswith("/query"):
            return FakeResponse(200, {"results": []})
        if method == "POST" and url.endswith("/pages"):
            synced_titles.append(
                kwargs["json"]["properties"]["Name"]["title"][0]["text"]["content"]
            )
            return FakeResponse(200, {"id": "page-new"})
        raise AssertionError(f"unexpected call {method} {url}")

    result = notion_connector.sync_opportunities(session, http=http)
    assert result["created"] == 1
    assert synced_titles == ["Active"]


def test_clear_removes_token_and_db_id(session, fake_keyring):
    _configure(session, fake_keyring)
    assert notion_connector.is_configured(session) is True

    status = notion_connector.clear(session)
    assert status["configured"] is False
    assert get_setting(session, notion_connector.DATABASE_ID_KEY) is None
    assert fake_keyring.get_password(
        notion_connector.KEYRING_REF, notion_connector.KEYRING_USERNAME
    ) is None

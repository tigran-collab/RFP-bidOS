"""Tests for the AI drafting provider abstraction: provider selection, the
Claude client config (keychain-backed, key never returned), rate limiting, and
Claude-provider drafting via a mocked client."""

import pytest

from app.services.kb import ai_provider, claims, claude_client, drafting
from tests.kb_factories import make_admin, make_entity


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    ai_provider.reset_rate_limit()
    yield
    ai_provider.reset_rate_limit()


@pytest.fixture
def fake_keychain(monkeypatch):
    """In-memory stand-in for the OS keychain so tests never touch the real one."""
    store: dict[tuple[str, str], str] = {}

    def set_password(ref, account, secret):
        store[(ref, account)] = secret
        return {"ok": True}

    def get_password(ref, account):
        return store.get((ref, account))

    def delete_password(ref, account):
        store.pop((ref, account), None)
        return {"deleted": True}

    monkeypatch.setattr(claude_client.credential_store, "set_password", set_password)
    monkeypatch.setattr(claude_client.credential_store, "get_password", get_password)
    monkeypatch.setattr(claude_client.credential_store, "delete_password", delete_password)
    monkeypatch.setattr(claude_client.credential_store, "is_available", lambda: True)
    return store


# --- provider selection ------------------------------------------------------


def test_resolve_provider_defaults_to_local():
    assert ai_provider.resolve_provider(None) == ai_provider.PROVIDER_LOCAL
    assert ai_provider.resolve_provider("nonsense") == ai_provider.PROVIDER_LOCAL
    assert ai_provider.resolve_provider("claude") == ai_provider.PROVIDER_CLAUDE
    assert ai_provider.resolve_provider("local") == ai_provider.PROVIDER_LOCAL


# --- rate limiting -----------------------------------------------------------


def test_rate_limit_trips_after_max(monkeypatch):
    monkeypatch.setattr(ai_provider, "RATE_LIMIT_MAX", 3)
    ai_provider.reset_rate_limit()
    for _ in range(3):
        ai_provider.enforce_rate_limit()
    with pytest.raises(ai_provider.DraftingRateLimitError):
        ai_provider.enforce_rate_limit()
    ai_provider.reset_rate_limit()
    ai_provider.enforce_rate_limit()  # window cleared


# --- Claude config (keychain) ------------------------------------------------


def test_claude_config_roundtrip_never_returns_key(session, fake_keychain):
    assert claude_client.is_configured() is False
    status = claude_client.save_config(session, "sk-ant-secret", "claude-opus-4-8")
    assert status["configured"] is True
    assert status["model"] == "claude-opus-4-8"
    assert "sk-ant-secret" not in str(status)  # key never surfaced
    assert claude_client.get_api_key() == "sk-ant-secret"

    claude_client.delete_config(session)
    assert claude_client.is_configured() is False
    assert claude_client.get_api_key() is None


def test_claude_status_defaults(session, fake_keychain):
    status = claude_client.get_status(session)
    assert status["configured"] is False
    assert status["model"] == claude_client.DEFAULT_MODEL
    assert "api_key" not in status and "key" not in status


# --- Claude-provider drafting (mocked client) --------------------------------


def _approved_claim(session, admin, entity):
    claim = claims.create_claim(
        session, admin,
        {"title": "Armed coverage", "canonical_text": "Aventus provides armed guards in CA.",
         "company_entity_id": entity.id},
    )
    claims.approve_claim(session, admin, claim.id)
    return claim


def test_generate_with_claude_provider(session, monkeypatch):
    admin = make_admin(session)
    entity = make_entity(session)
    _approved_claim(session, admin, entity)

    monkeypatch.setattr(claude_client, "load_config", lambda s: ("sk-test", "claude-opus-4-8"))
    captured = {}

    def fake_generate(prompt, *, api_key, model, **kw):
        captured["api_key"] = api_key
        captured["model"] = model
        return "Aventus provides armed guards in California [1]."

    monkeypatch.setattr(claude_client, "generate_text", fake_generate)

    result = drafting.generate_response(
        session, admin, {"question": "Describe your armed guard coverage.", "provider": "claude"},
    )
    assert "error" not in result
    assert result["response"]["model_name"] == "claude-opus-4-8"
    assert captured["api_key"] == "sk-test"
    assert result["citations"]  # cited the approved claim


def test_generate_with_claude_unconfigured_returns_error(session, monkeypatch):
    admin = make_admin(session)
    entity = make_entity(session)
    _approved_claim(session, admin, entity)
    monkeypatch.setattr(claude_client, "load_config", lambda s: (None, "claude-opus-4-8"))

    result = drafting.generate_response(
        session, admin, {"question": "Describe your armed guard coverage.", "provider": "claude"},
    )
    assert "error" in result
    assert "not configured" in result["error"].lower()


def test_generate_with_claude_error_is_mapped(session, monkeypatch):
    admin = make_admin(session)
    entity = make_entity(session)
    _approved_claim(session, admin, entity)
    monkeypatch.setattr(claude_client, "load_config", lambda s: ("sk-test", "claude-opus-4-8"))

    def boom(prompt, **kw):
        raise claude_client.ClaudeError("Claude API error: boom")

    monkeypatch.setattr(claude_client, "generate_text", boom)
    result = drafting.generate_response(
        session, admin, {"question": "Describe your armed guard coverage.", "provider": "claude"},
    )
    assert "error" in result and "claude" in result["error"].lower()


def test_claude_generate_text_extracts_text_blocks(monkeypatch):
    """claude_client.generate_text returns concatenated text blocks from a mocked
    Anthropic client (thinking blocks ignored)."""
    import anthropic

    class _Block:
        def __init__(self, type_, text=""):
            self.type = type_
            self.text = text

    class _Msg:
        content = [_Block("thinking", ""), _Block("text", "Drafted answer [1].")]

    class _Messages:
        def create(self, **kw):
            assert kw["model"] == "claude-opus-4-8"
            assert kw["messages"][0]["role"] == "user"
            return _Msg()

    class _FakeClient:
        def __init__(self, **kw):
            self.messages = _Messages()

    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)
    out = claude_client.generate_text("prompt", api_key="k", model="claude-opus-4-8")
    assert out == "Drafted answer [1]."

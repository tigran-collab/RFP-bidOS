"""Tests for the portal template catalog and add-portal source creation.

Fully offline: no browser, no network, no keychain. Verifies the catalog shape
and that add_portal_source creates a disabled, credential-requiring SourceConfig
from a template and from explicit args.
"""

import json

import pytest
from sqlmodel import select

from app.cli import add_portal_source
from app.models import SourceConfig
from app.services.scrapers.portal_templates import (
    PORTAL_TEMPLATES,
    get_template,
    list_templates,
)

REQUIRED_TEMPLATE_KEYS = {
    "display_name",
    "source_type",
    "portal_type",
    "login_url",
    "config_json",
    "notes",
}
EXPECTED_SLUGS = {"planetbids", "bidnet", "bonfire", "opengov", "demandstar", "generic"}


def test_expected_slugs_present():
    slugs = {t["slug"] for t in list_templates()}
    assert EXPECTED_SLUGS <= slugs


def test_every_template_has_required_keys_and_title_capable_config():
    for slug, template in PORTAL_TEMPLATES.items():
        assert REQUIRED_TEMPLATE_KEYS <= set(template.keys()), slug
        config = template["config_json"]
        assert isinstance(config, dict), slug
        if template["source_type"] == "authenticated_browser":
            # A browser template must be title-capable: either a field_map with
            # a title selector, or (fallback) at least a list_url so the table
            # parser can run.
            field_map = config.get("field_map") or {}
            assert "title" in field_map or "list_url" in config, slug
        else:
            # PlanetBids maps title through its field_map.
            assert "title" in (config.get("field_map") or {}), slug


def test_get_template_unknown_returns_none():
    assert get_template("does-not-exist") is None


def test_get_template_returns_deep_copy():
    a = get_template("bidnet")
    b = get_template("bidnet")
    assert a is not None and b is not None
    a["config_json"]["list_url"] = "MUTATED"
    # Mutating one copy must not affect the shared catalog or another copy.
    assert b["config_json"]["list_url"] != "MUTATED"
    assert PORTAL_TEMPLATES["bidnet"]["config_json"]["list_url"] != "MUTATED"


def test_bidnet_template_is_authenticated_browser():
    tpl = get_template("bidnet")
    assert tpl["source_type"] == "authenticated_browser"
    assert tpl["login_url"] == "https://www.bidnetdirect.com/"


def test_add_portal_from_template(session):
    result = add_portal_source(
        session,
        name="City of Example BidNet",
        template="bidnet",
        list_url="https://www.bidnetdirect.com/city-of-example/bids",
    )
    source = session.get(SourceConfig, result["source_id"])
    assert source is not None
    assert source.enabled is False
    assert source.requires_credentials is True
    assert source.credential_type == "Keyring"
    assert source.credential_secret_ref  # derived, non-empty
    assert source.source_type == "authenticated_browser"
    assert source.portal_type == "BidNet"
    # list_url from the arg was merged into the template skeleton.
    config = json.loads(source.config_json)
    assert config["list_url"] == "https://www.bidnetdirect.com/city-of-example/bids"
    assert "field_map" in config


def test_add_portal_from_explicit_args(session):
    result = add_portal_source(
        session,
        name="Custom Portal",
        source_type="authenticated_browser",
        login_url="https://custom.example.com/login",
        list_url="https://custom.example.com/bids",
    )
    source = session.get(SourceConfig, result["source_id"])
    assert source.enabled is False
    assert source.requires_credentials is True
    assert source.source_type == "authenticated_browser"
    assert source.login_url == "https://custom.example.com/login"
    config = json.loads(source.config_json)
    assert config["list_url"] == "https://custom.example.com/bids"


def test_add_portal_unknown_template_raises(session):
    with pytest.raises(ValueError):
        add_portal_source(session, name="X", template="nope")


def test_add_portal_explicit_requires_source_type_and_login(session):
    with pytest.raises(ValueError):
        add_portal_source(session, name="X", login_url="https://x.example.com")
    with pytest.raises(ValueError):
        add_portal_source(session, name="Y", source_type="authenticated_browser")


def test_add_portal_warns_on_duplicate_name(session):
    add_portal_source(session, name="Dup Portal", template="generic")
    result = add_portal_source(session, name="Dup Portal", template="generic")
    assert result["existing_warning"] is not None
    # Both were created (add-portal is idempotent-ish: warns, does not block).
    sources = list(
        session.exec(select(SourceConfig).where(SourceConfig.name == "Dup Portal")).all()
    )
    assert len(sources) == 2

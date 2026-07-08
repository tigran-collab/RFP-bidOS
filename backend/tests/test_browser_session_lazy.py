"""Assert the browser/PlanetBids modules import and degrade without Playwright.

Playwright is an optional, heavy dependency. The app and full test suite must
import and pass even when it is absent. These tests simulate the "not installed"
case by forcing the lazy import to fail, then assert:

  * the modules are already importable (they import fine regardless),
  * playwright_available() reports False,
  * the browser helpers raise a clear PlaywrightNotInstalledError,
  * the PlanetBids adapter degrades to [] with a diagnostic instead of crashing.
"""

import builtins
import json
from types import SimpleNamespace

import pytest

from app.services.scrapers import browser_session, planetbids
from app.services.scrapers.browser_session import PlaywrightNotInstalledError


@pytest.fixture
def no_playwright(monkeypatch):
    """Make any `import playwright...` raise ImportError."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "playwright" or name.startswith("playwright."):
            raise ImportError("simulated: playwright not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_modules_are_importable_without_playwright():
    # These imports already succeeded at module top; assert the key symbols
    # exist so a lazy-import regression that moved a top-level import is caught.
    assert hasattr(browser_session, "playwright_available")
    assert hasattr(browser_session, "assisted_login")
    assert hasattr(browser_session, "fetch_authenticated_json")
    assert hasattr(browser_session, "download_document_links_headed")
    assert hasattr(planetbids, "PlanetBidsAuthAdapter")


def test_playwright_available_false_when_missing(no_playwright):
    assert browser_session.playwright_available() is False


def test_helpers_raise_clear_error_when_missing(no_playwright):
    with pytest.raises(PlaywrightNotInstalledError):
        browser_session.assisted_login("https://example.gov", "/tmp/does-not-matter")
    with pytest.raises(PlaywrightNotInstalledError):
        browser_session.fetch_authenticated_json(
            "https://example.gov/api", "/tmp/does-not-matter"
        )
    with pytest.raises(PlaywrightNotInstalledError):
        browser_session.download_document_links_headed(
            "https://example.gov/bid",
            "/tmp/does-not-matter",
            "/tmp/downloads",
        )


def test_profile_lock_is_stable_per_dir():
    # The per-profile lock serializes concurrent persistent-context launches on
    # the same on-disk profile (assisted login vs a scrape/portal download). The
    # same dir must always return the SAME lock; different dirs get distinct ones.
    lock_a = browser_session._profile_lock("/tmp/profiles/1")
    lock_a_again = browser_session._profile_lock("/tmp/profiles/1/")
    lock_b = browser_session._profile_lock("/tmp/profiles/2")
    assert lock_a is lock_a_again
    assert lock_a is not lock_b


def test_adapter_degrades_when_playwright_missing(no_playwright):
    source = SimpleNamespace(
        id=7,
        source_type="planetbids",
        name="PB",
        config_json=json.dumps({"cid": 555, "field_map": {"title": "title"}}),
    )
    adapter = planetbids.PlanetBidsAuthAdapter()
    results = adapter.scrape(source)
    assert results == []
    assert any("playwright is not installed" in d.lower() for d in adapter.diagnostics)

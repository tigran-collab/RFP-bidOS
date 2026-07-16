"""The scrape pipeline must never ingest bids from outside the CA/TX region.

A source with a definite out-of-region state tag (NV, AZ) is skipped before any
candidate is fetched. A source with no state (a multi-state aggregator) or an
in-region state proceeds normally.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from app import models  # noqa: F401  (register tables)
from app.services import scraper


@pytest.fixture
def in_memory_engine(monkeypatch):
    # scrape_source opens `with Session(engine)` for the (here empty) ingest
    # loop; point it at an isolated in-memory DB so tests never touch the real
    # data file.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(scraper, "engine", engine, raising=True)
    return engine


def _source(**overrides):
    fields = dict(
        id=1,
        name="Test Source",
        source_type="public_page",
        base_url="https://example.gov/bids",
        state=None,
        enabled=True,
        requires_credentials=False,
        login_url=None,
        config_json=None,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_scrape_skips_out_of_region_source(monkeypatch):
    called = False

    def fake_scrape_candidates(*a, **k):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(scraper, "_scrape_candidates", fake_scrape_candidates)

    result = scraper.scrape_source(_source(state="NV"))

    assert called is False
    assert result["created_count"] == 0
    assert any("outside the operating region" in e for e in result["errors"])
    assert any("CA/TX" in e for e in result["errors"])


def test_preview_skips_out_of_region_source(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("out-of-region source must not be scraped")

    monkeypatch.setattr(scraper, "_scrape_candidates", boom)

    result = scraper.preview_source(_source(state="Arizona"))

    assert any("outside the operating region" in e for e in result["errors"])


def test_scrape_allows_in_region_source(monkeypatch, in_memory_engine):
    seen = {}

    def fake_scrape_candidates(source_config, result, detail_limit=None):
        seen["called"] = True
        return []

    monkeypatch.setattr(scraper, "_scrape_candidates", fake_scrape_candidates)

    result = scraper.scrape_source(_source(state="CA"))

    assert seen.get("called") is True
    assert not any("outside the operating region" in e for e in result["errors"])


def test_scrape_allows_stateless_aggregator(monkeypatch, in_memory_engine):
    # BidNet-style aggregators carry no single state and must still be scraped;
    # their per-candidate CA/TX filtering happens in the adapter.
    seen = {}

    def fake_scrape_candidates(source_config, result, detail_limit=None):
        seen["called"] = True
        return []

    monkeypatch.setattr(scraper, "_scrape_candidates", fake_scrape_candidates)

    result = scraper.scrape_source(
        _source(state=None, name="BidNet Direct", source_type="authenticated_browser")
    )

    assert seen.get("called") is True
    assert not any("outside the operating region" in e for e in result["errors"])

"""The /sources/scrape-enabled batch continues past a failing source, recording
the error, while single-source scrape keeps its 502 behavior."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  (register tables)
from app.main import app
from app.models import SourceConfig


@pytest.fixture
def sources_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.routers.sources.engine", engine, raising=True)
    client = TestClient(app)
    client._engine = engine
    return client


def _seed_sources(engine, names):
    ids = {}
    with Session(engine) as session:
        for name in names:
            source = SourceConfig(name=name, source_type="public_page", enabled=True)
            session.add(source)
            session.commit()
            session.refresh(source)
            ids[name] = source.id
    return ids


def _ok_result():
    return {
        "records_found": 1,
        "created_count": 1,
        "updated_count": 0,
        "skipped_duplicates": 0,
        "errors": [],
    }


def test_batch_continues_past_failing_source(sources_client, monkeypatch):
    _seed_sources(sources_client._engine, ["Bad Source", "Good Source"])

    def fake_scrape(source):
        if source.name == "Bad Source":
            raise RuntimeError("boom")
        return _ok_result()

    monkeypatch.setattr("app.routers.sources.scrape_source", fake_scrape)

    response = sources_client.post("/sources/scrape-enabled")
    assert response.status_code == 200
    summary = response.json()

    # The good source still ran and its counts were aggregated.
    assert summary["sources_scraped"] == 1
    assert summary["created_count"] == 1

    # The failing source is recorded, not fatal.
    assert any("Bad Source" in error for error in summary["errors"])
    error_entries = [r for r in summary["results"] if r.get("error")]
    assert len(error_entries) == 1
    assert error_entries[0]["source"] == "Bad Source"


def test_single_source_scrape_still_502_on_failure(sources_client, monkeypatch):
    ids = _seed_sources(sources_client._engine, ["Bad Source"])

    def fake_scrape(source):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.routers.sources.scrape_source", fake_scrape)

    response = sources_client.post(f"/sources/{ids['Bad Source']}/scrape")
    assert response.status_code == 502

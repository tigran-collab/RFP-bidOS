"""Exports router: a filter on a nonexistent opportunity returns 404 instead of
a header-only file."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  (register tables)
from app.main import app
from app.models import Opportunity


@pytest.fixture
def export_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.routers.exports.engine", engine, raising=True)
    client = TestClient(app)
    client._engine = engine
    return client


@pytest.mark.parametrize(
    "path",
    [
        "/exports/requirements.csv",
        "/exports/documents.csv",
        "/exports/logistics-qa.csv",
        "/exports/deadlines.ics",
    ],
)
def test_unknown_opportunity_id_is_404(export_client, path):
    response = export_client.get(path, params={"opportunity_id": 99999})
    assert response.status_code == 404


def test_existing_opportunity_id_returns_csv(export_client):
    with Session(export_client._engine) as session:
        opp = Opportunity(title="Guard Services", review_status="New")
        session.add(opp)
        session.commit()
        session.refresh(opp)
        opp_id = opp.id

    response = export_client.get(
        "/exports/documents.csv", params={"opportunity_id": opp_id}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")


def test_unfiltered_export_still_returns_csv(export_client):
    response = export_client.get("/exports/requirements.csv")
    assert response.status_code == 200

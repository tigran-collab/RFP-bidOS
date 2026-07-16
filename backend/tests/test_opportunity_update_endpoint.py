"""The generic PATCH editor must record human review decisions.

The frontend detail-page editor saves review_status through the generic
PATCH /opportunities/{id} (not /review). Without a reviewed_at stamp the
daily run's scorer treats that human decision as automated and may force
the row to "Do Not Pursue" (scorer.apply_scored_review_status).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  (register tables)
from app.main import app
from app.models import Opportunity


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.routers.opportunities.engine", engine, raising=True)
    test_client = TestClient(app)
    test_client._engine = engine
    return test_client


def _seed(client) -> int:
    with Session(client._engine) as session:
        opportunity = Opportunity(title="Security Guard Services")
        session.add(opportunity)
        session.commit()
        session.refresh(opportunity)
        return opportunity.id


def test_patch_review_status_stamps_reviewed_at(client):
    opportunity_id = _seed(client)

    response = client.patch(
        f"/opportunities/{opportunity_id}", json={"review_status": "Needs Review"}
    )

    assert response.status_code == 200
    with Session(client._engine) as session:
        row = session.get(Opportunity, opportunity_id)
        assert row.review_status == "Needs Review"
        assert row.reviewed_at is not None


def test_patch_without_review_status_does_not_stamp_reviewed_at(client):
    opportunity_id = _seed(client)

    response = client.patch(
        f"/opportunities/{opportunity_id}", json={"notes": "Checked the site."}
    )

    assert response.status_code == 200
    with Session(client._engine) as session:
        row = session.get(Opportunity, opportunity_id)
        assert row.notes == "Checked the site."
        assert row.reviewed_at is None

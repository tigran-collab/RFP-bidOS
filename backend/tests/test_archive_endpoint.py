"""The archive-past-deadlines endpoint wires the archiver into the API so a
UI-only operator can clear expired bids on demand (non-destructive)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  (register tables)
from app.models import Opportunity
from app.routers import opportunities as opp_router


@pytest.fixture
def engine(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(opp_router, "engine", engine, raising=True)
    return engine


def test_archive_endpoint_archives_expired_and_leaves_active(engine):
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(engine) as session:
        expired = Opportunity(
            title="Expired RFP",
            review_status="Needs Review",
            due_date=now - timedelta(days=2),
        )
        active = Opportunity(
            title="Future RFP",
            review_status="Pursue",
            due_date=now + timedelta(days=10),
        )
        session.add_all([expired, active])
        session.commit()
        expired_id, active_id = expired.id, active.id

    result = opp_router.archive_past_deadlines()

    assert result["archived_count"] == 1
    with Session(engine) as session:
        assert session.get(Opportunity, expired_id).review_status == "Archived"
        assert session.get(Opportunity, active_id).review_status == "Pursue"

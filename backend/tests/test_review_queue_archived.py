"""The review queue hides Archived opportunities unless explicitly requested.

Archived bids belong on the dedicated "Archived" tab; they must not clutter the
default working queue, but asking for status="Archived" still returns them.
"""

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
    with Session(engine) as session:
        session.add_all(
            [
                Opportunity(title="Active New", review_status="New"),
                Opportunity(title="Active Pursue", review_status="Pursue"),
                Opportunity(title="Old Expired", review_status="Archived"),
            ]
        )
        session.commit()
    return engine


def _titles(rows):
    return {row["title"] for row in rows}


def _queue(**overrides):
    # review_queue's signature uses FastAPI Query(...) defaults, which are not
    # None when the function is called directly; pass every param explicitly.
    params = dict(
        status=None,
        priority=None,
        state=None,
        min_score=None,
        max_score=None,
        service_type=None,
        source_id=None,
        deadline_risk=None,
        qa_risk=None,
        sort=None,
        direction=None,
    )
    params.update(overrides)
    return opp_router.review_queue(**params)


def test_default_queue_excludes_archived(engine):
    rows = _queue()
    assert _titles(rows) == {"Active New", "Active Pursue"}


def test_status_archived_returns_only_archived(engine):
    rows = _queue(status="Archived")
    assert _titles(rows) == {"Old Expired"}


def test_status_filter_still_scopes_to_a_single_active_status(engine):
    rows = _queue(status="Pursue")
    assert _titles(rows) == {"Active Pursue"}

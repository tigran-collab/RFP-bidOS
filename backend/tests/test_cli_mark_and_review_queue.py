"""CLI regression tests: mark-opportunity validates choice fields (invalid
values would otherwise poison every opportunity read endpoint), and
review-queue sorts without touching .timestamp() on sentinel datetimes."""

from datetime import datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from typer.testing import CliRunner

from app import models  # noqa: F401  (register tables)
from app.cli import cli
from app.models import Opportunity

runner = CliRunner()


@pytest.fixture
def cli_engine(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.cli.engine", engine, raising=True)
    return engine


def _seed(engine, **kwargs):
    defaults = dict(title="Guard Services", review_status="New")
    defaults.update(kwargs)
    with Session(engine) as session:
        opp = Opportunity(**defaults)
        session.add(opp)
        session.commit()
        session.refresh(opp)
        return opp.id


# ---------------------------------------------------------------------------
# mark-opportunity choice validation
# ---------------------------------------------------------------------------
def test_mark_opportunity_rejects_invalid_review_status(cli_engine):
    opp_id = _seed(cli_engine)
    result = runner.invoke(
        cli, ["mark-opportunity", str(opp_id), "--status", "Totally Bogus"]
    )
    assert result.exit_code == 1
    with Session(cli_engine) as session:
        assert session.get(Opportunity, opp_id).review_status == "New"


def test_mark_opportunity_rejects_invalid_priority(cli_engine):
    opp_id = _seed(cli_engine)
    result = runner.invoke(
        cli, ["mark-opportunity", str(opp_id), "--priority", "Urgent"]
    )
    assert result.exit_code == 1
    with Session(cli_engine) as session:
        assert session.get(Opportunity, opp_id).priority is None


def test_mark_opportunity_rejects_invalid_next_action(cli_engine):
    opp_id = _seed(cli_engine)
    result = runner.invoke(
        cli, ["mark-opportunity", str(opp_id), "--next-action", "Do Stuff"]
    )
    assert result.exit_code == 1
    with Session(cli_engine) as session:
        assert session.get(Opportunity, opp_id).next_action is None


def test_mark_opportunity_accepts_valid_choices(cli_engine):
    opp_id = _seed(cli_engine)
    result = runner.invoke(
        cli,
        [
            "mark-opportunity",
            str(opp_id),
            "--status",
            "Pursue",
            "--priority",
            "High",
            "--next-action",
            "Manual Review",
        ],
    )
    assert result.exit_code == 0
    with Session(cli_engine) as session:
        opp = session.get(Opportunity, opp_id)
        assert opp.review_status == "Pursue"
        assert opp.priority == "High"
        assert opp.next_action == "Manual Review"


# ---------------------------------------------------------------------------
# review-queue sort
# ---------------------------------------------------------------------------
def test_review_queue_sorts_status_then_due_date(cli_engine):
    _seed(cli_engine, title="New early due", review_status="New",
          due_date=datetime(2026, 7, 5))
    _seed(cli_engine, title="Pursue no due", review_status="Pursue")
    _seed(cli_engine, title="Pursue soon", review_status="Pursue",
          due_date=datetime(2026, 7, 10))

    result = runner.invoke(cli, ["review-queue"])
    assert result.exit_code == 0

    positions = {
        name: result.output.find(name)
        for name in ("Pursue soon", "Pursue no due", "New early due")
    }
    assert all(pos >= 0 for pos in positions.values())
    assert positions["Pursue soon"] < positions["Pursue no due"] < positions["New early due"]

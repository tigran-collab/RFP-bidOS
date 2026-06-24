"""Tests for the read-only local-chat context builder.

Uses the in-memory `session` fixture so no real data is touched.
"""

from datetime import datetime, timedelta

from app.models import Opportunity
from app.services.local_chat_context import (
    DEFAULT_CONTEXT_LIMIT,
    MAX_LIMIT,
    _bounded_limit,
    build_chat_context,
    context_summary,
    infer_context_mode,
)


def _seed(session, n=3):
    for i in range(n):
        session.add(
            Opportunity(
                title=f"Security Guard Services {i}",
                agency="County",
                location="San Jose, CA",
                due_date=datetime.utcnow() + timedelta(days=10 + i),
                review_status="New",
            )
        )
    session.commit()


def test_app_overview_context_counts_opportunities(session):
    _seed(session, 3)
    context = build_chat_context(session, "summarize opportunities", {"mode": "app_overview"})
    assert context["mode"] == "app_overview"
    assert context["opportunity_count"] == 3
    assert context["read_only"] is True


def test_context_summary_shape():
    summary = context_summary({"mode": "pursuit", "opportunity_count": 7})
    assert summary == {
        "mode": "pursuit",
        "opportunity_count": 7,
        "included_requirements": False,
        "included_documents": False,
        "read_only": True,
    }


def test_infer_context_mode_deadlines():
    assert infer_context_mode("which deadlines are coming up?") == "deadlines"


def test_infer_context_mode_opportunity_when_id_present():
    assert infer_context_mode("anything", {"opportunity_id": 5}) == "opportunity"


def test_bounded_limit_clamps_and_defaults():
    assert _bounded_limit("not-a-number") == DEFAULT_CONTEXT_LIMIT
    assert _bounded_limit(99999) == MAX_LIMIT
    assert _bounded_limit(5) == 5
    assert _bounded_limit(0) == 1  # floor at 1

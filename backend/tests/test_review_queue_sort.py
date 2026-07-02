"""Tests for the review-queue multi-field sort (_apply_sort).

Covers sort by bid score / relevance / deadline / created, direction override,
and that missing values always sort last regardless of direction.
"""

from datetime import datetime, timedelta

from app.models import Opportunity
from app.routers.opportunities import _apply_sort


def _opp(title, **kw):
    return Opportunity(title=title, **kw)


def test_sort_by_score_desc_default_nulls_last():
    a = _opp("a", bid_score=10.0)
    b = _opp("b", bid_score=50.0)
    c = _opp("c", bid_score=None)
    items = [a, c, b]
    _apply_sort(items, "score", None)  # default desc
    assert [o.title for o in items] == ["b", "a", "c"]


def test_direction_override_asc():
    a = _opp("a", bid_score=10.0)
    b = _opp("b", bid_score=50.0)
    c = _opp("c", bid_score=None)
    items = [a, c, b]
    _apply_sort(items, "score", "asc")
    # ascending by score, missing still last
    assert [o.title for o in items] == ["a", "b", "c"]


def test_sort_by_relevance_desc():
    a = _opp("a", relevance_score=20)
    b = _opp("b", relevance_score=160)
    items = [a, b]
    _apply_sort(items, "relevance", None)
    assert [o.title for o in items] == ["b", "a"]


def test_sort_by_deadline_default_soonest_first_nulls_last():
    now = datetime(2026, 7, 2)
    soon = _opp("soon", due_date=now + timedelta(days=2))
    later = _opp("later", due_date=now + timedelta(days=30))
    none_due = _opp("none", due_date=None)
    items = [later, none_due, soon]
    _apply_sort(items, "deadline", None)  # default asc (soonest first)
    assert [o.title for o in items] == ["soon", "later", "none"]


def test_unknown_sort_falls_back_to_default_without_crashing():
    a = _opp("a", bid_score=1.0)
    b = _opp("b", bid_score=2.0)
    items = [a, b]
    _apply_sort(items, "bogus", None)  # unknown -> historical review ordering
    assert len(items) == 2

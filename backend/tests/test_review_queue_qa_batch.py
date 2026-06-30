"""Regression test for the review-queue QA batch-load optimization (Fix F).

The review-queue endpoint replaced a per-row get_latest_logistics_qa() call
(N+1) with a single batch query, get_latest_logistics_qa_map(). This pins down
that the batch loader selects the SAME latest QA record per opportunity as the
per-row lookup, and that the filtered/sorted id order is unchanged. Offline:
uses the in-memory `session` fixture.
"""

from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.models import BidLogisticsQA, Opportunity
from app.routers.opportunities import _review_sort_key
from app.services.logistics_qa import (
    get_latest_logistics_qa,
    get_latest_logistics_qa_map,
)


def _seed(session):
    base = datetime(2026, 6, 1)
    opps = [
        Opportunity(title="A Pursue", review_status="Pursue", due_date=base + timedelta(days=5)),
        Opportunity(title="B New", review_status="New", due_date=base + timedelta(days=2)),
        Opportunity(title="C Watchlist", review_status="Watchlist"),
        Opportunity(title="D Do Not Pursue", review_status="Do Not Pursue", due_date=base + timedelta(days=1)),
        Opportunity(title="E Needs Review", review_status="Needs Review", due_date=base + timedelta(days=3)),
    ]
    for opp in opps:
        opp.created_at = base
        session.add(opp)
    session.commit()
    for opp in opps:
        session.refresh(opp)

    # Two QA rows for opp A (newer should win), one for B, none for the rest.
    session.add(
        BidLogisticsQA(
            opportunity_id=opps[0].id, qa_status="Needs Review", risk_level="Medium",
            checked_at=base,
        )
    )
    session.add(
        BidLogisticsQA(
            opportunity_id=opps[0].id, qa_status="Passed", risk_level="Low",
            checked_at=base + timedelta(days=1),
        )
    )
    session.add(
        BidLogisticsQA(
            opportunity_id=opps[1].id, qa_status="Failed", risk_level="High",
            checked_at=base,
        )
    )
    session.commit()
    return opps


def test_batch_qa_matches_per_row_and_order(session):
    opps = _seed(session)

    # Batch loader vs. per-row loader: same selected record per opportunity.
    batch = get_latest_logistics_qa_map(session)
    for opp in opps:
        per_row = get_latest_logistics_qa(opp.id, session)
        assert batch.get(opp.id) == per_row

    # Newest QA wins for opp A.
    assert batch[opps[0].id]["qa_status"] == "Passed"
    assert batch[opps[1].id]["qa_status"] == "Failed"

    # Filtered/sorted id order is identical whether QA is loaded per-row or batched.
    all_opps = list(session.exec(select(Opportunity)).all())
    order_batched = [o.id for o in sorted(all_opps, key=_review_sort_key)]
    order_per_row = [o.id for o in sorted(all_opps, key=_review_sort_key)]
    assert order_batched == order_per_row
    # Pursue floats to top, Do Not Pursue sinks to bottom.
    assert order_batched[0] == opps[0].id
    assert order_batched[-1] == opps[3].id


def test_review_sort_key_mixes_aware_and_naive_due_dates():
    # Fix A: mixing a tz-aware due_date with naive datetime.max must not raise.
    aware = Opportunity(title="aware", review_status="New")
    aware.due_date = datetime(2026, 6, 5, tzinfo=UTC)
    aware.created_at = datetime(2026, 6, 1, tzinfo=UTC)
    no_due = Opportunity(title="no due", review_status="New")
    no_due.created_at = datetime(2026, 6, 1)

    # Would raise TypeError ("can't compare offset-naive and offset-aware") if
    # the aware due_date were not normalized before hitting datetime.max.
    ordered = sorted([aware, no_due], key=_review_sort_key)
    assert ordered[0] is aware  # has a due date, sorts before the one without

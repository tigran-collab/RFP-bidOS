"""Tests for the notification digest service.

Offline: uses the in-memory `session` fixture. Seeds opportunities covering
each bucket and asserts the digest lists contain exactly the expected ids.
"""

from datetime import UTC, datetime, timedelta

from app.models import Opportunity
from app.services.notifications import build_digest, render_digest_text


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _seed(session):
    now = _utc_now()
    opps = {
        # Brand-new Relevant -> new_opportunities.
        "new_relevant": Opportunity(
            title="Brand New Relevant Guard RFP",
            agency="City A",
            relevance_decision="Relevant",
            review_status="New",
            created_at=now - timedelta(hours=1),
        ),
        # Not Relevant -> excluded from new_opportunities.
        "not_relevant": Opportunity(
            title="New Janitorial Contract",
            agency="City B",
            relevance_decision="Not Relevant",
            review_status="New",
            created_at=now - timedelta(hours=2),
        ),
        # Due in 3 days -> upcoming_deadlines (and is also Relevant + new).
        "due_soon": Opportunity(
            title="Due Soon Security Services",
            agency="County C",
            relevance_decision="Relevant",
            review_status="Needs Review",
            created_at=now - timedelta(hours=3),
            due_date=now + timedelta(days=3),
        ),
        # Past due -> at_risk, excluded from upcoming_deadlines.
        "past_due": Opportunity(
            title="Past Due Patrol RFP",
            agency="City D",
            relevance_decision="Relevant",
            review_status="Pursue",
            created_at=now - timedelta(days=2),
            due_date=now - timedelta(days=2),
        ),
        # Archived -> excluded everywhere.
        "archived": Opportunity(
            title="Archived Relevant RFP",
            agency="City E",
            relevance_decision="Relevant",
            review_status="Archived",
            created_at=now - timedelta(hours=1),
            due_date=now + timedelta(days=2),
        ),
        # Do Not Pursue with near deadline -> excluded from deadlines/at_risk.
        "do_not_pursue": Opportunity(
            title="Do Not Pursue Security RFP",
            agency="City F",
            relevance_decision="Relevant",
            review_status="Do Not Pursue",
            created_at=now - timedelta(days=2),
            due_date=now + timedelta(days=2),
        ),
    }
    for opp in opps.values():
        session.add(opp)
    session.commit()
    for opp in opps.values():
        session.refresh(opp)
    return opps


def test_new_opportunities_bucket(session):
    opps = _seed(session)
    digest = build_digest(session, days=7)
    ids = {item["id"] for item in digest["new_opportunities"]}
    # Relevant + recent + not archived/DNP-excluded-from-new.
    # do_not_pursue is only excluded from deadlines/at_risk, not from new (but
    # it was created 2 days ago which is within window, and is Relevant).
    assert opps["new_relevant"].id in ids
    assert opps["due_soon"].id in ids
    assert opps["past_due"].id in ids
    assert opps["do_not_pursue"].id in ids
    # Not Relevant and Archived are excluded.
    assert opps["not_relevant"].id not in ids
    assert opps["archived"].id not in ids


def test_upcoming_deadlines_bucket(session):
    opps = _seed(session)
    digest = build_digest(session, days=7)
    ids = {item["id"] for item in digest["upcoming_deadlines"]}
    assert ids == {opps["due_soon"].id}
    # Archived and Do Not Pursue are excluded even with near deadlines.
    assert opps["archived"].id not in ids
    assert opps["do_not_pursue"].id not in ids
    # Past due is not "upcoming".
    assert opps["past_due"].id not in ids
    item = digest["upcoming_deadlines"][0]
    assert item["days_until"] == 2 or item["days_until"] == 3


def test_at_risk_bucket(session):
    opps = _seed(session)
    digest = build_digest(session, days=7)
    ids = {item["id"] for item in digest["at_risk"]}
    assert ids == {opps["past_due"].id}


def test_counts_and_render(session):
    opps = _seed(session)
    digest = build_digest(session, days=7)
    counts = digest["counts"]
    assert counts["new_opportunities"] == len(digest["new_opportunities"])
    assert counts["upcoming_deadlines"] == len(digest["upcoming_deadlines"])
    assert counts["at_risk"] == len(digest["at_risk"])
    # active = all non-archived.
    assert counts["active_opportunities"] == 5

    text = render_digest_text(digest)
    assert "Due Soon Security Services" in text
    assert "New Opportunities" in text
    assert "Upcoming Deadlines" in text
    assert "At Risk" in text

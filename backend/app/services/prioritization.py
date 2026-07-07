"""
Deterministic opportunity prioritization (NO AI, no network).

Blends existing triage signals into a single 0-100 rank and a High/Medium/Low
tier so the operator can see which bids to work first. Everything here is a
pure rules/heuristics computation over fields already on the Opportunity row.

Weighting (all components sum to a nominal 0-100 before gates/penalties):
  * Relevance        ~0-40  relevance_decision (+ relevance_score signal)
  * Deadline urgency ~0-30  days until due_date (past due / missing handled)
  * Fit              ~0-20  normalized bid_score (negatives clamped to 0)
  * As-needed        -5     small penalty when as_needed_warning is set
  * Review-status gate:
      "Do Not Pursue"/"Archived" -> rank forced very low (<=5)
      "Pursue"                   -> small boost (+5)
      "Watchlist"                -> neutral
The final rank is clamped to [0, 100]. Tier: >=60 High, >=30 Medium, else Low.
"""

from datetime import datetime

from sqlmodel import Session, select

from app.models import Opportunity
from app.utils.dates import to_naive_utc

# Component weight ceilings.
RELEVANCE_MAX = 40.0
DEADLINE_MAX = 30.0
FIT_MAX = 20.0
AS_NEEDED_PENALTY = 5.0
PURSUE_BOOST = 5.0

# bid_score is roughly a -x..100 heuristic; treat 100 as a full-fit ceiling.
BID_SCORE_FULL = 100.0


def _utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC).replace(tzinfo=None)


def _relevance_component(opportunity: Opportunity, reasons: list[str]) -> float:
    decision = (opportunity.relevance_decision or "").strip().lower()
    if decision == "relevant":
        base = RELEVANCE_MAX
        reasons.append("Relevant match")
    elif decision == "maybe relevant":
        base = RELEVANCE_MAX * 0.5
        reasons.append("Maybe relevant")
    else:
        base = RELEVANCE_MAX * 0.15
        if decision:
            reasons.append("Low relevance")

    # Factor the numeric relevance_score (0-100) if present: scale the base
    # by how strong the scraper signal was, but never drop below 60% of base
    # so a strong decision still counts.
    score = opportunity.relevance_score
    if score is not None:
        fraction = max(0.0, min(float(score), 100.0)) / 100.0
        base = base * (0.6 + 0.4 * fraction)
    return base


def _deadline_component(opportunity: Opportunity, now: datetime, reasons: list[str]) -> float:
    due = opportunity.due_date
    if not due:
        # Missing due date: small neutral credit, not zero.
        reasons.append("No due date")
        return DEADLINE_MAX * 0.2

    days = (to_naive_utc(due) - now).total_seconds() / 86400.0
    if days < 0:
        reasons.append("Past due")
        return 0.0
    if days <= 3:
        reasons.append(f"Due in {int(round(days))} days")
        return DEADLINE_MAX
    if days <= 7:
        reasons.append(f"Due in {int(round(days))} days")
        return DEADLINE_MAX * 0.8
    if days <= 14:
        reasons.append(f"Due in {int(round(days))} days")
        return DEADLINE_MAX * 0.55
    if days <= 30:
        reasons.append(f"Due in {int(round(days))} days")
        return DEADLINE_MAX * 0.3
    reasons.append("Due in over 30 days")
    return DEADLINE_MAX * 0.1


def _fit_component(opportunity: Opportunity, reasons: list[str]) -> float:
    score = opportunity.bid_score
    if score is None:
        return 0.0
    clamped = max(0.0, min(float(score), BID_SCORE_FULL))
    fit = (clamped / BID_SCORE_FULL) * FIT_MAX
    if fit >= FIT_MAX * 0.75:
        reasons.append("Strong bid-score fit")
    return fit


def compute_priority(opportunity: Opportunity, now: datetime) -> dict:
    """Return a deterministic {rank, tier, reasons} for one opportunity.

    ``now`` must be a naive-UTC datetime so deadline math stays consistent.
    """
    reasons: list[str] = []

    rank = (
        _relevance_component(opportunity, reasons)
        + _deadline_component(opportunity, now, reasons)
        + _fit_component(opportunity, reasons)
    )

    if opportunity.as_needed_warning:
        rank -= AS_NEEDED_PENALTY
        reasons.append("As-needed caution")

    # Review-status gate takes precedence over the blended score.
    status = (opportunity.review_status or "New").strip()
    if status in {"Do Not Pursue", "Archived"}:
        rank = min(rank, 5.0)
        reasons.append(f"{status} (deprioritized)")
    elif status == "Pursue":
        rank += PURSUE_BOOST
        reasons.append("Marked Pursue")
    elif status == "Watchlist":
        reasons.append("On watchlist")

    rank = max(0.0, min(rank, 100.0))
    rank = round(rank, 1)

    if rank >= 60:
        tier = "High"
    elif rank >= 30:
        tier = "Medium"
    else:
        tier = "Low"

    return {"rank": rank, "tier": tier, "reasons": reasons}


def apply_priority_to_all(session: Session, now: datetime | None = None) -> int:
    """Compute and persist priority_rank/priority_tier for every opportunity.

    Uses a single naive-UTC ``now`` so all deadline comparisons are consistent
    within the run. Commits once and returns the number updated.
    """
    now = now or _utc_now()
    opportunities = list(session.exec(select(Opportunity)).all())
    for opportunity in opportunities:
        result = compute_priority(opportunity, now)
        opportunity.priority_rank = result["rank"]
        opportunity.priority_tier = result["tier"]
        session.add(opportunity)
    session.commit()
    return len(opportunities)

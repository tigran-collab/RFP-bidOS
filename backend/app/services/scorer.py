import re
from datetime import datetime
from typing import Any

from app.utils.dates import days_until_date
from app.services.scrapers.keywords import (
    AS_NEEDED_WARNING_KEYWORDS,
    NEGATIVE_KEYWORDS,
    PRIMARY_SECURITY_KEYWORDS,
    SECONDARY_SECURITY_KEYWORDS,
    matches_federal_scope,
)

SECURITY_TERMS = (
    "security",
    "guard",
    "guards",
    "protective",
    "protection",
    "surveillance",
)
SPECIALTY_SECURITY_TERMS = (
    "armed",
    "unarmed",
    "patrol",
    "facility",
    "facilities",
    "courthouse",
    "court house",
    "healthcare",
    "hospital",
    "medical center",
)
PREFERRED_STATE_CODES = ("ca", "tx", "nv", "az")
PREFERRED_STATE_NAMES = ("california", "texas", "nevada", "arizona")
LICENSE_TERMS = ("bsis", "ppo", "private patrol operator", "guard card")
AS_NEEDED_TERMS = (
    *AS_NEEDED_WARNING_KEYWORDS,
    "no guarantee",
)
GUARANTEE_TERMS = (
    "guaranteed minimum",
    "minimum guarantee",
    "minimum hours",
    "not-to-exceed",
)
PUBLIC_AGENCY_TERMS = (
    "city",
    "county",
    "state",
    "public",
    "department",
    "district",
    "authority",
    "university",
    "school",
)
MULTI_SITE_TERMS = ("multi-site", "multisite", "multiple sites", "various sites", "locations")
LOW_BURDEN_TERMS = ("quote", "informal", "short form", "simple response")
BONDING_TERMS = ("bond", "bonding", "performance bond", "payment bond")
INSURANCE_TERMS = ("excess insurance", "high insurance", "umbrella", "additional insured")
UNCLEAR_TERMS = ("unclear", "tbd", "to be determined", "unknown", "varies")
HEAVY_PROPOSAL_TERMS = ("technical proposal", "management plan", "transition plan", "oral presentation")
NON_SECURITY_TERMS = (
    "non-security",
    "non security",
    *NEGATIVE_KEYWORDS,
)


def score_opportunity_text(opportunity: Any) -> dict[str, Any]:
    text = _opportunity_text(opportunity)
    score = 0
    positive_factors: list[str] = []
    negative_factors: list[str] = []
    verification_needed: list[str] = []
    disqualified = False

    targeted_security_match = _has_any(
        text, (*PRIMARY_SECURITY_KEYWORDS, *SECONDARY_SECURITY_KEYWORDS)
    )
    non_security_match = _has_any(text, NON_SECURITY_TERMS)
    federal_scope_match = bool(matches_federal_scope(text))
    # The terminal auto-exclusion flag keys off the fields that identify the
    # ISSUER. A federal mention in the description or an operator note (e.g.
    # "confirmed this is NOT a federal agency") still penalizes the score,
    # but must never flip a row to Do Not Pursue unattended.
    federal_identity_match = bool(matches_federal_scope(_identity_text(opportunity)))
    security_match = (
        _has_any(text, SECURITY_TERMS)
        or targeted_security_match
        or getattr(opportunity, "relevance_decision", None) in {"Relevant", "Maybe Relevant"}
    ) and not (non_security_match and not targeted_security_match)
    if security_match:
        score += 30
        positive_factors.append("Security services match")
    else:
        score -= 50
        negative_factors.append("Non-security opportunity")

    if _has_any(text, SPECIALTY_SECURITY_TERMS):
        score += 15
        positive_factors.append("Specific guard or facility security scope")

    if targeted_security_match:
        score += 20
        positive_factors.append("Target security keyword match")

    if federal_scope_match:
        score -= 200
        disqualified = True
        negative_factors.append("Federal opportunity outside state/local scope")
        verification_needed.append("Exclude federal bids from pursuit surfaces")

    relevance_score = getattr(opportunity, "relevance_score", None)
    if relevance_score is not None and relevance_score >= 40:
        score += 10
        positive_factors.append("Scraper relevance signal")

    if _location_matches(getattr(opportunity, "location", None)):
        score += 15
        positive_factors.append("Preferred operating location")

    due_date = getattr(opportunity, "due_date", None)
    if due_date:
        score += 10
        positive_factors.append("Due date found")
        if _days_until(due_date) <= 7:
            score -= 25
            negative_factors.append("Due date too close")
    else:
        score -= 20
        negative_factors.append("Due date missing")
        verification_needed.append("Confirm proposal due date")

    if _has_any(text, LICENSE_TERMS):
        score += 15
        positive_factors.append("License terms appear aligned")
    elif security_match:
        score -= 75
        negative_factors.append("Required license not held or unclear")
        verification_needed.append("Verify BSIS/PPO/Guard Card requirements")

    if security_match:
        score += 10
        positive_factors.append("Guard Owl fit")

    if _has_any(text, PUBLIC_AGENCY_TERMS) or _has_any(text, MULTI_SITE_TERMS):
        score += 10
        positive_factors.append("Public agency or multi-site scope")

    as_needed = _has_any(text, AS_NEEDED_TERMS) or bool(
        getattr(opportunity, "as_needed_warning", False)
    )
    has_strategic_offset = (
        _has_any(text, GUARANTEE_TERMS)
        or _estimated_value(opportunity) >= 250000
        or _has_any(text, LOW_BURDEN_TERMS)
    )
    if as_needed:
        score -= 40
        negative_factors.append("As-needed/on-call scope has uncertain volume")
        if not has_strategic_offset:
            score -= 20
            verification_needed.append("Confirm guaranteed minimum, likely usage, or low response burden")

    if getattr(opportunity, "pre_bid_mandatory", False):
        pre_bid_date = getattr(opportunity, "pre_bid_date", None)
        if pre_bid_date is None or _days_until(pre_bid_date) < 0:
            score -= 100
            disqualified = True
            negative_factors.append("Mandatory pre-bid missed or possibly missed")
            verification_needed.append("Confirm mandatory pre-bid attendance")

    estimated_value = _estimated_value(opportunity)
    if estimated_value and estimated_value < 100000 and _has_any(text, HEAVY_PROPOSAL_TERMS):
        score -= 25
        negative_factors.append("Heavy proposal with low value")

    if _has_any(text, BONDING_TERMS) and _has_any(text, INSURANCE_TERMS):
        score -= 30
        negative_factors.append("Excessive bonding/insurance")
        verification_needed.append("Verify bonding and insurance burden")

    if _has_any(text, UNCLEAR_TERMS) or (
        security_match and as_needed and not has_strategic_offset
    ):
        score -= 20
        negative_factors.append("Unclear scope or unclear volume")

    decision = _decision(score, disqualified)
    reason = _reason(decision, positive_factors, negative_factors)

    return {
        "score": int(score),
        "decision": decision,
        "reason": reason,
        "positive_factors": positive_factors,
        "negative_factors": negative_factors,
        "verification_needed": verification_needed,
        "suggested_review_status": _suggested_review_status(score, disqualified),
        "hard_exclusion": federal_identity_match,
    }


def _suggested_review_status(score: int, disqualified: bool) -> str:
    """Suggest a review status from the score. Never archives or deletes."""
    if disqualified or score < 0:
        return "Do Not Pursue"
    return "Needs Review"


TERMINAL_REVIEW_STATUSES = {"Do Not Pursue", "Archived"}


def apply_scored_review_status(
    opportunity: Any,
    suggested: str,
    allow_terminal: bool = True,
    force_unreviewed_terminal: bool = False,
) -> None:
    """Apply a suggested review status without overriding a human decision.

    Only updates when the opportunity has not yet been triaged
    (review_status is None or "New").

    When ``allow_terminal`` is False (used by the unattended daily run), an
    untriaged "New" item is never moved straight to a terminal status such as
    "Do Not Pursue"/"Archived" -- it is capped at "Needs Review" so a relevant
    bid scraped from a sparse row cannot silently vanish from every attention
    surface. The default (True) preserves the prior behavior for explicit
    manual/CLI use.
    """
    current = getattr(opportunity, "review_status", None)
    unreviewed_needs_review = (
        force_unreviewed_terminal
        and suggested in TERMINAL_REVIEW_STATUSES
        and current == "Needs Review"
        and getattr(opportunity, "reviewed_at", None) is None
    )
    if current in (None, "", "New") or unreviewed_needs_review:
        if not allow_terminal and suggested in TERMINAL_REVIEW_STATUSES:
            suggested = "Needs Review"
        opportunity.review_status = suggested


def _identity_text(opportunity: Any) -> str:
    """The fields that say WHO issued the opportunity, for hard exclusions."""
    fields = ("title", "agency", "source", "source_url")
    values = [str(getattr(opportunity, field, "") or "") for field in fields]
    return " ".join(values).lower()


def _opportunity_text(opportunity: Any) -> str:
    fields = (
        "title",
        "agency",
        "source",
        "source_url",
        "location",
        "service_type",
        "contract_type",
        "status",
        "description",
        "notes",
        "relevance_decision",
        "relevance_reason",
        "keyword_matches_json",
        "negative_matches_json",
    )
    values = [str(getattr(opportunity, field, "") or "") for field in fields]
    return " ".join(values).lower()


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _location_matches(location: Any) -> bool:
    if not location:
        return False
    location_text = str(location).lower()
    if any(name in location_text for name in PREFERRED_STATE_NAMES):
        return True
    return any(
        re.search(rf"\b{code}\b", location_text) for code in PREFERRED_STATE_CODES
    )


def _days_until(value: datetime) -> int:
    # DATE-granularity so an item due today reads as 0, not -1 in the afternoon.
    return days_until_date(value)


def _estimated_value(opportunity: Any) -> float:
    value = getattr(opportunity, "estimated_value", None)
    if value is None:
        return 0.0
    return float(value)


def _decision(score: int, disqualified: bool) -> str:
    if disqualified or score < 0:
        return "No Bid"
    if score >= 70:
        return "Bid"
    if score >= 45:
        return "Conditional Bid"
    return "Usually No Bid"


def _reason(decision: str, positives: list[str], negatives: list[str]) -> str:
    if negatives:
        return f"{decision}: {negatives[0]}."
    if positives:
        return f"{decision}: {positives[0]}."
    return f"{decision}: limited opportunity detail available."

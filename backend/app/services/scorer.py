from datetime import datetime, timezone
from typing import Any


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
PREFERRED_LOCATIONS = (" ca", "california", " tx", "texas", " nv", "nevada", " az", "arizona")
LICENSE_TERMS = ("bsis", "ppo", "private patrol operator", "guard card")
AS_NEEDED_TERMS = (
    "as-needed",
    "as needed",
    "on-call",
    "on call",
    "standby",
    "no guaranteed minimum",
    "no guarantee",
    "indefinite quantity",
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
    "landscaping",
    "janitorial",
    "construction",
    "paving",
    "food service",
)


def score_opportunity_text(opportunity: Any) -> dict[str, Any]:
    text = _opportunity_text(opportunity)
    score = 0
    positive_factors: list[str] = []
    negative_factors: list[str] = []
    verification_needed: list[str] = []
    disqualified = False

    non_security_match = _has_any(text, NON_SECURITY_TERMS)
    security_match = _has_any(text, SECURITY_TERMS) and not non_security_match
    if security_match:
        score += 30
        positive_factors.append("Security services match")
    else:
        score -= 50
        negative_factors.append("Non-security opportunity")

    if _has_any(text, SPECIALTY_SECURITY_TERMS):
        score += 15
        positive_factors.append("Specific guard or facility security scope")

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

    if security_match and _has_any(text, ("guard owl", "guardowl", "guard management", "mobile patrol")):
        score += 10
        positive_factors.append("Guard Owl fit")
    elif security_match:
        score += 10
        positive_factors.append("Guard Owl fit")

    if _has_any(text, PUBLIC_AGENCY_TERMS) or _has_any(text, MULTI_SITE_TERMS):
        score += 10
        positive_factors.append("Public agency or multi-site scope")

    as_needed = _has_any(text, AS_NEEDED_TERMS)
    has_strategic_offset = (
        _has_any(text, GUARANTEE_TERMS)
        or _estimated_value(opportunity) >= 250000
        or _has_any(text, LOW_BURDEN_TERMS)
    )
    if as_needed:
        score -= 40
        negative_factors.append("As-needed/on-call scope has uncertain volume")
        if not has_strategic_offset:
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
    }


def _suggested_review_status(score: int, disqualified: bool) -> str:
    """Suggest a review status from the score. Never archives or deletes."""
    if disqualified or score < 0:
        return "Do Not Pursue"
    return "Needs Review"


def apply_scored_review_status(opportunity: Any, suggested: str) -> None:
    """Apply a suggested review status without overriding a human decision.

    Only updates when the opportunity has not yet been triaged
    (review_status is None or "New").
    """
    current = getattr(opportunity, "review_status", None)
    if current in (None, "", "New"):
        opportunity.review_status = suggested


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
    )
    values = [str(getattr(opportunity, field, "") or "") for field in fields]
    return " ".join(values).lower()


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _location_matches(location: Any) -> bool:
    if not location:
        return False
    location_text = f" {str(location).lower()} "
    return any(term in location_text for term in PREFERRED_LOCATIONS)


def _days_until(value: datetime) -> int:
    if value.tzinfo is None:
        now = datetime.utcnow()
        delta = value - now
    else:
        now = datetime.now(timezone.utc)
        delta = value.astimezone(timezone.utc) - now
    return delta.days


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

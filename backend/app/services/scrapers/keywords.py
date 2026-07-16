import re
from dataclasses import dataclass


PRIMARY_SECURITY_KEYWORDS = (
    "security guard",
    "security guards",
    "security officer",
    "security officers",
    "armed security",
    "unarmed security",
    "guard services",
    "security services",
    "private security",
    "patrol services",
    "mobile patrol",
    "vehicle patrol",
    "foot patrol",
    "roving patrol",
    "facility security",
    "building security",
    "courthouse security",
    "court security",
    "parking security",
    "campus security",
    "school security",
    "hospital security",
    "healthcare security",
    "public safety officer",
    "fire watch",
    "access control",
    "lobby security",
    "guard post",
    "standing post",
    "alarm response",
    "incident response",
)

SECONDARY_SECURITY_KEYWORDS = (
    "safety ambassador",
    "public safety",
    "trespass",
    "loitering",
    "security monitoring",
    "site security",
    "event security",
    "emergency response",
    "visitor screening",
    "entry screening",
    "id check",
    "perimeter patrol",
    "parking enforcement",
)

NEGATIVE_KEYWORDS = (
    "janitorial",
    "landscaping",
    "pest control",
    "food service",
    "catering",
    "construction",
    "paving",
    "roofing",
    "hvac",
    "plumbing",
    "electrical",
    "engineering",
    "architectural",
    "design services",
    "legal services",
    "auditing",
    "accounting",
    "medical supplies",
    "vehicles",
    "fleet",
    "office supplies",
    "uniforms only",
    "software only",
    "it services",
    "cybersecurity only",
    "police vehicles",
    "ammunition",
    "firearms",
    "weapons",
    "body armor",
    "recruitment services",
)

FEDERAL_SCOPE_KEYWORDS = (
    "sam.gov",
    "sam gov",
    "grants.gov",
    "federal business opportunities",
    "u.s. department",
    "us department",
    "united states department",
    "department of veterans affairs",
    "veterans affairs",
    "national cemetery administration",
    "general services administration",
    "department of homeland security",
    "department of defense",
    "department of justice",
    "federal bureau",
    "federal agency",
    "federal government",
)

# State agencies that share a federal department's name are state/local scope,
# not federal: "California Department of Veterans Affairs" runs the Veterans
# Homes, and CA/NV have their own Departments of Justice/Defense. Strip the
# state-qualified phrase before federal matching so only unqualified or
# US-qualified mentions count.
_STATE_QUALIFIED_FEDERAL_LOOKALIKE_RE = re.compile(
    r"\b(?:state of\s+)?(?:california|texas|nevada|arizona)[.,]?\s+"
    r"department of (?:veterans affairs|justice|defense)\b"
)


def matches_federal_scope(text: str) -> list[str]:
    """Return the federal-scope keywords found in ``text``, word-bounded.

    Substring matching is not safe here: "us department" appears inside
    ordinary phrases like "services for variouS DEPARTMENTs", and a false
    federal hit disqualifies the opportunity outright.
    """
    cleaned = _STATE_QUALIFIED_FEDERAL_LOOKALIKE_RE.sub(" ", text)
    return [
        keyword
        for keyword in FEDERAL_SCOPE_KEYWORDS
        if re.search(rf"\b{re.escape(keyword)}\b", cleaned)
    ]

AS_NEEDED_WARNING_KEYWORDS = (
    "as needed",
    "as-needed",
    "on-call",
    "on call",
    "standby",
    "bench",
    "no guaranteed minimum",
    "task order",
    "blanket contract",
    "indefinite quantity",
    "requirements contract",
)

PROCUREMENT_KEYWORDS = (
    "bid",
    "rfp",
    "rfq",
    "ifb",
    "itb",
    "solicitation",
    "proposal",
    "quote",
    "tender",
    "contract",
    "procurement",
    "opportunity",
    "opportunities",
)

GENERIC_NAVIGATION_TITLES = frozenset(
    {
        "home",
        "search",
        "contact",
        "contact us",
        "careers",
        "jobs",
        "news",
        "events",
        "calendar",
        "privacy policy",
        "terms of use",
        "accessibility",
        "mobile main navigation",
        "main navigation",
        "navigation",
        "menu",
        "skip to main content",
        "departments",
        "services",
        "government",
        "business",
        "doing business",
        "residents",
        "visitors",
        "vendor registration",
        "login",
        "log in",
        "sign in",
        "register",
        "faq",
        "help",
        "about",
        "about us",
    }
)


@dataclass(frozen=True)
class RelevanceResult:
    relevance_score: int
    keyword_matches: list[str]
    negative_matches: list[str]
    as_needed_matches: list[str]
    relevance_decision: str
    relevance_reason: str


def score_candidate_relevance(candidate) -> dict:
    title = _normalize(getattr(candidate, "title", None))
    body = _normalize(
        " ".join(
            str(value or "")
            for value in (
                getattr(candidate, "description", None),
                getattr(candidate, "raw_text", None),
                getattr(candidate, "service_type", None),
                getattr(candidate, "contract_type", None),
                getattr(candidate, "agency", None),
                getattr(candidate, "source_url", None),
                getattr(candidate, "detail_url", None),
                getattr(candidate, "portal_url", None),
            )
        )
    )
    combined = f"{title} {body}".strip()

    primary_title = _matches(title, PRIMARY_SECURITY_KEYWORDS)
    primary_body = _matches(body, PRIMARY_SECURITY_KEYWORDS)
    secondary_title = _matches(title, SECONDARY_SECURITY_KEYWORDS)
    secondary_body = _matches(body, SECONDARY_SECURITY_KEYWORDS)
    negative_title = _matches(title, NEGATIVE_KEYWORDS)
    negative_body = _matches(body, NEGATIVE_KEYWORDS)
    federal_scope = matches_federal_scope(combined)
    as_needed = _matches(combined, AS_NEEDED_WARNING_KEYWORDS)
    procurement_title = _matches(title, PROCUREMENT_KEYWORDS)
    procurement_any = _matches(combined, PROCUREMENT_KEYWORDS)

    score = 0
    score += 50 * len(primary_title)
    score += 30 * len([kw for kw in primary_body if kw not in primary_title])
    score += 20 * len(secondary_title)
    score += 10 * len([kw for kw in secondary_body if kw not in secondary_title])
    if procurement_title:
        score += 10
    if getattr(candidate, "due_date", None) or getattr(candidate, "solicitation_number", None):
        score += 10
    if getattr(candidate, "document_urls", None):
        score += 5

    score -= 60 * len(negative_title)
    score -= 30 * len([kw for kw in negative_body if kw not in negative_title])
    score -= 100 * len(federal_scope)
    if not (primary_title or primary_body or secondary_title or secondary_body):
        score -= 50
    if title in GENERIC_NAVIGATION_TITLES:
        score -= 50
    if as_needed:
        score -= 15

    keyword_matches = _unique(
        [*primary_title, *primary_body, *secondary_title, *secondary_body]
    )
    negative_matches = _unique([*negative_title, *negative_body, *federal_scope])
    has_security_match = bool(keyword_matches)
    has_procurement_or_security_signal = bool(procurement_any or keyword_matches)

    if score >= 40 and has_security_match:
        decision = "Relevant"
    elif score >= 20 and has_procurement_or_security_signal:
        decision = "Maybe Relevant"
    else:
        decision = "Not Relevant"

    if negative_matches and not has_security_match:
        decision = "Not Relevant"
    if federal_scope:
        decision = "Not Relevant"

    reason_parts = []
    if keyword_matches:
        reason_parts.append(f"matched {', '.join(keyword_matches[:4])}")
    if negative_matches:
        reason_parts.append(f"negative {', '.join(negative_matches[:3])}")
    if federal_scope:
        reason_parts.append("federal scope excluded")
    if as_needed:
        reason_parts.append("as-needed/on-call caution")
    if not reason_parts:
        reason_parts.append("no security service keyword match")

    return {
        "relevance_score": int(score),
        "keyword_matches": keyword_matches,
        "negative_matches": negative_matches,
        "as_needed_matches": _unique(as_needed),
        "relevance_decision": decision,
        "relevance_reason": "; ".join(reason_parts),
    }


def _normalize(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _matches(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if keyword in text]


def _unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result

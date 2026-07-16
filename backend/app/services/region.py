"""Operating-region rule: the business sources bids from California and Texas only.

Everything that decides whether a source or a scraped candidate belongs to the
business's operating region routes through here so the allow-list lives in ONE
place. Nevada and Arizona were previously in scope; they are now out of region
and are recognized by name only so out-of-region detection still catches them.
"""

from __future__ import annotations

import re

# The only states the business pursues. Widen this set (and STATE_NAME_BY_CODE)
# to re-open a region; every gate below reads from it.
ALLOWED_STATES = frozenset({"CA", "TX"})

# Full-name lookups for the states we reason about. In-region states plus the
# recently-removed ones, so `is_out_of_region_state("Arizona")` returns True.
STATE_NAME_BY_CODE: dict[str, str] = {
    "CA": "california",
    "TX": "texas",
    "NV": "nevada",
    "AZ": "arizona",
}


def normalize_state_code(value: str | None) -> str | None:
    """Return a two-letter state code for ``value``, or None if unrecognized.

    Accepts a two-letter postal code (any case) or a known full state name.
    Unknown two-letter codes are returned as-is (uppercased) so a filter value
    like "NM" is not silently dropped; free-text that is neither is None.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    upper = text.upper()
    if len(upper) == 2 and upper.isalpha():
        return upper
    lower = text.lower()
    for code, name in STATE_NAME_BY_CODE.items():
        if lower == name:
            return code
    return None


def is_allowed_state(value: str | None) -> bool:
    """True when ``value`` names a state inside the operating region."""
    code = normalize_state_code(value)
    return code is not None and code in ALLOWED_STATES


def is_out_of_region_state(value: str | None) -> bool:
    """True only when ``value`` names a recognized state OUTSIDE the region.

    A null/blank/unrecognized value is NOT out-of-region: multi-state
    aggregators (BidNet) carry no single state and must still be scraped, then
    filtered per-candidate. Only a definite out-of-region tag (e.g. "NV",
    "Arizona") gates a whole source out.
    """
    code = normalize_state_code(value)
    return code is not None and code not in ALLOWED_STATES


def allowed_states_label() -> str:
    """Human-readable label for the allowed set, e.g. "CA/TX"."""
    return "/".join(sorted(ALLOWED_STATES))


def text_mentions_state(text: str, code: str) -> bool:
    """True if already-lowercased ``text`` carries evidence of state ``code``.

    Matches the full state name, the word-bounded two-letter code, and the URL
    query/path forms portals use (``state=ca``, ``state/ca``, ``/california``).
    Callers pass text that is already lowercased.
    """
    code = code.upper()
    lowered = code.lower()
    state_name = STATE_NAME_BY_CODE.get(code)
    if state_name and state_name in text:
        return True
    if re.search(rf"\b{re.escape(lowered)}\b", text):
        return True
    if f"state={lowered}" in text or f"state/{lowered}" in text:
        return True
    if state_name and f"/{state_name}" in text:
        return True
    return False

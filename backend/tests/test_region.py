"""Unit tests for the CA/TX operating-region rule."""

from app.services.region import (
    ALLOWED_STATES,
    allowed_states_label,
    is_allowed_state,
    is_out_of_region_state,
    normalize_state_code,
    text_mentions_state,
)


def test_allowed_set_is_ca_tx_only():
    assert ALLOWED_STATES == frozenset({"CA", "TX"})
    assert allowed_states_label() == "CA/TX"


def test_normalize_state_code_from_codes_and_names():
    assert normalize_state_code("ca") == "CA"
    assert normalize_state_code(" tx ") == "TX"
    assert normalize_state_code("California") == "CA"
    assert normalize_state_code("nevada") == "NV"
    # Unknown two-letter codes pass through (never silently dropped).
    assert normalize_state_code("NM") == "NM"
    # Free text that is neither a code nor a known name is unrecognized.
    assert normalize_state_code("somewhere") is None
    assert normalize_state_code(None) is None
    assert normalize_state_code("") is None


def test_is_allowed_state():
    assert is_allowed_state("CA") is True
    assert is_allowed_state("Texas") is True
    assert is_allowed_state("NV") is False
    assert is_allowed_state(None) is False


def test_is_out_of_region_only_for_recognized_other_states():
    assert is_out_of_region_state("NV") is True
    assert is_out_of_region_state("Arizona") is True
    # In-region states are not out of region.
    assert is_out_of_region_state("CA") is False
    assert is_out_of_region_state("TX") is False
    # Null / unrecognized are NOT out-of-region (aggregators carry no state and
    # must still be scraped, then filtered per-candidate).
    assert is_out_of_region_state(None) is False
    assert is_out_of_region_state("") is False
    assert is_out_of_region_state("Multi-State") is False


def test_text_mentions_state_matches_name_code_and_url_forms():
    assert text_mentions_state("security services in san diego, ca", "CA") is True
    assert text_mentions_state("city of austin, texas", "TX") is True
    assert text_mentions_state("https://portal/bids?state=ca", "CA") is True
    assert text_mentions_state("https://portal/california/lapg", "CA") is True
    # Word-bounded: "ca" inside "california" is matched by name, not a stray hit.
    assert text_mentions_state("las vegas nevada", "CA") is False
    assert text_mentions_state("las vegas nevada", "NV") is True

"""Tests for scraper extraction helpers (extraction_utils.py).

Pure string parsing -- no network, no DB. These pin down two parsing bugs:
estimated-value decimal handling and solicitation-number stopword rejection.
"""

from datetime import UTC, datetime, timedelta

from app.services.scrapers.extraction_utils import (
    extract_due_date,
    extract_estimated_value,
    extract_pre_bid_date,
    extract_q_and_a_deadline,
    extract_solicitation_number,
    parse_date,
)


# --- Fix D: estimated value decimals ----------------------------------------
def test_estimated_value_single_decimal_digit_not_truncated():
    assert extract_estimated_value("Estimated value: $1,234.5") == 1234.5
    assert extract_estimated_value("Budget: $50.5") == 50.5


def test_estimated_value_two_decimals():
    assert extract_estimated_value("Estimated value: $50.50") == 50.50
    assert extract_estimated_value("Not to exceed $2,000.00") == 2000.00


def test_estimated_value_thousands_no_decimals():
    assert extract_estimated_value("Contract value: $1,234,567") == 1234567.0


def test_estimated_value_none_when_absent():
    assert extract_estimated_value("Security guard services for the county") is None


# --- Fix E: solicitation number stopword rejection --------------------------
def test_solicitation_number_real_value():
    assert extract_solicitation_number("RFP-2026-01 for security services") == "2026-01"
    assert extract_solicitation_number("See IFB 44 for details") == "44"


def test_solicitation_number_rejects_stopword():
    # "RFP for security services" must not capture the stopword "for".
    assert extract_solicitation_number("RFP for security services") is None


def test_solicitation_number_labeled_form():
    assert (
        extract_solicitation_number("Solicitation Number: 2026170 issued today")
        == "2026170"
    )


# --- Fix 1: no global date fallback (date fabrication) ----------------------
def test_extract_due_date_keyword_anchored():
    result = extract_due_date("Proposals accepted. Due date: 07/15/2026 at 2pm.")
    assert result is not None
    assert (result.year, result.month, result.day) == (2026, 7, 15)


def test_extract_due_date_none_when_no_keyword_only_stray_date():
    # A stray date with no deadline keyword must NOT be returned as the due date.
    assert extract_due_date("This notice was posted on 07/15/2026 for review.") is None


def test_extract_pre_bid_and_qa_none_without_keyword():
    text = "General background paragraph dated 08/01/2026 with no deadline labels."
    assert extract_pre_bid_date(text) is None
    assert extract_q_and_a_deadline(text) is None


def test_extract_pre_bid_keyword_anchored():
    result = extract_pre_bid_date("Pre-bid: 06/30/2026 at 10am.")
    assert result is not None
    assert (result.year, result.month, result.day) == (2026, 6, 30)


# --- Fix 7: date plausibility guard -----------------------------------------
def test_parse_date_rejects_two_digit_year_mapping_to_1970():
    # "%y" maps 70 -> 1970, which is implausible for a bid; must be rejected.
    assert parse_date("01/15/70") is None


def test_parse_date_accepts_near_future_date():
    near = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30)
    parsed = parse_date(near.strftime("%m/%d/%Y"))
    assert parsed is not None
    assert (parsed.year, parsed.month, parsed.day) == (near.year, near.month, near.day)


def test_parse_date_accepts_current_dated_value():
    parsed = parse_date("06/30/2026")
    assert parsed is not None
    assert (parsed.year, parsed.month, parsed.day) == (2026, 6, 30)

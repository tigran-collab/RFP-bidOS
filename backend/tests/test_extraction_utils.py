"""Tests for scraper extraction helpers (extraction_utils.py).

Pure string parsing -- no network, no DB. These pin down two parsing bugs:
estimated-value decimal handling and solicitation-number stopword rejection.
"""

from app.services.scrapers.extraction_utils import (
    extract_estimated_value,
    extract_solicitation_number,
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

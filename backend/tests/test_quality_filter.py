"""Tests for the candidate quality filter (scrapers/quality.py).

The quality pass runs before relevance scoring and strips page-chrome,
navigation, and social links that generic government pages emit as link
candidates. These tests pin the hard-reject rules and the keep/drop boundary
for real listings. Pure string heuristics — no network, no AI, no DB.
"""

from datetime import datetime

from app.services.scrapers.base import ScraperResult
from app.services.scrapers.quality import assess_candidate


def _candidate(title, **kwargs):
    return ScraperResult(title=title, **kwargs)


# --- Hard rejections --------------------------------------------------------


def test_navigation_title_is_rejected():
    result = assess_candidate(_candidate("Home"))
    assert result.keep is False
    assert result.reason == "navigation/chrome title"


def test_mobile_main_navigation_is_rejected():
    result = assess_candidate(_candidate("Mobile main navigation"))
    assert result.keep is False
    assert result.reason == "navigation/chrome title"


def test_social_link_is_rejected():
    result = assess_candidate(
        _candidate("Bid Opportunities", source_url="https://facebook.com/cityofx")
    )
    assert result.keep is False
    assert result.reason == "social/contact link"


def test_chrome_term_in_title_is_rejected():
    result = assess_candidate(_candidate("Privacy Policy and Terms of Use"))
    assert result.keep is False
    assert result.reason == "chrome/footer text in title"


def test_raw_url_title_is_rejected():
    result = assess_candidate(_candidate("https://example.gov/purchasing"))
    assert result.keep is False
    assert result.reason == "title is a raw URL"


def test_too_short_title_is_rejected():
    result = assess_candidate(_candidate("Bid"))
    assert result.keep is False
    assert result.reason == "title too short"


def test_non_procurement_page_is_dropped():
    result = assess_candidate(
        _candidate(
            "Veterans Memorial Park Dedication Ceremony",
            source_url="https://city.gov/events/dedication",
        )
    )
    assert result.keep is False


# --- Real listings are kept -------------------------------------------------


def test_real_security_solicitation_is_kept():
    result = assess_candidate(
        _candidate(
            "Request for Proposals - Unarmed Security Guard Services",
            solicitation_number="RFP-2026-01",
            due_date=datetime(2026, 7, 15),
            source_url="https://city.gov/bids/rfp-2026-01",
        )
    )
    assert result.keep is True
    assert result.reason is None
    assert result.score >= 0.45


def test_listing_with_procurement_url_and_number_is_kept():
    result = assess_candidate(
        _candidate(
            "Patrol Services Solicitation",
            solicitation_number="IFB-44",
            source_url="https://county.gov/procurement/solicitations/44",
        )
    )
    assert result.keep is True

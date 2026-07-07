"""Tests for the security-relevance filter (scrapers/keywords.py).

This is the logic that decides which scraped candidates are worth saving as
opportunities. A regression here silently drops real security-guard contracts
or floods the review queue with unrelated work, so the decision boundaries are
pinned down here. Pure string heuristics — no network, no AI, no DB.
"""

from datetime import datetime

from app.services.scrapers.base import ScraperResult
from app.services.scrapers.keywords import score_candidate_relevance


def _candidate(title, **kwargs):
    return ScraperResult(title=title, **kwargs)


# --- Security services should be kept ---------------------------------------


def test_security_guard_services_is_relevant():
    result = score_candidate_relevance(
        _candidate("Unarmed Security Guard Services", solicitation_number="RFP-26-01")
    )
    assert result["relevance_decision"] == "Relevant"
    assert result["relevance_score"] >= 40
    assert result["keyword_matches"]  # at least one security keyword matched


def test_armed_contract_security_is_relevant():
    result = score_candidate_relevance(
        _candidate("Armed and Unarmed Contract Security Services")
    )
    assert result["relevance_decision"] == "Relevant"


def test_mobile_patrol_is_relevant():
    result = score_candidate_relevance(
        _candidate("Mobile Patrol Services for City Facilities")
    )
    assert result["relevance_decision"] == "Relevant"


def test_fire_watch_is_relevant():
    result = score_candidate_relevance(
        _candidate("Fire Watch and Standing Post Security", due_date=datetime(2026, 8, 1))
    )
    assert result["relevance_decision"] == "Relevant"


# --- Unrelated service categories should be rejected ------------------------


def test_janitorial_is_not_relevant():
    result = score_candidate_relevance(_candidate("Janitorial Services for City Hall"))
    assert result["relevance_decision"] == "Not Relevant"
    assert "janitorial" in result["negative_matches"]


def test_landscaping_is_not_relevant():
    result = score_candidate_relevance(
        _candidate("Landscaping and Grounds Maintenance Contract")
    )
    assert result["relevance_decision"] == "Not Relevant"


def test_it_services_is_not_relevant():
    result = score_candidate_relevance(_candidate("IT Services and Network Support"))
    assert result["relevance_decision"] == "Not Relevant"


def test_weapons_supply_is_not_relevant():
    # Hardware/ammunition supply is not a guard-staffing opportunity.
    result = score_candidate_relevance(_candidate("Firearms and Ammunition Supply"))
    assert result["relevance_decision"] == "Not Relevant"


def test_unrelated_commodity_is_not_relevant():
    result = score_candidate_relevance(
        _candidate("Refrigerated Liquid Carbon Dioxide")
    )
    assert result["relevance_decision"] == "Not Relevant"


def test_navigation_title_is_not_relevant():
    result = score_candidate_relevance(_candidate("Home"))
    assert result["relevance_decision"] == "Not Relevant"


# --- Federal scope should be rejected even when security-relevant ------------


def test_federal_security_guard_opportunity_is_not_relevant():
    result = score_candidate_relevance(
        _candidate(
            "National Cemetery Administration - Unarmed Security Guards",
            agency="U.S. Department of Veterans Affairs",
        )
    )
    assert result["relevance_decision"] == "Not Relevant"
    assert "national cemetery administration" in result["negative_matches"]
    assert "federal scope excluded" in result["relevance_reason"]


def test_sam_gov_security_opportunity_is_not_relevant():
    result = score_candidate_relevance(
        _candidate(
            "Armed Security Guard Services",
            source_url="https://sam.gov/opp/example",
        )
    )
    assert result["relevance_decision"] == "Not Relevant"
    assert "sam.gov" in result["negative_matches"]


# --- As-needed / on-call language is a caution, not a rejection -------------


def test_as_needed_security_is_flagged_but_not_rejected():
    result = score_candidate_relevance(
        _candidate("As-Needed Unarmed Security Guard Services")
    )
    assert result["as_needed_matches"], "as-needed language should be flagged"
    # Still a security opportunity — caution, not auto-reject.
    assert result["relevance_decision"] in ("Relevant", "Maybe Relevant")


def test_on_call_patrol_is_flagged():
    result = score_candidate_relevance(
        _candidate("On-Call Mobile Patrol Services", contract_type="Task Order")
    )
    assert result["as_needed_matches"]
    assert result["relevance_decision"] in ("Relevant", "Maybe Relevant")


# --- Weaker but plausible signals land in the middle bucket -----------------


def test_secondary_only_signal_is_maybe_relevant():
    # "event security" is a secondary keyword: enough to look at, not enough to
    # auto-promote to Relevant.
    result = score_candidate_relevance(_candidate("Event Security Coordination"))
    assert result["relevance_decision"] == "Maybe Relevant"

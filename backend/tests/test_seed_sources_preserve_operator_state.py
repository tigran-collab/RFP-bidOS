"""Regression test: reseeding must not clobber operator-managed source state.

Operators toggle `enabled` and edit `notes`; an idempotent reseed should keep
those while still propagating curated corrections (portal_type, config_json).
"""

from sqlmodel import select

from app.models import SourceConfig
from app.seed_sources import REAL_PUBLIC_SOURCES, seed_real_sources


def _curated_entry(name: str) -> dict:
    for entry in REAL_PUBLIC_SOURCES:
        if entry["name"] == name:
            return entry
    raise AssertionError(f"curated entry not found: {name}")


def test_reseed_preserves_enabled_and_notes_but_updates_curated_fields(session):
    entry = _curated_entry("City of Mesa, AZ - Purchasing Solicitations (Open Data)")

    # Operator has disabled the source, written custom notes, and the stored
    # portal_type/config_json have drifted from the curated values.
    existing = SourceConfig(
        name=entry["name"],
        source_type="public_page",
        base_url=entry["base_url"],
        portal_type="Stale Portal Type",
        state=entry["state"],
        enabled=False,
        notes="Operator: disabled pending legal review.",
        config_json=None,
    )
    session.add(existing)
    session.commit()
    session.refresh(existing)

    seed_real_sources(session)

    refreshed = session.exec(
        select(SourceConfig).where(SourceConfig.name == entry["name"])
    ).first()
    assert refreshed is not None

    # Operator-managed fields preserved.
    assert refreshed.enabled is False
    assert refreshed.notes == "Operator: disabled pending legal review."

    # Curated fields still propagate.
    assert refreshed.portal_type == entry["portal_type"]
    assert refreshed.source_type == entry["source_type"]
    assert refreshed.config_json == entry["config_json"]


def test_reseed_preserves_operator_tuned_config_json(session):
    # Cal eProcure's curated entry ships no config_json; an operator-tuned
    # config on the existing row must survive a reseed.
    entry = _curated_entry("Cal eProcure (California State)")
    assert entry.get("config_json") is None

    tuned = '{"row_selector": ".bid-row", "list_url": "https://caleprocure.ca.gov/bids"}'
    existing = SourceConfig(
        name=entry["name"],
        source_type="public_page",
        base_url=entry["base_url"],
        portal_type=entry["portal_type"],
        state=entry["state"],
        enabled=True,
        notes="Operator tuned.",
        config_json=tuned,
    )
    session.add(existing)
    session.commit()

    seed_real_sources(session)

    refreshed = session.exec(
        select(SourceConfig).where(SourceConfig.name == entry["name"])
    ).first()
    assert refreshed.config_json == tuned


def test_reseed_still_propagates_curated_config_json(session):
    # When the curated entry DOES provide a config_json, drifted stored
    # configs are corrected on reseed.
    entry = _curated_entry("City of Mesa, AZ - Purchasing Solicitations (Open Data)")
    assert entry.get("config_json")

    existing = SourceConfig(
        name=entry["name"],
        source_type=entry["source_type"],
        base_url=entry["base_url"],
        portal_type=entry["portal_type"],
        state=entry["state"],
        enabled=True,
        config_json='{"stale": true}',
    )
    session.add(existing)
    session.commit()

    seed_real_sources(session)

    refreshed = session.exec(
        select(SourceConfig).where(SourceConfig.name == entry["name"])
    ).first()
    assert refreshed.config_json == entry["config_json"]


def test_seed_new_row_sets_enabled_and_notes_from_curated(session):
    # With an empty DB, new IN-REGION rows must adopt the curated enabled/notes
    # values. (Out-of-region rows are force-disabled; see test_seed_region.)
    seed_real_sources(session)

    entry = _curated_entry(
        "City of Los Angeles - RAMP Open Bid Opportunities (Open Data)"
    )
    assert entry["state"] == "CA" and entry["enabled"] is True
    created = session.exec(
        select(SourceConfig).where(SourceConfig.name == entry["name"])
    ).first()
    assert created is not None
    assert created.enabled == entry["enabled"]
    assert created.notes == entry["notes"]

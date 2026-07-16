"""Seeding enforces the CA/TX operating region: out-of-region sources (NV, AZ)
are seeded disabled and force-disabled on reseed even if toggled on."""

from sqlmodel import select

from app.models import SourceConfig
from app.seed_sources import REAL_PUBLIC_SOURCES, seed_real_sources
from app.services.region import is_out_of_region_state


def test_new_out_of_region_sources_are_seeded_disabled(session):
    seed_real_sources(session)
    sources = list(session.exec(select(SourceConfig)).all())
    assert sources, "expected curated sources to be seeded"

    for source in sources:
        if is_out_of_region_state(source.state):
            assert source.enabled is False, (
                f"{source.name} ({source.state}) is out of region but enabled"
            )
        elif source.state in {"CA", "TX"}:
            # In-region curated rows keep their curated enabled flag (all True).
            assert source.enabled is True


def test_reseed_force_disables_reenabled_out_of_region_row(session):
    # An operator re-enabled an AZ source; region is a hard rule, so a reseed
    # must switch it back off.
    az_entry = next(
        e for e in REAL_PUBLIC_SOURCES if is_out_of_region_state(e["state"])
    )
    existing = SourceConfig(
        name=az_entry["name"],
        source_type=az_entry.get("source_type", "public_page"),
        base_url=az_entry["base_url"],
        portal_type=az_entry["portal_type"],
        state=az_entry["state"],
        enabled=True,
        notes="Operator re-enabled.",
    )
    session.add(existing)
    session.commit()

    seed_real_sources(session)

    refreshed = session.exec(
        select(SourceConfig).where(SourceConfig.name == az_entry["name"])
    ).first()
    assert refreshed.enabled is False


def test_reseed_leaves_in_region_enabled_row_untouched(session):
    ca_entry = next(e for e in REAL_PUBLIC_SOURCES if e["state"] == "CA")
    existing = SourceConfig(
        name=ca_entry["name"],
        source_type=ca_entry.get("source_type", "public_page"),
        base_url=ca_entry["base_url"],
        portal_type=ca_entry["portal_type"],
        state=ca_entry["state"],
        enabled=True,
    )
    session.add(existing)
    session.commit()

    seed_real_sources(session)

    refreshed = session.exec(
        select(SourceConfig).where(SourceConfig.name == ca_entry["name"])
    ).first()
    assert refreshed.enabled is True


def test_reseed_preserves_operator_disabled_in_region_row(session):
    # The region force-disable must NOT bleed into re-ENABLING: an operator who
    # disabled an in-region (CA) source keeps it disabled across a reseed.
    ca_entry = next(e for e in REAL_PUBLIC_SOURCES if e["state"] == "CA")
    existing = SourceConfig(
        name=ca_entry["name"],
        source_type=ca_entry.get("source_type", "public_page"),
        base_url=ca_entry["base_url"],
        portal_type=ca_entry["portal_type"],
        state=ca_entry["state"],
        enabled=False,
        notes="Operator disabled pending review.",
    )
    session.add(existing)
    session.commit()

    seed_real_sources(session)

    refreshed = session.exec(
        select(SourceConfig).where(SourceConfig.name == ca_entry["name"])
    ).first()
    assert refreshed.enabled is False
    assert refreshed.notes == "Operator disabled pending review."

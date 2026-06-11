"""
Curated real-world public procurement sources for CA, TX, NV, and AZ.

Rules:
- Public pages only. No login-required sources are enabled.
- JS-heavy single-page portals are seeded disabled with a note, since the
  public-page scraper only parses server-rendered HTML.
- Seeding is idempotent: existing rows are matched by base_url, then name,
  and are never duplicated.
"""

from sqlmodel import Session, select

from app.models import SourceConfig

AUTH_NOT_REQUIRED = "Not Required"

# Each entry: name, base_url, portal_type, state, enabled, notes
REAL_PUBLIC_SOURCES: list[dict] = [
    # --- California ---
    {
        "name": "Cal eProcure (California State)",
        "base_url": "https://caleprocure.ca.gov/pages/public-search.aspx",
        "portal_type": "Other",
        "state": "CA",
        "enabled": False,
        "notes": "California state procurement public search. JavaScript portal; HTML scraper gets limited results. Review manually.",
    },
    {
        "name": "Los Angeles County - Doing Business",
        "base_url": "https://doingbusiness.lacounty.gov/",
        "portal_type": "Generic Public",
        "state": "CA",
        "enabled": True,
        "notes": "LA County vendor/business portal with links to open solicitations.",
    },
    {
        "name": "City of Los Angeles (LABAVN)",
        "base_url": "https://labavn.org/",
        "portal_type": "Other",
        "state": "CA",
        "enabled": False,
        "notes": "LA Business Assistance Virtual Network. Listing details may require free registration; do not log in.",
    },
    {
        "name": "City of San Diego Purchasing & Contracting",
        "base_url": "https://www.sandiego.gov/purchasing-contracting",
        "portal_type": "Generic Public",
        "state": "CA",
        "enabled": True,
        "notes": "San Diego purchasing department page; bid opportunities run through PlanetBids portal links.",
    },
    {
        "name": "San Francisco City Partner",
        "base_url": "https://sfcitypartner.sfgov.org/",
        "portal_type": "Other",
        "state": "CA",
        "enabled": False,
        "notes": "City and County of San Francisco contracting portal. JavaScript portal; limited HTML scraping.",
    },
    {
        "name": "Santa Clara County Procurement",
        "base_url": "https://procurement.sccgov.org/",
        "portal_type": "Generic Public",
        "state": "CA",
        "enabled": False,
        "notes": "County procurement department. Verify URL and structure before enabling.",
    },
    {
        "name": "City of San Jose Purchasing",
        "base_url": "https://www.sanjoseca.gov/your-government/departments-offices/finance/purchasing-risk-management",
        "portal_type": "Generic Public",
        "state": "CA",
        "enabled": False,
        "notes": "San Jose finance/purchasing page. Bids often run through Biddingo portal links.",
    },
    {
        "name": "LA Metro Business Opportunities",
        "base_url": "https://business.metro.net/",
        "portal_type": "Other",
        "state": "CA",
        "enabled": False,
        "notes": "Transit agency procurement portal. JavaScript portal; limited HTML scraping. Transit security contracts appear here.",
    },
    # --- Texas ---
    {
        "name": "Texas Electronic State Business Daily (ESBD)",
        "base_url": "https://www.txsmartbuy.com/esbd",
        "portal_type": "Other",
        "state": "TX",
        "enabled": False,
        "notes": "Texas state procurement public search. JavaScript portal; limited HTML scraping. Review manually.",
    },
    {
        "name": "City of Houston Purchasing",
        "base_url": "https://purchasing.houstontx.gov/",
        "portal_type": "Generic Public",
        "state": "TX",
        "enabled": True,
        "notes": "Houston strategic procurement division with public bid listings.",
    },
    {
        "name": "City of Dallas Procurement Services",
        "base_url": "https://dallascityhall.com/departments/office-procurement-services",
        "portal_type": "Generic Public",
        "state": "TX",
        "enabled": False,
        "notes": "Dallas procurement office page. SSL certificate verification failed during smoke test (June 2026); verify manually before enabling.",
    },
    {
        "name": "City of Austin Solicitations (Finance Online)",
        "base_url": "https://financeonline.austintexas.gov/afo/account_services/solicitation/solicitations.cfm",
        "portal_type": "Generic Public",
        "state": "TX",
        "enabled": True,
        "notes": "Austin public solicitation listing; server-rendered table of open solicitations.",
    },
    {
        "name": "City of San Antonio Procurement",
        "base_url": "https://www.sa.gov/Directory/Departments/Finance/Procurement",
        "portal_type": "Generic Public",
        "state": "TX",
        "enabled": False,
        "notes": "San Antonio procurement directory page. Verify URL and structure before enabling.",
    },
    {
        "name": "City of Fort Worth Purchasing",
        "base_url": "https://www.fortworthtexas.gov/departments/finance/purchasing",
        "portal_type": "Generic Public",
        "state": "TX",
        "enabled": False,
        "notes": "Fort Worth purchasing division page. Verify URL and structure before enabling.",
    },
    # --- Nevada ---
    {
        "name": "Nevada State Purchasing Division",
        "base_url": "https://purchasing.nv.gov/",
        "portal_type": "Generic Public",
        "state": "NV",
        "enabled": True,
        "notes": "Nevada state purchasing with public solicitation listings.",
    },
    {
        "name": "Clark County Purchasing & Contracts",
        "base_url": "https://www.clarkcountynv.gov/government/departments/finance/purchasing",
        "portal_type": "Generic Public",
        "state": "NV",
        "enabled": False,
        "notes": "Clark County purchasing page returned 404 during smoke test (June 2026); bids likely moved to an external eProcurement portal. Verify manually before enabling.",
    },
    {
        "name": "City of Las Vegas Purchasing & Contracts",
        "base_url": "https://www.lasvegasnevada.gov/Business/Purchasing-Contracts",
        "portal_type": "Generic Public",
        "state": "NV",
        "enabled": False,
        "notes": "Las Vegas purchasing page. Verify URL and structure before enabling.",
    },
    {
        "name": "Washoe County Purchasing",
        "base_url": "https://www.washoecounty.gov/comptroller/Divisions/purchasing/bids.php",
        "portal_type": "Generic Public",
        "state": "NV",
        "enabled": True,
        "notes": "Washoe County (Reno area) open bids page under the comptroller's office. URL verified June 2026.",
    },
    {
        "name": "City of Reno Purchasing",
        "base_url": "https://www.reno.gov/government/departments/finance/purchasing",
        "portal_type": "Generic Public",
        "state": "NV",
        "enabled": False,
        "notes": "Reno purchasing page. Verify URL and structure before enabling.",
    },
    # --- Arizona ---
    {
        "name": "Arizona Procurement Portal (APP)",
        "base_url": "https://app.az.gov/",
        "portal_type": "Other",
        "state": "AZ",
        "enabled": False,
        "notes": "Arizona state procurement portal. JavaScript single-page app; limited HTML scraping. Review manually.",
    },
    {
        "name": "Maricopa County Procurement Services",
        "base_url": "https://www.maricopa.gov/2087/Procurement-Services",
        "portal_type": "Generic Public",
        "state": "AZ",
        "enabled": True,
        "notes": "Maricopa County (Phoenix area) procurement services with public solicitation links. URL verified June 2026.",
    },
    {
        "name": "City of Phoenix Solicitations",
        "base_url": "https://solicitations.phoenix.gov/",
        "portal_type": "Generic Public",
        "state": "AZ",
        "enabled": True,
        "notes": "Phoenix public solicitations listing.",
    },
    {
        "name": "City of Tucson Procurement",
        "base_url": "https://www.tucsonaz.gov/Departments/Business-Services",
        "portal_type": "Generic Public",
        "state": "AZ",
        "enabled": False,
        "notes": "Tucson business services/procurement page. Verify URL and structure before enabling.",
    },
    {
        "name": "Pima County Procurement",
        "base_url": "https://www.pima.gov/199/Procurement",
        "portal_type": "Generic Public",
        "state": "AZ",
        "enabled": False,
        "notes": "Pima County (Tucson area) procurement page. Verify URL and structure before enabling.",
    },
]


def seed_real_sources(session: Session) -> dict:
    """
    Idempotently insert curated public sources. Matches by base_url, then name.
    Rows matched by name are refreshed with the curated URL, portal type,
    state, enabled flag, and notes, so URL corrections propagate on reseed.
    """
    created = 0
    updated = 0
    skipped = 0
    for entry in REAL_PUBLIC_SOURCES:
        existing = session.exec(
            select(SourceConfig).where(SourceConfig.base_url == entry["base_url"])
        ).first()
        if existing is None:
            existing = session.exec(
                select(SourceConfig).where(SourceConfig.name == entry["name"])
            ).first()
        if existing is not None:
            changed = False
            for field in ("base_url", "portal_type", "state", "enabled", "notes"):
                if getattr(existing, field) != entry[field]:
                    setattr(existing, field, entry[field])
                    changed = True
            if changed:
                session.add(existing)
                updated += 1
            else:
                skipped += 1
            continue

        session.add(
            SourceConfig(
                name=entry["name"],
                source_type="public_page",
                base_url=entry["base_url"],
                portal_type=entry["portal_type"],
                state=entry["state"],
                enabled=entry["enabled"],
                notes=entry["notes"],
                requires_credentials=False,
                auth_status=AUTH_NOT_REQUIRED,
            )
        )
        created += 1

    session.commit()
    return {
        "created": created,
        "updated": updated,
        "skipped_existing": skipped,
        "total_curated": len(REAL_PUBLIC_SOURCES),
    }

"""Tests for the scraper capabilities summary.

Assisted-login source types (planetbids, authenticated_browser) support
authenticated scraping through a persisted browser session, mirroring the
exemption in scraper._auth_skip_message; every other credentialed source is
still reported as not scrapable in this phase.
"""

from types import SimpleNamespace

from app.services.scrapers.capabilities import get_source_scraper_capabilities


def _source(**kwargs):
    values = {
        "id": 7,
        "name": "Example Procurement",
        "base_url": "https://example.gov/bids",
        "source_type": "public_page",
        "portal_type": None,
        "requires_credentials": False,
        "auth_status": None,
        "credential_username": None,
        "credential_secret_ref": None,
    }
    values.update(kwargs)
    return SimpleNamespace(**values)


def test_public_source_supports_public_scrape():
    caps = get_source_scraper_capabilities(_source())

    assert caps["supports_public_scrape"] is True
    assert caps["supports_authenticated_scrape"] is False


def test_generic_credentialed_source_reports_unsupported():
    caps = get_source_scraper_capabilities(_source(requires_credentials=True))

    assert caps["supports_public_scrape"] is False
    assert caps["supports_authenticated_scrape"] is False
    assert "requires credentials" in caps["message"]


def test_planetbids_source_reports_authenticated_scrape_supported():
    caps = get_source_scraper_capabilities(
        _source(
            name="Example Transit PlanetBids",
            base_url="https://vendors.planetbids.com/portal/12345",
            source_type="planetbids",
            requires_credentials=True,
            auth_status="Configured",
        )
    )

    assert caps["supports_authenticated_scrape"] is True
    assert caps["supports_public_scrape"] is False
    assert caps["requires_credentials"] is True
    assert caps["portal_type"] == "PlanetBids"
    assert "assisted-login" in caps["message"]


def test_authenticated_browser_source_reports_authenticated_scrape_supported():
    caps = get_source_scraper_capabilities(
        _source(
            name="Example Portal (assisted)",
            source_type="authenticated_browser",
            requires_credentials=True,
        )
    )

    assert caps["supports_authenticated_scrape"] is True
    assert caps["supports_public_scrape"] is False


def test_bidnet_source_still_reports_placeholder():
    caps = get_source_scraper_capabilities(
        _source(
            name="BidNet Direct",
            base_url="https://www.bidnetdirect.com/california",
            requires_credentials=True,
        )
    )

    assert caps["supports_public_scrape"] is False
    assert caps["supports_authenticated_scrape"] is False

"""
Scraper capabilities service.

Returns a standardised capabilities summary for a SourceConfig record.
No network requests are made. No credentials are read or logged.
"""

from app.services.scrapers.bidnet_placeholder import (
    BidNetPlaceholderAdapter,
    _MISSING_CREDS_MSG,
    _NOT_ENABLED_MSG,
    is_bidnet_source,
)

_GENERIC_UNSUPPORTED_MSG = (
    "This source requires credentials. "
    "Authenticated scraping is not enabled in this phase."
)
_PUBLIC_MSG = "Public scraping is available for this source."

_PORTAL_TYPE_HINTS = {
    "planetbids": "PlanetBids",
    "sam.gov": "SAM.gov",
    "bonfire": "Bonfire",
    "opengov": "OpenGov",
    "demandstar": "DemandStar",
    "bidnet": "BidNet",
    "bidnetdirect": "BidNet",
}


def _infer_portal_type(source_config) -> str:
    if source_config.portal_type:
        return source_config.portal_type
    text = f"{(source_config.name or '').lower()} {(source_config.base_url or '').lower()}"
    for hint, label in _PORTAL_TYPE_HINTS.items():
        if hint in text:
            return label
    return "Generic Public"


def get_source_scraper_capabilities(source_config) -> dict:
    """
    Returns a capabilities dict for the given source.

    Fields:
      source_id                    int
      portal_type                  str | None
      supports_public_scrape       bool
      supports_authenticated_scrape bool  — always False in this phase
      requires_credentials         bool
      auth_status                  str | None
      message                      str
    """
    portal_type = _infer_portal_type(source_config)
    requires_credentials = bool(source_config.requires_credentials)
    auth_status = source_config.auth_status

    if is_bidnet_source(source_config):
        adapter = BidNetPlaceholderAdapter()
        auth_check = adapter.check_auth_ready(source_config)
        return {
            "source_id": source_config.id,
            "portal_type": portal_type,
            "supports_public_scrape": False,
            "supports_authenticated_scrape": False,
            "requires_credentials": requires_credentials,
            "auth_status": auth_status,
            "message": auth_check["message"],
        }

    if requires_credentials:
        return {
            "source_id": source_config.id,
            "portal_type": portal_type,
            "supports_public_scrape": False,
            "supports_authenticated_scrape": False,
            "requires_credentials": True,
            "auth_status": auth_status,
            "message": _GENERIC_UNSUPPORTED_MSG,
        }

    return {
        "source_id": source_config.id,
        "portal_type": portal_type,
        "supports_public_scrape": True,
        "supports_authenticated_scrape": False,
        "requires_credentials": False,
        "auth_status": auth_status,
        "message": _PUBLIC_MSG,
    }

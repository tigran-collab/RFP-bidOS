_BIDNET_IDENTIFIERS = {"bidnet", "bidnetdirect", "bidnetdirect.com"}

_NOT_ENABLED_MSG = (
    "BidNet credentials are configured, but authenticated BidNet scraping "
    "is not enabled in this phase."
)
_MISSING_CREDS_MSG = (
    "BidNet credentials are not configured. "
    "Add credential references to enable future authenticated access."
)
_UNSUPPORTED_MSG = (
    "This authenticated source is configured, but authenticated scraping "
    "is not enabled in this phase."
)


def _is_bidnet(source_config) -> bool:
    name = (source_config.name or "").lower()
    url = (source_config.base_url or "").lower()
    portal = (source_config.portal_type or "").lower()
    text = f"{name} {url} {portal}"
    return any(ident in text for ident in _BIDNET_IDENTIFIERS)


class BidNetPlaceholderAdapter:
    def can_handle(self, source_config) -> bool:
        return _is_bidnet(source_config)

    def check_auth_ready(self, source_config) -> dict:
        has_creds = bool(
            source_config.requires_credentials
            and (
                source_config.credential_secret_ref
                or source_config.credential_username
            )
        )
        if has_creds:
            return {
                "ready": False,
                "message": _NOT_ENABLED_MSG,
                "missing_fields": [],
            }
        return {
            "ready": False,
            "message": _MISSING_CREDS_MSG,
            "missing_fields": ["credential references not configured"],
        }

    def scrape_authenticated(self, source_config) -> dict:
        has_creds = bool(
            source_config.requires_credentials
            and (
                source_config.credential_secret_ref
                or source_config.credential_username
            )
        )
        return {
            "supported": False,
            "message": _NOT_ENABLED_MSG if has_creds else _MISSING_CREDS_MSG,
            "records": [],
        }


def get_scraper_capabilities(source_config) -> dict:
    """
    Returns a capabilities summary for a source, including whether
    authenticated scraping is possible and what portal type it is.
    """
    adapter = BidNetPlaceholderAdapter()

    portal_type = source_config.portal_type or _infer_portal_type(source_config)
    requires_credentials = bool(source_config.requires_credentials)
    public_scraping_available = not requires_credentials

    if adapter.can_handle(source_config):
        auth_check = adapter.check_auth_ready(source_config)
        return {
            "source_id": source_config.id,
            "source_name": source_config.name,
            "portal_type": portal_type,
            "requires_credentials": requires_credentials,
            "public_scraping_available": public_scraping_available,
            "authenticated_scraping_available": False,
            "authenticated_scraping_notice": auth_check["message"],
            "auth_ready": auth_check["ready"],
            "auth_missing_fields": auth_check["missing_fields"],
        }

    if requires_credentials:
        return {
            "source_id": source_config.id,
            "source_name": source_config.name,
            "portal_type": portal_type,
            "requires_credentials": True,
            "public_scraping_available": False,
            "authenticated_scraping_available": False,
            "authenticated_scraping_notice": _UNSUPPORTED_MSG,
            "auth_ready": False,
            "auth_missing_fields": [],
        }

    return {
        "source_id": source_config.id,
        "source_name": source_config.name,
        "portal_type": portal_type,
        "requires_credentials": False,
        "public_scraping_available": True,
        "authenticated_scraping_available": False,
        "authenticated_scraping_notice": None,
        "auth_ready": False,
        "auth_missing_fields": [],
    }


def _infer_portal_type(source_config) -> str:
    if source_config.portal_type:
        return source_config.portal_type
    name = (source_config.name or "").lower()
    url = (source_config.base_url or "").lower()
    text = f"{name} {url}"
    if "planetbids" in text:
        return "PlanetBids"
    if "sam.gov" in text or "sam.gov" in url:
        return "SAM.gov"
    if "bonfire" in text:
        return "Bonfire"
    if "opengov" in text:
        return "OpenGov"
    if "demandstar" in text:
        return "DemandStar"
    return "Generic Public"

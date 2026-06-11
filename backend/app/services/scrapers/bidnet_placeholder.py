"""
BidNet placeholder adapter.

Detects BidNet sources and reports their capability status.
Never performs login, credential submission, or authenticated scraping.
Never logs or returns password values.
"""

_BIDNET_IDENTIFIERS = {"bidnet", "bidnetdirect", "bidnetdirect.com"}

_NOT_ENABLED_MSG = (
    "BidNet credentials are configured, but authenticated BidNet scraping "
    "is not enabled in this phase."
)
_MISSING_CREDS_MSG = (
    "BidNet credentials are not configured. "
    "Add credential references to enable future authenticated access."
)


def is_bidnet_source(source_config) -> bool:
    name = (source_config.name or "").lower()
    url = (source_config.base_url or "").lower()
    portal = (source_config.portal_type or "").lower()
    combined = f"{name} {url} {portal}"
    return any(ident in combined for ident in _BIDNET_IDENTIFIERS)


def _has_credential_references(source_config) -> bool:
    return bool(
        source_config.requires_credentials
        and (
            source_config.credential_secret_ref
            or source_config.credential_username
        )
    )


class BidNetPlaceholderAdapter:
    def can_handle(self, source_config) -> bool:
        return is_bidnet_source(source_config)

    def check_auth_ready(self, source_config) -> dict:
        if _has_credential_references(source_config):
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

    def scrape_authenticated(self, source_config) -> list[dict]:
        # Authenticated scraping is not enabled in this phase.
        # Returns empty list — callers should check check_auth_ready first.
        return []

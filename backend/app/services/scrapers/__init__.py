from app.services.scrapers.authenticated_browser import AuthenticatedBrowserAdapter
from app.services.scrapers.base import BaseScraperAdapter, ScraperResult
from app.services.scrapers.generic_public import GenericPublicAdapter
from app.services.scrapers.planetbids import PlanetBidsAuthAdapter
from app.services.scrapers.socrata import SocrataAdapter

__all__ = [
    "AuthenticatedBrowserAdapter",
    "BaseScraperAdapter",
    "GenericPublicAdapter",
    "PlanetBidsAuthAdapter",
    "ScraperResult",
    "SocrataAdapter",
]

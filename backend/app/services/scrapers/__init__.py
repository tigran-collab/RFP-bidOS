from app.services.scrapers.base import BaseScraperAdapter, ScraperResult
from app.services.scrapers.generic_public import GenericPublicAdapter
from app.services.scrapers.socrata import SocrataAdapter

__all__ = [
    "BaseScraperAdapter",
    "GenericPublicAdapter",
    "ScraperResult",
    "SocrataAdapter",
]

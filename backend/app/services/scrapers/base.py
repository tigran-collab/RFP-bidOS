from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class ScraperResult:
    title: str
    agency: str | None = None
    solicitation_number: str | None = None
    source_url: str | None = None
    detail_url: str | None = None
    portal_url: str | None = None
    location: str | None = None
    due_date: datetime | None = None
    pre_bid_date: datetime | None = None
    q_and_a_deadline: datetime | None = None
    service_type: str | None = None
    contract_type: str | None = None
    estimated_value: float | None = None
    description: str | None = None
    document_urls: list[str] = field(default_factory=list)
    raw_text: str | None = None
    confidence_score: float = 0.0
    quality_score: float = 0.0


class BaseScraperAdapter(Protocol):
    def can_handle(self, source_config) -> bool:
        ...

    def scrape(self, source_config) -> list[ScraperResult]:
        ...

from typing import Protocol


class AuthenticatedScraperAdapter(Protocol):
    def can_handle(self, source_config) -> bool:
        ...

    def check_auth_ready(self, source_config) -> dict:
        """
        Returns a dict with keys:
          ready: bool
          message: str
          missing_fields: list[str]
        """
        ...

    def scrape_authenticated(self, source_config) -> list[dict]:
        """
        Returns a list of raw record dicts.
        In this phase all implementations return an empty list with a
        controlled unsupported message via check_auth_ready first.
        Never performs network login, credential submission, or
        scraping behind a login wall.
        """
        ...

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

    def scrape_authenticated(self, source_config) -> dict:
        """
        Returns a dict with keys:
          supported: bool
          message: str
          records: list (empty when unsupported)
        """
        ...

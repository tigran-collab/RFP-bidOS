from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
DOWNLOAD_ROOT = DATA_ROOT / "downloads"
PROCESSED_ROOT = DATA_ROOT / "processed"
BROWSER_PROFILE_ROOT = DATA_ROOT / "browser_profiles"
DEFAULT_DATABASE_PATH = DATA_ROOT / "rfp_bidos.db"


def sqlite_url_for_path(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def resolve_sqlite_database_url(database_url: str) -> str:
    """Anchor relative SQLite file URLs to backend/, independent of CWD."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return database_url

    raw_path = database_url.removeprefix(prefix)
    if raw_path in ("", ":memory:"):
        return database_url

    path = Path(raw_path)
    if path.is_absolute() or raw_path.startswith("/"):
        return database_url
    return sqlite_url_for_path(BACKEND_ROOT / path)


def sqlite_file_path_from_url(database_url: str) -> Path | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    raw_path = database_url.removeprefix(prefix)
    if raw_path in ("", ":memory:"):
        return None
    return Path(raw_path)


class Settings(BaseSettings):
    app_name: str = "RFP BidOS"
    database_url: str = sqlite_url_for_path(DEFAULT_DATABASE_PATH)
    ollama_model: str = "qwen3:8b"
    ollama_base_url: str = "http://127.0.0.1:11434"

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def _resolve_database_url(cls, value: str | None) -> str:
        return resolve_sqlite_database_url(
            str(value) if value else sqlite_url_for_path(DEFAULT_DATABASE_PATH)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

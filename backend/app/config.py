from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "RFP BidOS"
    database_url: str = "sqlite:///./data/rfp_bidos.db"
    ollama_model: str = "qwen3:8b"
    ollama_base_url: str = "http://127.0.0.1:11434"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()

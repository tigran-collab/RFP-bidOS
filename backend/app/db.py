from pathlib import Path

from sqlmodel import SQLModel, create_engine

from app import models  # noqa: F401
from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, echo=False)


def init_db() -> None:
    if settings.database_url.startswith("sqlite:///"):
        db_path = settings.database_url.replace("sqlite:///", "", 1)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)

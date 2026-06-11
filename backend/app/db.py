from pathlib import Path

from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine

from app import models  # noqa: F401
from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, echo=False)


def init_db() -> None:
    if settings.database_url.startswith("sqlite:///"):
        db_path = settings.database_url.replace("sqlite:///", "", 1)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)
    if settings.database_url.startswith("sqlite:///"):
        _ensure_document_parser_columns()


def _ensure_document_parser_columns() -> None:
    columns = {
        "extracted_text_path": "VARCHAR",
        "page_count": "INTEGER",
        "parsed_at": "DATETIME",
    }
    with Session(engine) as session:
        existing_columns = {
            row[1] for row in session.exec(text("PRAGMA table_info(document)")).all()
        }
        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                session.exec(
                    text(f"ALTER TABLE document ADD COLUMN {column_name} {column_type}")
                )
        session.commit()

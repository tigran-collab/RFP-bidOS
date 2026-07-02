from pathlib import Path

from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine

from app import models  # noqa: F401
from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, echo=False)

_SQLITE_COLUMN_MIGRATIONS: tuple[tuple[str, dict[str, str]], ...] = (
    (
        "document",
        {
            "extracted_text_path": "VARCHAR",
            "page_count": "INTEGER",
            "parsed_at": "DATETIME",
        },
    ),
    (
        "opportunity",
        {
            "ai_recommendation": "VARCHAR",
            "ai_score": "FLOAT",
            "ai_reason": "VARCHAR",
            "ai_risk_level": "VARCHAR",
            "ai_evaluated_at": "DATETIME",
        },
    ),
    (
        "opportunity",
        {
            "ai_summary": "VARCHAR",
            "ai_summary_at": "DATETIME",
        },
    ),
    (
        "opportunity",
        {
            "review_status": "VARCHAR DEFAULT 'New'",
            "review_notes": "VARCHAR",
            "reviewed_at": "DATETIME",
            "reviewed_by": "VARCHAR",
            "priority": "VARCHAR",
            "next_action": "VARCHAR",
        },
    ),
    (
        "opportunity",
        {
            "submission_method": "VARCHAR",
            "submission_portal": "VARCHAR",
            "required_forms_summary": "VARCHAR",
            "deadline_risk": "VARCHAR",
            "logistics_confidence_score": "FLOAT",
            "logistics_notes": "VARCHAR",
            "description": "VARCHAR",
            "notes": "VARCHAR",
        },
    ),
    (
        "opportunity",
        {
            "relevance_score": "INTEGER",
            "relevance_decision": "VARCHAR",
            "keyword_matches_json": "VARCHAR",
            "negative_matches_json": "VARCHAR",
            "as_needed_warning": "BOOLEAN DEFAULT 0",
            "relevance_reason": "VARCHAR",
        },
    ),
    (
        "opportunity",
        {
            "priority_rank": "FLOAT",
            "priority_tier": "VARCHAR",
        },
    ),
    (
        "requirement",
        {
            "requirement_type": "VARCHAR",
            "title": "VARCHAR",
            "due_date": "DATETIME",
            "assigned_response_section": "VARCHAR",
            "notes": "VARCHAR",
            "created_at": "DATETIME",
            "updated_at": "DATETIME",
            "extractor_type": "VARCHAR",
        },
    ),
    (
        "sourceconfig",
        {
            "requires_credentials": "BOOLEAN DEFAULT 0",
            "credential_type": "VARCHAR",
            "credential_username": "VARCHAR",
            "credential_secret_ref": "VARCHAR",
            "credential_notes": "VARCHAR",
            "auth_status": "VARCHAR DEFAULT 'Not Configured'",
            "auth_last_checked_at": "DATETIME",
            "last_scrape_at": "DATETIME",
            "last_scrape_status": "VARCHAR",
            "last_scrape_summary": "VARCHAR",
            "portal_type": "VARCHAR",
            "state": "VARCHAR",
            "config_json": "VARCHAR",
        },
    ),
    (
        "scraperun",
        {
            "source_id": "INTEGER",
            "created_count": "INTEGER DEFAULT 0",
            "updated_count": "INTEGER DEFAULT 0",
            "skipped_duplicates": "INTEGER DEFAULT 0",
        },
    ),
)


def init_db() -> None:
    if settings.database_url.startswith("sqlite:///"):
        db_path = settings.database_url.replace("sqlite:///", "", 1)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)
    if settings.database_url.startswith("sqlite:///"):
        for table, columns in _SQLITE_COLUMN_MIGRATIONS:
            _ensure_columns(table, columns)


def _ensure_columns(table: str, columns: dict[str, str]) -> None:
    with Session(engine) as session:
        existing_columns = {
            row[1] for row in session.exec(text(f"PRAGMA table_info({table})")).all()
        }
        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                session.exec(
                    text(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}")
                )
        session.commit()

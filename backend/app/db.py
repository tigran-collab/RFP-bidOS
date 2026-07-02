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
        _ensure_opportunity_ai_columns()
        _ensure_opportunity_summary_columns()
        _ensure_opportunity_review_columns()
        _ensure_opportunity_logistics_columns()
        _ensure_opportunity_relevance_columns()
        _ensure_opportunity_priority_columns()
        _ensure_requirement_matrix_columns()
        _ensure_source_scraper_columns()
        _ensure_scrape_run_stat_columns()


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


def _ensure_opportunity_ai_columns() -> None:
    columns = {
        "ai_recommendation": "VARCHAR",
        "ai_score": "FLOAT",
        "ai_reason": "VARCHAR",
        "ai_risk_level": "VARCHAR",
        "ai_evaluated_at": "DATETIME",
    }
    with Session(engine) as session:
        existing_columns = {
            row[1] for row in session.exec(text("PRAGMA table_info(opportunity)")).all()
        }
        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                session.exec(
                    text(f"ALTER TABLE opportunity ADD COLUMN {column_name} {column_type}")
                )
        session.commit()


def _ensure_opportunity_summary_columns() -> None:
    columns = {
        "ai_summary": "VARCHAR",
        "ai_summary_at": "DATETIME",
    }
    with Session(engine) as session:
        existing_columns = {
            row[1] for row in session.exec(text("PRAGMA table_info(opportunity)")).all()
        }
        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                session.exec(
                    text(f"ALTER TABLE opportunity ADD COLUMN {column_name} {column_type}")
                )
        session.commit()


def _ensure_opportunity_review_columns() -> None:
    columns = {
        "review_status": "VARCHAR DEFAULT 'New'",
        "review_notes": "VARCHAR",
        "reviewed_at": "DATETIME",
        "reviewed_by": "VARCHAR",
        "priority": "VARCHAR",
        "next_action": "VARCHAR",
    }
    with Session(engine) as session:
        existing_columns = {
            row[1] for row in session.exec(text("PRAGMA table_info(opportunity)")).all()
        }
        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                session.exec(
                    text(f"ALTER TABLE opportunity ADD COLUMN {column_name} {column_type}")
                )
        session.commit()


def _ensure_opportunity_logistics_columns() -> None:
    columns = {
        "submission_method": "VARCHAR",
        "submission_portal": "VARCHAR",
        "required_forms_summary": "VARCHAR",
        "deadline_risk": "VARCHAR",
        "logistics_confidence_score": "FLOAT",
        "logistics_notes": "VARCHAR",
        "description": "VARCHAR",
        "notes": "VARCHAR",
    }
    with Session(engine) as session:
        existing_columns = {
            row[1] for row in session.exec(text("PRAGMA table_info(opportunity)")).all()
        }
        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                session.exec(
                    text(f"ALTER TABLE opportunity ADD COLUMN {column_name} {column_type}")
                )
        session.commit()


def _ensure_opportunity_relevance_columns() -> None:
    columns = {
        "relevance_score": "INTEGER",
        "relevance_decision": "VARCHAR",
        "keyword_matches_json": "VARCHAR",
        "negative_matches_json": "VARCHAR",
        "as_needed_warning": "BOOLEAN DEFAULT 0",
        "relevance_reason": "VARCHAR",
    }
    with Session(engine) as session:
        existing_columns = {
            row[1] for row in session.exec(text("PRAGMA table_info(opportunity)")).all()
        }
        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                session.exec(
                    text(f"ALTER TABLE opportunity ADD COLUMN {column_name} {column_type}")
                )
        session.commit()


def _ensure_opportunity_priority_columns() -> None:
    columns = {
        "priority_rank": "FLOAT",
        "priority_tier": "VARCHAR",
    }
    with Session(engine) as session:
        existing_columns = {
            row[1] for row in session.exec(text("PRAGMA table_info(opportunity)")).all()
        }
        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                session.exec(
                    text(f"ALTER TABLE opportunity ADD COLUMN {column_name} {column_type}")
                )
        session.commit()


def _ensure_requirement_matrix_columns() -> None:
    columns = {
        "requirement_type": "VARCHAR",
        "title": "VARCHAR",
        "due_date": "DATETIME",
        "assigned_response_section": "VARCHAR",
        "notes": "VARCHAR",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
        "extractor_type": "VARCHAR",
    }
    with Session(engine) as session:
        existing_columns = {
            row[1] for row in session.exec(text("PRAGMA table_info(requirement)")).all()
        }
        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                session.exec(
                    text(f"ALTER TABLE requirement ADD COLUMN {column_name} {column_type}")
                )
        session.commit()


def _ensure_source_scraper_columns() -> None:
    columns = {
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
    }
    with Session(engine) as session:
        existing_columns = {
            row[1] for row in session.exec(text("PRAGMA table_info(sourceconfig)")).all()
        }
        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                session.exec(
                    text(f"ALTER TABLE sourceconfig ADD COLUMN {column_name} {column_type}")
                )
        session.commit()


def _ensure_scrape_run_stat_columns() -> None:
    columns = {
        "source_id": "INTEGER",
        "created_count": "INTEGER DEFAULT 0",
        "updated_count": "INTEGER DEFAULT 0",
        "skipped_duplicates": "INTEGER DEFAULT 0",
    }
    with Session(engine) as session:
        existing_columns = {
            row[1] for row in session.exec(text("PRAGMA table_info(scraperun)")).all()
        }
        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                session.exec(
                    text(f"ALTER TABLE scraperun ADD COLUMN {column_name} {column_type}")
                )
        session.commit()

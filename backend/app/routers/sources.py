from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlmodel import Session, select

from app.db import engine
from app.models import ScrapeRun, SourceConfig
from app.schemas import SourceConfigCreate, SourceConfigRead, SourceConfigUpdate
from app.services.scraper import scrape_source

router = APIRouter(prefix="/sources", tags=["sources"])


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.get("", response_model=list[SourceConfigRead])
def list_sources() -> list[SourceConfig]:
    with Session(engine) as session:
        return list(session.exec(select(SourceConfig)).all())


@router.post("", response_model=SourceConfigRead, status_code=201)
def create_source(payload: SourceConfigCreate) -> SourceConfig:
    source = SourceConfig(**payload.model_dump())
    with Session(engine) as session:
        session.add(source)
        session.commit()
        session.refresh(source)
        return source


@router.post("/scrape-enabled")
def scrape_enabled_sources() -> dict:
    summary = {
        "sources_scraped": 0,
        "records_found": 0,
        "created_count": 0,
        "skipped_duplicates": 0,
        "errors": [],
        "results": [],
    }

    with Session(engine) as session:
        sources = list(
            session.exec(select(SourceConfig).where(SourceConfig.enabled == True)).all()
        )

    for source in sources:
        result = _run_scrape_for_source(source)
        summary["sources_scraped"] += 1
        summary["records_found"] += result["records_found"]
        summary["created_count"] += result["created_count"]
        summary["skipped_duplicates"] += result["skipped_duplicates"]
        summary["errors"].extend(result["errors"])
        summary["results"].append({"source": source.name, **result})

    return summary


@router.post("/{source_id}/scrape")
def scrape_source_by_id(source_id: int) -> dict:
    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
        if not source.enabled:
            raise HTTPException(status_code=400, detail="Source is disabled")

    return _run_scrape_for_source(source)


@router.patch("/{source_id}", response_model=SourceConfigRead)
def update_source(source_id: int, payload: SourceConfigUpdate) -> SourceConfig:
    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")

        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(source, field, value)

        session.add(source)
        session.commit()
        session.refresh(source)
        return source


def _run_scrape_for_source(source: SourceConfig) -> dict:
    run = ScrapeRun(source_name=source.name, status="running")
    with Session(engine) as session:
        session.add(run)
        session.commit()
        session.refresh(run)

    result = scrape_source(source)
    status = "failed" if result["errors"] else "completed"

    with Session(engine) as session:
        scrape_run = session.get(ScrapeRun, run.id)
        if scrape_run is not None:
            scrape_run.finished_at = utc_now()
            scrape_run.status = status
            scrape_run.records_found = result["records_found"]
            scrape_run.error_message = "; ".join(result["errors"]) or None
            session.add(scrape_run)
            session.commit()

    return result

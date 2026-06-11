from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlmodel import Session, select

from app.db import engine
from app.models import ScrapeRun, SourceConfig
from app.schemas import (
    ScraperCapabilitiesResponse,
    SourceConfigCreate,
    SourceConfigRead,
    SourceConfigUpdate,
)
from app.seed_sources import seed_real_sources
from app.services.scraper import preview_source, scrape_source
from app.services.scrapers.capabilities import get_source_scraper_capabilities
from app.services.source_credentials import (
    get_source_auth_status,
    update_source_auth_status,
)

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
        "candidates_found": 0,
        "candidates_kept": 0,
        "candidates_filtered": 0,
        "created_count": 0,
        "updated_count": 0,
        "skipped_duplicates": 0,
        "documents_discovered": 0,
        "documents_skipped": 0,
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
        summary["candidates_found"] += result.get("total_candidates_found", 0)
        summary["candidates_kept"] += result.get("candidates_kept", 0)
        summary["candidates_filtered"] += result.get("candidates_filtered", 0)
        summary["created_count"] += result["created_count"]
        summary["updated_count"] += result["updated_count"]
        summary["skipped_duplicates"] += result["skipped_duplicates"]
        summary["documents_discovered"] += result.get("documents_discovered", 0)
        summary["documents_skipped"] += result.get("documents_skipped", 0)
        summary["errors"].extend(result["errors"])
        summary["results"].append({"source": source.name, **result})

    return summary


@router.post("/seed")
def seed_sources_route() -> dict:
    with Session(engine) as session:
        return seed_real_sources(session)


# Must be registered before /{source_id}/scraper-capabilities to avoid
# FastAPI trying to coerce "scraper-capabilities" as an int path param.
@router.get("/scraper-capabilities/all", response_model=list[ScraperCapabilitiesResponse])
def get_all_source_scraper_capabilities() -> list[dict]:
    with Session(engine) as session:
        sources = list(session.exec(select(SourceConfig)).all())
    return [get_source_scraper_capabilities(s) for s in sources]


@router.post("/{source_id}/scrape")
def scrape_source_by_id(source_id: int) -> dict:
    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
        if not source.enabled:
            raise HTTPException(status_code=400, detail="Source is disabled")

    return _run_scrape_for_source(source)


@router.post("/{source_id}/preview")
def preview_source_by_id(source_id: int) -> dict:
    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")

    return preview_source(source)


@router.get("/{source_id}/auth-status")
def get_source_auth_status_by_id(source_id: int) -> dict:
    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")

    return get_source_auth_status(source)


@router.post("/{source_id}/auth-status/check")
def check_source_auth_status_by_id(source_id: int) -> dict:
    with Session(engine) as session:
        result = update_source_auth_status(source_id, session)
        if result.get("error"):
            raise HTTPException(status_code=404, detail=result["error"])
        return result


@router.get("/{source_id}/scraper-capabilities", response_model=ScraperCapabilitiesResponse)
def get_source_scraper_capabilities_by_id(source_id: int) -> dict:
    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
    return get_source_scraper_capabilities(source)


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
    run = ScrapeRun(source_name=source.name, source_id=source.id, status="running")
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
            scrape_run.created_count = result["created_count"]
            scrape_run.updated_count = result["updated_count"]
            scrape_run.skipped_duplicates = result["skipped_duplicates"]
            scrape_run.error_message = "; ".join(result["errors"]) or None
            session.add(scrape_run)
        source_record = session.get(SourceConfig, source.id)
        if source_record is not None:
            source_record.last_scrape_at = utc_now()
            source_record.last_scrape_status = status
            source_record.last_scrape_summary = _scrape_summary(result)
            session.add(source_record)
            session.commit()

    return result


def _scrape_summary(result: dict) -> str:
    return (
        f"{result['records_found']} candidates, "
        f"{result['created_count']} created, "
        f"{result['updated_count']} updated, "
        f"{result['skipped_duplicates']} skipped duplicates, "
        f"{len(result['errors'])} errors"
    )

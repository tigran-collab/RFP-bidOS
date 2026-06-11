from fastapi import APIRouter, HTTPException
from sqlmodel import Session, select

from app.db import engine
from app.models import SourceConfig
from app.schemas import SourceConfigCreate, SourceConfigRead, SourceConfigUpdate

router = APIRouter(prefix="/sources", tags=["sources"])


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

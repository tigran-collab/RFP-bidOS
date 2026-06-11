from datetime import datetime

from fastapi import APIRouter, HTTPException
from sqlmodel import Session, select

from app.db import engine
from app.models import Document, Opportunity, Requirement
from app.schemas import (
    DocumentRead,
    OpportunityCreate,
    OpportunityRead,
    OpportunityUpdate,
    RequirementRead,
)

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=list[OpportunityRead])
def list_opportunities() -> list[Opportunity]:
    with Session(engine) as session:
        return list(session.exec(select(Opportunity)).all())


@router.get("/{opportunity_id}", response_model=OpportunityRead)
def get_opportunity(opportunity_id: int) -> Opportunity:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return opportunity


@router.post("", response_model=OpportunityRead, status_code=201)
def create_opportunity(payload: OpportunityCreate) -> Opportunity:
    opportunity = Opportunity(**payload.model_dump())
    with Session(engine) as session:
        session.add(opportunity)
        session.commit()
        session.refresh(opportunity)
        return opportunity


@router.patch("/{opportunity_id}", response_model=OpportunityRead)
def update_opportunity(opportunity_id: int, payload: OpportunityUpdate) -> Opportunity:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")

        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(opportunity, field, value)
        opportunity.updated_at = datetime.utcnow()

        session.add(opportunity)
        session.commit()
        session.refresh(opportunity)
        return opportunity


@router.delete("/{opportunity_id}")
def delete_opportunity(opportunity_id: int) -> dict[str, str]:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        session.delete(opportunity)
        session.commit()
        return {"status": "deleted"}


@router.get("/{opportunity_id}/documents", response_model=list[DocumentRead])
def list_opportunity_documents(opportunity_id: int) -> list[Document]:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        statement = select(Document).where(Document.opportunity_id == opportunity_id)
        return list(session.exec(statement).all())


@router.get("/{opportunity_id}/requirements", response_model=list[RequirementRead])
def list_opportunity_requirements(opportunity_id: int) -> list[Requirement]:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        statement = select(Requirement).where(Requirement.opportunity_id == opportunity_id)
        return list(session.exec(statement).all())

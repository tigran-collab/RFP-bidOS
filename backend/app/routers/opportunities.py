from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlmodel import Session, select

from app.db import engine
from app.models import Document, Opportunity, OpportunityEvaluation, Requirement
from app.schemas import (
    DocumentRead,
    OpportunityCreate,
    OpportunityEvaluationRead,
    OpportunityRead,
    OpportunityUpdate,
    RequirementRead,
)
from app.services.ai_evaluator import (
    LOCAL_AI_UNAVAILABLE,
    evaluate_opportunity_with_local_ai,
)
from app.services.downloader import download_documents_for_opportunity
from app.services.parser import parse_documents_for_opportunity
from app.services.requirement_extractor import (
    INVALID_JSON,
    NO_PARSED_TEXT,
    extract_requirements_with_local_ai,
    refresh_requirements_with_local_ai,
)
from app.services.scorer import score_opportunity_text

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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
        opportunity.updated_at = utc_now()

        session.add(opportunity)
        session.commit()
        session.refresh(opportunity)
        return opportunity


@router.post("/{opportunity_id}/score")
def score_opportunity(opportunity_id: int) -> dict:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")

        scoring_result = score_opportunity_text(opportunity)
        opportunity.bid_score = scoring_result["score"]
        opportunity.bid_decision = scoring_result["decision"]
        opportunity.bid_reason = scoring_result["reason"]
        opportunity.updated_at = utc_now()

        session.add(opportunity)
        session.commit()
        session.refresh(opportunity)

        return {"scoring_result": scoring_result, "opportunity": opportunity}


@router.post("/{opportunity_id}/ai-evaluate")
def ai_evaluate_opportunity(opportunity_id: int) -> dict:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")

        result = evaluate_opportunity_with_local_ai(opportunity_id, session)
        if result.get("error") == LOCAL_AI_UNAVAILABLE:
            raise HTTPException(status_code=503, detail=LOCAL_AI_UNAVAILABLE)
        return result


@router.get("/{opportunity_id}/evaluations", response_model=list[OpportunityEvaluationRead])
def list_opportunity_evaluations(opportunity_id: int) -> list[OpportunityEvaluation]:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        statement = (
            select(OpportunityEvaluation)
            .where(OpportunityEvaluation.opportunity_id == opportunity_id)
            .order_by(OpportunityEvaluation.created_at.desc())
        )
        return list(session.exec(statement).all())


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


@router.post("/{opportunity_id}/download-documents")
def download_opportunity_documents(opportunity_id: int) -> dict:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return download_documents_for_opportunity(opportunity_id, session)


@router.post("/{opportunity_id}/parse-documents")
def parse_opportunity_documents(opportunity_id: int) -> dict:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return parse_documents_for_opportunity(opportunity_id, session)


@router.post("/{opportunity_id}/extract-requirements")
def extract_opportunity_requirements(opportunity_id: int) -> dict:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        result = extract_requirements_with_local_ai(opportunity_id, session)
        if result.get("error") == LOCAL_AI_UNAVAILABLE:
            raise HTTPException(status_code=503, detail=LOCAL_AI_UNAVAILABLE)
        if result.get("error") == NO_PARSED_TEXT:
            raise HTTPException(status_code=400, detail=NO_PARSED_TEXT)
        if result.get("error") == INVALID_JSON:
            raise HTTPException(status_code=502, detail=INVALID_JSON)
        return result


@router.post("/{opportunity_id}/requirements/refresh")
def refresh_opportunity_requirements(opportunity_id: int) -> dict:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        result = refresh_requirements_with_local_ai(opportunity_id, session)
        if result.get("error") == LOCAL_AI_UNAVAILABLE:
            raise HTTPException(status_code=503, detail=LOCAL_AI_UNAVAILABLE)
        if result.get("error") == NO_PARSED_TEXT:
            raise HTTPException(status_code=400, detail=NO_PARSED_TEXT)
        if result.get("error") == INVALID_JSON:
            raise HTTPException(status_code=502, detail=INVALID_JSON)
        return result


@router.get("/{opportunity_id}/requirements", response_model=list[RequirementRead])
def list_opportunity_requirements(opportunity_id: int) -> list[Requirement]:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        statement = select(Requirement).where(Requirement.opportunity_id == opportunity_id)
        return list(session.exec(statement).all())

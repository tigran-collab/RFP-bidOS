from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session, select

from app.db import engine
from app.models import Document, Opportunity, OpportunityEvaluation, Requirement, SourceConfig
from app.schemas import (
    DocumentRead,
    OpportunityCreate,
    OpportunityEvaluationRead,
    OpportunityRead,
    OpportunityReviewUpdate,
    OpportunityUpdate,
    PursuitPrepByStatusRequest,
    PursuitPrepRequest,
    RequirementRead,
)
from app.services.ai_evaluator import (
    LOCAL_AI_UNAVAILABLE,
    evaluate_opportunity_with_local_ai,
)
from app.services.downloader import download_documents_for_opportunity
from app.services.parser import parse_documents_for_opportunity
from app.services.scraper import discover_documents_for_opportunity
from app.services.requirement_extractor import (
    INVALID_JSON,
    NO_PARSED_TEXT,
    extract_requirements_with_local_ai,
    refresh_requirements_with_local_ai,
)
from app.services.pursuit_workflow import (
    run_pursuit_prep,
    run_pursuit_prep_for_status,
)
from app.services.scorer import apply_scored_review_status, score_opportunity_text

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.get("", response_model=list[OpportunityRead])
def list_opportunities() -> list[Opportunity]:
    with Session(engine) as session:
        return list(session.exec(select(Opportunity)).all())


# Ordering precedence for the review queue: actively-pursued and to-be-triaged
# items float to the top; declined/archived sink to the bottom.
REVIEW_STATUS_ORDER = {
    "Pursue": 0,
    "Needs Review": 1,
    "New": 2,
    "Watchlist": 3,
    "Do Not Pursue": 4,
    "Archived": 5,
}


@router.get("/review-queue", response_model=list[OpportunityRead])
def review_queue(
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    state: str | None = Query(default=None),
    min_score: float | None = Query(default=None),
    max_score: float | None = Query(default=None),
    service_type: str | None = Query(default=None),
    source_id: int | None = Query(default=None),
) -> list[Opportunity]:
    with Session(engine) as session:
        opportunities = list(session.exec(select(Opportunity)).all())
        source_name = None
        if source_id is not None:
            source = session.get(SourceConfig, source_id)
            source_name = source.name if source else "no-such-source"

    def keep(opp: Opportunity) -> bool:
        if status and (opp.review_status or "New") != status:
            return False
        if priority and (opp.priority or "") != priority:
            return False
        if service_type and service_type.lower() not in (opp.service_type or "").lower():
            return False
        if min_score is not None and (opp.bid_score is None or opp.bid_score < min_score):
            return False
        if max_score is not None and (opp.bid_score is None or opp.bid_score > max_score):
            return False
        if state:
            haystack = f"{opp.location or ''} {opp.source or ''}".lower()
            if state.lower() not in haystack:
                return False
        if source_name is not None and (opp.source or "") != source_name:
            return False
        return True

    filtered = [opp for opp in opportunities if keep(opp)]
    filtered.sort(key=_review_sort_key)
    return filtered


@router.post("/pursuit-prep/by-status")
def pursuit_prep_by_status(payload: PursuitPrepByStatusRequest) -> dict:
    with Session(engine) as session:
        return run_pursuit_prep_for_status(
            payload.status, session, steps=payload.steps, limit=payload.limit
        )


def _review_sort_key(opp: Opportunity) -> tuple:
    review_rank = REVIEW_STATUS_ORDER.get(opp.review_status or "New", 2)
    has_due = 0 if opp.due_date else 1
    due = opp.due_date or datetime.max
    score = opp.bid_score if opp.bid_score is not None else -1e9
    created = opp.created_at or datetime.min
    return (review_rank, has_due, due, -score, -created.timestamp())


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


@router.patch("/{opportunity_id}/review", response_model=OpportunityRead)
def review_opportunity(opportunity_id: int, payload: OpportunityReviewUpdate) -> Opportunity:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")

        updates = payload.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(opportunity, field, value)
        opportunity.reviewed_at = utc_now()
        opportunity.updated_at = utc_now()

        session.add(opportunity)
        session.commit()
        session.refresh(opportunity)
        return opportunity


@router.post("/{opportunity_id}/pursuit-prep")
def pursuit_prep(opportunity_id: int, payload: PursuitPrepRequest | None = None) -> dict:
    steps = payload.steps if payload else None
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return run_pursuit_prep(opportunity_id, session, steps=steps)


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
        apply_scored_review_status(opportunity, scoring_result["suggested_review_status"])
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


@router.post("/{opportunity_id}/discover-documents")
def discover_opportunity_documents(opportunity_id: int) -> dict:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return discover_documents_for_opportunity(opportunity_id, session)


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

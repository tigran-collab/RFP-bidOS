from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session, select

from app.db import engine
from app.models import (
    BidLogisticsQA,
    Document,
    Opportunity,
    OpportunityEvaluation,
    Requirement,
    SourceConfig,
)
from app.schemas import (
    DocumentRead,
    OpportunityCreate,
    OpportunityEvaluationRead,
    OpportunityRead,
    ExtractLogisticsByStatusRequest,
    LogisticsQAByStatusRequest,
    ManualDocumentUrlRequest,
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
from app.services.ai_summary import summarize_opportunity
from app.services.downloader import download_documents_for_opportunity
from app.services.parser import STATUS_NOT_DOWNLOADED, parse_documents_for_opportunity
from app.services.portal_document_downloader import download_portal_documents_headed
from app.services.scraper import discover_documents_for_opportunity
from app.services.requirement_extractor import (
    INVALID_JSON,
    NO_PARSED_TEXT,
    extract_requirements_with_local_ai,
    refresh_requirements_with_local_ai,
)
from app.services.logistics_extractor import (
    apply_logistics_all,
    apply_logistics_for_status,
    apply_logistics_to_opportunity,
)
from app.services.logistics_qa import (
    get_latest_logistics_qa,
    get_latest_logistics_qa_map,
    run_logistics_qa,
    run_logistics_qa_for_status,
)
from app.services.pursuit_workflow import (
    run_pursuit_prep,
    run_pursuit_prep_for_status,
)
from app.services.scorer import apply_scored_review_status, score_opportunity_text
from app.services.prioritization import apply_priority_to_all
from app.utils.dates import to_naive_utc

router = APIRouter(prefix="/opportunities", tags=["opportunities"])

# Mirrors the invalid-JSON error string returned by
# ai_evaluator.evaluate_opportunity_with_local_ai so the /ai-evaluate handler
# can map it to the same HTTP status /extract-requirements uses for INVALID_JSON.
AI_EVALUATE_INVALID_JSON = "Local AI model returned invalid JSON."


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


@router.get("/review-queue")
def review_queue(
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    state: str | None = Query(default=None),
    min_score: float | None = Query(default=None),
    max_score: float | None = Query(default=None),
    service_type: str | None = Query(default=None),
    source_id: int | None = Query(default=None),
    deadline_risk: str | None = Query(default=None),
    qa_risk: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    direction: str | None = Query(default=None),
) -> list[dict]:
    with Session(engine) as session:
        opportunities = list(session.exec(select(Opportunity)).all())
        source_name = None
        if source_id is not None:
            source = session.get(SourceConfig, source_id)
            source_name = source.name if source else "no-such-source"
        # Batch-load the latest QA per opportunity in one query (avoids N+1).
        qa_by_opp = get_latest_logistics_qa_map(session)
        latest_qa = {opp.id: qa_by_opp.get(opp.id) for opp in opportunities}

    def keep(opp: Opportunity) -> bool:
        if status and (opp.review_status or "New") != status:
            return False
        if priority and (opp.priority or "") != priority:
            return False
        if deadline_risk and (opp.deadline_risk or "") != deadline_risk:
            return False
        if qa_risk:
            qa = latest_qa.get(opp.id)
            if not qa or qa.get("risk_level") != qa_risk:
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
    _apply_sort(filtered, sort, direction)

    results = []
    for opp in filtered:
        item = OpportunityRead.model_validate(opp, from_attributes=True).model_dump(
            mode="json"
        )
        qa = latest_qa.get(opp.id)
        item["logistics_qa_status"] = qa.get("qa_status") if qa else None
        item["logistics_qa_risk"] = qa.get("risk_level") if qa else None
        results.append(item)
    return results


@router.post("/pursuit-prep/by-status")
def pursuit_prep_by_status(payload: PursuitPrepByStatusRequest) -> dict:
    with Session(engine) as session:
        return run_pursuit_prep_for_status(
            payload.status, session, steps=payload.steps, limit=payload.limit
        )


@router.post("/extract-logistics")
def extract_logistics_batch(payload: ExtractLogisticsByStatusRequest | None = None) -> dict:
    review_status = payload.review_status if payload else None
    limit = payload.limit if payload else 10
    with Session(engine) as session:
        if review_status:
            return apply_logistics_for_status(review_status, session, limit=limit)
        return apply_logistics_all(session, limit=limit)


@router.post("/logistics-qa/by-status")
def logistics_qa_by_status(payload: LogisticsQAByStatusRequest) -> dict:
    with Session(engine) as session:
        return run_logistics_qa_for_status(payload.status, session, limit=payload.limit)


def _review_sort_key(opp: Opportunity) -> tuple:
    review_rank = REVIEW_STATUS_ORDER.get(opp.review_status or "New", 2)
    has_due = 0 if opp.due_date else 1
    due = to_naive_utc(opp.due_date) if opp.due_date else datetime.max
    score = opp.bid_score if opp.bid_score is not None else -1e9
    created = to_naive_utc(opp.created_at) if opp.created_at else datetime.min
    return (review_rank, has_due, due, -score, -created.timestamp())


def _priority_sort_key(opp: Opportunity) -> tuple:
    # Highest priority_rank first; opportunities without a rank sort last, then
    # fall back to the standard review ordering for stability.
    has_rank = 0 if opp.priority_rank is not None else 1
    rank = opp.priority_rank if opp.priority_rank is not None else -1e9
    return (has_rank, -rank, _review_sort_key(opp))


# Sortable fields for the review queue and their natural (default) direction.
# All keep missing values last regardless of direction.
_SORT_DEFAULT_DESC = {
    "priority": True,   # highest priority first
    "score": True,      # best bid_score first (bid decision)
    "relevance": True,  # most relevant first
    "deadline": False,  # soonest due first
    "created": True,    # most recently added first
}


def _sort_value(opp: Opportunity, sort: str) -> float | None:
    if sort == "priority":
        return opp.priority_rank
    if sort == "score":
        return opp.bid_score
    if sort == "relevance":
        return opp.relevance_score
    if sort == "deadline":
        return to_naive_utc(opp.due_date).timestamp() if opp.due_date else None
    if sort == "created":
        return to_naive_utc(opp.created_at).timestamp() if opp.created_at else None
    return None


def _apply_sort(filtered: list, sort: str | None, direction: str | None) -> None:
    """Sort in place. Unknown/None sort -> historical review ordering."""
    key = (sort or "").lower()
    if key not in _SORT_DEFAULT_DESC:
        filtered.sort(key=_review_sort_key)
        return
    desc = _SORT_DEFAULT_DESC[key]
    if direction in ("asc", "desc"):
        desc = direction == "desc"
    sign = -1.0 if desc else 1.0

    def sort_key(opp: Opportunity) -> tuple:
        value = _sort_value(opp, key)
        if value is None:
            return (1, 0.0)  # missing values always sort last
        return (0, sign * float(value))

    filtered.sort(key=sort_key)


@router.post("/prioritize")
def prioritize_opportunities() -> dict:
    with Session(engine) as session:
        updated = apply_priority_to_all(session)
        return {"updated": updated}


@router.get("/{opportunity_id}", response_model=OpportunityRead)
def get_opportunity(opportunity_id: int) -> Opportunity:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return opportunity


@router.post("", response_model=OpportunityRead, status_code=201)
def create_opportunity(payload: OpportunityCreate) -> Opportunity:
    data = payload.model_dump()
    # Manual entry: default the source so these are distinguishable from scraped.
    if not data.get("source"):
        data["source"] = "Manual"
    if not data.get("review_status"):
        data["review_status"] = "New"
    opportunity = Opportunity(**data)
    opportunity.created_at = utc_now()
    opportunity.updated_at = utc_now()
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


@router.post("/{opportunity_id}/logistics-qa")
def logistics_qa_one(opportunity_id: int) -> dict:
    with Session(engine) as session:
        result = run_logistics_qa(opportunity_id, session)
        if result.get("error"):
            raise HTTPException(status_code=404, detail=result["error"])
        return result


@router.get("/{opportunity_id}/logistics-qa")
def get_logistics_qa(opportunity_id: int) -> dict:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        result = get_latest_logistics_qa(opportunity_id, session)
        if result is None:
            return {"opportunity_id": opportunity_id, "qa_status": None}
        return result


@router.post("/{opportunity_id}/extract-logistics")
def extract_logistics_one(opportunity_id: int) -> dict:
    with Session(engine) as session:
        result = apply_logistics_to_opportunity(opportunity_id, session)
        if result.get("error"):
            raise HTTPException(status_code=404, detail=result["error"])
        return result


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
        error = result.get("error")
        if error == LOCAL_AI_UNAVAILABLE:
            raise HTTPException(status_code=503, detail=LOCAL_AI_UNAVAILABLE)
        # Mirror /extract-requirements: an invalid-JSON model response is a
        # 502, not a silent HTTP 200 carrying an {"error": ...} body. The
        # success shape (result["opportunity"]/["evaluation"]) is unchanged.
        if error == AI_EVALUATE_INVALID_JSON:
            raise HTTPException(status_code=502, detail=AI_EVALUATE_INVALID_JSON)
        return result


@router.post("/{opportunity_id}/ai-summary")
def ai_summary_opportunity(opportunity_id: int) -> dict:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")

        return summarize_opportunity(opportunity_id, session)


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
        # No DB-level cascade is configured, so remove child rows first to
        # avoid leaving Documents/Requirements/Evaluations/QA orphaned.
        for child_model in (Document, Requirement, OpportunityEvaluation, BidLogisticsQA):
            children = session.exec(
                select(child_model).where(child_model.opportunity_id == opportunity_id)
            ).all()
            for child in children:
                session.delete(child)
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


@router.post("/{opportunity_id}/documents/manual-url")
def attach_manual_document_url(opportunity_id: int, payload: ManualDocumentUrlRequest) -> dict:
    url = (payload.url or "").strip()
    if not (url.lower().startswith("http://") or url.lower().startswith("https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")

        existing = session.exec(
            select(Document).where(
                Document.opportunity_id == opportunity_id,
                Document.source_url == url,
            )
        ).first()
        if existing is not None:
            return {
                "status": "exists",
                "document_id": existing.id,
                "url": url,
                "filename": existing.filename,
            }

        suffix = Path(unquote(urlparse(url).path)).suffix.lower().lstrip(".") or None
        filename = payload.label or Path(unquote(urlparse(url).path)).name or "document"
        document = Document(
            opportunity_id=opportunity_id,
            filename=filename,
            path="",
            file_type=suffix,
            source_url=url,
            parsed_status=STATUS_NOT_DOWNLOADED,
        )
        session.add(document)
        session.commit()
        session.refresh(document)
        return {
            "status": "created",
            "document_id": document.id,
            "url": url,
            "filename": document.filename,
            "file_type": document.file_type,
        }


@router.post("/{opportunity_id}/download-documents")
def download_opportunity_documents(opportunity_id: int) -> dict:
    # expire_on_commit=False: each per-document commit inside the batch would
    # otherwise expire previously-refreshed Document instances, so every entry
    # but the last serialized as {} once the session closed. See H4.
    with Session(engine, expire_on_commit=False) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        discovery = discover_documents_for_opportunity(opportunity_id, session)
        download = download_documents_for_opportunity(opportunity_id, session)

    return {
        **download,
        "documents_discovered": discovery.get("documents_discovered", 0),
        "documents_skipped_discovery": discovery.get("documents_skipped", 0),
        "discovery_errors": discovery.get("errors", []),
        "errors": [
            *(discovery.get("errors") or []),
            *(download.get("errors") or []),
        ],
    }


@router.post("/{opportunity_id}/download-portal-documents")
def download_opportunity_portal_documents(opportunity_id: int) -> dict:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return download_portal_documents_headed(opportunity_id, session)


@router.post("/{opportunity_id}/parse-documents")
def parse_opportunity_documents(opportunity_id: int) -> dict:
    # expire_on_commit=False so each parsed Document stays populated after the
    # per-document commits; otherwise all but the last serialize as {}. See H4.
    with Session(engine, expire_on_commit=False) as session:
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

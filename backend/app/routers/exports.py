from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlmodel import Session

from app.db import engine
from app.models import Opportunity
from app.services.exports import (
    export_deadlines_ics,
    export_documents_csv,
    export_logistics_qa_csv,
    export_opportunities_csv,
    export_requirements_csv,
)

router = APIRouter(prefix="/exports", tags=["exports"])


def _csv_response(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _require_opportunity(session: Session, opportunity_id: int | None) -> None:
    if opportunity_id is not None and session.get(Opportunity, opportunity_id) is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")


@router.get("/opportunities.csv")
def export_opportunities(
    review_status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
) -> Response:
    with Session(engine) as session:
        content, _ = export_opportunities_csv(
            session, filters={"review_status": review_status, "priority": priority}
        )
    return _csv_response(content, "opportunities.csv")


@router.get("/requirements.csv")
def export_requirements(opportunity_id: int | None = Query(default=None)) -> Response:
    with Session(engine) as session:
        _require_opportunity(session, opportunity_id)
        content, _ = export_requirements_csv(session, opportunity_id=opportunity_id)
    return _csv_response(content, "requirements.csv")


@router.get("/documents.csv")
def export_documents(opportunity_id: int | None = Query(default=None)) -> Response:
    with Session(engine) as session:
        _require_opportunity(session, opportunity_id)
        content, _ = export_documents_csv(session, opportunity_id=opportunity_id)
    return _csv_response(content, "documents.csv")


@router.get("/logistics-qa.csv")
def export_logistics_qa(opportunity_id: int | None = Query(default=None)) -> Response:
    with Session(engine) as session:
        _require_opportunity(session, opportunity_id)
        content, _ = export_logistics_qa_csv(session, opportunity_id=opportunity_id)
    return _csv_response(content, "logistics_qa.csv")


@router.get("/deadlines.ics")
def export_deadlines(opportunity_id: int | None = Query(default=None)) -> Response:
    with Session(engine) as session:
        _require_opportunity(session, opportunity_id)
        content = export_deadlines_ics(session, opportunity_id=opportunity_id)
    return Response(
        content=content,
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=deadlines.ics"},
    )

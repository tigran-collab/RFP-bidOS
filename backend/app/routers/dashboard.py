from fastapi import APIRouter, Query
from sqlmodel import Session

from app.db import engine
from app.services.dashboard import get_operations_dashboard
from app.services.notifications import build_digest

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/operations")
def operations_dashboard() -> dict:
    with Session(engine) as session:
        return get_operations_dashboard(session)


@router.get("/digest")
def dashboard_digest(
    days: int = Query(default=7),
    limit: int = Query(default=50),
) -> dict:
    with Session(engine) as session:
        return build_digest(session, days=days, limit=limit)

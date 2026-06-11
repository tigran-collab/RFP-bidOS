from fastapi import APIRouter
from sqlmodel import Session

from app.db import engine
from app.services.dashboard import get_operations_dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/operations")
def operations_dashboard() -> dict:
    with Session(engine) as session:
        return get_operations_dashboard(session)

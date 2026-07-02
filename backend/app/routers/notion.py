"""Notion connector endpoints.

Lets the local web UI configure the Notion integration and sync opportunities
to the user's Notion database.

Security invariants:
  * The integration token travels from the browser to the LOCAL backend only.
    It is stored ONLY in the OS keychain via ``credential_store`` — never in the
    database, never returned by any GET, never logged.
  * The (non-secret) database id lives in the AppSetting store.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlmodel import Session

from app.db import engine
from app.services import notion_connector

router = APIRouter(prefix="/notion", tags=["notion"])


class NotionConfigRequest(BaseModel):
    token: str
    database_id: str


class NotionSyncRequest(BaseModel):
    status: str | None = None
    limit: int | None = 200
    opportunity_ids: list[int] | None = None


@router.get("/status")
def get_notion_status() -> dict:
    with Session(engine) as session:
        return notion_connector.notion_status(session)


@router.put("/config")
def put_notion_config(payload: NotionConfigRequest) -> dict:
    with Session(engine) as session:
        return notion_connector.configure(
            session, token=payload.token, database_id=payload.database_id
        )


@router.delete("/config")
def delete_notion_config() -> dict:
    with Session(engine) as session:
        return notion_connector.clear(session)


@router.post("/sync")
def post_notion_sync(payload: NotionSyncRequest | None = None) -> dict:
    payload = payload or NotionSyncRequest()
    with Session(engine) as session:
        return notion_connector.sync_opportunities(
            session,
            opportunity_ids=payload.opportunity_ids,
            status=payload.status,
            limit=payload.limit if payload.limit is not None else 200,
        )

from fastapi import APIRouter, HTTPException
from sqlmodel import Session, select

from app.db import engine
from app.models import Document
from app.schemas import DocumentRead
from app.services.parser import parse_all_documents, parse_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/parse-all")
def parse_all_downloaded_documents() -> dict:
    with Session(engine) as session:
        return parse_all_documents(session)


@router.get("", response_model=list[DocumentRead])
def list_documents() -> list[Document]:
    with Session(engine) as session:
        return list(session.exec(select(Document)).all())


@router.post("/{document_id}/parse")
def parse_document_by_id(document_id: int) -> dict:
    with Session(engine) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return parse_document(document_id, session)

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.db import engine
from app.models import Document
from app.schemas import DocumentRead
from app.services.downloader import (
    download_document_by_id,
    resolve_downloaded_document_path,
)
from app.services.parser import parse_all_documents, parse_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/parse-all")
def parse_all_downloaded_documents() -> dict:
    # expire_on_commit=False so every parsed Document in the returned list stays
    # populated after the per-document commits (otherwise all but the last
    # serialize as {} once the session closes). See H4.
    with Session(engine, expire_on_commit=False) as session:
        return parse_all_documents(session)


@router.get("", response_model=list[DocumentRead])
def list_documents() -> list[Document]:
    with Session(engine) as session:
        return list(session.exec(select(Document)).all())


@router.post("/{document_id}/parse")
def parse_document_by_id(document_id: int) -> dict:
    # expire_on_commit=False so the returned Document stays populated even when
    # the handler performs more than one commit (e.g. dedup paths). See H4.
    with Session(engine, expire_on_commit=False) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return parse_document(document_id, session)


@router.post("/{document_id}/download")
def download_document_file(document_id: int) -> dict:
    # expire_on_commit=False: the hash-dedup path commits after appending the
    # matched Document, which would otherwise expire it into {}. See H4.
    with Session(engine, expire_on_commit=False) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return download_document_by_id(document_id, session)


@router.get("/{document_id}/file")
def get_document_file(document_id: int) -> FileResponse:
    with Session(engine) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        path = resolve_downloaded_document_path(document)
        if path is None:
            raise HTTPException(
                status_code=404,
                detail="Downloaded file not found. Run Download Documents first.",
            )
        filename = document.filename or path.name

    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=filename,
    )

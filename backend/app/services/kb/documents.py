"""Source Document Vault service: secure storage of uploaded files, metadata,
listing/filtering, archival, and safe file access.

Uploaded files are validated (extension + size + MIME), stored under
``data/kb_documents/`` with a content hash, and the original is always retained
alongside the extracted text (chunks). Files are treated as untrusted data.
"""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from re import sub
from typing import Any

from sqlmodel import Session, select

from app.config import KB_DOCUMENT_ROOT
from app.kb_models import KbDocument, KbDocumentChunk, KbUser
from app.kb_vocab import (
    DOC_STATUS_ARCHIVED,
    DOC_STATUS_UPLOADED,
    PERM_ARCHIVE_DOCUMENTS,
    PERM_EDIT_METADATA,
    PERM_UPLOAD_DOCUMENTS,
)
from app.models import utcnow_naive
from app.services.kb.audit import record_audit
from app.services.kb.extraction import SUPPORTED_EXTS, normalize_file_type
from app.services.kb.permissions import require_permission

# Hard ceiling per uploaded file (mirrors the opportunity downloader's cap).
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

# Extension -> canonical MIME (used for validation + FileResponse).
MIME_BY_EXT = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "txt": "text/plain",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}

_META_SCALARS = (
    "title",
    "doc_type",
    "category",
    "company_entity_id",
    "applicable_state",
    "applicable_industry",
    "service_type",
    "notes",
)
_META_DATES = ("effective_date", "expiration_date", "last_reviewed_at")


class KbDocumentError(RuntimeError):
    status_code = 400


class KbDocumentNotFoundError(RuntimeError):
    status_code = 404


def _parse_date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _safe_filename(name: str, fallback: str = "document") -> str:
    cleaned = sub(r"[^A-Za-z0-9._-]+", "_", name or "").strip("._")
    return cleaned or fallback


def create_document(
    session: Session,
    actor: KbUser,
    *,
    filename: str,
    content: bytes,
    metadata: dict | None = None,
) -> KbDocument:
    """Validate and store an uploaded file, returning the Uploaded document row.

    Processing (extraction/chunking/candidate extraction) is triggered
    separately (processing.process_document) so this call returns promptly.
    """
    require_permission(actor, PERM_UPLOAD_DOCUMENTS)
    metadata = metadata or {}

    file_type = normalize_file_type(filename, metadata.get("mime_type"))
    if file_type not in SUPPORTED_EXTS:
        raise KbDocumentError(
            f"Unsupported file type '{file_type or 'unknown'}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTS))}."
        )
    if not content:
        raise KbDocumentError("Uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise KbDocumentError(
            f"File exceeds the maximum size of {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    digest = sha256(content).hexdigest()
    safe_name = _safe_filename(Path(filename).name, fallback=f"document.{file_type}")
    KB_DOCUMENT_ROOT.mkdir(parents=True, exist_ok=True)
    stored_name = f"{digest[:16]}_{safe_name}"
    target = KB_DOCUMENT_ROOT / stored_name
    if not target.exists():
        target.write_bytes(content)

    now = utcnow_naive()
    document = KbDocument(
        title=str(metadata.get("title") or Path(filename).stem or safe_name).strip(),
        filename=safe_name,
        path=str(target),
        file_type=file_type,
        mime_type=metadata.get("mime_type") or MIME_BY_EXT.get(file_type),
        sha256=digest,
        size_bytes=len(content),
        doc_type=metadata.get("doc_type"),
        category=metadata.get("category"),
        company_entity_id=metadata.get("company_entity_id"),
        applicable_state=metadata.get("applicable_state"),
        applicable_industry=metadata.get("applicable_industry"),
        service_type=metadata.get("service_type"),
        tags_json=json.dumps(metadata.get("tags") or []) or None,
        effective_date=_parse_date(metadata.get("effective_date")),
        expiration_date=_parse_date(metadata.get("expiration_date")),
        notes=metadata.get("notes"),
        uploaded_by=actor.id,
        uploaded_at=now,
        processing_status=DOC_STATUS_UPLOADED,
        created_at=now,
        updated_at=now,
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    record_audit(
        session, actor, "document.upload", target_type="document",
        target_id=document.id, detail={"filename": safe_name, "sha256": digest},
    )
    return document


def update_document_metadata(
    session: Session, actor: KbUser, document_id: int, payload: dict
) -> KbDocument:
    require_permission(actor, PERM_EDIT_METADATA)
    document = get_document(session, document_id)
    for field in _META_SCALARS:
        if field in payload:
            setattr(document, field, payload[field])
    if "tags" in payload:
        document.tags_json = json.dumps(payload["tags"] or []) or None
    for field in _META_DATES:
        if field in payload:
            setattr(document, field, _parse_date(payload[field]))
    document.updated_at = utcnow_naive()
    session.add(document)
    session.commit()
    session.refresh(document)
    record_audit(
        session, actor, "document.update", target_type="document",
        target_id=document.id, detail={"fields": sorted(payload.keys())},
    )
    return document


def archive_document(
    session: Session, actor: KbUser, document_id: int, archived: bool = True
) -> KbDocument:
    require_permission(actor, PERM_ARCHIVE_DOCUMENTS)
    document = get_document(session, document_id)
    document.archived = archived
    if archived:
        document.processing_status = DOC_STATUS_ARCHIVED
    document.updated_at = utcnow_naive()
    session.add(document)
    session.commit()
    session.refresh(document)
    record_audit(
        session, actor, "document.archive" if archived else "document.unarchive",
        target_type="document", target_id=document.id,
    )
    return document


def get_document(session: Session, document_id: int) -> KbDocument:
    document = session.get(KbDocument, document_id)
    if document is None:
        raise KbDocumentNotFoundError(f"Document {document_id} not found")
    return document


def list_documents(
    session: Session,
    *,
    company_entity_id: int | None = None,
    category: str | None = None,
    doc_type: str | None = None,
    state: str | None = None,
    industry: str | None = None,
    service_type: str | None = None,
    processing_status: str | None = None,
    archived: bool | None = False,
    expiration: str | None = None,
    now: datetime | None = None,
) -> list[KbDocument]:
    now = now or utcnow_naive()
    documents = list(session.exec(select(KbDocument)).all())
    out = []
    for d in documents:
        if archived is not None and d.archived != archived:
            continue
        if company_entity_id is not None and d.company_entity_id != company_entity_id:
            continue
        if category and d.category != category:
            continue
        if doc_type and d.doc_type != doc_type:
            continue
        if state and d.applicable_state != state:
            continue
        if industry and d.applicable_industry != industry:
            continue
        if service_type and d.service_type != service_type:
            continue
        if processing_status and d.processing_status != processing_status:
            continue
        if expiration == "expired" and not (
            d.expiration_date and d.expiration_date < now
        ):
            continue
        if expiration == "active" and d.expiration_date and d.expiration_date < now:
            continue
        out.append(d)
    out.sort(key=lambda d: (d.uploaded_at or d.created_at or now), reverse=True)
    return out


def get_document_detail(session: Session, document_id: int) -> dict:
    from app.services.kb.serializers import chunk_to_dict, document_to_dict

    document = get_document(session, document_id)
    chunks = list(
        session.exec(
            select(KbDocumentChunk)
            .where(KbDocumentChunk.document_id == document_id)
            .order_by(KbDocumentChunk.chunk_index)
        ).all()
    )
    return {
        "document": document_to_dict(document),
        "chunks": [chunk_to_dict(c) for c in chunks],
    }


def resolve_document_file(document: KbDocument) -> Path | None:
    """Return a safe existing path for the stored original, or None."""
    if not document.path:
        return None
    path = Path(document.path)
    try:
        resolved = path.resolve()
        root = KB_DOCUMENT_ROOT.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def delete_document(session: Session, actor: KbUser, document_id: int) -> None:
    """Remove a document, its chunks, and the stored original file."""
    require_permission(actor, PERM_ARCHIVE_DOCUMENTS)
    document = get_document(session, document_id)
    chunks = session.exec(
        select(KbDocumentChunk).where(KbDocumentChunk.document_id == document_id)
    ).all()
    for chunk in chunks:
        session.delete(chunk)
    stored = resolve_document_file(document)
    session.delete(document)
    session.commit()
    if stored is not None:
        # Only delete the stored file if no other document references it.
        others = session.exec(
            select(KbDocument).where(KbDocument.path == str(stored))
        ).first()
        if others is None:
            stored.unlink(missing_ok=True)
    record_audit(
        session, actor, "document.delete", target_type="document", target_id=document_id
    )

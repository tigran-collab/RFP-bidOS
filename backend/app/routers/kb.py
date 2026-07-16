"""Company Knowledge Base API.

All routes are under ``/kb``. The acting user is resolved from the
``X-KB-User-Id`` header (defaults to the seeded administrator for single-user
installs); role-based permissions are enforced in the service layer, whose
typed exceptions are translated to HTTP status codes by handlers registered in
main.py.
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.db import engine
from app import kb_vocab
from app.kb_schemas import (
    AnswerCreate,
    AnswerUpdate,
    ArchiveRequest,
    ClaimCreate,
    ClaimSourceRequest,
    ClaimUpdate,
    CommentCreate,
    ConflictResolveRequest,
    DetectConflictsRequest,
    ClaudeConfigUpdate,
    DocumentMetadataUpdate,
    EntityCreate,
    EntityUpdate,
    GalleryAssetUpdate,
    GenerateRequest,
    GoogleDriveConfigUpdate,
    GoogleDriveImportRequest,
    QuestionCreate,
    ResponseUpdate,
    ReviewRequestCreate,
    ReviewResolveRequest,
    SaveToProjectRequest,
    StatusChangeRequest,
    SupersedeRequest,
    TransformRequest,
    UserCreate,
    UserUpdate,
)
from app.services.kb import (
    admin,
    answers,
    claims,
    conflicts,
    dashboard,
    documents,
    drafting,
    gallery,
    processing,
    responses,
    reviews,
    search,
)
from app.kb_vocab import (
    PERM_APPROVE_CLAIMS,
    PERM_MANAGE_USERS,
    PERM_RESOLVE_CONFLICTS,
    PERM_UPLOAD_DOCUMENTS,
)
from app.services.kb import ai_provider, claude_client, google_drive_connector
from app.services.kb.audit import list_audit, record_audit
from app.services.kb.permissions import require_permission, resolve_acting_user
from app.services.kb.documents import MAX_UPLOAD_BYTES
from app.services.kb.gallery import MAX_GALLERY_BYTES
from app.services.kb.retrieval import RetrievalFilters
from app.services.kb.serializers import (
    answer_to_dict,
    approval_to_dict,
    audit_to_dict,
    claim_to_dict,
    comment_to_dict,
    conflict_to_dict,
    document_to_dict,
    entity_to_dict,
    question_to_dict,
    response_to_dict,
    review_request_to_dict,
    user_to_dict,
)
from app.services.ollama_client import (
    LOCAL_AI_UNAVAILABLE,
    OLLAMA_GENERATE_FAILED,
    OLLAMA_TIMEOUT,
)

router = APIRouter(prefix="/kb", tags=["knowledge-base"])


def _actor(session: Session, user_id: int | None):
    return resolve_acting_user(session, user_id)


async def _read_capped(upload: UploadFile, cap: int) -> bytes | None:
    """Read an upload in bounded chunks, returning None once it exceeds ``cap``
    so an oversized file is never fully buffered."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _map_ai_error(error: str) -> HTTPException:
    low = error.lower()
    if "rate limit" in low:
        return HTTPException(status_code=429, detail=error)
    if error == LOCAL_AI_UNAVAILABLE or "not configured" in low:
        return HTTPException(status_code=503, detail=error)
    if error == OLLAMA_TIMEOUT or "timed out" in low:
        return HTTPException(status_code=504, detail=error)
    if error.startswith(OLLAMA_GENERATE_FAILED) or "ollama" in low or "claude" in low:
        return HTTPException(status_code=502, detail=error)
    return HTTPException(status_code=400, detail=error)


# --- meta / vocab ------------------------------------------------------------


@router.get("/meta")
def get_meta() -> dict:
    return {
        "roles": [
            {"value": r, "label": kb_vocab.ROLE_LABELS.get(r, r)} for r in kb_vocab.ROLES
        ],
        "permissions": list(kb_vocab.PERMISSIONS),
        "role_permissions": {r: sorted(p) for r, p in kb_vocab.ROLE_PERMISSIONS.items()},
        "claim_statuses": list(kb_vocab.CLAIM_STATUSES),
        "answer_statuses": list(kb_vocab.ANSWER_STATUSES),
        "doc_statuses": list(kb_vocab.DOC_STATUSES),
        "claim_categories": list(kb_vocab.CLAIM_CATEGORIES),
        "answer_categories": list(kb_vocab.ANSWER_CATEGORIES),
        "document_types": list(kb_vocab.DOCUMENT_TYPES),
        "gallery_categories": list(kb_vocab.GALLERY_CATEGORIES),
        "gallery_image_exts": list(kb_vocab.GALLERY_IMAGE_EXTS),
        "service_types": list(kb_vocab.SERVICE_TYPES),
        "industries": list(kb_vocab.INDUSTRIES),
        "states": list(kb_vocab.US_STATES),
        "geographic_scopes": list(kb_vocab.GEOGRAPHIC_SCOPES),
        "confidence_levels": list(kb_vocab.CONFIDENCE_LEVELS),
        "tones": list(kb_vocab.RESPONSE_TONES),
        "detail_levels": list(kb_vocab.RESPONSE_DETAIL_LEVELS),
        "response_review_statuses": list(kb_vocab.RESPONSE_REVIEW_STATUSES),
        "conflict_resolutions": list(kb_vocab.CONFLICT_RESOLUTIONS),
        "ai_providers": [
            {"value": p, "label": ai_provider.PROVIDER_LABELS[p]}
            for p in ai_provider.PROVIDERS
        ],
    }


@router.get("/whoami")
def whoami(x_kb_user_id: int | None = Header(default=None)) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return {
            "user": user_to_dict(actor),
            "permissions": sorted(kb_vocab.ROLE_PERMISSIONS.get(actor.role, [])),
        }


# --- dashboard ---------------------------------------------------------------


@router.get("/dashboard")
def kb_dashboard(
    company_entity_id: int | None = Query(default=None),
    state: str | None = Query(default=None),
    service_type: str | None = Query(default=None),
    industry: str | None = Query(default=None),
    category: str | None = Query(default=None),
    approval_status: str | None = Query(default=None),
    document_type: str | None = Query(default=None),
) -> dict:
    filters = {
        "company_entity_id": company_entity_id,
        "state": state,
        "service_type": service_type,
        "industry": industry,
        "category": category,
        "approval_status": approval_status,
        "document_type": document_type,
    }
    filters = {k: v for k, v in filters.items() if v is not None}
    with Session(engine) as session:
        return dashboard.get_kb_dashboard(session, filters)


# --- users / entities --------------------------------------------------------


@router.get("/users")
def list_users(x_kb_user_id: int | None = Header(default=None)) -> list[dict]:
    with Session(engine) as session:
        _actor(session, x_kb_user_id)
        return [user_to_dict(u) for u in admin.list_users(session)]


@router.post("/users", status_code=201)
def create_user(payload: UserCreate, x_kb_user_id: int | None = Header(default=None)) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return user_to_dict(admin.create_user(session, actor, payload.model_dump()))


@router.patch("/users/{user_id}")
def update_user(
    user_id: int, payload: UserUpdate, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return user_to_dict(
            admin.update_user(session, actor, user_id, payload.model_dump(exclude_unset=True))
        )


@router.get("/entities")
def list_entities(x_kb_user_id: int | None = Header(default=None)) -> list[dict]:
    with Session(engine) as session:
        _actor(session, x_kb_user_id)
        return [entity_to_dict(e) for e in admin.list_entities(session)]


@router.post("/entities", status_code=201)
def create_entity(
    payload: EntityCreate, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return entity_to_dict(admin.create_entity(session, actor, payload.model_dump()))


@router.patch("/entities/{entity_id}")
def update_entity(
    entity_id: int, payload: EntityUpdate, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return entity_to_dict(
            admin.update_entity(session, actor, entity_id, payload.model_dump(exclude_unset=True))
        )


# --- document vault ----------------------------------------------------------


@router.get("/documents")
def list_documents(
    company_entity_id: int | None = Query(default=None),
    category: str | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    state: str | None = Query(default=None),
    industry: str | None = Query(default=None),
    service_type: str | None = Query(default=None),
    processing_status: str | None = Query(default=None),
    expiration: str | None = Query(default=None),
    archived: bool | None = Query(default=False),
) -> list[dict]:
    with Session(engine) as session:
        docs = documents.list_documents(
            session,
            company_entity_id=company_entity_id,
            category=category,
            doc_type=doc_type,
            state=state,
            industry=industry,
            service_type=service_type,
            processing_status=processing_status,
            expiration=expiration,
            archived=archived,
        )
        return [document_to_dict(d, include_flags=False) for d in docs]


@router.post("/documents", status_code=201)
async def upload_documents(
    files: list[UploadFile] = File(...),
    title: str | None = Form(default=None),
    doc_type: str | None = Form(default=None),
    category: str | None = Form(default=None),
    company_entity_id: int | None = Form(default=None),
    applicable_state: str | None = Form(default=None),
    applicable_industry: str | None = Form(default=None),
    service_type: str | None = Form(default=None),
    effective_date: str | None = Form(default=None),
    expiration_date: str | None = Form(default=None),
    tags: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    process: bool = Form(default=True),
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    single = len(files) == 1
    created: list[dict] = []
    errors: list[str] = []
    doc_ids: list[int] = []
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        # Reject unauthorized callers BEFORE buffering any request body, and
        # bound the read so an oversized upload can't be fully spooled to memory.
        require_permission(actor, PERM_UPLOAD_DOCUMENTS)
        for upload in files:
            content = await _read_capped(upload, MAX_UPLOAD_BYTES)
            if content is None:
                errors.append(
                    f"{upload.filename}: exceeds the maximum size of "
                    f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
                )
                continue
            meta = {
                "title": title if single else None,
                "doc_type": doc_type,
                "category": category,
                "company_entity_id": company_entity_id,
                "applicable_state": applicable_state,
                "applicable_industry": applicable_industry,
                "service_type": service_type,
                "effective_date": effective_date,
                "expiration_date": expiration_date,
                "tags": [t.strip() for t in tags.split(",")] if tags else None,
                "notes": notes,
                "mime_type": upload.content_type,
            }
            try:
                doc = documents.create_document(
                    session, actor, filename=upload.filename or "document",
                    content=content, metadata=meta,
                )
                created.append(document_to_dict(doc, include_flags=False))
                doc_ids.append(doc.id)
            except documents.KbDocumentError as exc:
                errors.append(f"{upload.filename}: {exc}")
    if process:
        for doc_id in doc_ids:
            processing.enqueue_processing(doc_id)
    return {"documents": created, "errors": errors, "processing": process}


@router.get("/documents/{document_id}")
def get_document(document_id: int) -> dict:
    with Session(engine) as session:
        return documents.get_document_detail(session, document_id)


@router.patch("/documents/{document_id}")
def update_document(
    document_id: int,
    payload: DocumentMetadataUpdate,
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        doc = documents.update_document_metadata(
            session, actor, document_id, payload.model_dump(exclude_unset=True)
        )
        return document_to_dict(doc)


@router.post("/documents/{document_id}/process")
def process_document(document_id: int, x_kb_user_id: int | None = Header(default=None)) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        # Reprocessing mutates chunks + candidate claims; gate it like ingest.
        require_permission(actor, PERM_UPLOAD_DOCUMENTS)
        result = process_document_sync(session, document_id)
        return result


def process_document_sync(session: Session, document_id: int) -> dict:
    result = processing.process_document(session, document_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/documents/{document_id}/archive")
def archive_document(
    document_id: int, payload: ArchiveRequest, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        doc = documents.archive_document(session, actor, document_id, payload.archived)
        return document_to_dict(doc)


@router.delete("/documents/{document_id}")
def delete_document(document_id: int, x_kb_user_id: int | None = Header(default=None)) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        documents.delete_document(session, actor, document_id)
        return {"status": "deleted"}


@router.get("/documents/{document_id}/file")
def get_document_file(document_id: int) -> FileResponse:
    with Session(engine) as session:
        document = documents.get_document(session, document_id)
        path = documents.resolve_document_file(document)
        if path is None:
            raise HTTPException(status_code=404, detail="Stored file not found")
        media_type = document.mime_type or "application/octet-stream"
        filename = document.filename or path.name
    return FileResponse(path, media_type=media_type, filename=filename)


# --- Media Gallery -----------------------------------------------------------


@router.post("/gallery", status_code=201)
async def upload_gallery_assets(
    files: list[UploadFile] = File(...),
    title: str | None = Form(default=None),
    category: str | None = Form(default=None),
    company_entity_id: int | None = Form(default=None),
    description: str | None = Form(default=None),
    alt_text: str | None = Form(default=None),
    tags: str | None = Form(default=None),
    effective_date: str | None = Form(default=None),
    expiration_date: str | None = Form(default=None),
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    single = len(files) == 1
    created: list[dict] = []
    errors: list[str] = []
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        require_permission(actor, PERM_UPLOAD_DOCUMENTS)
        for upload in files:
            content = await _read_capped(upload, MAX_GALLERY_BYTES)
            if content is None:
                errors.append(
                    f"{upload.filename}: exceeds the maximum size of "
                    f"{MAX_GALLERY_BYTES // (1024 * 1024)} MB."
                )
                continue
            meta = {
                "title": title if single else None,
                "category": category,
                "company_entity_id": company_entity_id,
                "description": description,
                "alt_text": alt_text,
                "tags": [t.strip() for t in tags.split(",")] if tags else None,
                "effective_date": effective_date,
                "expiration_date": expiration_date,
                "mime_type": upload.content_type,
            }
            try:
                asset = gallery.create_asset(
                    session, actor, filename=upload.filename or "asset",
                    content=content, metadata=meta,
                )
                created.append(gallery.asset_to_dict(asset))
            except gallery.GalleryAssetError as exc:
                errors.append(f"{upload.filename}: {exc}")
    return {"assets": created, "errors": errors}


@router.get("/gallery")
def list_gallery_assets(
    category: str | None = Query(default=None),
    company_entity_id: int | None = Query(default=None),
    tag: str | None = Query(default=None),
    archived: bool = Query(default=False),
) -> list[dict]:
    with Session(engine) as session:
        assets = gallery.list_assets(
            session,
            category=category,
            company_entity_id=company_entity_id,
            tag=tag,
            archived=archived,
        )
        return [gallery.asset_to_dict(a) for a in assets]


@router.get("/gallery/{asset_id}")
def get_gallery_asset(asset_id: int) -> dict:
    with Session(engine) as session:
        return gallery.asset_to_dict(gallery.get_asset(session, asset_id))


@router.patch("/gallery/{asset_id}")
def update_gallery_asset(
    asset_id: int,
    payload: GalleryAssetUpdate,
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        asset = gallery.update_asset(
            session, actor, asset_id, payload.model_dump(exclude_unset=True)
        )
        return gallery.asset_to_dict(asset)


@router.post("/gallery/{asset_id}/archive")
def archive_gallery_asset(
    asset_id: int, payload: ArchiveRequest, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        asset = gallery.archive_asset(session, actor, asset_id, payload.archived)
        return gallery.asset_to_dict(asset)


@router.delete("/gallery/{asset_id}")
def delete_gallery_asset(
    asset_id: int, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        gallery.delete_asset(session, actor, asset_id)
        return {"status": "deleted"}


@router.get("/gallery/{asset_id}/file")
def get_gallery_asset_file(asset_id: int) -> FileResponse:
    with Session(engine) as session:
        asset = gallery.get_asset(session, asset_id)
        path = gallery.resolve_asset_file(asset)
        if path is None:
            raise HTTPException(status_code=404, detail="Stored image not found")
        media_type = asset.mime_type or "application/octet-stream"
        filename = asset.filename or path.name
    # Inline so the browser renders the image in <img>; SVGs are safe here
    # because <img> does not execute embedded scripts.
    return FileResponse(path, media_type=media_type, filename=filename)


# --- claims ------------------------------------------------------------------


@router.get("/claims")
def list_claims(
    company_entity_id: int | None = Query(default=None),
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    state: str | None = Query(default=None),
    service_type: str | None = Query(default=None),
    industry: str | None = Query(default=None),
    x_kb_user_id: int | None = Header(default=None),
) -> list[dict]:
    with Session(engine) as session:
        from app.services.kb.permissions import can_view_restricted

        actor = _actor(session, x_kb_user_id)
        rows = claims.list_claims(
            session,
            company_entity_id=company_entity_id,
            category=category,
            status=status,
            state=state,
            service_type=service_type,
            industry=industry,
            include_restricted=can_view_restricted(actor),
        )
        return [claim_to_dict(c) for c in rows]


@router.post("/claims", status_code=201)
def create_claim(payload: ClaimCreate, x_kb_user_id: int | None = Header(default=None)) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return claim_to_dict(claims.create_claim(session, actor, payload.model_dump(exclude_unset=True)))


@router.get("/claims/{claim_id}")
def get_claim(claim_id: int, x_kb_user_id: int | None = Header(default=None)) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return claims.get_claim_detail(session, claim_id, actor)


@router.patch("/claims/{claim_id}")
def update_claim(
    claim_id: int, payload: ClaimUpdate, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    data = payload.model_dump(exclude_unset=True)
    change_note = data.pop("change_note", None)
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return claim_to_dict(claims.update_claim(session, actor, claim_id, data, change_note))


@router.post("/claims/{claim_id}/approve")
def approve_claim(
    claim_id: int, payload: StatusChangeRequest | None = None,
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    note = payload.note if payload else None
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return claim_to_dict(claims.approve_claim(session, actor, claim_id, note))


@router.post("/claims/{claim_id}/reject")
def reject_claim(
    claim_id: int, payload: StatusChangeRequest | None = None,
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    note = payload.note if payload else None
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return claim_to_dict(claims.reject_claim(session, actor, claim_id, note))


@router.post("/claims/{claim_id}/restrict")
def restrict_claim(
    claim_id: int, payload: StatusChangeRequest | None = None,
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    note = payload.note if payload else None
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return claim_to_dict(claims.restrict_claim(session, actor, claim_id, note))


@router.post("/claims/{claim_id}/archive")
def archive_claim(
    claim_id: int, payload: StatusChangeRequest | None = None,
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    note = payload.note if payload else None
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return claim_to_dict(claims.archive_claim(session, actor, claim_id, note))


@router.post("/claims/{claim_id}/submit")
def submit_claim(
    claim_id: int, payload: StatusChangeRequest | None = None,
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    note = payload.note if payload else None
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return claim_to_dict(claims.submit_for_review(session, actor, claim_id, note))


@router.post("/claims/{claim_id}/supersede")
def supersede_claim(
    claim_id: int, payload: SupersedeRequest, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return claim_to_dict(
            claims.supersede_claim(session, actor, claim_id, payload.superseded_by_id, payload.note)
        )


@router.post("/claims/{claim_id}/sources", status_code=201)
def add_claim_source(
    claim_id: int, payload: ClaimSourceRequest, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    from app.services.kb.serializers import claim_source_to_dict

    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        src = claims.add_claim_source(session, actor, claim_id, **payload.model_dump(exclude_unset=True))
        return claim_source_to_dict(src)


@router.post("/claims/{claim_id}/restore/{version_id}")
def restore_claim_version(
    claim_id: int, version_id: int, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return claim_to_dict(claims.restore_claim_version(session, actor, claim_id, version_id))


@router.post("/claims/expire")
def expire_claims(x_kb_user_id: int | None = Header(default=None)) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        require_permission(actor, PERM_APPROVE_CLAIMS)
        return {"expired": claims.expire_due_claims(session)}


# --- reusable questions / answers --------------------------------------------


@router.get("/questions")
def list_questions(category: str | None = Query(default=None)) -> list[dict]:
    with Session(engine) as session:
        return [question_to_dict(q) for q in answers.list_questions(session, category=category)]


@router.post("/questions", status_code=201)
def create_question(payload: QuestionCreate, x_kb_user_id: int | None = Header(default=None)) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return question_to_dict(answers.create_question(session, actor, payload.model_dump()))


@router.get("/answers")
def list_answers(
    company_entity_id: int | None = Query(default=None),
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[dict]:
    with Session(engine) as session:
        rows = answers.list_answers(
            session, company_entity_id=company_entity_id, category=category, status=status
        )
        return [answer_to_dict(a) for a in rows]


@router.post("/answers", status_code=201)
def create_answer(payload: AnswerCreate, x_kb_user_id: int | None = Header(default=None)) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return answer_to_dict(answers.create_answer(session, actor, payload.model_dump(exclude_unset=True)))


@router.get("/answers/{answer_id}")
def get_answer(answer_id: int) -> dict:
    with Session(engine) as session:
        return answers.get_answer_detail(session, answer_id)


@router.patch("/answers/{answer_id}")
def update_answer(
    answer_id: int, payload: AnswerUpdate, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    data = payload.model_dump(exclude_unset=True)
    change_note = data.pop("change_note", None)
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return answer_to_dict(answers.update_answer(session, actor, answer_id, data, change_note))


@router.post("/answers/{answer_id}/approve")
def approve_answer(
    answer_id: int, payload: StatusChangeRequest | None = None,
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    note = payload.note if payload else None
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return answer_to_dict(answers.approve_answer(session, actor, answer_id, note))


@router.post("/answers/{answer_id}/reject")
def reject_answer(
    answer_id: int, payload: StatusChangeRequest | None = None,
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    note = payload.note if payload else None
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return answer_to_dict(answers.reject_answer(session, actor, answer_id, note))


@router.post("/answers/{answer_id}/archive")
def archive_answer(
    answer_id: int, payload: StatusChangeRequest | None = None,
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    note = payload.note if payload else None
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return answer_to_dict(answers.archive_answer(session, actor, answer_id, note))


# --- responses / drafting ----------------------------------------------------


@router.post("/responses/generate")
def generate_response(payload: GenerateRequest, x_kb_user_id: int | None = Header(default=None)) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        result = drafting.generate_response(session, actor, payload.model_dump(exclude_unset=True))
        if result.get("error"):
            raise _map_ai_error(result["error"])
        return result


@router.get("/responses")
def list_responses(
    opportunity_id: int | None = Query(default=None),
    review_status: str | None = Query(default=None),
    company_entity_id: int | None = Query(default=None),
) -> list[dict]:
    with Session(engine) as session:
        rows = responses.list_responses(
            session,
            opportunity_id=opportunity_id,
            review_status=review_status,
            company_entity_id=company_entity_id,
        )
        return [response_to_dict(r) for r in rows]


@router.get("/responses/{response_id}")
def get_response(response_id: int) -> dict:
    with Session(engine) as session:
        return responses.get_response_detail(session, response_id)


@router.patch("/responses/{response_id}")
def update_response(
    response_id: int, payload: ResponseUpdate, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return response_to_dict(
            responses.update_response(session, actor, response_id, payload.model_dump(exclude_unset=True))
        )


@router.post("/responses/{response_id}/transform")
def transform_response(
    response_id: int, payload: TransformRequest, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        result = drafting.transform_response(
            session, actor, response_id, payload.operation, payload.instructions,
            provider=payload.provider,
        )
        if result.get("error"):
            raise _map_ai_error(result["error"])
        return result


# --- AI drafting provider config ---------------------------------------------


@router.get("/ai-config")
def get_ai_config() -> dict:
    """Drafting-provider status. Never returns the Claude API key."""
    from app.services.ollama_client import is_ollama_available

    with Session(engine) as session:
        return {
            "default_provider": ai_provider.PROVIDER_LOCAL,
            "providers": [
                {"value": p, "label": ai_provider.PROVIDER_LABELS[p]}
                for p in ai_provider.PROVIDERS
            ],
            "local": {"available": is_ollama_available()},
            "claude": claude_client.get_status(session),
        }


@router.put("/ai-config/claude")
def put_claude_config(
    payload: ClaudeConfigUpdate, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        require_permission(actor, PERM_MANAGE_USERS)
        try:
            status = claude_client.save_config(session, payload.api_key, payload.model)
        except claude_client.ClaudeError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        record_audit(
            session, actor, "ai.config.claude.update", target_type="ai_config",
            detail={"model": status.get("model"), "key_set": bool(payload.api_key)},
        )
        return status


@router.delete("/ai-config/claude")
def delete_claude_config(x_kb_user_id: int | None = Header(default=None)) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        require_permission(actor, PERM_MANAGE_USERS)
        status = claude_client.delete_config(session)
        record_audit(
            session, actor, "ai.config.claude.delete", target_type="ai_config",
        )
        return status


# --- Google Drive import -----------------------------------------------------


@router.get("/google-drive/status")
def google_drive_status() -> dict:
    """Connector status. Never returns any token or secret."""
    with Session(engine) as session:
        return google_drive_connector.get_status(session)


@router.put("/google-drive/config")
def put_google_drive_config(
    payload: GoogleDriveConfigUpdate, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        require_permission(actor, PERM_MANAGE_USERS)
        try:
            status = google_drive_connector.configure(
                session, payload.model_dump(exclude_unset=True)
            )
        except google_drive_connector.DriveConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        record_audit(
            session, actor, "gdrive.config.update", target_type="gdrive_config",
            detail={"folder_id": status.get("folder_id"), "has_refresh": status.get("has_refresh")},
        )
        return status


@router.delete("/google-drive/config")
def delete_google_drive_config(x_kb_user_id: int | None = Header(default=None)) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        require_permission(actor, PERM_MANAGE_USERS)
        status = google_drive_connector.clear(session)
        record_audit(session, actor, "gdrive.config.delete", target_type="gdrive_config")
        return status


@router.get("/google-drive/files")
def list_google_drive_files(
    folder_id: str | None = Query(default=None),
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        require_permission(actor, PERM_UPLOAD_DOCUMENTS)
        return google_drive_connector.list_files(session, folder_id=folder_id)


@router.post("/google-drive/import")
def import_google_drive_files(
    payload: GoogleDriveImportRequest, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        # create_document enforces the uploader permission per file; requiring it
        # up front rejects unauthorized callers before any Drive download.
        require_permission(actor, PERM_UPLOAD_DOCUMENTS)
        return google_drive_connector.import_files(
            session, actor, payload.file_ids, company_entity_id=payload.company_entity_id
        )


@router.post("/responses/{response_id}/save-to-project")
def save_response_to_project(
    response_id: int, payload: SaveToProjectRequest, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return response_to_dict(
            responses.save_to_project(
                session, actor, response_id, **payload.model_dump(exclude_unset=True)
            )
        )


@router.delete("/responses/{response_id}")
def delete_response(response_id: int, x_kb_user_id: int | None = Header(default=None)) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        responses.delete_response(session, actor, response_id)
        return {"status": "deleted"}


# --- conflicts ---------------------------------------------------------------


@router.get("/conflicts")
def list_conflicts(
    status: str | None = Query(default="Open"),
    company_entity_id: int | None = Query(default=None),
) -> list[dict]:
    with Session(engine) as session:
        rows = conflicts.list_conflicts(session, status=status, company_entity_id=company_entity_id)
        return [conflict_to_dict(c) for c in rows]


@router.post("/conflicts/detect")
def detect_conflicts(
    payload: DetectConflictsRequest | None = None,
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    entity_id = payload.company_entity_id if payload else None
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        require_permission(actor, PERM_RESOLVE_CONFLICTS)
        return {"detected": conflicts.detect_conflicts(session, company_entity_id=entity_id)}


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(
    conflict_id: int, payload: ConflictResolveRequest, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return conflict_to_dict(
            conflicts.resolve_conflict(
                session, actor, conflict_id,
                resolution=payload.resolution,
                authoritative_claim_id=payload.authoritative_claim_id,
                explanation=payload.explanation,
            )
        )


@router.post("/conflicts/{conflict_id}/dismiss")
def dismiss_conflict(
    conflict_id: int, payload: StatusChangeRequest | None = None,
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    note = payload.note if payload else None
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return conflict_to_dict(conflicts.dismiss_conflict(session, actor, conflict_id, note))


# --- reviews / comments / approvals / audit ----------------------------------


@router.get("/review-requests")
def list_review_requests(
    status: str | None = Query(default="Open"),
    target_type: str | None = Query(default=None),
    assigned_to: int | None = Query(default=None),
) -> list[dict]:
    with Session(engine) as session:
        rows = reviews.list_review_requests(
            session, status=status, target_type=target_type, assigned_to=assigned_to
        )
        return [review_request_to_dict(r) for r in rows]


@router.post("/review-requests", status_code=201)
def create_review_request(
    payload: ReviewRequestCreate, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return review_request_to_dict(
            reviews.create_review_request(
                session, actor, target_type=payload.target_type, target_id=payload.target_id,
                note=payload.note, assigned_to=payload.assigned_to,
            )
        )


@router.post("/review-requests/{request_id}/resolve")
def resolve_review_request(
    request_id: int, payload: ReviewResolveRequest, x_kb_user_id: int | None = Header(default=None)
) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return review_request_to_dict(
            reviews.resolve_review_request(
                session, actor, request_id, status=payload.status, resolution=payload.resolution
            )
        )


@router.get("/comments")
def list_comments(target_type: str = Query(...), target_id: int = Query(...)) -> list[dict]:
    with Session(engine) as session:
        return [comment_to_dict(c) for c in reviews.list_comments(session, target_type, target_id)]


@router.post("/comments", status_code=201)
def add_comment(payload: CommentCreate, x_kb_user_id: int | None = Header(default=None)) -> dict:
    with Session(engine) as session:
        actor = _actor(session, x_kb_user_id)
        return comment_to_dict(
            reviews.add_comment(
                session, actor, target_type=payload.target_type,
                target_id=payload.target_id, body=payload.body,
            )
        )


@router.get("/approvals")
def list_approvals(target_type: str = Query(...), target_id: int = Query(...)) -> list[dict]:
    with Session(engine) as session:
        return [approval_to_dict(a) for a in reviews.list_approvals(session, target_type, target_id)]


@router.get("/audit")
def get_audit(
    target_type: str | None = Query(default=None),
    target_id: int | None = Query(default=None),
    actor_id: int | None = Query(default=None),
    limit: int = Query(default=200),
) -> list[dict]:
    with Session(engine) as session:
        rows = list_audit(
            session, target_type=target_type, target_id=target_id, actor_id=actor_id, limit=limit
        )
        return [audit_to_dict(a) for a in rows]


# --- search ------------------------------------------------------------------


@router.get("/search")
def kb_search(
    q: str = Query(default=""),
    kinds: str | None = Query(default=None),
    exact_phrase: bool = Query(default=False),
    include_restricted: bool = Query(default=False),
    company_entity_id: int | None = Query(default=None),
    state: str | None = Query(default=None),
    service_type: str | None = Query(default=None),
    industry: str | None = Query(default=None),
    category: str | None = Query(default=None),
    x_kb_user_id: int | None = Header(default=None),
) -> dict:
    with Session(engine) as session:
        from app.services.kb.permissions import can_view_restricted

        actor = _actor(session, x_kb_user_id)
        allow_restricted = include_restricted and can_view_restricted(actor)
        kind_tuple = tuple(k.strip() for k in kinds.split(",")) if kinds else (
            "document", "claim", "answer", "response", "chunk"
        )
        filters = RetrievalFilters(
            company_entity_id=company_entity_id,
            state=state,
            service_type=service_type,
            industry=industry,
            category=category,
        )
        return search.search_all(
            session, q, filters=filters, kinds=kind_tuple,
            exact_phrase=exact_phrase, include_restricted=allow_restricted,
        )

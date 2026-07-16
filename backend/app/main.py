from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routers import (
    analysis,
    dashboard,
    documents,
    exports,
    kb,
    notion,
    opportunities,
    portals,
    scraper,
    sources,
)

ALLOWED_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # init_db() is idempotent (create_all + _ensure_columns), so running it on
    # every boot is safe and keeps `uvicorn app.main:app` from 500ing on a
    # fresh install ("no such table") or after a schema change ("no such
    # column"), which _ensure_columns otherwise only fixed from the CLI.
    from app.db import init_db

    init_db()
    yield


app = FastAPI(title="RFP BidOS", lifespan=lifespan)


@app.middleware("http")
async def reject_cross_origin_writes(request: Request, call_next):
    """Block cross-origin state-changing requests (localhost CSRF defense).

    CORSMiddleware does not stop no-preflight "simple" POSTs from a malicious
    page hitting 127.0.0.1:8000 (portal login with keychain prefill, downloads,
    deletes). For unsafe methods, reject a present-but-foreign Origin. A missing
    Origin (curl, desktop, server-to-server tools) is allowed.
    """
    if request.method not in SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-origin request rejected"},
            )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(opportunities.router)
app.include_router(documents.router)
app.include_router(scraper.router)
app.include_router(analysis.router)
app.include_router(sources.router)
app.include_router(portals.router)
app.include_router(dashboard.router)
app.include_router(exports.router)
app.include_router(notion.router)
app.include_router(kb.router)


def _register_kb_exception_handlers() -> None:
    """Map knowledge-base service exceptions (each carries a ``status_code``) to
    JSON error responses, so services can raise typed errors and routers stay
    thin. Registered once at import."""
    from app.services.kb import (
        admin as kb_admin,
        answers as kb_answers,
        claims as kb_claims,
        conflicts as kb_conflicts,
        documents as kb_documents,
        gallery as kb_gallery,
        google_drive_connector as kb_gdrive,
        permissions as kb_permissions,
        responses as kb_responses,
        reviews as kb_reviews,
    )

    kb_exception_types = (
        kb_permissions.KbAuthError,
        kb_permissions.KbPermissionError,
        kb_claims.ClaimNotFoundError,
        kb_answers.AnswerNotFoundError,
        kb_documents.KbDocumentError,
        kb_documents.KbDocumentNotFoundError,
        kb_conflicts.ConflictNotFoundError,
        kb_conflicts.ConflictResolutionError,
        kb_responses.ResponseNotFoundError,
        kb_reviews.KbReviewError,
        kb_admin.KbAdminError,
        kb_admin.KbAdminNotFoundError,
        kb_gallery.GalleryAssetError,
        kb_gallery.GalleryAssetNotFoundError,
        kb_gdrive.DriveConfigError,
        kb_gdrive.DriveError,
    )

    def _handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=getattr(exc, "status_code", 400),
            content={"detail": str(exc)},
        )

    for exc_type in kb_exception_types:
        app.add_exception_handler(exc_type, _handler)


_register_kb_exception_handlers()


@app.get("/")
def read_root() -> dict[str, str]:
    return {"app": "RFP BidOS"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

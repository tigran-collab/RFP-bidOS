from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routers import (
    analysis,
    dashboard,
    documents,
    exports,
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


@app.get("/")
def read_root() -> dict[str, str]:
    return {"app": "RFP BidOS"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
